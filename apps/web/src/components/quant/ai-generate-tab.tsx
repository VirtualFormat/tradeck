"use client";

/**
 * Tab 3「AI 策略生成」：描述 → 任务化生成（POST 登记拿 task_id → 轮询终态）
 * 任务化动机：LLM 生成长代码常超 60s，同步等待会被 nginx/CF 砍成 504/524；
 * 任务脱离连接独立存活，掉线重连轮询即恢复。未配置 AI 时 POST 返回 200
 * {valid:false, error}（不建任务），按降级路径展示。
 * 生成成功后可保存到 AI 策略库（POST /api/quant/ai-save → quant strategies/ai/），
 * 保存的策略立即出现在回测/选股的策略列表（loader 每次请求重建注册表，热生效）。
 */
import { useEffect, useRef, useState } from "react";
import {
  CircleNotchIcon,
  FloppyDiskIcon,
  SparkleIcon,
  StopIcon,
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
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";

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

const POLL_INTERVAL_MS = 2000;
const POLL_RETRY_WARN = 3;
const POLL_RETRY_GIVEUP = 90;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function AIGenerateTab() {
  const [description, setDescription] = useState("");
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<AIResult | null>(null);
  const [notConfigured, setNotConfigured] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const taskRef = useRef<{ id: string; cancelled: boolean } | null>(null);

  // 卸载时标记本地取消（停止轮询渲染；后端任务 TTL 自动回收）
  useEffect(
    () => () => {
      if (taskRef.current) taskRef.current.cancelled = true;
    },
    []
  );

  async function generate() {
    if (!description.trim() || generating) return;
    setGenerating(true);
    setResult(null);
    setError(null);
    setNotConfigured(false);
    setSavedId(null);
    setSaveError(null);
    setReconnecting(false);
    try {
      // 登记任务（秒回）；未配置 AI 时返回 200 {valid:false, error} 走降级展示
      const res = await fetch("/api/quant/ai-generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description: description.trim() }),
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
          setResult(data);
        } else {
          setError("生成服务不可用，请稍后重试");
        }
        return;
      }
      // 轮询直至终态；连续失败计数用于「连接中断」提示
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
          if (final) {
            setResult(final);
            if (!final.valid && final.error) setError(final.error);
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
      setGenerating(false);
    }
  }

  /** 停止生成：标记本地取消（停止轮询），后端取消幂等尽力而为 */
  function stop() {
    const task = taskRef.current;
    if (!task) return;
    task.cancelled = true;
    fetch(`/api/quant/ai-task/${task.id}/cancel`, { method: "POST" }).catch(
      () => {}
    );
    setGenerating(false);
  }

  const displayCode = result?.valid && result.code ? result.code : null;

  async function save() {
    if (!result?.valid || !result.code || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      const res = await fetch("/api/quant/ai-save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: result.code }),
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
    } catch {
      setSaveError("保存请求失败，请检查网络后重试");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">策略思路</CardTitle>
          <CardDescription>
            用自然语言描述买卖规则，AI 生成策略代码
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="quant-ai-desc">策略描述</Label>
            <Textarea
              id="quant-ai-desc"
              placeholder="例：20 日均线上穿 60 日均线时买入，跌破 20 日均线时卖出，止损 8%"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={generating}
              rows={6}
            />
          </div>
          {generating ? (
            <div className="flex gap-2">
              <Button className="flex-1" disabled>
                <CircleNotchIcon className="animate-spin" />
                {reconnecting ? "连接中断，重试中…" : "生成中…"}
              </Button>
              <Button variant="outline" onClick={stop}>
                <StopIcon />
                停止
              </Button>
            </div>
          ) : (
            <Button
              className="w-full"
              onClick={generate}
              disabled={description.trim().length < 4}
            >
              <SparkleIcon />
              生成
            </Button>
          )}
          {result?.valid && result.meta && (
            <div className="space-y-2 rounded-lg border p-3">
              <div className="text-sm font-medium">
                {result.meta.name ?? result.meta.id ?? "生成策略"}
              </div>
              {typeof result.meta.description === "string" && (
                <p className="text-xs text-muted-foreground">
                  {result.meta.description}
                </p>
              )}
              {Array.isArray(result.meta.tags) && (
                <div className="flex flex-wrap gap-1.5">
                  {result.meta.tags.map((tag) => (
                    <Badge key={String(tag)} variant="outline">
                      {String(tag)}
                    </Badge>
                  ))}
                </div>
              )}
              {savedId ? (
                <p className="text-xs text-muted-foreground">
                  已保存为 <span className="font-medium text-foreground">{savedId}</span>，
                  可在回测 / 选股 Tab 的策略列表中选用
                </p>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full"
                  onClick={save}
                  disabled={saving}
                >
                  {saving ? (
                    <CircleNotchIcon className="animate-spin" />
                  ) : (
                    <FloppyDiskIcon />
                  )}
                  {saving ? "保存中…" : "保存到策略库"}
                </Button>
              )}
              {saveError && <EmptyState title={saveError} compact />}
            </div>
          )}
          {result && !result.valid && result.error && !notConfigured && (
            <EmptyState title={result.error} compact />
          )}
          {error && !notConfigured && <EmptyState title={error} compact />}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">生成代码</CardTitle>
          {generating && (
            <CardDescription>
              AI 正在生成策略代码，一般需要 1-2 分钟…
            </CardDescription>
          )}
        </CardHeader>
        <CardContent>
          {notConfigured ? (
            <EmptyState
              title="AI 未配置"
              description="需在 quant 容器配置 AI_API_KEY 环境变量后重试"
              compact
            />
          ) : generating ? (
            <div className="space-y-2">
              {Array.from({ length: 10 }).map((_, i) => (
                <Skeleton key={i} className="h-4 w-full" />
              ))}
            </div>
          ) : displayCode ? (
            <ScrollArea className="h-[480px] rounded-lg border bg-muted/30">
              <pre className="p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap">
                {displayCode}
              </pre>
            </ScrollArea>
          ) : (
            <EmptyState
              title="描述策略思路并生成"
              description="生成的策略代码将实时显示在这里"
              compact
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
