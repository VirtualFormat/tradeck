"use client";

/**
 * Tab「步进优化」：walk-forward 样本外验证
 * 左侧策略 / 标的池 / 区间 / train-test-step 天数 / 优化目标 / 参数网格，
 * 右侧复利样本外收益 + 折数 + 每折明细表（区间 / 参数 / OOS 收益 / 夏普）
 * 数据走 POST /api/quant/walkforward 代理；422 透传后端 detail 文案
 */
import { useState } from "react";
import { CaretDownIcon, PlayIcon } from "@phosphor-icons/react";

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
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
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
  foldOosReturn,
  foldOosSharpe,
  foldParams,
  objectiveLabel,
  OBJECTIVE_OPTIONS,
  parseSymbols,
  pnlStyle,
  type ParamGridRange,
  type StrategyDef,
  type WalkforwardResult,
} from "./types";

interface WalkforwardTabProps {
  strategies: StrategyDef[];
  strategiesLoading: boolean;
  strategyId: string;
  onStrategyChange: (id: string) => void;
}

export function WalkforwardTab({
  strategies,
  strategiesLoading,
  strategyId,
  onStrategyChange,
}: WalkforwardTabProps) {
  const [symbolsInput, setSymbolsInput] = useState("");
  const [universe, setUniverse] = useState<UniverseValue>("hs300");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [trainDays, setTrainDays] = useState("180");
  const [testDays, setTestDays] = useState("60");
  const [stepDays, setStepDays] = useState("60");
  const [objective, setObjective] = useState(DEFAULT_OBJECTIVE);
  const [grid, setGrid] = useState<Record<string, ParamGridRange>>({});
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<WalkforwardResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const strategy = strategies.find((s) => s.id === strategyId) ?? null;
  const symbols = parseSymbols(symbolsInput);
  // 标的池=自选标的时 payload 传 symbols 不传 universe（显式优先语义与后端互斥校验一致）
  const isCustomPool = universe === "custom";

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

  async function runWalkforward() {
    if (!strategyId || !startDate || loading) return;
    setLoading(true);
    setError(null);
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
      symbols: isCustomPool && symbols.length > 0 ? symbols : null,
      universe: isCustomPool ? undefined : universe,
      start: startDate,
      end: endDate || undefined,
      train_days: Number(trainDays) || undefined,
      test_days: Number(testDays) || undefined,
      step_days: Number(stepDays) || undefined,
      objective,
      param_grid,
    };
    try {
      const res = await fetch("/api/quant/walkforward", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        // P1-1：透传 detail 的非 2xx 统一展示后端原因，无 detail 才落笼统文案
        const data = await res.json().catch(() => null);
        if (data?.detail) {
          setError(String(data.detail));
          setResult(null);
          return;
        }
        setError("步进优化服务不可用，请稍后重试");
        setResult(null);
        return;
      }
      setResult((await res.json()) as WalkforwardResult);
    } catch {
      setError("步进优化请求失败，请检查网络后重试");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">步进优化设置</CardTitle>
          <CardDescription>滚动窗口训练 + 样本外验证</CardDescription>
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
          {/* 折区间天数：train / test / step */}
          <div className="grid grid-cols-3 gap-2">
            <div className="space-y-1.5">
              <Label htmlFor="quant-wf-train">训练天数</Label>
              <Input
                id="quant-wf-train"
                type="number"
                min={20}
                step={1}
                value={trainDays}
                onValueChange={(v) => setTrainDays(v)}
                disabled={loading}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="quant-wf-test">测试天数</Label>
              <Input
                id="quant-wf-test"
                type="number"
                min={5}
                step={1}
                value={testDays}
                onValueChange={(v) => setTestDays(v)}
                disabled={loading}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="quant-wf-step">步进天数</Label>
              <Input
                id="quant-wf-step"
                type="number"
                min={5}
                step={1}
                value={stepDays}
                onValueChange={(v) => setStepDays(v)}
                disabled={loading}
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="quant-wf-objective">优化目标</Label>
            <Select
              value={objective}
              onValueChange={(v: string | null) =>
                setObjective(v ?? DEFAULT_OBJECTIVE)
              }
              disabled={loading}
            >
              <SelectTrigger id="quant-wf-objective" className="w-full">
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
            onClick={runWalkforward}
            disabled={
              loading || !strategyId || !startDate || !gridHasRange(grid)
            }
          >
            <PlayIcon />
            {loading ? "步进优化中…" : "运行步进优化"}
          </Button>
        </CardContent>
      </Card>

      {loading ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">步进优化结果</CardTitle>
            <CardDescription>逐折训练与样本外回测中，耗时较长</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-[320px] w-full" />
            </div>
          </CardContent>
        </Card>
      ) : error ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">步进优化结果</CardTitle>
          </CardHeader>
          <CardContent>
            <EmptyState title={error} compact />
          </CardContent>
        </Card>
      ) : result ? (
        <WalkforwardResultView result={result} objective={objective} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">步进优化结果</CardTitle>
          </CardHeader>
          <CardContent>
            <EmptyState
              title="配置折区间并运行步进优化"
              description="左侧设置训练 / 测试 / 步进天数与参数网格后点击「运行步进优化」"
              compact
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function WalkforwardResultView({
  result,
  objective,
}: {
  result: WalkforwardResult;
  objective: string;
}) {
  const folds = result.folds ?? [];
  return (
    <div className="space-y-4">
      {/* 概要条：复利样本外收益 + 折数 + 耗时 */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-2 py-3">
          <Badge>目标 {objectiveLabel(objective)}</Badge>
          <Badge variant="secondary">
            复利样本外收益{" "}
            <span
              className="tabular-nums"
              style={pnlStyle(result.compounded_oos_return)}
            >
              {fmtPct(result.compounded_oos_return)}
            </span>
          </Badge>
          <Badge variant="outline" className="tabular-nums">
            完成 {result.n_folds} / 计划 {result.n_planned_folds} 折
          </Badge>
          {result.degradation != null && (
            <Badge
              variant="outline"
              style={
                result.degradation > 0
                  ? {
                      color: "var(--warn)",
                      borderColor:
                        "color-mix(in oklch, var(--warn) 50%, transparent)",
                    }
                  : undefined
              }
            >
              IS→OOS 退化 {fmtPct(result.degradation)}
            </Badge>
          )}
          {result.consistency != null && (
            <Badge variant="outline" className="tabular-nums">
              一致性 {fmtPct(result.consistency)}
            </Badge>
          )}
          {result.elapsed_ms != null && (
            <span className="text-[11px] text-muted-foreground/70 tabular-nums">
              耗时 {(result.elapsed_ms / 1000).toFixed(1)}s
            </span>
          )}
        </CardContent>
      </Card>

      {/* 折叠失败明细（P1-2：skipped 不可见会让用户误判为 bug） */}
      {(result.n_skipped ?? 0) > 0 && (
        <Card>
          <CardContent className="py-3">
            <Collapsible>
              <CollapsibleTrigger
                render={
                  <Button
                    variant="ghost"
                    size="sm"
                    className="w-full justify-start gap-1.5 text-xs text-muted-foreground"
                  />
                }
              >
                <CaretDownIcon />
                跳过 {result.n_skipped} 折（展开查看原因）
              </CollapsibleTrigger>
              <CollapsibleContent>
                <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
                  {(result.skipped ?? []).map((s, i) => (
                    <li key={i} className="tabular-nums">
                      折 {(s.index ?? i) + 1}：
                      {s.reason ?? "训练未优化出参数"}
                    </li>
                  ))}
                </ul>
              </CollapsibleContent>
            </Collapsible>
          </CardContent>
        </Card>
      )}

      {/* 每折明细 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">每折明细</CardTitle>
          <CardDescription>
            每折训练区间网格寻优，测试区间样本外回测
          </CardDescription>
        </CardHeader>
        <CardContent>
          {folds.length === 0 ? (
            <EmptyState title="无完成的折" compact />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">折</TableHead>
                  <TableHead>训练区间</TableHead>
                  <TableHead>测试区间</TableHead>
                  <TableHead>该折参数</TableHead>
                  <TableHead className="text-right">OOS 收益</TableHead>
                  <TableHead className="text-right">OOS 夏普</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {folds.map((fold, i) => {
                  const params = foldParams(fold);
                  const oosReturn = foldOosReturn(fold);
                  return (
                    <TableRow key={i}>
                      <TableCell className="tabular-nums text-muted-foreground">
                        {i + 1}
                      </TableCell>
                      <TableCell className="tabular-nums text-xs">
                        {fold.train_start ?? "—"} ~ {fold.train_end ?? "—"}
                      </TableCell>
                      <TableCell className="tabular-nums text-xs">
                        {fold.test_start ?? "—"} ~ {fold.test_end ?? "—"}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(params).map(([key, value]) => (
                            <Badge
                              key={key}
                              variant="outline"
                              className="tabular-nums"
                            >
                              {key}={String(value)}
                            </Badge>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell
                        className="text-right tabular-nums"
                        style={pnlStyle(oosReturn)}
                      >
                        {fmtPct(oosReturn)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {fmtNum(foldOosSharpe(fold))}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
