"use client";

/**
 * AI 工具调用轨迹折叠卡
 * 流式中逐个追加；每条：工具名 + 状态点 + 耗时 + 参数/结果预览
 * 根节点 not-typeset，防 typeset 排版渗入 shadcn 组件
 */
import { WrenchIcon, CaretDownIcon } from "@phosphor-icons/react";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

export interface ToolCall {
  id: string;
  tool: string;
  arguments?: Record<string, unknown>;
  status: "running" | "ok" | "error";
  preview?: string;
  elapsed_ms?: number;
}

function StatusDot({ status }: { status: ToolCall["status"] }) {
  return (
    <span
      className={cn(
        "inline-block h-1.5 w-1.5 shrink-0 rounded-full",
        status === "running" && "animate-pulse bg-warn",
        status === "ok" && "bg-up",
        status === "error" && "bg-down"
      )}
    />
  );
}

function argsPreview(args?: Record<string, unknown>): string {
  if (!args) return "";
  const entries = Object.entries(args).slice(0, 3);
  return entries.map(([k, v]) => `${k}=${String(v)}`).join("  ");
}

export function ToolTrail({ calls }: { calls: ToolCall[] }) {
  if (calls.length === 0) return null;
  return (
    <Collapsible className="not-typeset" defaultOpen={false}>
      <CollapsibleTrigger className="group flex w-full items-center gap-2 rounded-md border bg-muted/40 px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted">
        <WrenchIcon className="h-3.5 w-3.5 shrink-0" />
        <span>工具调用 · {calls.length}</span>
        <CaretDownIcon className="ml-auto h-3.5 w-3.5 transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-1 space-y-1 rounded-md border bg-muted/20 p-2">
        {calls.map((c) => (
          <div key={c.id} className="flex items-start gap-2 text-xs">
            <StatusDot status={c.status} />
            <Badge variant="outline" className="shrink-0 font-mono text-[10px]">
              {c.tool}
            </Badge>
            <span className="min-w-0 flex-1 truncate text-muted-foreground">
              {c.status === "running" ? argsPreview(c.arguments) : c.preview || argsPreview(c.arguments)}
            </span>
            {typeof c.elapsed_ms === "number" && c.elapsed_ms > 0 && (
              <span className="shrink-0 tabular-nums text-muted-foreground/70">
                {(c.elapsed_ms / 1000).toFixed(1)}s
              </span>
            )}
          </div>
        ))}
      </CollapsibleContent>
    </Collapsible>
  );
}
