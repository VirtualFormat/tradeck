"use client";

/**
 * Tab 2「选股扫描」：策略 + 参数 + 标的池（自定义或 universe）→ 截面扫描结果表
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
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import { StrategyParamsForm, StrategyPicker } from "./strategy-picker";
import {
  buildParamsPayload,
  parseSymbols,
  type ParamValues,
  type StrategyDef,
} from "./types";

/** 标的池 universe 选项（标的输入为空时生效，自定义标的时置灰） */
const UNIVERSE_OPTIONS = [
  { value: "tracked", label: "tracked 100 只（默认）" },
  { value: "cn", label: "A 股" },
  { value: "us", label: "美股" },
  { value: "hk", label: "港股" },
  { value: "all", label: "全部" },
] as const;
type UniverseValue = (typeof UNIVERSE_OPTIONS)[number]["value"];

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
  const [universe, setUniverse] = useState<UniverseValue>("tracked");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScreenResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const strategy = strategies.find((s) => s.id === strategyId) ?? null;
  const symbols = parseSymbols(symbolsInput);
  const hasCustomSymbols = symbols.length > 0;

  async function runScreen() {
    if (!strategyId || loading) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/quant/screen", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          strategy_id: strategyId,
          // 留空 = 按 universe 选股池扫描；自定义标的时 universe 不生效
          symbols: hasCustomSymbols ? symbols : null,
          universe: hasCustomSymbols ? undefined : universe,
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
            <Label htmlFor="quant-sc-symbols">
              标的（逗号分隔，可选）
            </Label>
            <Input
              id="quant-sc-symbols"
              placeholder="留空 = tracked 100 只（可逗号分隔自定义）"
              value={symbolsInput}
              onValueChange={(v) => setSymbolsInput(v)}
              disabled={loading}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="quant-sc-universe">选股池</Label>
            {hasCustomSymbols ? (
              <Tooltip>
                <TooltipTrigger
                  render={<span className="block cursor-not-allowed" />}
                >
                  <Select value={universe} disabled>
                    <SelectTrigger
                      id="quant-sc-universe"
                      className="w-full pointer-events-none"
                    >
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
                </TooltipTrigger>
                <TooltipContent>
                  自定义标的时 universe 不生效
                </TooltipContent>
              </Tooltip>
            ) : (
              <Select
                value={universe}
                onValueChange={(v: string | null) =>
                  setUniverse((v as UniverseValue) ?? "tracked")
                }
                disabled={loading}
              >
                <SelectTrigger id="quant-sc-universe" className="w-full">
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
            )}
          </div>
          <Button
            className="w-full"
            onClick={runScreen}
            disabled={loading || !strategyId}
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
