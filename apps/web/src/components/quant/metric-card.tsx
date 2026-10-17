"use client";

/**
 * 回测核心指标卡：label + 问号 tooltip（指标解释）+ 数值（收益类正负着色）
 */
import { QuestionIcon } from "@phosphor-icons/react";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface MetricCardProps {
  label: string;
  /** tooltip 里的指标解释文案；不传则不显示问号 */
  hint?: string;
  value: string;
  /** 收益类数值（正红负绿）；不传或 null 用默认前景色 */
  colored?: number | null;
}

export function MetricCard({ label, hint, value, colored }: MetricCardProps) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border bg-muted/30 p-3">
      <span className="flex items-center gap-1 text-xs text-muted-foreground">
        {label}
        {hint && (
          <Tooltip>
            <TooltipTrigger
              render={
                <span className="inline-flex cursor-help text-muted-foreground/70 hover:text-muted-foreground" />
              }
            >
              <QuestionIcon size={12} />
            </TooltipTrigger>
            <TooltipContent className="max-w-64">{hint}</TooltipContent>
          </Tooltip>
        )}
      </span>
      <span
        className="text-lg font-semibold tabular-nums"
        style={
          colored == null || colored === 0
            ? undefined
            : { color: colored > 0 ? "var(--up)" : "var(--down)" }
        }
      >
        {value}
      </span>
    </div>
  );
}
