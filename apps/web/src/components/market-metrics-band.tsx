/**
 * 首页底部跨市场指标带。
 * 单位契约：
 * - 宏观 value 为小数比例，展示时 ×100；变化为绝对百分点差。
 * - 跨资产 chg_1d 已是百分数，直接追加 %，不再次 ×100。
 * - 收益率 curve.latest 已是百分数；spread_bp 已是 bp。
 */
import { EmptyState } from "@/components/empty-state";
import { MetricTile } from "@/components/dashboard/metric-tile";
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  fetchCrossAssets,
  fetchYieldCurve,
  fetchYieldSpread,
  getCPI,
  getEFFR,
  getUnemployment,
  type MacroSeries,
  type RateSeries,
  type YieldCurvePoint,
} from "@/lib/openbb";
import { cn } from "@/lib/utils";

interface MacroMetric {
  label: string;
  latest: MacroSeries | RateSeries | null;
  previous: MacroSeries | RateSeries | null;
  dateMode: "month" | "day";
}

const COMMODITIES = [
  { symbol: "GC=F", label: "黄金" },
  { symbol: "CL=F", label: "原油" },
  { symbol: "SI=F", label: "白银" },
  { symbol: "BTC-USD", label: "比特币" },
] as const;

function lastTwo<T>(series: T[]): [T | null, T | null] {
  const latest = series.at(-1) ?? null;
  const previous = series.at(-2) ?? null;
  return [latest, previous];
}

function macroValue(point: MacroSeries | RateSeries | null): number | null {
  if (!point) return null;
  const value = "rate" in point ? point.rate : point.value;
  return Number.isFinite(value) ? value : null;
}

function formatMacroValue(point: MacroSeries | RateSeries | null): string {
  const value = macroValue(point);
  return value == null ? "—" : `${(value * 100).toFixed(2)}%`;
}

function macroChange(
  latest: MacroSeries | RateSeries | null,
  previous: MacroSeries | RateSeries | null
): { text: string; className: string } | null {
  const latestValue = macroValue(latest);
  const previousValue = macroValue(previous);
  if (latestValue == null || previousValue == null) return null;

  // 宏观源保存的是小数比例；两期差值 ×100 后就是“百分点”。
  const diffPoints = (latestValue - previousValue) * 100;
  if (Math.abs(diffPoints) < 0.005) {
    return { text: "→ 0.00 pp", className: "text-muted-foreground" };
  }
  return {
    text: `${diffPoints > 0 ? "↑" : "↓"} ${Math.abs(diffPoints).toFixed(2)} pp`,
    className: diffPoints > 0 ? "text-warn" : "text-muted-foreground",
  };
}

function formatMacroDate(
  date: string | null | undefined,
  mode: "month" | "day"
): string | null {
  if (!date) return null;
  const match = date.match(/^(\d{4})-(\d{2})(?:-(\d{2}))?/);
  if (!match) return null;
  if (mode === "month") return `${match[1]}-${match[2]}`;
  return match[3] ? `${match[2]}-${match[3]}` : `${match[1]}-${match[2]}`;
}

function formatAssetPrice(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const maximumFractionDigits = Math.abs(value) >= 1000 ? 0 : 2;
  return `$${value.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits,
  })}`;
}

function formatAssetChange(value: number | null): string | null {
  if (value == null || !Number.isFinite(value)) return null;
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function movementClass(value: number | null): string {
  if (value == null || value === 0) return "text-muted-foreground";
  return value > 0 ? "text-up" : "text-down";
}

function findYield(
  curve: YieldCurvePoint[],
  tenor: "2Y" | "10Y" | "30Y",
  months: number
): number | null {
  const point = curve.find(
    (item) => item.tenor === tenor || item.months === months
  );
  return point?.latest != null && Number.isFinite(point.latest)
    ? point.latest
    : null;
}

function formatYield(value: number | null): string {
  return value == null ? "—" : `${value.toFixed(2)}%`;
}

function formatSpread(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const rounded = Math.round(value);
  return `${rounded > 0 ? "+" : ""}${rounded} bp`;
}

export async function MarketMetricsBand() {
  const [cpi, unemployment, effr, crossAssets, curve, spreadSeries] =
    await Promise.all([
      getCPI("oecd", 2).catch(() => []),
      getUnemployment("oecd", 2).catch(() => []),
      getEFFR("federal_reserve", 2).catch(() => []),
      fetchCrossAssets().catch(() => []),
      fetchYieldCurve().catch(() => []),
      fetchYieldSpread(30).catch(() => []),
    ]);

  const [latestCpi, previousCpi] = lastTwo(cpi);
  const [latestUnemployment, previousUnemployment] = lastTwo(unemployment);
  const [latestEffr, previousEffr] = lastTwo(effr);
  const macroMetrics: MacroMetric[] = [
    {
      label: "美国 CPI",
      latest: latestCpi,
      previous: previousCpi,
      dateMode: "month",
    },
    {
      label: "美国失业率",
      latest: latestUnemployment,
      previous: previousUnemployment,
      dateMode: "month",
    },
    {
      label: "联邦基金利率",
      latest: latestEffr,
      previous: previousEffr,
      dateMode: "day",
    },
  ];

  const commodityMap = new Map(
    crossAssets
      .filter((item) => item.category === "commodity")
      .map((item) => [item.symbol, item] as const)
  );
  const commodities = COMMODITIES.map((definition) => ({
    ...definition,
    data: commodityMap.get(definition.symbol) ?? null,
  }));
  const hasCommodityData = commodities.some(({ data }) => data != null);
  const commodityAvailable = commodities.filter(({ data }) => data != null).length;

  const yield2Y = findYield(curve, "2Y", 24);
  const yield10Y = findYield(curve, "10Y", 120);
  const yield30Y = findYield(curve, "30Y", 360);
  const latestSpread = spreadSeries.at(-1)?.spread_bp;
  const spread =
    latestSpread != null && Number.isFinite(latestSpread)
      ? latestSpread
      : yield10Y != null && yield2Y != null
        ? (yield10Y - yield2Y) * 100
        : null;
  const inverted = spread != null && spread < 0;
  const hasYieldData =
    yield2Y != null || yield10Y != null || yield30Y != null || spread != null;
  const yieldDate = curve.find((point) => point.latest_date)?.latest_date ?? null;
  const spreadDate = spreadSeries.at(-1)?.date ?? yieldDate;

  return (
    <div className="rounded-xl p-3 ring-1 ring-foreground/10">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card size="sm" className="gap-2.5 py-3 xl:h-[113px]">
          <CardHeader className="px-3.5">
            <CardTitle className="text-xs font-semibold text-fg-dim">
              宏观速览
            </CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-3 gap-2.5 px-3.5">
            {macroMetrics.map((metric) => {
              const change = macroChange(metric.latest, metric.previous);
              return (
                <MetricTile
                  key={metric.label}
                  label={metric.label}
                  value={formatMacroValue(metric.latest)}
                  meta={change?.text ?? null}
                  metaClassName={change?.className}
                  detail={formatMacroDate(
                    metric.latest?.date,
                    metric.dateMode
                  )}
                />
              );
            })}
          </CardContent>
        </Card>

        <Card size="sm" className="gap-2.5 py-3 xl:h-[113px]">
          <CardHeader className="px-3.5">
            <CardTitle className="text-xs font-semibold text-fg-dim">
              跨资产
            </CardTitle>
            <CardAction className="text-[10px] text-muted-foreground">
              {commodityAvailable}/{commodities.length} 可用
            </CardAction>
          </CardHeader>
          <CardContent className="px-3.5">
            {hasCommodityData ? (
              <div className="grid grid-cols-4 gap-2.5">
                {commodities.map(({ symbol, label, data }) => (
                  <MetricTile
                    key={symbol}
                    label={label}
                    value={formatAssetPrice(data?.close ?? null)}
                    meta={formatAssetChange(data?.chg_1d ?? null)}
                    metaClassName={movementClass(data?.chg_1d ?? null)}
                    detail={
                      data?.latest_date?.slice(5) ??
                      (data ? null : "缺失")
                    }
                  />
                ))}
              </div>
            ) : (
              <EmptyState
                inline
                title="暂无跨资产数据"
                className="h-[57px] items-center justify-center rounded-lg bg-secondary/70 text-center"
              />
            )}
          </CardContent>
        </Card>

        <Card size="sm" className="gap-2.5 py-3 xl:h-[113px]">
          <CardHeader className="px-3.5">
            <CardTitle className="text-xs font-semibold text-fg-dim">
              国债收益率 · 美债
            </CardTitle>
            {yieldDate && (
              <CardAction className="text-[10px] text-muted-foreground tabular-nums">
                {yieldDate.slice(5)}
              </CardAction>
            )}
          </CardHeader>
          <CardContent className="px-3.5">
            {hasYieldData ? (
              <div className="grid grid-cols-4 gap-2.5">
                <MetricTile label="2年期" value={formatYield(yield2Y)} />
                <MetricTile label="10年期" value={formatYield(yield10Y)} />
                <MetricTile label="30年期" value={formatYield(yield30Y)} />
                <MetricTile
                  label="10Y-2Y"
                  value={formatSpread(spread)}
                  meta={spread == null ? null : inverted ? "倒挂" : "正常"}
                  detail={spreadDate?.slice(5) ?? null}
                  metaClassName={
                    spread == null
                      ? undefined
                      : inverted
                        ? "text-warn"
                        : "text-muted-foreground"
                  }
                  className={cn(
                    inverted && "bg-warn/10 ring-1 ring-warn/40"
                  )}
                  valueClassName={inverted ? "text-warn" : undefined}
                />
              </div>
            ) : (
              <EmptyState
                inline
                title="暂无美债收益率数据"
                className="h-[57px] items-center justify-center rounded-lg bg-secondary/70 text-center"
              />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
