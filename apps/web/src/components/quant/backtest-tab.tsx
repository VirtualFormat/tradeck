"use client";

/**
 * Tab 1「策略回测」：左侧策略/参数/标的/区间/资金表单，右侧结果区
 * 结果区结构：概要条 → 核心指标卡网格（tooltip 解释）→ 净值曲线 → 卖出归因 → 交易明细表
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { EquityChart } from "./equity-chart";
import { MetricCard } from "./metric-card";
import { StrategyParamsForm, StrategyPicker } from "./strategy-picker";
import { TradesTable } from "./trades-table";
import {
  buildParamsPayload,
  exitReasonLabel,
  fmtMoney,
  fmtNum,
  fmtPct,
  parseSymbols,
  pnlStyle,
  type BacktestResult,
  type ParamValues,
  type StrategyDef,
} from "./types";

/** 指标卡 label → tooltip 解释文案 */
const METRIC_HINTS: Record<string, string> = {
  总收益: "回测期末权益相对初始资金的累计收益率，已含费用/滑点/成交约束。",
  年化: "总收益按复利折算为一年，短周期可能被放大。",
  超额收益: "策略总收益减同期基准，正值跑赢基准。",
  最大回撤: "权益从历史高点到随后最低点的最大跌幅。",
  夏普: "平均收益÷总波动×√252 年化，越高单位波动收益越多。",
  索提诺: "平均收益÷下行偏差×√252，只惩罚负收益波动。",
  卡玛: "年化收益÷最大回撤绝对值。",
  胜率: "盈利交易占比，样本少时仅供参考。",
  盈亏比: "平均盈利÷平均亏损。",
  平均持仓: "已完成交易的平均持仓天数。",
};

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
              onValueChange={(v) => setSymbolsInput(v)}
              disabled={loading}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="quant-bt-start">开始日期</Label>
              <Input
                id="quant-bt-start"
                // base-ui Input 对 type="date" 的受控处理与标准 input 不一致，
                // 日期值进不了 React state 导致按钮永久 disabled——用 text + 格式校验
                type="text"
                placeholder="YYYY-MM-DD"
                inputMode="numeric"
                value={startDate}
                onValueChange={(v) => setStartDate(v)}
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
                onValueChange={(v) => setInitialCapital(v)}
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

      {loading ? (
        <BacktestResultSkeleton />
      ) : error ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">回测结果</CardTitle>
          </CardHeader>
          <CardContent>
            <EmptyState title={error} compact />
          </CardContent>
        </Card>
      ) : result ? (
        <BacktestResultView result={result} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">回测结果</CardTitle>
          </CardHeader>
          <CardContent>
            <EmptyState
              title="选择策略并运行回测"
              description="左侧配置策略、标的与区间后点击「运行回测」"
              compact
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/** 结果区骨架：概要条 + 指标卡网格 + 图表 + 表格占位 */
function BacktestResultSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-9 w-full" />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
        {Array.from({ length: 12 }).map((_, i) => (
          <Skeleton key={i} className="h-20 w-full" />
        ))}
      </div>
      <Skeleton className="h-[320px] w-full" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}

function BacktestResultView({ result }: { result: BacktestResult }) {
  const { stats } = result;
  const benchmark = result.benchmark ?? null;
  const unadjusted = result.unadjusted ?? stats.unadjusted ?? [];
  const trades = result.trades ?? [];
  const equityCurve = result.equity_curve ?? [];
  const exitStats = stats.exit_stats ?? {};
  const hasExcess = benchmark?.excess_return != null;

  const metrics: {
    label: string;
    value: string;
    colored?: number | null;
  }[] = [
    {
      label: "总收益",
      value: fmtPct(stats.total_return),
      colored: stats.total_return,
    },
    {
      label: "年化",
      value: fmtPct(stats.annual_return),
      colored: stats.annual_return,
    },
    ...(hasExcess
      ? [
          {
            label: "超额收益",
            value: fmtPct(benchmark?.excess_return),
            colored: benchmark?.excess_return,
          },
        ]
      : []),
    { label: "最大回撤", value: fmtPct(stats.max_drawdown) },
    { label: "夏普", value: fmtNum(stats.sharpe) },
    { label: "索提诺", value: fmtNum(stats.sortino) },
    { label: "卡玛", value: fmtNum(stats.calmar) },
    { label: "胜率", value: fmtPct(stats.win_rate) },
    { label: "盈亏比", value: fmtNum(stats.profit_loss_ratio) },
    {
      label: "交易数",
      value: stats.trades == null ? "—" : String(stats.trades),
    },
    { label: "平均持仓", value: `${fmtNum(stats.avg_hold_days, 1)} 天` },
    { label: "最终净值", value: fmtNum(stats.final_value) },
  ];

  return (
    <div className="space-y-4">
      {/* 1. 概要条 */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-2 py-3">
          <Badge>{result.strategy}</Badge>
          <span className="text-xs text-muted-foreground tabular-nums">
            {result.range.join(" ~ ")}
            {stats.days != null && ` · ${stats.days} 天`}
          </span>
          {benchmark && (
            <Badge variant="outline">基准 {benchmark.symbol}</Badge>
          )}
          {unadjusted.length > 0 && (
            <Badge
              variant="outline"
              style={{
                color: "var(--warn)",
                borderColor:
                  "color-mix(in oklch, var(--warn) 50%, transparent)",
              }}
            >
              {unadjusted.length} 只未复权
            </Badge>
          )}
        </CardContent>
      </Card>

      {/* 2. 核心指标卡网格 */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
        {metrics.map((m) => (
          <MetricCard
            key={m.label}
            label={m.label}
            hint={METRIC_HINTS[m.label]}
            value={m.value}
            colored={m.colored}
          />
        ))}
      </div>

      {/* 3. 净值曲线 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">净值曲线</CardTitle>
          <CardDescription>归一化净值（起点 = 1）</CardDescription>
        </CardHeader>
        <CardContent>
          {equityCurve.length > 0 ? (
            <EquityChart data={equityCurve} />
          ) : (
            <EmptyState title="无净值曲线数据" compact className="h-[280px]" />
          )}
        </CardContent>
      </Card>

      {/* 4. 卖出归因 */}
      {Object.keys(exitStats).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">卖出归因</CardTitle>
            <CardDescription>按卖出原因拆分的成交表现</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>卖出原因</TableHead>
                  <TableHead className="text-right">笔数</TableHead>
                  <TableHead className="text-right">胜率</TableHead>
                  <TableHead className="text-right">总盈亏</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Object.entries(exitStats).map(([reason, s]) => (
                  <TableRow key={reason}>
                    <TableCell>
                      <Badge variant="outline">{exitReasonLabel(reason)}</Badge>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {s.count}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtPct(s.win_rate)}
                    </TableCell>
                    <TableCell
                      className="text-right tabular-nums"
                      style={pnlStyle(s.total_pnl)}
                    >
                      {fmtMoney(s.total_pnl)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* 5. 交易明细 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">交易明细</CardTitle>
          <CardDescription>共 {trades.length} 笔已完成交易</CardDescription>
        </CardHeader>
        <CardContent>
          {trades.length === 0 ? (
            <EmptyState
              title="区间内无成交"
              description="回测区间内策略未产生任何买卖信号"
              compact
            />
          ) : (
            <TradesTable trades={trades} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
