"use client";

/**
 * Tab 3「AI 策略生成」：描述 → SSE 流式生成策略代码
 * 后端未配置 AI 时返回非流式 JSON {valid:false, error}，这里按 Content-Type 分支处理。
 * 保存到 AI 策略库的后端接口属 E4，本期不渲染保存按钮（见下方注释）。
 */
import { useEffect, useRef, useState } from "react";
import { SparkleIcon } from "@phosphor-icons/react";

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

/** 从 SSE 缓冲中解析 token：兼容 data: 行与纯文本 token 流 */
function extractChunkText(chunk: string): string {
  if (!chunk.includes("data:")) return chunk;
  return chunk
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).replace(/^ /, ""))
    .filter((line) => line !== "[DONE]")
    .join("\n");
}

/** 流结束后从累计文本中提取最终 JSON 结果（去掉 markdown 围栏） */
function parseFinalResult(text: string): AIResult | null {
  const cleaned = text
    .replace(/```(?:json)?/g, "")
    .trim();
  const match = cleaned.match(/\{[\s\S]*"valid"[\s\S]*\}/);
  if (!match) return null;
  try {
    return JSON.parse(match[0]) as AIResult;
  } catch {
    return null;
  }
}

export function AIGenerateTab() {
  const [description, setDescription] = useState("");
  const [generating, setGenerating] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [result, setResult] = useState<AIResult | null>(null);
  const [notConfigured, setNotConfigured] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // 卸载时中断未完成的流
  useEffect(() => () => abortRef.current?.abort(), []);

  async function generate() {
    if (!description.trim() || generating) return;
    setGenerating(true);
    setStreamText("");
    setResult(null);
    setError(null);
    setNotConfigured(false);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const res = await fetch("/api/quant/ai-generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description: description.trim() }),
        signal: controller.signal,
      });
      const contentType = res.headers.get("Content-Type") ?? "";
      if (!res.ok) {
        setError("生成服务不可用，请稍后重试");
        return;
      }
      if (contentType.includes("application/json")) {
        // 非流式降级：AI 未配置等场景
        const data = (await res.json()) as AIResult;
        if (!data.valid && data.error) {
          setNotConfigured(true);
          setResult(data);
        } else {
          setResult(data);
        }
        return;
      }
      if (!res.body) {
        setError("生成服务返回为空");
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let accumulated = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        accumulated += extractChunkText(decoder.decode(value, { stream: true }));
        setStreamText(accumulated);
      }
      const final = parseFinalResult(accumulated);
      if (final) {
        setResult(final);
        if (!final.valid && final.error) setError(final.error);
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError("生成请求失败，请检查网络后重试");
      }
    } finally {
      setGenerating(false);
    }
  }

  const displayCode = result?.valid && result.code ? result.code : streamText;

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
          <Button
            className="w-full"
            onClick={generate}
            disabled={generating || description.trim().length < 4}
          >
            <SparkleIcon />
            {generating ? "生成中…" : "生成"}
          </Button>
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
              {/* 保存到 AI 策略库的后端接口属 E4，落地前不渲染保存按钮 */}
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
            <CardDescription>正在流式生成，代码实时输出…</CardDescription>
          )}
        </CardHeader>
        <CardContent>
          {notConfigured ? (
            <EmptyState
              title="AI 未配置"
              description="需在 quant 容器配置 AI_API_KEY 环境变量后重试"
              compact
            />
          ) : generating && !streamText ? (
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
