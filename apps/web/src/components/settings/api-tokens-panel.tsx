"use client";

/**
 * API 令牌（PAT）管理面板：列表 / 签发 / 撤销
 * 数据全部经 Next 代理路由 /api/account/tokens（BFF 转发 api 服务），不直连后端
 * 明文令牌只在签发成功的 Dialog 中展示一次，关闭即丢弃（不落任何存储）
 */
import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { format } from "date-fns";
import { CheckIcon, CopyIcon, PlusIcon, TrashIcon } from "@phosphor-icons/react";

import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from "@/components/ui/input-group";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

// ─── 类型与常量（与 api 服务 /api/auth/tokens 契约对齐） ─────────────────

type TokenStatus = "active" | "expired" | "revoked";

interface ApiToken {
  id: number;
  name: string;
  token_prefix: string;
  scopes: string[];
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  status: TokenStatus;
}

interface CreatedToken {
  id: number;
  name: string;
  token: string;
  token_prefix: string;
  scopes: string[];
  created_at: string;
  expires_at: string;
}

/** 签发成功后的一次性展示内容（MCP 地址在签发时按当前站点取） */
interface CreatedView {
  token: CreatedToken;
  mcpUrl: string;
}

const SCOPE_OPTIONS = [
  {
    value: "strategy:read",
    label: "策略读取",
    description: "读取策略指南、策略列表与源码",
  },
  {
    value: "strategy:write",
    label: "策略写入",
    description: "校验并保存策略（会在沙箱中试运行代码）",
  },
  {
    value: "backtest",
    label: "回测",
    description: "提交回测任务、查询结果与取消",
  },
] as const;

const SCOPE_LABELS: Record<string, string> = Object.fromEntries(
  SCOPE_OPTIONS.map((s) => [s.value, s.label])
);

const EXPIRES_ITEMS: Record<string, string> = {
  "30": "30 天",
  "90": "90 天",
  "180": "180 天",
  "365": "365 天",
};

const STATUS_META: Record<
  TokenStatus,
  { label: string; variant: "default" | "secondary" | "destructive" }
> = {
  active: { label: "有效", variant: "default" },
  expired: { label: "已过期", variant: "secondary" },
  revoked: { label: "已撤销", variant: "destructive" },
};

// 与 api 服务每人有效令牌上限一致（仅用于前端提示，最终以后端 409 为准）
const MAX_ACTIVE_TOKENS = 5;
const NAME_MAX_LENGTH = 64;

// ─── 工具函数 ────────────────────────────────────────────────

function fmtDateTime(value: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : format(d, "yyyy-MM-dd HH:mm");
}

/** 从失败响应提取可读文案：FastAPI detail（字符串 / 422 数组）或 BFF error */
async function readError(res: Response, fallback: string): Promise<string> {
  if (res.status === 401) return "登录已过期，请刷新页面重新登录";
  const data = (await res.json().catch(() => null)) as {
    detail?: unknown;
    error?: unknown;
  } | null;
  const detail = data?.detail ?? data?.error;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const msg = (detail[0] as { msg?: unknown } | undefined)?.msg;
    if (typeof msg === "string" && msg) return `参数无效：${msg}`;
  }
  return fallback;
}

function mcpConfigSample(view: CreatedView): string {
  return JSON.stringify(
    {
      mcpServers: {
        tradeck: {
          type: "http",
          url: view.mcpUrl,
          headers: { Authorization: `Bearer ${view.token.token}` },
        },
      },
    },
    null,
    2
  );
}

// ─── 复制按钮（navigator.clipboard，非安全上下文下不可用则提示手动复制） ─────

function useCopy() {
  const [copied, setCopied] = useState<string | null>(null);
  const [copyError, setCopyError] = useState<string | null>(null);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(null), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  const copy = useCallback(async (key: string, text: string) => {
    try {
      if (!navigator.clipboard) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(text);
      setCopied(key);
      setCopyError(null);
    } catch {
      setCopyError("复制失败，请手动选中内容复制");
    }
  }, []);

  return { copied, copyError, copy };
}

// ─── 创建 Dialog：表单 → 成功后一次性展示明文 ─────────────────────

function CreateTokenForm({
  onCreated,
  onCancel,
}: {
  onCreated: (view: CreatedView) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(
    SCOPE_OPTIONS.map((s) => s.value)
  );
  const [expiresDays, setExpiresDays] = useState("90");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function toggleScope(scope: string, checked: boolean) {
    setScopes((current) =>
      checked
        ? SCOPE_OPTIONS.map((s) => s.value).filter(
            (s) => s === scope || current.includes(s)
          )
        : current.filter((s) => s !== scope)
    );
    setError(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setError("请填写令牌名称");
      return;
    }
    if (scopes.length === 0) {
      setError("至少选择一项权限");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch("/api/account/tokens", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: trimmed,
          scopes,
          expires_days: Number(expiresDays),
        }),
        cache: "no-store",
      });
      if (!res.ok) {
        setError(await readError(res, "创建失败，请稍后重试"));
        return;
      }
      const token = (await res.json()) as CreatedToken;
      onCreated({ token, mcpUrl: `${window.location.origin}/mcp` });
    } catch {
      setError("创建失败，请检查网络后重试");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="grid gap-4" onSubmit={handleSubmit} noValidate>
      <div className="grid gap-2">
        <Label htmlFor="api-token-name">名称</Label>
        <Input
          id="api-token-name"
          value={name}
          maxLength={NAME_MAX_LENGTH}
          placeholder="如：办公室 IDE"
          autoComplete="off"
          onChange={(event) => {
            setName(event.target.value);
            setError(null);
          }}
        />
      </div>

      <div className="grid gap-2">
        <Label id="api-token-scopes-label">权限</Label>
        <div
          role="group"
          aria-labelledby="api-token-scopes-label"
          className="grid gap-3"
        >
          {SCOPE_OPTIONS.map((scope) => {
            const fieldId = `api-token-scope-${scope.value}`;
            return (
              <div key={scope.value} className="flex items-start gap-2">
                <Checkbox
                  id={fieldId}
                  className="mt-0.5"
                  checked={scopes.includes(scope.value)}
                  onCheckedChange={(checked) =>
                    toggleScope(scope.value, checked === true)
                  }
                />
                <div className="grid gap-1">
                  <Label htmlFor={fieldId} className="font-normal">
                    {scope.label}
                    <span className="font-mono text-xs text-muted-foreground">
                      {scope.value}
                    </span>
                  </Label>
                  <p className="text-xs text-muted-foreground">
                    {scope.description}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="api-token-expires">有效期</Label>
        <Select
          items={EXPIRES_ITEMS}
          value={expiresDays}
          onValueChange={(value: string | null) => setExpiresDays(value ?? "90")}
        >
          <SelectTrigger id="api-token-expires" className="w-full">
            <SelectValue placeholder="选择有效期" />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(EXPIRES_ITEMS).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}

      <DialogFooter>
        <Button
          type="button"
          variant="outline"
          disabled={submitting}
          onClick={onCancel}
        >
          取消
        </Button>
        <Button type="submit" disabled={submitting}>
          {submitting ? "创建中…" : "创建令牌"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function CreatedTokenView({
  view,
  onDone,
}: {
  view: CreatedView;
  onDone: () => void;
}) {
  const { copied, copyError, copy } = useCopy();
  const config = mcpConfigSample(view);

  return (
    <div className="grid min-w-0 gap-4">
      <div className="grid gap-2">
        <Label htmlFor="api-token-plaintext">令牌</Label>
        <InputGroup>
          <InputGroupInput
            id="api-token-plaintext"
            readOnly
            value={view.token.token}
            className="font-mono text-xs"
            onFocus={(event) => event.currentTarget.select()}
          />
          <InputGroupAddon align="inline-end">
            <InputGroupButton
              size="icon-xs"
              aria-label="复制令牌"
              onClick={() => copy("token", view.token.token)}
            >
              {copied === "token" ? <CheckIcon /> : <CopyIcon />}
            </InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
        <p className="text-xs text-warn">
          令牌只显示这一次，关闭后无法再次查看；遗失请撤销后重新创建。
        </p>
      </div>

      <div className="grid min-w-0 gap-2">
        <div className="flex items-center justify-between gap-2">
          <Label id="api-token-config-label">MCP 客户端配置示例</Label>
          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={() => copy("config", config)}
          >
            {copied === "config" ? <CheckIcon /> : <CopyIcon />}
            复制配置
          </Button>
        </div>
        <pre
          aria-labelledby="api-token-config-label"
          className="max-h-56 overflow-auto rounded-lg bg-muted p-3 font-mono text-xs leading-relaxed"
        >
          {config}
        </pre>
        <p className="text-xs text-muted-foreground">
          字段名因客户端而异：核心是 HTTP 地址 {view.mcpUrl} 与请求头
          Authorization: Bearer &lt;令牌&gt;。
        </p>
      </div>

      {copyError ? (
        <p role="alert" className="text-xs text-destructive">
          {copyError}
        </p>
      ) : null}

      <DialogFooter>
        <Button type="button" onClick={onDone}>
          我已保存，关闭
        </Button>
      </DialogFooter>
    </div>
  );
}

function CreateTokenDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}) {
  // 明文只存在于该组件内存；关闭动画结束即清空（表单经 key 重建复位）
  const [created, setCreated] = useState<CreatedView | null>(null);
  const [formKey, setFormKey] = useState(0);

  function handleOpenChangeComplete(nextOpen: boolean) {
    if (nextOpen) return;
    setCreated(null);
    setFormKey((k) => k + 1);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      onOpenChangeComplete={handleOpenChangeComplete}
      // 展示明文期间禁止点遮罩误关（仍可用按钮 / Esc 主动关闭）
      disablePointerDismissal={created !== null}
    >
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{created ? "令牌已创建" : "创建 API 令牌"}</DialogTitle>
          <DialogDescription>
            {created
              ? `「${created.token.name}」将于 ${fmtDateTime(created.token.expires_at)} 到期。`
              : "令牌代表你的身份访问 tradeck，请只授予需要的权限并妥善保管。"}
          </DialogDescription>
        </DialogHeader>

        {created ? (
          <CreatedTokenView view={created} onDone={() => onOpenChange(false)} />
        ) : (
          <CreateTokenForm
            key={formKey}
            onCreated={(view) => {
              setCreated(view);
              onCreated();
            }}
            onCancel={() => onOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

// ─── 撤销确认 Dialog ─────────────────────────────────────────

function RevokeTokenDialog({
  token,
  open,
  onOpenChange,
  onRevoked,
}: {
  token: ApiToken | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRevoked: () => void;
}) {
  const [revoking, setRevoking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleOpenChange(nextOpen: boolean) {
    if (revoking) return;
    if (!nextOpen) setError(null);
    onOpenChange(nextOpen);
  }

  async function handleRevoke() {
    if (!token) return;
    setRevoking(true);
    setError(null);
    try {
      const res = await fetch(`/api/account/tokens/${token.id}`, {
        method: "DELETE",
        cache: "no-store",
      });
      if (!res.ok) {
        setError(await readError(res, "撤销失败，请稍后重试"));
        return;
      }
      onRevoked();
      onOpenChange(false);
    } catch {
      setError("撤销失败，请检查网络后重试");
    } finally {
      setRevoking(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>撤销令牌</DialogTitle>
          <DialogDescription>
            确认撤销「{token?.name}」（{token?.token_prefix}…）？使用该令牌的 MCP
            客户端将在 30 秒内失效，此操作不可恢复。
          </DialogDescription>
        </DialogHeader>
        {error ? (
          <p role="alert" className="text-xs text-destructive">
            {error}
          </p>
        ) : null}
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={revoking}
            onClick={() => handleOpenChange(false)}
          >
            取消
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={revoking}
            onClick={handleRevoke}
          >
            {revoking ? "撤销中…" : "确认撤销"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── 列表 ─────────────────────────────────────────────────

function TokensTable({
  tokens,
  onRevoke,
}: {
  tokens: ApiToken[];
  onRevoke: (token: ApiToken) => void;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>名称</TableHead>
          <TableHead>前缀</TableHead>
          <TableHead>权限</TableHead>
          <TableHead>状态</TableHead>
          <TableHead>到期</TableHead>
          <TableHead>最近使用</TableHead>
          <TableHead className="text-right">操作</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {tokens.map((token) => {
          const status = STATUS_META[token.status] ?? STATUS_META.expired;
          return (
            <TableRow key={token.id}>
              <TableCell className="max-w-48 truncate font-medium">
                {token.name}
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">
                {token.token_prefix}…
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  {token.scopes.map((scope) => (
                    <Badge key={scope} variant="outline">
                      {SCOPE_LABELS[scope] ?? scope}
                    </Badge>
                  ))}
                </div>
              </TableCell>
              <TableCell>
                <Badge variant={status.variant}>{status.label}</Badge>
              </TableCell>
              <TableCell className="text-xs tabular-nums">
                {fmtDateTime(token.expires_at)}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground tabular-nums">
                {token.last_used_at ? fmtDateTime(token.last_used_at) : "从未使用"}
              </TableCell>
              <TableCell className="text-right">
                {token.status === "active" ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    onClick={() => onRevoke(token)}
                  >
                    <TrashIcon />
                    撤销
                  </Button>
                ) : (
                  <span className="text-xs text-muted-foreground">—</span>
                )}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

export function ApiTokensPanel() {
  const [tokens, setTokens] = useState<ApiToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  // 撤销目标与 Dialog 开关分离：关闭动画期间目标仍在，文案不闪空
  const [revokeTarget, setRevokeTarget] = useState<ApiToken | null>(null);
  const [revokeOpen, setRevokeOpen] = useState(false);

  const openRevoke = useCallback((token: ApiToken) => {
    setRevokeTarget(token);
    setRevokeOpen(true);
  }, []);

  const loadTokens = useCallback(async () => {
    try {
      const res = await fetch("/api/account/tokens", { cache: "no-store" });
      if (!res.ok) {
        setLoadError(await readError(res, "令牌列表加载失败，请稍后重试"));
        return;
      }
      const data: unknown = await res.json();
      setTokens(Array.isArray(data) ? (data as ApiToken[]) : []);
      setLoadError(null);
    } catch {
      setLoadError("令牌列表加载失败，请检查网络后重试");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // 首帧渲染后再拉取（setState 在 effect 微任务里，避开 react-hooks/set-state-in-effect）
    void Promise.resolve().then(loadTokens);
  }, [loadTokens]);

  const activeCount = tokens.filter((t) => t.status === "active").length;
  const atLimit = activeCount >= MAX_ACTIVE_TOKENS;

  let body: ReactNode;
  if (loading) {
    body = (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-9 w-full" />
        ))}
      </div>
    );
  } else if (loadError && tokens.length === 0) {
    body = (
      <div className="flex flex-col items-center gap-2">
        <EmptyState title="加载失败" description={loadError} compact />
        <Button variant="outline" size="sm" onClick={() => void loadTokens()}>
          重试
        </Button>
      </div>
    );
  } else if (tokens.length === 0) {
    body = (
      <EmptyState
        title="还没有 API 令牌"
        description="创建令牌后，即可在 MCP 客户端中以你的身份连接 tradeck"
      />
    );
  } else {
    body = <TokensTable tokens={tokens} onRevoke={openRevoke} />;
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>我的令牌</CardTitle>
          <CardDescription>
            有效令牌 {activeCount} / {MAX_ACTIVE_TOKENS}，有效期最长 365 天；
            令牌只在创建时显示一次
          </CardDescription>
          <CardAction>
            <Button
              size="sm"
              disabled={loading || atLimit}
              onClick={() => setCreateOpen(true)}
            >
              <PlusIcon />
              {atLimit ? "已达上限" : "创建令牌"}
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent>
          {loadError && tokens.length > 0 ? (
            <p role="alert" className="mb-2 text-xs text-destructive">
              {loadError}
            </p>
          ) : null}
          {body}
        </CardContent>
      </Card>

      <CreateTokenDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={() => void loadTokens()}
      />
      <RevokeTokenDialog
        token={revokeTarget}
        open={revokeOpen}
        onOpenChange={setRevokeOpen}
        onRevoked={() => void loadTokens()}
      />
    </>
  );
}
