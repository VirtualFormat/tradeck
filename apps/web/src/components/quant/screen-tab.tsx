"use client";

/**
 * Tab 2「选股扫描」：策略 + 参数 + 标的池 → 截面扫描结果表
 */
import { useState } from "react";
import { MagnifyingGlassIcon } from "@phosphor-icons/react";

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

import { StrategyParamsForm, StrategyPicker } from "./strategy-picker";
import {
  buildParamsPayload,
  parseSymbols,
  type ParamValues,
  type StrategyDef,
} from "./types";

interface ScreenRow {
  symbol: string;
  name: string | null;
  score: number | null;
  entry: boolean;
  exit: boolean;
  market: string | null;
}

interface ScreenResult {
  strategy_id: string;
  as_of: string | null;
  rows: ScreenRow[];
  total: number;
  unadjusted?: string[];
}

const MARKET_VARIANT: Record<string, "default" | "secondary" | "outline"> = {
  CN: "default",
  HK: "secondary",
  US: "outline",
};

interface ScreenTabProps {
  strategies: StrategyDef[];
  strategiesLoading: boolean;
  strategyId: string;
  onStrategyChange: (id: string) => void;
  paramValues: ParamValues;
  onParamValuesChange: (values: ParamValues) => void;
}

export function ScreenTab({
  strategies,
  strategiesLoading,
  strategyId,
  onStrategyChange,
  paramValues,
  onParamValuesChange,
}: ScreenTabProps) {
  const [symbolsInput, setSymbolsInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScreenResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const strategy = strategies.find((s) => s.id === strategyId) ?? null;

  async function runScreen() {
    const symbols = parseSymbols(symbolsInput);
    if (!strategyId || symbols.length === 0 || loading) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/quant/screen", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          strategy_id: strategyId,
          symbols,
          params: buildParamsPayload(strategy, paramValues),
        }),
      });
      if (!res.ok) {
        setError("扫描服务不可用，请稍后重试");
        setResult(null);
        return;
      }
      setResult((await res.json()) as ScreenResult);
    } catch {
      setError("扫描请求失败，请检查网络后重试");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">扫描设置</CardTitle>
          <CardDescription>在标的池上运行策略信号</CardDescription>
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
            <Label htmlFor="quant-sc-symbols">标的池（逗号分隔）</Label>
            <Input
              id="quant-sc-symbols"
              placeholder="600519.SH,000001.SZ,AAPL"
              value={symbolsInput}
              onChange={(e) => setSymbolsInput(e.target.value)}
              disabled={loading}
            />
          </div>
          <Button
            className="w-full"
            onClick={runScreen}
            disabled={
              loading || !strategyId || parseSymbols(symbolsInput).length === 0
            }
          >
            <MagnifyingGlassIcon />
            {loading ? "扫描中…" : "扫描"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">扫描结果</CardTitle>
          {result && (
            <CardDescription className="flex flex-wrap items-center gap-1.5">
              <span>
                截至 {result.as_of ?? "—"} · 共 {result.total} 只
              </span>
              {(result.unadjusted?.length ?? 0) > 0 && (
                <Badge variant="outline">
                  {result.unadjusted?.length} 只未复权
                </Badge>
              )}
            </CardDescription>
          )}
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-9 w-full" />
              ))}
            </div>
          ) : error ? (
            <EmptyState title={error} compact />
          ) : result ? (
            result.rows.length === 0 ? (
              <EmptyState title="标的池内无扫描结果" compact />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>代码</TableHead>
                    <TableHead>名称</TableHead>
                    <TableHead className="text-right">得分</TableHead>
                    <TableHead>入场</TableHead>
                    <TableHead>出场</TableHead>
                    <TableHead>市场</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {result.rows.map((row) => (
                    <TableRow key={row.symbol}>
                      <TableCell className="font-mono text-xs">
                        {row.symbol}
                      </TableCell>
                      <TableCell>{row.name ?? "—"}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {row.score == null ? "—" : row.score.toFixed(4)}
                      </TableCell>
                      <TableCell>
                        <Badge variant={row.entry ? "default" : "outline"}>
                          {row.entry ? "是" : "否"}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant={row.exit ? "destructive" : "outline"}>
                          {row.exit ? "是" : "否"}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {row.market ? (
                          <Badge
                            variant={MARKET_VARIANT[row.market] ?? "outline"}
                          >
                            {row.market}
                          </Badge>
                        ) : (
                          "—"
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )
          ) : (
            <EmptyState
              title="选择策略并扫描"
              description="左侧配置策略与标的池后点击「扫描」"
              compact
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
