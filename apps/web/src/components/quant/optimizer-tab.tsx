"use client";

/**
 * Tab「参数优化」：左侧策略 / 标的池 / 区间 / 优化目标 / 参数网格，
 * 右侧最优参数卡 + 组合计数 + 排名表（前 50 行）
 * 数据走 POST /api/quant/optimize 代理；422 透传后端 detail 文案
 */
import { useState } from "react";
import { PlayIcon } from "@phosphor-icons/react";

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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import {
  buildDefaultGrid,
  DEFAULT_OBJECTIVE,
  gridHasRange,
  OptimizeConfigFields,
  type UniverseValue,
} from "./optimize-config";
import { StrategyPicker } from "./strategy-picker";
import {
  fmtNum,
  fmtPct,
  objectiveLabel,
  OBJECTIVE_OPTIONS,
  OPTIMIZE_TABLE_MAX_ROWS,
  parseSymbols,
  pnlStyle,
  type OptimizeResult,
  type ParamGridRange,
  type StrategyDef,
} from "./types";

interface OptimizerTabProps {
  strategies: StrategyDef[];
  strategiesLoading: boolean;
  strategyId: string;
  onStrategyChange: (id: string) => void;
}

export function OptimizerTab({
  strategies,
  strategiesLoading,
  strategyId,
  onStrategyChange,
}: OptimizerTabProps) {
  const [symbolsInput, setSymbolsInput] = useState("");
  const [universe, setUniverse] = useState<UniverseValue>("tracked");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [objective, setObjective] = useState(DEFAULT_OBJECTIVE);
  const [grid, setGrid] = useState<Record<string, ParamGridRange>>({});
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<OptimizeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const strategy = strategies.find((s) => s.id === strategyId) ?? null;
  const symbols = parseSymbols(symbolsInput);
  const hasCustomSymbols = symbols.length > 0;

  /** 切策略：参数网格重置为新策略 schema 默认 min/max/step */
  function handleStrategyChange(id: string) {
    onStrategyChange(id);
    setGrid(buildDefaultGrid(strategies.find((s) => s.id === id) ?? null));
  }

  function setGridField(
    paramId: string,
    field: "min" | "max" | "step",
    value: string
  ) {
    const n = value === "" ? undefined : Number(value);
    setGrid((prev) => ({
      ...prev,
      [paramId]: {
        ...prev[paramId],
        [field]: n != null && Number.isNaN(n) ? undefined : n,
      },
    }));
  }

  async function runOptimize() {
    if (!strategyId || !startDate || loading) return;
    setLoading(true);
    setError(null);
    // 网格：min/max/step 全填的走区间，否则该参数不优化（固定默认值）
    const param_grid: Record<
      string,
      { min: number; max: number; step: number }
    > = {};
    for (const [id, r] of Object.entries(grid)) {
      if (r.min != null && r.max != null && r.step != null) {
        param_grid[id] = { min: r.min, max: r.max, step: r.step };
      }
    }
    const payload = {
      strategy_id: strategyId,
      symbols: hasCustomSymbols ? symbols : null,
      universe: hasCustomSymbols ? undefined : universe,
      start: startDate,
      end: endDate || undefined,
      objective,
      param_grid,
    };
    try {
      const res = await fetch("/api/quant/optimize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        // P1-1：422（参数非法）与透传 detail 的 5xx 统一展示后端原因，
        // 无 detail 才落笼统文案（大网格跑几分钟属正常，勿误导为服务挂了）
        const data = await res.json().catch(() => null);
        if (data?.detail) {
          setError(String(data.detail));
          setResult(null);
          return;
        }
        setError("优化服务不可用，请稍后重试");
        setResult(null);
        return;
      }
      setResult((await res.json()) as OptimizeResult);
    } catch {
      setError("优化请求失败，请检查网络后重试");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">优化设置</CardTitle>
          <CardDescription>网格搜索最优参数组合</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <StrategyPicker
            strategies={strategies}
            strategyId={strategyId}
            onStrategyChange={handleStrategyChange}
            disabled={strategiesLoading || loading}
          />
          <OptimizeConfigFields
            state={{
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
              hasGridRange: gridHasRange(grid),
              disabled: loading,
            }}
            strategy={strategy}
          />
          <div className="space-y-1.5">
            <Label htmlFor="quant-opt-objective">优化目标</Label>
            <Select
              value={objective}
              onValueChange={(v: string | null) =>
                setObjective(v ?? DEFAULT_OBJECTIVE)
              }
              disabled={loading}
            >
              <SelectTrigger id="quant-opt-objective" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {OBJECTIVE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            className="w-full"
            onClick={runOptimize}
            disabled={
              loading || !strategyId || !startDate || !gridHasRange(grid)
            }
          >
            <PlayIcon />
            {loading ? "优化中…" : "运行优化"}
          </Button>
        </CardContent>
      </Card>

      {loading ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">优化结果</CardTitle>
            <CardDescription>网格搜索进行中，组合多时耗时较长</CardDescription>
          </CardHeader>
          <CardContent>
            <OptimizeResultSkeleton />
          </CardContent>
        </Card>
      ) : error ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">优化结果</CardTitle>
          </CardHeader>
          <CardContent>
            <EmptyState title={error} compact />
          </CardContent>
        </Card>
      ) : result ? (
        <OptimizeResultView result={result} objective={objective} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">优化结果</CardTitle>
          </CardHeader>
          <CardContent>
            <EmptyState
              title="配置参数网格并运行优化"
              description="左侧选择策略与优化目标，至少为一条参数填完整 min / max / step"
              compact
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function OptimizeResultSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-9 w-full" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-[320px] w-full" />
    </div>
  );
}

function OptimizeResultView({
  result,
  objective,
}: {
  result: OptimizeResult;
  objective: string;
}) {
  // 排名表参数列：取结果里出现过的参数键（保持 best_params 的键序）
  const paramKeys = Object.keys(result.best_params ?? {});
  const rows = result.results.slice(0, OPTIMIZE_TABLE_MAX_ROWS);
  const bestParams = result.best_params ?? {};

  return (
    <div className="space-y-4">
      {/* 概要条：组合 / 成功 / 失败计数 + 耗时 */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-2 py-3">
          <Badge>目标 {objectiveLabel(objective)}</Badge>
          <Badge variant="outline" className="tabular-nums">
            组合 {result.n_combinations}
          </Badge>
          <Badge variant="outline" className="tabular-nums">
            成功 {result.n_completed}
          </Badge>
          <Badge
            variant="outline"
            className="tabular-nums"
            style={
              result.n_errors > 0
                ? {
                    color: "var(--warn)",
                    borderColor:
                      "color-mix(in oklch, var(--warn) 50%, transparent)",
                  }
                : undefined
            }
          >
            失败 {result.n_errors}
          </Badge>
          {result.elapsed_ms != null && (
            <span className="text-[11px] text-muted-foreground/70 tabular-nums">
              耗时 {(result.elapsed_ms / 1000).toFixed(1)}s
            </span>
          )}
        </CardContent>
      </Card>

      {/* 最优参数卡 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">最优参数</CardTitle>
          <CardDescription>
            目标值{" "}
            <span className="tabular-nums">{fmtNum(result.best_score, 4)}</span>
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          {Object.keys(bestParams).length === 0 ? (
            <EmptyState title="无最优参数（全部组合失败）" compact />
          ) : (
            Object.entries(bestParams).map(([key, value]) => (
              <Badge key={key} variant="secondary" className="tabular-nums">
                {key} = {String(value)}
              </Badge>
            ))
          )}
        </CardContent>
      </Card>

      {/* 排名表（前 50 行） */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">排名</CardTitle>
          <CardDescription>
            按目标值排序，展示前 {OPTIMIZE_TABLE_MAX_ROWS} 行
          </CardDescription>
        </CardHeader>
        <CardContent>
          {rows.length === 0 ? (
            <EmptyState title="无完成的组合" compact />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">#</TableHead>
                  {paramKeys.map((key) => (
                    <TableHead key={key} className="text-right">
                      {key}
                    </TableHead>
                  ))}
                  <TableHead className="text-right">
                    {objectiveLabel(objective)}
                  </TableHead>
                  <TableHead className="text-right">总收益</TableHead>
                  <TableHead className="text-right">夏普</TableHead>
                  <TableHead className="text-right">最大回撤</TableHead>
                  <TableHead className="text-right">交易数</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.rank}>
                    <TableCell className="tabular-nums text-muted-foreground">
                      {row.rank}
                    </TableCell>
                    {paramKeys.map((key) => (
                      <TableCell key={key} className="text-right tabular-nums">
                        {row.params[key] != null
                          ? String(row.params[key])
                          : "—"}
                      </TableCell>
                    ))}
                    <TableCell
                      className="text-right tabular-nums"
                      style={pnlStyle(row.objective_raw)}
                    >
                      {fmtNum(row.objective_raw, 4)}
                    </TableCell>
                    <TableCell
                      className="text-right tabular-nums"
                      style={pnlStyle(row.total_return)}
                    >
                      {fmtPct(row.total_return)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtNum(row.sharpe)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtPct(row.max_drawdown)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.trades ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
