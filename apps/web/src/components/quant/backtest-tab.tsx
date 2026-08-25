"use client";

/**
 * Tab 1「策略回测」：策略选择 + 参数表单 + 标的/区间/资金 → 运行回测 → 统计卡片
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { StrategyParamsForm, StrategyPicker } from "./strategy-picker";
import {
  buildParamsPayload,
  fmtNum,
  fmtPct,
  parseSymbols,
  pnlStyle,
  type ParamValues,
  type StrategyDef,
} from "./types";

interface BacktestStats {
  total_return: number | null;
  annual_return: number | null;
  max_drawdown: number | null;
  sharpe: number | null;
  calmar: number | null;
  trades: number | null;
  win_rate: number | null;
  profit_loss_ratio: number | null;
  turnover: number | null;
  days: number | null;
  final_value: number | null;
  risk_free_rate?: number | null;
  unadjusted?: string[];
}

interface BacktestResult {
  stats: BacktestStats;
  strategy: string;
  symbols: string[];
  range: string[];
  unadjusted?: string[];
}

interface BacktestTabProps {
  strategies: StrategyDef[];
  strategiesLoading: boolean;
  strategyId: string;
  onStrategyChange: (id: string) => void;
  paramValues: ParamValues;
  onParamValuesChange: (values: ParamValues) => void;
}

export function BacktestTab({
  strategies,
  strategiesLoading,
  strategyId,
  onStrategyChange,
  paramValues,
  onParamValuesChange,
}: BacktestTabProps) {
  const [symbolsInput, setSymbolsInput] = useState("600519.SH,AAPL");
  const [startDate, setStartDate] = useState("");
  const [initialCapital, setInitialCapital] = useState("100000");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const strategy = strategies.find((s) => s.id === strategyId) ?? null;

  async function runBacktest() {
    const symbols = parseSymbols(symbolsInput);
    if (!strategyId || symbols.length === 0 || !startDate || loading) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/quant/backtest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          strategy_id: strategyId,
          symbols,
          start: startDate,
          params: buildParamsPayload(strategy, paramValues),
          initial_capital: Number(initialCapital) || undefined,
        }),
      });
      if (!res.ok) {
        setError("回测服务不可用，请稍后重试");
        setResult(null);
        return;
      }
      setResult((await res.json()) as BacktestResult);
    } catch {
      setError("回测请求失败，请检查网络后重试");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  const stats = result?.stats ?? null;
  const unadjusted = result?.unadjusted ?? stats?.unadjusted ?? [];

  const statCards: { label: string; value: string; colored?: number | null }[] =
    stats
      ? [
          {
            label: "总收益",
            value: fmtPct(stats.total_return),
            colored: stats.total_return,
          },
          {
            label: "年化收益",
            value: fmtPct(stats.annual_return),
            colored: stats.annual_return,
          },
          {
            label: "最大回撤",
            value: fmtPct(stats.max_drawdown),
            colored: stats.max_drawdown,
          },
          { label: "夏普比率", value: fmtNum(stats.sharpe) },
          { label: "卡玛比率", value: fmtNum(stats.calmar) },
          {
            label: "胜率",
            value: fmtPct(stats.win_rate),
            colored: stats.win_rate,
          },
          { label: "交易次数", value: stats.trades == null ? "—" : String(stats.trades) },
          { label: "最终净值", value: fmtNum(stats.final_value) },
        ]
      : [];

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">回测设置</CardTitle>
          <CardDescription>选择策略与参数，运行历史回测</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <StrategyPicker
            strategies={strategies}
            strategyId={strategyId}
            onStrategyChange={onStrategyChange}
            disabled={strategiesLoading || loading}
          />
          <StrategyParamsForm
            strategy={strategy}
            values={paramValues}
            onChange={onParamValuesChange}
            disabled={loading}
          />
          <div className="space-y-1.5">
            <Label htmlFor="quant-bt-symbols">标的（逗号分隔）</Label>
            <Input
              id="quant-bt-symbols"
              placeholder="600519.SH,AAPL"
              value={symbolsInput}
              onChange={(e) => setSymbolsInput(e.target.value)}
              disabled={loading}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="quant-bt-start">开始日期</Label>
              <Input
                id="quant-bt-start"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                disabled={loading}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="quant-bt-capital">初始资金</Label>
              <Input
                id="quant-bt-capital"
                type="number"
                min={1}
                value={initialCapital}
                onChange={(e) => setInitialCapital(e.target.value)}
                disabled={loading}
              />
            </div>
          </div>
          <Button
            className="w-full"
            onClick={runBacktest}
            disabled={
              loading ||
              !strategyId ||
              parseSymbols(symbolsInput).length === 0 ||
              !startDate
            }
          >
            <PlayIcon />
            {loading ? "回测中…" : "运行回测"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">回测结果</CardTitle>
          {result && (
            <CardDescription className="flex flex-wrap items-center gap-1.5">
              <span>
                {result.strategy} · {result.symbols.join(" / ")} ·{" "}
                {result.range.join(" ~ ")}
              </span>
              {unadjusted.length > 0 && (
                <Badge variant="outline">{unadjusted.length} 只未复权</Badge>
              )}
            </CardDescription>
          )}
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
          ) : error ? (
            <EmptyState title={error} compact />
          ) : stats ? (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {statCards.map((card) => (
                <div
                  key={card.label}
                  className={cn(
                    "rounded-lg border bg-muted/30 p-3",
                    "flex flex-col gap-1"
                  )}
                >
                  <span className="text-xs text-muted-foreground">
                    {card.label}
                  </span>
                  <span
                    className="text-lg font-semibold tabular-nums"
                    style={pnlStyle(card.colored)}
                  >
                    {card.value}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              title="选择策略并运行回测"
              description="左侧配置策略、标的与区间后点击「运行回测」"
              compact
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
