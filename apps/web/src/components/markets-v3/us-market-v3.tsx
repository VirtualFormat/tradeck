import { MoversPanel } from "@/components/dashboard/movers-panel";
import { EmptyState } from "@/components/empty-state";
import { MarketSummaryCard } from "@/components/markets-v3/market-summary-card";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { fmtDataDate, fmtPrice } from "@/lib/format";
import {
  fetchCrossAssets,
  fetchEarningsCalendar,
  fetchEconomicCalendar,
  fetchMarketInternals,
  fetchMarketSummary,
  fetchYieldCurve,
  fetchYieldSpread,
  type CrossAssetItem,
  type EarningsCalendarItem,
  type EconomicCalendarItem,
  type MarketInternal,
  type MarketSummary,
  type YieldCurvePoint,
  type YieldSpreadPoint,
} from "@/lib/openbb";
import { cn } from "@/lib/utils";

import { SectorRotation } from "./sector-rotation";
import { UsMarketInternals } from "./us-market-internals";
import { UsMarketContext, UsMarketTabs } from "./us-market-tabs";

interface UsMarketV3Props {
  date?: string;
}

interface RatePressureProps {
  curve: YieldCurvePoint[];
  spread: YieldSpreadPoint[];
  crossAssets: CrossAssetItem[];
}

const CROSS_ASSET_SYMBOLS = ["DX-Y.NYB", "^VIX", "USDCNH", "GC=F"];
const SHANGHAI_TIME_ZONE = "Asia/Shanghai";

function shanghaiToday(): string {
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: SHANGHAI_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function signedPercent(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function changeClass(value: number | null | undefined): string {
  if (value == null || value === 0) return "text-muted-foreground";
  return value > 0 ? "text-up" : "text-down";
}

function rateValue(value: number | null | undefined): string {
  return value == null ? "—" : `${value.toFixed(2)}%`;
}

function spreadValue(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(0)} bp`;
}

function MarketBreadthCard({ summary }: { summary: MarketSummary | null }) {
  const ratio = summary?.up_ratio == null ? null : summary.up_ratio * 100;
  const hasData = Boolean(
    summary?.date &&
      summary.coverage_sufficient &&
      summary.coverage_count > 0
  );
  const coverageLabel = summary
    ? `覆盖 ${summary.coverage_count.toLocaleString("zh-CN")} 只`
    : "至少 5,000 只";

  return (
    <MarketSummaryCard
      title="市场宽度"
      description={`日 K · ${coverageLabel}`}
      action={
        <Badge variant="secondary" className="text-[10px] tabular-nums">
          {fmtDataDate(summary?.date) ?? "等待快照"}
        </Badge>
      }
      className="h-full xl:min-h-[210px]"
      contentClassName="flex h-full min-h-0 flex-col justify-between gap-4"
    >
      {hasData && summary ? (
        <>
          <div className="grid grid-cols-3 gap-2">
            <div className="rounded-lg bg-secondary px-3 py-2.5">
              <div className="text-[10px] text-muted-foreground">上涨</div>
              <div className="mt-1 text-lg font-semibold text-up tabular-nums">
                {summary.up.toLocaleString("zh-CN")}
              </div>
            </div>
            <div className="rounded-lg bg-secondary px-3 py-2.5">
              <div className="text-[10px] text-muted-foreground">平盘</div>
              <div className="mt-1 text-lg font-semibold text-foreground tabular-nums">
                {summary.flat.toLocaleString("zh-CN")}
              </div>
            </div>
            <div className="rounded-lg bg-secondary px-3 py-2.5">
              <div className="text-[10px] text-muted-foreground">下跌</div>
              <div className="mt-1 text-lg font-semibold text-down tabular-nums">
                {summary.down.toLocaleString("zh-CN")}
              </div>
            </div>
          </div>
          <div>
            <div className="mb-1.5 flex items-center justify-between text-[11px] text-muted-foreground">
              <span>上涨占比</span>
              <span className="font-medium text-foreground tabular-nums">
                {ratio == null ? "—" : `${ratio.toFixed(0)}%`}
              </span>
            </div>
            <div className="flex h-2 overflow-hidden rounded-full bg-muted">
              <div
                className="bg-up transition-[width]"
                style={{ width: `${Math.max(0, Math.min(100, ratio ?? 0))}%` }}
              />
              <div className="min-w-px flex-1 bg-down" />
            </div>
          </div>
        </>
      ) : (
        <EmptyState
          compact
          title="暂无美股市场宽度"
          description="未找到覆盖至少 5,000 只标的的有效日 K 快照"
          className="min-h-28 justify-center"
        />
      )}
    </MarketSummaryCard>
  );
}

function RatePressure({ curve, spread, crossAssets }: RatePressureProps) {
  const twoYear = curve.find((point) => point.tenor === "2Y");
  const tenYear = curve.find((point) => point.tenor === "10Y");
  const spreadPoint = spread.at(-1);
  const spreadBp =
    spreadPoint?.spread_bp ??
    (twoYear?.latest != null && tenYear?.latest != null
      ? (tenYear.latest - twoYear.latest) * 100
      : null);
  const vix = crossAssets.find((item) => item.symbol === "^VIX");
  const curveDate = tenYear?.latest_date ?? twoYear?.latest_date ?? null;
  const spreadDate = spreadPoint?.date ?? curveDate;

  const metrics = [
    {
      label: "美债 2Y",
      value: rateValue(twoYear?.latest),
      meta: fmtDataDate(twoYear?.latest_date) ?? "无日期",
      metaClassName: "text-warn",
    },
    {
      label: "美债 10Y",
      value: rateValue(tenYear?.latest),
      meta: fmtDataDate(tenYear?.latest_date) ?? "无日期",
      metaClassName: "text-warn",
    },
    {
      label: "10Y-2Y",
      value: spreadValue(spreadBp),
      meta: spreadBp == null ? "等待数据" : spreadBp < 0 ? "倒挂" : "正常",
      metaClassName: spreadBp != null && spreadBp < 0 ? "text-warn" : "text-muted-foreground",
      detail: fmtDataDate(spreadDate),
    },
    {
      label: "VIX",
      value: fmtPrice(vix?.close),
      meta: signedPercent(vix?.chg_1d),
      metaClassName: changeClass(vix?.chg_1d),
      detail: fmtDataDate(vix?.latest_date),
    },
  ];

  return (
    <section aria-label="利率与风险压力" className="grid grid-cols-2 gap-2 md:grid-cols-4">
      {metrics.map((metric) => (
        <Card key={metric.label} size="sm" className="gap-0 py-2.5 shadow-none">
          <CardContent className="min-w-0 px-3">
            <div className="text-[10px] text-muted-foreground">{metric.label}</div>
            <div className="mt-1 text-base font-semibold text-foreground tabular-nums">
              {metric.value}
            </div>
            <div className="mt-0.5 flex min-w-0 items-center justify-between gap-1 text-[10px]">
              <span className={cn("truncate font-medium tabular-nums", metric.metaClassName)}>
                {metric.meta}
              </span>
              {metric.detail ? (
                <span className="shrink-0 text-muted-foreground tabular-nums">
                  {metric.detail}
                </span>
              ) : null}
            </div>
          </CardContent>
        </Card>
      ))}
    </section>
  );
}

function CrossAssetPanel({ items }: { items: CrossAssetItem[] }) {
  const selected = CROSS_ASSET_SYMBOLS.map((symbol) =>
    items.find((item) => item.symbol === symbol)
  ).filter((item): item is CrossAssetItem => Boolean(item));

  return (
    <MarketSummaryCard
      title="跨资产联动"
      description="美元、波动率、人民币与黄金"
      action={
        <Badge variant="outline" className="text-[10px]">
          {selected.length}/{CROSS_ASSET_SYMBOLS.length} 覆盖
        </Badge>
      }
      className="h-full"
    >
      {selected.length > 0 ? (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-2 2xl:grid-cols-4">
          {selected.map((item) => (
            <div key={item.symbol} className="min-w-0 rounded-lg bg-secondary px-3 py-2.5">
              <div className="truncate text-[10px] text-muted-foreground">
                {item.name}
              </div>
              <div className="mt-1 text-sm font-semibold text-foreground tabular-nums">
                {fmtPrice(item.close)}
              </div>
              <div className="mt-0.5 flex min-w-0 items-center justify-between gap-1 text-[10px]">
                <span className={cn("font-medium tabular-nums", changeClass(item.chg_1d))}>
                  {signedPercent(item.chg_1d)}
                </span>
                <span className="truncate text-muted-foreground tabular-nums">
                  {fmtDataDate(item.latest_date) ?? "无日期"}
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState
          compact
          title="暂无跨资产数据"
          description="当前接口未返回美元、VIX、人民币或黄金"
          className="min-h-28 justify-center"
        />
      )}
    </MarketSummaryCard>
  );
}

export async function UsMarketV3({ date }: UsMarketV3Props) {
  const today = shanghaiToday();
  const [
    summaries,
    internals,
    crossAssets,
    yieldCurve,
    yieldSpread,
    earnings,
    economic,
  ] =
    await Promise.all([
      fetchMarketSummary(date).catch(() => [] as MarketSummary[]),
      fetchMarketInternals(180).catch(() => [] as MarketInternal[]),
      fetchCrossAssets().catch(() => [] as CrossAssetItem[]),
      fetchYieldCurve().catch(() => [] as YieldCurvePoint[]),
      fetchYieldSpread(30).catch(() => [] as YieldSpreadPoint[]),
      fetchEarningsCalendar(14).catch(() => [] as EarningsCalendarItem[]),
      fetchEconomicCalendar(7).catch(() => [] as EconomicCalendarItem[]),
    ]);

  const usSummary =
    summaries.find((item) => item.market.toUpperCase() === "US") ?? null;

  const movers = <MoversPanel market="us" date={date} />;
  const sectors = <SectorRotation items={crossAssets} />;
  const crossAsset = <CrossAssetPanel items={crossAssets} />;
  const events = (
    <UsMarketContext earnings={earnings} economic={economic} today={today} />
  );

  return (
    <div className="flex min-w-0 flex-col gap-4 md:gap-5 xl:gap-6">
      <section className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_26.875rem]">
        <MarketBreadthCard summary={usSummary} />
        <UsMarketInternals items={internals} />
      </section>

      <UsMarketTabs
        movers={movers}
        sectors={sectors}
        ratePressure={
          <RatePressure
            curve={yieldCurve}
            spread={yieldSpread}
            crossAssets={crossAssets}
          />
        }
        crossAsset={crossAsset}
        events={events}
      />
    </div>
  );
}
