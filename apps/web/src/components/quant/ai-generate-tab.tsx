"use client";

/**
 * Tab 3「AI 策略生成」工作台：新建 / 选取已有 / 导入 三种来源统一进编辑器，
 * 之后可手动编辑或让 LLM 基于当前代码调整，满意后保存进策略库。
 *
 * 任务化动机：LLM 生成长代码常超 60s，同步等待会被 nginx/CF 砍成 504/524；
 * 任务脱离连接独立存活，掉线重连轮询即恢复。未配置 AI 时 POST 返回 200
 * {valid:false, error}（不建任务），按降级路径展示。
 * 保存走统一入口 POST /api/quant/strategy-save（validator 全量校验 +
 * 按 META.id 前缀落盘 ai/ 或 custom/），保存成功经 onSaved 回调刷新
 * 外层策略列表，新策略立即出现在回测/选股 Tab（loader 热加载）。
 */
import { useEffect, useRef, useState } from "react";
import {
  CircleNotchIcon,
  FloppyDiskIcon,
  FolderOpenIcon,
  SparkleIcon,
  StopIcon,
  UploadSimpleIcon,
} from "@phosphor-icons/react";

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
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";

import type { StrategyDef } from "./types";

interface AIMeta {
  id?: string;
  name?: string;
  description?: string;
  tags?: string[];
  [key: string]: unknown;
}

interface AIResult {
  valid: boolean;
  code?: string;
  meta?: AIMeta;
  error?: string | null;
}

interface AITaskState {
  task_id: string;
  status: "pending" | "running" | "done" | "failed" | "cancelled";
  result?: AIResult | null;
  error?: string | null;
}

type Mode = "create" | "existing" | "import";

const MODE_OPTIONS: { value: Mode; label: string }[] = [
  { value: "create", label: "新建策略" },
  { value: "existing", label: "选取已有" },
  { value: "import", label: "导入文件" },
];

const POLL_INTERVAL_MS = 2000;
const POLL_RETRY_WARN = 3;
const POLL_RETRY_GIVEUP = 90;
const MAX_IMPORT_BYTES = 50_000;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

interface AIGenerateTabProps {
  strategies: StrategyDef[];
  strategiesLoading: boolean;
  onSaved?: () => void;
}

export function AIGenerateTab({
  strategies,
  strategiesLoading,
  onSaved,
}: AIGenerateTabProps) {
  const [mode, setMode] = useState<Mode>("create");
  const [selectedId, setSelectedId] = useState("");
  const [description, setDescription] = useState("");
  // 编辑器内容（唯一事实源）：手动编辑直接改它，生成/调整成功后整体替换
  const [code, setCode] = useState("");
  // 从已有策略加载的原始 id（保存时作 overwrite_id 提示后端覆盖/重命名）
  const [loadedId, setLoadedId] = useState<string | null>(null);
  const [loadedSource, setLoadedSource] = useState<string | null>(null);
  const [generatedMeta, setGeneratedMeta] = useState<AIMeta | null>(null);

  const [busy, setBusy] = useState(false);
  const [loadingCode, setLoadingCode] = useState(false);
  const [notConfigured, setNotConfigured] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);

  const taskRef = useRef<{ id: string; cancelled: boolean } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 卸载时标记本地取消（停止轮询渲染；后端任务 TTL 自动回收）
  useEffect(
    () => () => {
      if (taskRef.current) taskRef.current.cancelled = true;
    },
    []
  );

  function resetOutput() {
    setError(null);
    setNotConfigured(false);
    setSavedId(null);
    setSaveError(null);
    setReconnecting(false);
  }

  /** 载入已有策略源码进编辑器（builtin 只读元数据，编辑后另存新策略） */
  async function loadExisting(id: string) {
    if (!id) return;
    setCode(""); // 先清空：加载中显示骨架，失败也不残留上一个策略的代码
    setLoadedId(null);
    setLoadedSource(null);
    setLoadingCode(true);
    resetOutput();
    try {
      const res = await fetch(
        `/api/quant/strategy-code?id=${encodeURIComponent(id)}`,
        { cache: "no-store" }
      );
      const data = (await res.json().catch(() => ({}))) as {
        id?: string;
        name?: string;
        source?: string;
        code?: string;
        detail?: string;
      };
      if (!res.ok || !data.code) {
        setError(data.detail ?? "策略源码加载失败");
        return;
      }
      setCode(data.code);
      setLoadedId(data.id ?? id);
      setLoadedSource(data.source ?? null);
      setGeneratedMeta(null);
      setDirty(false);
    } catch {
      setError("策略源码加载失败，请检查网络后重试");
    } finally {
      setLoadingCode(false);
    }
  }

  /** 导入本地 .py 文件进编辑器（仅前端读文件，不落盘；保存时才走后端校验） */
  async function importFile(file: File) {
    resetOutput();
    if (file.size > MAX_IMPORT_BYTES) {
      setError(`文件过大（${(file.size / 1024).toFixed(1)} KB），上限 50 KB`);
      return;
    }
    try {
      const text = await file.text();
      setCode(text);
      setLoadedId(null);
      setLoadedSource(null);
      setGeneratedMeta(null);
      setDirty(false);
    } catch {
      setError("文件读取失败");
    }
  }

  /** 统一轮询循环：登记任务后轮询至终态，done 时把生成代码灌进编辑器 */
  async function runTask(endpoint: string, body: Record<string, string>) {
    setBusy(true);
    resetOutput();
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        setError("生成服务不可用，请稍后重试");
        return;
      }
      const data = (await res.json()) as AIResult & { task_id?: string };
      if (!data.task_id) {
        // 未配置降级（quant 未建任务）
        if (data.valid === false && data.error) {
          setNotConfigured(true);
        } else {
          setError("生成服务不可用，请稍后重试");
        }
        return;
      }
      const taskId = data.task_id;
      taskRef.current = { id: taskId, cancelled: false };
      let failures = 0;
      while (true) {
        await sleep(POLL_INTERVAL_MS);
        const task = taskRef.current;
        if (!task || task.cancelled || task.id !== taskId) return;
        let state: AITaskState | null = null;
        try {
          const pollRes = await fetch(`/api/quant/ai-task/${taskId}`);
          if (pollRes.ok) state = (await pollRes.json()) as AITaskState;
        } catch {
          state = null;
        }
        if (!state) {
          failures += 1;
          if (failures >= POLL_RETRY_WARN) setReconnecting(true);
          if (failures >= POLL_RETRY_GIVEUP) {
            setReconnecting(false);
            setError("生成服务连接中断，请重新发起");
            return;
          }
          continue;
        }
        failures = 0;
        setReconnecting(false);
        if (state.status === "done") {
          const final = state.result;
          if (final?.valid && final.code) {
            setCode(final.code);
            setGeneratedMeta(final.meta ?? null);
            // 调整后 META.id 可能改名：loadedId 仍指向原策略；
            // dirty 保持：从已有策略载入（dirty=false）→ AI 调整 → 可直接保存覆盖原策略
            setSavedId(null);
          } else if (final && !final.valid && final.error) {
            setError(final.error);
            if (final.code) setCode(final.code);
          } else {
            setError("生成服务返回为空");
          }
          return;
        }
        if (state.status === "cancelled") return;
        if (state.status === "failed") {
          setError(state.error ?? "生成执行失败");
          return;
        }
      }
    } catch {
      setError("生成请求失败，请检查网络后重试");
    } finally {
      setBusy(false);
    }
  }

  function generate() {
    if (!description.trim() || busy) return;
    void runTask("/api/quant/ai-generate", {
      description: description.trim(),
    });
  }

  function tweak() {
    if (!description.trim() || !code.trim() || busy) return;
    void runTask("/api/quant/ai-tweak", {
      code,
      description: description.trim(),
    });
  }

  /** 停止生成：标记本地取消（停止轮询），后端取消幂等尽力而为 */
  function stop() {
    const task = taskRef.current;
    if (!task) return;
    task.cancelled = true;
    fetch(`/api/quant/ai-task/${task.id}/cancel`, { method: "POST" }).catch(
      () => {}
    );
    setBusy(false);
  }

  async function save() {
    if (!code.trim() || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      const payload: Record<string, string> = { code };
      // 从已有策略载入且 META.id 未变 → 覆盖原策略（builtin 会被后端 409 拦下，
      // 提示改 id 另存）；META.id 变了 → 改名保存（后端按 overwrite_id 移动文件）
      if (loadedId) {
        payload.overwrite_id = loadedId;
      }
      const res = await fetch("/api/quant/strategy-save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = (await res.json().catch(() => ({}))) as {
        saved?: boolean;
        strategy_id?: string;
        detail?: string;
        error?: string;
      };
      if (!res.ok || !data.saved) {
        setSaveError(data.detail ?? data.error ?? "保存失败，请稍后重试");
        return;
      }
      setSavedId(data.strategy_id ?? null);
      setLoadedId(data.strategy_id ?? null);
      setLoadedSource(
        (data.strategy_id ?? "").startsWith("ai_") ? "ai" : "custom"
      );
      setDirty(false);
      onSaved?.();
    } catch {
      setSaveError("保存请求失败，请检查网络后重试");
    } finally {
      setSaving(false);
    }
  }

  const isBuiltinLoaded = loadedSource === "builtin";
  const hasCode = code.trim().length > 0;
  const canTweak = hasCode && description.trim().length >= 4;

  return (
    <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">策略来源与调整</CardTitle>
          <CardDescription>
            新建、选取已有或导入策略，手动编辑或交给 AI 调整
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label>来源</Label>
            <div className="flex gap-2">
              {MODE_OPTIONS.map((opt) => (
                <Button
                  key={opt.value}
                  type="button"
                  variant={mode === opt.value ? "default" : "outline"}
                  size="sm"
                  className="flex-1"
                  disabled={busy}
                  onClick={() => setMode(opt.value)}
                >
                  {opt.value === "create" && <SparkleIcon />}
                  {opt.value === "existing" && <FolderOpenIcon />}
                  {opt.value === "import" && <UploadSimpleIcon />}
                  {opt.label}
                </Button>
              ))}
            </div>
          </div>

          {mode === "existing" && (
            <div className="space-y-1.5">
              <Label htmlFor="quant-ai-pick">选择策略</Label>
              <Select
                value={selectedId}
                onValueChange={(v: string | null) => {
                  const id = v ?? "";
                  setSelectedId(id);
                  if (id) void loadExisting(id);
                }}
                disabled={busy || strategiesLoading || strategies.length === 0}
              >
                <SelectTrigger id="quant-ai-pick" className="w-full">
                  <SelectValue
                    placeholder={
                      strategiesLoading ? "加载策略列表…" : "选择策略"
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {strategies.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {mode === "import" && (
            <div className="space-y-1.5">
              <Label htmlFor="quant-ai-import">策略文件（.py）</Label>
              <input
                ref={fileInputRef}
                id="quant-ai-import"
                type="file"
                accept=".py,text/x-python,text/plain"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void importFile(f);
                  e.target.value = "";
                }}
              />
              <Button
                type="button"
                variant="outline"
                className="w-full"
                disabled={busy}
                onClick={() => fileInputRef.current?.click()}
              >
                <UploadSimpleIcon />
                选择本地策略文件
              </Button>
            </div>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="quant-ai-desc">
              {mode === "create" ? "策略描述" : "调整要求"}
            </Label>
            <Textarea
              id="quant-ai-desc"
              placeholder={
                mode === "create"
                  ? "例：20 日均线上穿 60 日均线时买入，跌破 20 日均线时卖出，止损 8%"
                  : "例：把止损从 8% 收紧到 5%，并加入成交量放大过滤"
              }
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={busy}
              rows={5}
            />
          </div>

          {busy ? (
            <div className="flex gap-2">
              <Button className="flex-1" disabled>
                <CircleNotchIcon className="animate-spin" />
                {reconnecting ? "连接中断，重试中…" : "AI 处理中…"}
              </Button>
              <Button variant="outline" onClick={stop}>
                <StopIcon />
                停止
              </Button>
            </div>
          ) : (
            <div className="flex gap-2">
              {mode === "create" && (
                <Button
                  className="flex-1"
                  onClick={generate}
                  disabled={description.trim().length < 4}
                >
                  <SparkleIcon />
                  生成
                </Button>
              )}
              {mode !== "create" && (
                <Button
                  className="flex-1"
                  onClick={tweak}
                  disabled={!canTweak}
                >
                  <SparkleIcon />
                  AI 调整
                </Button>
              )}
              {mode === "create" && hasCode && (
                <Button
                  variant="outline"
                  onClick={tweak}
                  disabled={!canTweak}
                >
                  基于当前代码调整
                </Button>
              )}
            </div>
          )}

          {generatedMeta && (
            <div className="space-y-2 rounded-lg border p-3">
              <div className="text-sm font-medium">
                {generatedMeta.name ?? generatedMeta.id ?? "生成策略"}
              </div>
              {typeof generatedMeta.description === "string" && (
                <p className="text-xs text-muted-foreground">
                  {generatedMeta.description}
                </p>
              )}
              {Array.isArray(generatedMeta.tags) && (
                <div className="flex flex-wrap gap-1.5">
                  {generatedMeta.tags.map((tag) => (
                    <Badge key={String(tag)} variant="outline">
                      {String(tag)}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          )}

          {isBuiltinLoaded && (
            <p className="text-xs text-muted-foreground">
              内置策略只读：编辑后保存需改 META.id 另存为新策略
            </p>
          )}
          {savedId && (
            <p className="text-xs text-muted-foreground">
              已保存为{" "}
              <span className="font-medium text-foreground">{savedId}</span>
              ，可在回测 / 选股 Tab 的策略列表中选用
            </p>
          )}
          {saveError && <EmptyState title={saveError} compact />}
          {error && !notConfigured && <EmptyState title={error} compact />}
          {notConfigured && (
            <EmptyState
              title="AI 未配置"
              description="需在 quant 容器配置 AI_API_KEY 环境变量后重试"
              compact
            />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-2">
            <div className="space-y-1">
              <CardTitle className="text-sm">策略代码</CardTitle>
              {busy && (
                <CardDescription>
                  AI 正在生成 / 调整策略代码，一般需要 1-2 分钟…
                </CardDescription>
              )}
            </div>
            {hasCode && (
              <Button
                variant="outline"
                size="sm"
                onClick={save}
                disabled={saving || busy || (!dirty && savedId !== null)}
              >
                {saving ? (
                  <CircleNotchIcon className="animate-spin" />
                ) : (
                  <FloppyDiskIcon />
                )}
                {saving ? "保存中…" : savedId && !dirty ? "已保存" : "保存到策略库"}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {(busy && !hasCode) || loadingCode ? (
            <div className="space-y-2">
              {Array.from({ length: 10 }).map((_, i) => (
                <Skeleton key={i} className="h-4 w-full" />
              ))}
            </div>
          ) : hasCode ? (
            <Textarea
              aria-label="策略代码编辑器"
              className="h-[520px] resize-none rounded-lg border bg-muted/30 p-4 font-mono text-xs leading-relaxed"
              value={code}
              onChange={(e) => {
                setCode(e.target.value);
                setDirty(true);
                setSavedId(null);
              }}
              disabled={busy}
              spellCheck={false}
            />
          ) : (
            <EmptyState
              title="从左侧新建、选取或导入策略"
              description="策略代码会显示在这里，可手动编辑或交给 AI 调整"
              compact
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
