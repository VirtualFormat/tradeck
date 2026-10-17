"use client";

/**
 * 参数优化 / 步进优化共享配置区
 * 标的池 / 日期区间 / 参数网格（数值参数 min/max/step 三输入行）表单，
 * optimizer-tab 与 walkforward-tab 复用，差异（优化目标 / 折区间天数）由子组件注入
 */
import { CalendarIcon } from "@phosphor-icons/react";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import type { ParamGridRange, StrategyDef } from "./types";

/** 标的池 universe 选项（全部量化页签共享：回测/选股/优化/步进）。
 *  custom 为「自选标的」——选中时展开标的输入框，payload 传 symbols 不传 universe。
 *  cn/all 为全市场重档位，回测页签的 localStorage 记忆恢复会过滤（见 backtest-tab）。 */
export const UNIVERSE_OPTIONS = [
  { value: "hs300", label: "沪深300 成分" },
  { value: "csi500", label: "中证500 成分" },
  { value: "tracked", label: "tracked 100 只" },
  { value: "cn", label: "A 股全市场" },
  { value: "all", label: "全部（A 股全市场 + tracked 美港）" },
  { value: "custom", label: "自选标的" },
] as const;
export type UniverseValue = (typeof UNIVERSE_OPTIONS)[number]["value"];

/** 标的输入框 placeholder 跟随选股池档位（留空时实际生效的池子） */
export const UNIVERSE_PLACEHOLDER: Record<UniverseValue, string> = {
  hs300: "留空 = 沪深300 成分（可逗号分隔自定义）",
  csi500: "留空 = 中证500 成分（可逗号分隔自定义）",
  tracked: "留空 = tracked 100 只（可逗号分隔自定义）",
  cn: "留空 = A 股全市场（可逗号分隔自定义）",
  all: "留空 = A 股全市场 + tracked 美港（可逗号分隔自定义）",
  custom: "逗号分隔，如 600519.SH, 000001.SZ",
};

/** Date → YYYY-MM-DD */
export function fmtDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** 默认优化目标（搜索收益 + 风险平衡） */
export const DEFAULT_OBJECTIVE = "sharpe";

export interface OptConfigState {
  symbolsInput: string;
  setSymbolsInput: (v: string) => void;
  universe: UniverseValue;
  setUniverse: (v: UniverseValue) => void;
  startDate: string;
  setStartDate: (v: string) => void;
  endDate: string;
  setEndDate: (v: string) => void;
  grid: Record<string, ParamGridRange>;
  setGridField: (
    paramId: string,
    field: "min" | "max" | "step",
    value: string
  ) => void;
  /** 网格是否至少含一条完整区间（min/max/step 都填） */
  hasGridRange: boolean;
  disabled?: boolean;
}

interface OptimizeConfigFieldsProps {
  state: OptConfigState;
  strategy: StrategyDef | null;
}

/** 数值参数网格行：type 为 float/int（或缺省）且有 min/max 的 schema 参数 */
export function gridParams(strategy: StrategyDef | null) {
  return (strategy?.params ?? []).filter(
    (p) => p.type !== "bool" && p.type !== "select"
  );
}

export function buildDefaultGrid(
  strategy: StrategyDef | null
): Record<string, ParamGridRange> {
  const grid: Record<string, ParamGridRange> = {};
  for (const p of gridParams(strategy)) {
    grid[p.id] = {
      min: p.min,
      max: p.max,
      step: p.step ?? (p.type === "int" ? 1 : undefined),
    };
  }
  return grid;
}

/** 网格是否有一条完整区间（运行优化/步进优化的前置校验） */
export function gridHasRange(grid: Record<string, ParamGridRange>): boolean {
  return Object.values(grid).some(
    (r) => r.min != null && r.max != null && r.step != null
  );
}

/** 共享表单：标的 + universe + 日期区间 + 参数网格（策略选择器由父组件放前面） */
export function OptimizeConfigFields({
  state,
  strategy,
}: OptimizeConfigFieldsProps) {
  const {
    symbolsInput,
    setSymbolsInput,
    universe,
    setUniverse,
    startDate,
    setStartDate,
    endDate,
    setEndDate,
    grid,
    setGridField,
    disabled,
  } = state;
  const params = gridParams(strategy);

  return (
    <>
      <div className="space-y-1.5">
        <Label htmlFor="quant-opt-universe">标的池</Label>
        <Select
          value={universe}
          onValueChange={(v: string | null) =>
            setUniverse((v as UniverseValue) ?? "hs300")
          }
          disabled={disabled}
        >
          <SelectTrigger id="quant-opt-universe" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {UNIVERSE_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {universe === "custom" && (
        <div className="space-y-1.5">
          <Label htmlFor="quant-opt-symbols">标的（逗号分隔）</Label>
          <Input
            id="quant-opt-symbols"
            placeholder={UNIVERSE_PLACEHOLDER.custom}
            value={symbolsInput}
            onValueChange={(v) => setSymbolsInput(v)}
            disabled={disabled}
          />
        </div>
      )}
      <OptDateRange
        startDate={startDate}
        setStartDate={setStartDate}
        endDate={endDate}
        setEndDate={setEndDate}
        disabled={disabled}
      />
      {params.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-fg-dim">
            参数网格（min / max / step，至少填一条完整区间）
          </p>
          {params.map((p) => {
            const row = grid[p.id] ?? {};
            const base = `quant-opt-grid-${p.id}`;
            return (
              <div key={p.id} className="space-y-1.5">
                <Label>{p.label ?? p.id}</Label>
                <div className="grid grid-cols-3 gap-2">
                  {(["min", "max", "step"] as const).map((field) => (
                    <Input
                      key={field}
                      id={`${base}-${field}`}
                      type="number"
                      aria-label={`${p.label ?? p.id} ${field}`}
                      placeholder={
                        row[field] != null ? String(row[field]) : field
                      }
                      value={row[field] ?? ""}
                      onValueChange={(v) => setGridField(p.id, field, v)}
                      disabled={disabled}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

interface OptDateRangeProps {
  startDate: string;
  setStartDate: (v: string) => void;
  endDate: string;
  setEndDate: (v: string) => void;
  disabled?: boolean;
}

/** 起止日期选择（Popover + Calendar，与回测页签同款交互） */
export function OptDateRange({
  startDate,
  setStartDate,
  endDate,
  setEndDate,
  disabled,
}: OptDateRangeProps) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {(
        [
          ["开始日期", "start", startDate, setStartDate],
          ["结束日期", "end", endDate, setEndDate],
        ] as const
      ).map(([label, key, value, setValue]) => (
        <div key={key} className="space-y-1.5">
          <Label htmlFor={`quant-opt-${key}`}>{label}</Label>
          <Popover>
            <PopoverTrigger
              render={
                <Button
                  id={`quant-opt-${key}`}
                  variant="outline"
                  className="w-full justify-start gap-1.5 font-normal"
                  disabled={disabled}
                />
              }
            >
              <CalendarIcon className="size-3.5 text-fg-dim" />
              {value || (
                <span className="text-muted-foreground">
                  {key === "end" ? "默认今天" : "选择日期"}
                </span>
              )}
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <Calendar
                mode="single"
                selected={value ? new Date(`${value}T00:00:00`) : undefined}
                onSelect={(d) => setValue(d ? fmtDate(d) : "")}
                disabled={(date) => date > new Date()}
              />
            </PopoverContent>
          </Popover>
        </div>
      ))}
    </div>
  );
}
