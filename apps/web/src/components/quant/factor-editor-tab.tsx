"use client";

/**
 * Tab 5「因子编辑器」：因子列表 + 新建/编辑（DSL 实时编译诊断）+ 生命周期
 * 数据全部经 Next 代理路由（/api/quant/factors/*），不直连 quant 容器
 * factors 模块（J1-J3）未就位时 quant 返回 503，列表降级为空态
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  CheckCircleIcon,
  CodeIcon,
  PencilSimpleIcon,
  PlusIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
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
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

// ---- 与 quant /api/factors* 对齐的类型契约（apps/quant/app/api.py 阶段 J4） ----

interface FactorSpec {
  id: string;
  label: string;
  group: string;
  kind: string; // base/virtual/uf/cf
  formula?: string;
  version?: number;
  direction?: number;
  status?: string; // draft/active/watch/retired
  members?: { id: string; weight: number }[] | null;
}

interface CompileError {
  code: string;
  message: string;
  position?: number;
}

interface CompilePreviewResult {
  ok: boolean;
  errors: CompileError[];
  preview?: {
    mean?: number | null;
    std?: number | null;
    min?: number | null;
    max?: number | null;
    valid_ratio?: number | null;
    sample_values?: { date: string; value: number }[];
  } | null;
}

// ---- 常量与纯函数 ----

const FACTOR_ID_RE = /^(uf|cf)_[A-Za-z0-9][A-Za-z0-9_-]{0,62}$/;
const MAX_CF_MEMBERS = 8;
// 复合因子初始引用两条内置动量因子（示意，可改）
const DEFAULT_CF_MEMBERS = [
  { id: "momentum_5d", weight: 1 },
  { id: "momentum_20d", weight: 1 },
];

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  active: "启用",
  watch: "观察",
  retired: "退役",
};

const KIND_BADGE: Record<string, { label: string; variant: "default" | "secondary" | "outline" }> = {
  base: { label: "内置", variant: "secondary" },
  virtual: { label: "虚拟", variant: "secondary" },
  uf: { label: "DSL 因子", variant: "outline" },
  cf: { label: "复合", variant: "default" },
};

function statusLabel(status?: string): string {
  return STATUS_LABEL[status ?? ""] ?? (status || "—");
}

function isBuiltin(f: FactorSpec): boolean {
  return !(f.id.startsWith("uf_") || f.id.startsWith("cf_"));
}

function fmtNum(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "—" : v.toFixed(4);
}

/** 样例因子值序列：sample_values 缺失时退化为 mean/std/min/max 合成折线 */
function buildPreviewData(
  p: CompilePreviewResult["preview"]
): { date: string; value: number }[] {
  if (!p) return [];
  const samples = (p.sample_values ?? []).filter(
    (s) => Number.isFinite(s.value) && typeof s.date === "string"
  );
  if (samples.length > 0) return samples;
  const stats = [p.min, p.mean, p.max, p.mean, p.std].filter(
    (v): v is number => typeof v === "number" && Number.isFinite(v)
  );
  if (stats.length === 0) return [];
  return stats.map((value, i) => ({ date: `样本${i + 1}`, value }));
}

const previewChartConfig = {
  value: { label: "因子值", color: "var(--chart-1)" },
} satisfies ChartConfig;

/** 新建/编辑表单状态（统一 state，新建与编辑共用一套字段） */
interface FactorForm {
  id: string;
  label: string;
  group: string;
  kind: "uf" | "cf";
  formula: string;
  direction: string;
  members: { id: string; weight: number }[];
}

function emptyForm(): FactorForm {
  return {
    id: "",
    label: "",
    group: "自定义",
    kind: "uf",
    formula: "",
    direction: "1",
    members: DEFAULT_CF_MEMBERS,
  };
}

function formOfFactor(f: FactorSpec): FactorForm {
  return {
    id: f.id,
    label: f.label,
    group: f.group,
    kind: f.id.startsWith("cf_") || f.kind === "cf" ? "cf" : "uf",
    formula: f.formula ?? "",
    direction: String(f.direction ?? 1),
    members:
      f.members && f.members.length > 0 ? f.members : DEFAULT_CF_MEMBERS,
  };
}

// ---- 主组件 ----

export function FactorEditorTab() {
  const [factors, setFactors] = useState<FactorSpec[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // 编辑对话框状态：null=关闭；factor=null 表示新建
  const [dialog, setDialog] = useState<{
    factor: FactorSpec | null;
    form: FactorForm;
  } | null>(null);
  const [saving, setSaving] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  // 编译诊断：idle=未输入可编译内容，loading=诊断中，其余为最近一次结果
  const [compile, setCompile] = useState<
    "idle" | "loading" | CompilePreviewResult
  >("idle");
  const compileSeq = useRef(0);
  const [deleteTarget, setDeleteTarget] = useState<FactorSpec | null>(null);
  const [deleting, setDeleting] = useState(false);

  /** 拉取因子列表（setState 全在异步回调里，供首载 effect 与操作后刷新共用） */
  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/quant/factors", { cache: "no-store" });
      setFactors(res.ok ? ((await res.json()) as FactorSpec[]) : []);
    } catch {
      setFactors([]);
    }
  }, []);

  useEffect(() => {
    // 挂到宏任务里再拉数据：effect 体内不同步触发 setState（react-hooks 规范）
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load]);

  // 公式 / 成员变化后防抖 500ms 自动跑编译诊断；
  // setState 一律放在回调/微任务里，effect 体内只做外部订阅（react-hooks 规范）
  useEffect(() => {
    if (!dialog) return;
    const { form } = dialog;
    const compilable =
      form.kind === "cf" || form.formula.trim().length > 0;
    const seq = ++compileSeq.current;
    // 微任务里置 loading，避免 effect 体内同步 setState
    queueMicrotask(() => {
      if (compileSeq.current === seq) {
        setCompile(compilable ? "loading" : "idle");
      }
    });
    if (!compilable) return;
    const timer = setTimeout(async () => {
      try {
        const res = await fetch("/api/quant/factors/compile-preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(
            form.kind === "cf"
              ? { formula: "", kind: "cf", members: form.members }
              : { formula: form.formula, kind: "uf" }
          ),
        });
        if (compileSeq.current !== seq) return;
        if (!res.ok) {
          const data = (await res.json().catch(() => null)) as {
            error?: string;
          } | null;
          setCompile({
            ok: false,
            errors: [
              {
                code: "HTTP",
                message: data?.error ?? "编译服务不可用",
              },
            ],
            preview: null,
          });
          return;
        }
        setCompile((await res.json()) as CompilePreviewResult);
      } catch {
        if (compileSeq.current === seq) {
          setCompile({
            ok: false,
            errors: [{ code: "NET", message: "编译请求失败，请检查网络" }],
            preview: null,
          });
        }
      }
    }, 500);
    return () => {
      clearTimeout(timer);
    };
  }, [dialog]);

  function updateForm(patch: Partial<FactorForm>) {
    setDialog((d) => (d ? { ...d, form: { ...d.form, ...patch } } : d));
    setDialogError(null);
  }

  function updateMember(
    index: number,
    patch: Partial<{ id: string; weight: number }>
  ) {
    setDialog((d) =>
      d
        ? {
            ...d,
            form: {
              ...d.form,
              members: d.form.members.map((m, i) =>
                i === index ? { ...m, ...patch } : m
              ),
            },
          }
        : d
    );
  }

  async function save() {
    if (!dialog || saving) return;
    const { factor, form } = dialog;
    // 前端与后端同口径校验，早失败省一次往返
    if (!factor && !FACTOR_ID_RE.test(form.id)) {
      setDialogError("id 须以 uf_ 或 cf_ 前缀开头，仅含字母/数字/下划线/连字符");
      return;
    }
    if (!form.label.trim()) {
      setDialogError("请填写因子名称");
      return;
    }
    if (form.kind === "uf" && !form.formula.trim()) {
      setDialogError("请填写 DSL 公式");
      return;
    }
    if (form.kind === "cf" && form.members.some((m) => !m.id.trim())) {
      setDialogError("复合因子成员 id 不能为空");
      return;
    }
    setSaving(true);
    setDialogError(null);
    try {
      const payload = {
        label: form.label.trim(),
        group: form.group.trim() || "自定义",
        direction: Number(form.direction),
        ...(form.kind === "cf"
          ? { members: form.members }
          : { formula: form.formula.trim() }),
      };
      const res = await fetch(
        factor
          ? `/api/quant/factors/${encodeURIComponent(factor.id)}`
          : "/api/quant/factors",
        {
          method: factor ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(
            factor
              ? payload
              : { ...payload, id: form.id.trim(), kind: form.kind }
          ),
        }
      );
      if (!res.ok) {
        const data = (await res.json().catch(() => null)) as {
          error?: string;
        } | null;
        setDialogError(data?.error ?? "保存失败，请稍后重试");
        return;
      }
      setDialog(null);
      await load();
    } catch {
      setDialogError("保存请求失败，请检查网络后重试");
    } finally {
      setSaving(false);
    }
  }

  async function changeStatus(factor: FactorSpec, status: string) {
    try {
      const res = await fetch(
        `/api/quant/factors/${encodeURIComponent(factor.id)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        }
      );
      if (!res.ok) {
        const data = (await res.json().catch(() => null)) as {
          error?: string;
        } | null;
        setNotice(data?.error ?? "状态更新失败");
        return;
      }
      setNotice(null);
      await load();
    } catch {
      setNotice("状态更新失败，请检查网络后重试");
    }
  }

  async function confirmDelete() {
    if (!deleteTarget || deleting) return;
    setDeleting(true);
    try {
      const res = await fetch(
        `/api/quant/factors/${encodeURIComponent(deleteTarget.id)}`,
        { method: "DELETE" }
      );
      if (!res.ok) {
        const data = (await res.json().catch(() => null)) as {
          error?: string;
        } | null;
        setNotice(data?.error ?? "删除失败");
      } else {
        setNotice(null);
      }
    } catch {
      setNotice("删除请求失败，请检查网络后重试");
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
      await load();
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div className="space-y-1.5">
          <CardTitle className="text-sm">因子库</CardTitle>
          <CardDescription>
            内置因子与用户自定义因子（uf_* DSL 因子 / cf_* 复合因子），公式变更自动版本 +1
          </CardDescription>
        </div>
        <Button
          size="sm"
          onClick={() => {
            setDialog({ factor: null, form: emptyForm() });
            setDialogError(null);
          }}
        >
          <PlusIcon />
          新建因子
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {notice && <EmptyState title={notice} compact inline />}
        {factors === null ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : factors.length === 0 ? (
          <EmptyState
            title="暂无因子"
            description="quant 因子注册表未返回数据；若 J1-J3 尚未就位，接口会返回 503，请确认 factors 模块已实现后重试"
            compact
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>名称</TableHead>
                <TableHead>分组</TableHead>
                <TableHead>类型</TableHead>
                <TableHead className="text-right">版本</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {factors.map((f) => {
                const builtin = isBuiltin(f);
                return (
                  <TableRow key={f.id}>
                    <TableCell className="max-w-[220px]">
                      <span className="block truncate font-mono text-xs">
                        {f.id}
                      </span>
                    </TableCell>
                    <TableCell>{f.label}</TableCell>
                    <TableCell>{f.group}</TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          KIND_BADGE[f.kind]?.variant ?? "outline"
                        }
                      >
                        {KIND_BADGE[f.kind]?.label ?? f.kind}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      v{f.version ?? 1}
                    </TableCell>
                    <TableCell>
                      {/* base-ui 的 onValueChange 回调类型为 string | null，守卫 null */}
                      {builtin ? (
                        <Badge variant="outline">
                          {statusLabel(f.status ?? "active")}
                        </Badge>
                      ) : (
                        <Select
                          value={f.status ?? "draft"}
                          onValueChange={(v) => {
                            if (v !== null) void changeStatus(f, v);
                          }}
                        >
                          <SelectTrigger size="sm" className="w-24">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {Object.entries(STATUS_LABEL).map(
                              ([value, label]) => (
                                <SelectItem key={value} value={value}>
                                  {label}
                                </SelectItem>
                              )
                            )}
                          </SelectContent>
                        </Select>
                      )}
                    </TableCell>
                    <TableCell>
                      {!builtin && (
                        <div className="flex items-center gap-1">
                          <Button
                            size="icon-sm"
                            variant="ghost"
                            aria-label={`编辑 ${f.id}`}
                            onClick={() => {
                              setDialog({ factor: f, form: formOfFactor(f) });
                              setDialogError(null);
                            }}
                          >
                            <PencilSimpleIcon />
                          </Button>
                          <Button
                            size="icon-sm"
                            variant="ghost"
                            aria-label={`删除 ${f.id}`}
                            onClick={() => setDeleteTarget(f)}
                          >
                            <TrashIcon />
                          </Button>
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>

      {/* 新建 / 编辑对话框 */}
      <Dialog
        open={dialog !== null}
        onOpenChange={(open) => {
          if (!open && !saving) setDialog(null);
        }}
      >
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {dialog?.factor ? `编辑因子 ${dialog.factor.id}` : "新建因子"}
            </DialogTitle>
            <DialogDescription>
              DSL 公式实时编译诊断（错误码 E001-E016）；保存时再次校验，公式变更版本 +1
            </DialogDescription>
          </DialogHeader>

          {dialog && (
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="factor-id">因子 ID</Label>
                  <Input
                    id="factor-id"
                    value={dialog.form.id}
                    disabled={dialog.factor !== null}
                    onChange={(e) =>
                      updateForm({
                        id: e.target.value,
                        kind: e.target.value.startsWith("cf_") ? "cf" : "uf",
                      })
                    }
                    placeholder="uf_my_momentum"
                    className="font-mono"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="factor-label">名称</Label>
                  <Input
                    id="factor-label"
                    value={dialog.form.label}
                    onChange={(e) => updateForm({ label: e.target.value })}
                    placeholder="我的动量因子"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="factor-group">分组</Label>
                  <Input
                    id="factor-group"
                    value={dialog.form.group}
                    onChange={(e) => updateForm({ group: e.target.value })}
                    placeholder="自定义"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>方向</Label>
                  <Select
                    value={dialog.form.direction}
                    onValueChange={(v) => {
                      if (v !== null) updateForm({ direction: v });
                    }}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="1">高好（值越大越好）</SelectItem>
                      <SelectItem value="-1">低好（值越小越好）</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {dialog.form.kind === "uf" ? (
                <div className="space-y-1.5">
                  <Label htmlFor="factor-formula">DSL 公式</Label>
                  <Textarea
                    id="factor-formula"
                    value={dialog.form.formula}
                    onChange={(e) => updateForm({ formula: e.target.value })}
                    placeholder="ts_mean(close, 20) / close - 1"
                    className="min-h-24 font-mono text-xs"
                  />
                </div>
              ) : (
                <div className="space-y-1.5">
                  <Label>复合因子成员（最多 {MAX_CF_MEMBERS} 个）</Label>
                  <div className="space-y-2">
                    {dialog.form.members.map((m, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <Input
                          value={m.id}
                          onChange={(e) =>
                            updateMember(i, { id: e.target.value })
                          }
                          placeholder="因子 id（uf/base/virtual）"
                          className="font-mono text-xs"
                        />
                        <Input
                          type="number"
                          min={0.01}
                          step={0.1}
                          value={String(m.weight)}
                          onChange={(e) =>
                            updateMember(i, {
                              weight: Number(e.target.value) || 0,
                            })
                          }
                          aria-label={`成员 ${i + 1} 权重`}
                          className="w-24 tabular-nums"
                        />
                        <Button
                          size="icon-sm"
                          variant="ghost"
                          aria-label={`移除成员 ${i + 1}`}
                          disabled={dialog.form.members.length <= 1}
                          onClick={() =>
                            updateForm({
                              members: dialog.form.members.filter(
                                (_, j) => j !== i
                              ),
                            })
                          }
                        >
                          <TrashIcon />
                        </Button>
                      </div>
                    ))}
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={
                        dialog.form.members.length >= MAX_CF_MEMBERS
                      }
                      onClick={() =>
                        updateForm({
                          members: [
                            ...dialog.form.members,
                            { id: "", weight: 1 },
                          ],
                        })
                      }
                    >
                      <PlusIcon />
                      添加成员
                    </Button>
                  </div>
                </div>
              )}

              {/* 编译诊断 + 样例预览 */}
              <div className="space-y-2 rounded-lg border p-3">
                <div className="flex items-center gap-2 text-xs font-medium">
                  <CodeIcon className="size-3.5" />
                  编译诊断
                  {compile === "loading" && (
                    <span className="text-muted-foreground">诊断中…</span>
                  )}
                </div>
                {compile === "idle" ? (
                  <p className="text-xs text-muted-foreground">
                    输入公式后自动诊断
                  </p>
                ) : compile === "loading" ? (
                  <Skeleton className="h-8 w-full" />
                ) : compile.ok ? (
                  <div className="space-y-2">
                    <div className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400">
                      <CheckCircleIcon className="size-3.5" />
                      编译通过
                    </div>
                    {compile.preview && (
                      <>
                        <div className="grid grid-cols-3 gap-2 text-xs sm:grid-cols-5">
                          {(
                            [
                              ["均值", compile.preview.mean],
                              ["标准差", compile.preview.std],
                              ["最小", compile.preview.min],
                              ["最大", compile.preview.max],
                            ] as const
                          ).map(([label, v]) => (
                            <div key={label}>
                              <div className="text-muted-foreground">
                                {label}
                              </div>
                              <div className="tabular-nums">{fmtNum(v)}</div>
                            </div>
                          ))}
                          <div>
                            <div className="text-muted-foreground">
                              有效值占比
                            </div>
                            <div className="tabular-nums">
                              {compile.preview.valid_ratio == null
                                ? "—"
                                : `${(compile.preview.valid_ratio * 100).toFixed(1)}%`}
                            </div>
                          </div>
                        </div>
                        {(() => {
                          const data = buildPreviewData(compile.preview);
                          if (data.length < 2) return null;
                          return (
                            <ChartContainer
                              config={previewChartConfig}
                              className="aspect-auto h-32 w-full"
                            >
                              <LineChart
                                data={data}
                                margin={{
                                  top: 4,
                                  right: 8,
                                  bottom: 0,
                                  left: 8,
                                }}
                              >
                                <CartesianGrid vertical={false} />
                                <XAxis
                                  dataKey="date"
                                  tickLine={false}
                                  axisLine={false}
                                  tickMargin={6}
                                  minTickGap={32}
                                />
                                <YAxis
                                  tickLine={false}
                                  axisLine={false}
                                  tickMargin={6}
                                  width={48}
                                  domain={["auto", "auto"]}
                                />
                                <ChartTooltip
                                  content={<ChartTooltipContent hideLabel />}
                                />
                                <Line
                                  type="monotone"
                                  dataKey="value"
                                  stroke="var(--color-value)"
                                  strokeWidth={1.5}
                                  dot={false}
                                />
                              </LineChart>
                            </ChartContainer>
                          );
                        })()}
                      </>
                    )}
                  </div>
                ) : (
                  <ul className="space-y-1">
                    {(compile.errors ?? []).map((err, i) => (
                      <li
                        key={i}
                        className="flex items-start gap-1.5 text-xs text-destructive"
                      >
                        <span className="font-mono font-medium">
                          {err.code}
                        </span>
                        <span>
                          {err.message}
                          {typeof err.position === "number" &&
                            `（位置 ${err.position}）`}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}

          <DialogFooter>
            {dialogError ? (
              <p role="alert" className="mr-auto text-xs text-destructive">
                {dialogError}
              </p>
            ) : null}
            <Button
              type="button"
              variant="outline"
              disabled={saving}
              onClick={() => setDialog(null)}
            >
              取消
            </Button>
            <Button
              type="button"
              disabled={saving || (dialog !== null && dialog.form.id === "")}
              className={cn(saving && "opacity-60")}
              onClick={() => void save()}
            >
              {saving ? "保存中…" : "保存"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 删除确认对话框 */}
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open && !deleting) setDeleteTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除因子</DialogTitle>
            <DialogDescription>
              删除「{deleteTarget?.label}」（{deleteTarget?.id}
              ）后不可恢复；引用该因子的复合因子与策略可能失效。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={deleting}
              onClick={() => setDeleteTarget(null)}
            >
              取消
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={deleting}
              onClick={() => void confirmDelete()}
            >
              {deleting ? "删除中…" : "确认删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
