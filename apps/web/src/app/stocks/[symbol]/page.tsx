/**
 * 个股详情页
 * 路由：/stocks/[symbol]
 * 数据：OpenBB API（profile + metrics + income + historical）
 */
import { notFound, redirect } from "next/navigation";
import { normalizeSymbol } from "@/lib/utils";
import {
  getEquityProfile,
  getFundamentalMetrics,
  getIncomeStatements,
  getEquityHistorical,
  getAnalystConsensus,
  getBalanceSheets,
  getCashFlowStatements,
  fetchTechnicals,
  fetchAnnouncements,
  fetchResearchReports,
  getEquityQuotes,
} from "@/lib/openbb";
import { fmtPrice, fmtPct } from "@/lib/format";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { TradingViewChart } from "@/components/tradingview-chart";
import { EmptyState } from "@/components/empty-state";

function MetricRow({
  label,
  value,
  accent,
}: {
  label: string;
  value: string | null;
  accent?: boolean;
}) {
  if (value == null || value === "—") {
    return (
      <div className="flex items-center justify-between border-b border-border/50 py-2">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className="tab-nums text-sm text-muted-foreground">—</span>
      </div>
    );
  }
  const isPositive = accent && value.startsWith("+");
  const isNegative = accent && value.startsWith("-");
  const colorClass = isPositive
    ? "text-up"
    : isNegative
    ? "text-down"
    : "text-fg-dim";
  return (
    <div className="flex items-center justify-between border-b border-border/50 py-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={`tab-nums text-sm ${colorClass}`}>{value}</span>
    </div>
  );
}

const CURRENCY_PREFIX: Record<string, string> = {
  USD: "US$",
  CNY: "CN¥",
  HKD: "HK$",
};

function fmtBigNumber(
  value: number | null | undefined,
  currency: string | null
): string {
  if (value == null) return "—";
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  const normalizedCurrency = currency?.toUpperCase() ?? null;
  const prefix = normalizedCurrency
    ? CURRENCY_PREFIX[normalizedCurrency] ?? `${normalizedCurrency} `
    : "";
  if (abs >= 1e12)
    return `${sign}${prefix}${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9)
    return `${sign}${prefix}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6)
    return `${sign}${prefix}${(abs / 1e6).toFixed(2)}M`;
  return `${sign}${prefix}${abs.toLocaleString("en-US")}`;
}

const MARKET_TIME_ZONE_LABEL: Record<string, string> = {
  "America/New_York": "美东时间",
  "Asia/Hong_Kong": "香港时间",
  "Asia/Shanghai": "北京时间",
};

function getMarketTimeZone(symbol: string): string {
  const normalized = symbol.toUpperCase();
  if (normalized.endsWith(".HK")) return "Asia/Hong_Kong";
  if (/\.(SH|SS|SZ|BJ)$/.test(normalized)) return "Asia/Shanghai";
  return "America/New_York";
}

function normalizeCurrency(value: string | null | undefined): string | null {
  const normalized = value?.trim().toUpperCase();
  return normalized || null;
}

function normalizeDate(value: string | null | undefined): string | null {
  const match = value?.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : null;
}

function dateInTimeZone(date: Date, timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function quoteDateInMarket(
  value: string | null | undefined,
  timeZone: string
): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return dateInTimeZone(date, timeZone);
}

function fmtQuoteAsOf(
  value: string | null | undefined,
  timeZone: string
): string {
  if (!value) return "截止时间未提供";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "截止时间未提供";
  const formatted = new Intl.DateTimeFormat("zh-CN", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(date);
  return `${formatted} ${MARKET_TIME_ZONE_LABEL[timeZone]}`;
}

/** 分析师评级英文 → 中文 */
const RECOMMENDATION_LABEL: Record<string, string> = {
  strong_buy: "强力买入",
  buy: "买入",
  hold: "持有",
  underperform: "跑输大盘",
  sell: "卖出",
  strong_sell: "强力卖出",
};

function fmtRatio(value: number | null | undefined): string {
  if (value == null) return "—";
  return value.toFixed(2);
}

/** 带符号小数（用于 MACD 等正负有意义的指标，配合 accent 着色） */
function fmtSigned(value: number | null | undefined, digits: number = 4): string {
  if (value == null) return "—";
  return value >= 0 ? `+${value.toFixed(digits)}` : value.toFixed(digits);
}

/** 公告重点类型（业绩预告/分红等，Badge 着 accent 色） */
const HOT_ANNOUNCEMENT_CATEGORIES = [
  "业绩预告",
  "分红",
  "重大事项",
  "风险提示",
  "回购",
];

/** 研报评级 → Badge 类名（红涨绿跌：买入=红/增持=浅红/中性=灰/卖出=绿） */
function ratingBadgeClass(rating: string | null): string {
  switch (rating) {
    case "买入":
      return "border-up/50 text-up";
    case "增持":
      return "border-up/25 text-up/70";
    case "卖出":
    case "减持":
      return "border-down/50 text-down";
    case "中性":
    default:
      return "border-border text-muted-foreground";
  }
}

export default async function StockDetailPage({
  params,
}: {
  params: Promise<{ symbol: string }>;
}) {
  const { symbol: rawSymbol } = await params;
  if (!rawSymbol) notFound();

  // 归一化为标准 symbol（裸码补后缀/港股补零），非标准写法重定向到规范 URL
  const symbol = normalizeSymbol(rawSymbol);
  if (symbol !== rawSymbol.toUpperCase()) {
    redirect(`/stocks/${encodeURIComponent(symbol)}`);
  }

  // A 股判断（.SH 新标准/.SS/.SZ/.BJ）
  const isAShare = /\.(SH|SS|SZ|BJ)$/.test(symbol.toUpperCase());
  const historyEnd = new Date();
  const historyStart = new Date(historyEnd);
  historyStart.setUTCDate(historyStart.getUTCDate() - 180);
  const historyStartDate = historyStart.toISOString().slice(0, 10);
  const historyEndDate = historyEnd.toISOString().slice(0, 10);

  // 并行拉取所有数据（全部读 backend DB，<50ms，无数据走空态）
  // profile/metrics：全市场都可读（A 股沪市经 yfinance 出向映射已可拉取）
  // income：SEC 源仅美股，A 股跳过；公告/研报：仅 A 股（东财源）
  const [
    profile,
    metrics,
    income,
    historical,
    consensus,
    balance,
    cashFlow,
    technicals,
    announcements,
    researchReports,
    quotes,
  ] = await Promise.all([
      getEquityProfile(symbol).catch(() => null),
      getFundamentalMetrics(symbol).catch(() => null),
      isAShare ? Promise.resolve([]) : getIncomeStatements(symbol).catch(() => []),
      getEquityHistorical(
        symbol,
        historyStartDate,
        historyEndDate
      ).catch(() => []),
      getAnalystConsensus(symbol).catch(() => null),
      getBalanceSheets(symbol, "annual").catch(() => []),
      getCashFlowStatements(symbol, "annual").catch(() => []),
      fetchTechnicals(symbol, 120).catch(() => []),
      isAShare
        ? fetchAnnouncements(symbol, 30).catch(() => [])
        : Promise.resolve([]),
      isAShare
        ? fetchResearchReports(symbol, 90).catch(() => [])
        : Promise.resolve([]),
      getEquityQuotes([symbol]).catch(() => []),
    ]);

  const displayName = profile?.name ?? symbol;
  const quote = quotes[0] ?? null;
  const marketTimeZone = getMarketTimeZone(symbol);
  const latestHistory =
    historical.length > 0 ? historical[historical.length - 1] : null;
  const latestHistoryDate = normalizeDate(latestHistory?.date);
  const quoteMarketDate = quoteDateInMarket(quote?.data_as_of, marketTimeZone);
  const historicalLastPrice = latestHistory?.close ?? null;
  const prevClose =
    historical.length > 1 ? historical[historical.length - 2].close : null;
  const historicalChangePct =
    historicalLastPrice != null && prevClose != null && prevClose !== 0
      ? (historicalLastPrice - prevClose) / prevClose
      : null;
  const usesQuoteSnapshot =
    quote?.last_price != null &&
    quoteMarketDate != null &&
    (latestHistoryDate == null || quoteMarketDate >= latestHistoryDate);
  const lastPrice = usesQuoteSnapshot ? quote.last_price : historicalLastPrice;
  const changePct = usesQuoteSnapshot
    ? quote.change_percent ?? historicalChangePct
    : historicalChangePct;
  const priceAsOf = usesQuoteSnapshot
    ? `行情截止 · ${fmtQuoteAsOf(quote.data_as_of, marketTimeZone)}${
        quote.fetched_at
          ? ` · 抓取于 ${fmtQuoteAsOf(quote.fetched_at, marketTimeZone)}`
          : ""
      }`
    : latestHistory
      ? `日K收盘 · ${latestHistoryDate ?? latestHistory.date}`
      : null;
  const changeAsOf =
    usesQuoteSnapshot && quote.change_percent == null && latestHistory
      ? `涨跌幅按 ${latestHistory.date} 日K计算`
      : null;
  const financialCurrency = normalizeCurrency(profile?.currency);
  const subtitle = [profile?.exchange, profile?.currency, profile?.sector]
    .filter(Boolean)
    .join(" · ");

  // ── 分析师共识派生值 ──
  const targetLow = consensus?.target_low ?? null;
  const targetHigh = consensus?.target_high ?? null;
  const targetMid = consensus?.target_consensus ?? null;
  const consensusCurrency = normalizeCurrency(consensus?.currency);
  const displayedPriceCurrencies = [
    financialCurrency,
    usesQuoteSnapshot ? normalizeCurrency(quote?.currency) : null,
  ].filter((currency): currency is string => currency != null);
  const displayedPriceMatchesConsensus =
    consensusCurrency != null &&
    displayedPriceCurrencies.length > 0 &&
    displayedPriceCurrencies.every(
      (currency) => currency === consensusCurrency
    );
  const usesDisplayedConsensusPrice =
    displayedPriceMatchesConsensus && lastPrice != null && lastPrice > 0;
  const consensusCurrentPrice =
    consensus?.current_price != null && consensus.current_price > 0
      ? consensus.current_price
      : null;
  const refPrice = usesDisplayedConsensusPrice
    ? lastPrice
    : consensusCurrentPrice;
  const refPriceLabel = usesDisplayedConsensusPrice ? "现价" : "共识参考价";
  const recoLabel = consensus?.recommendation
    ? RECOMMENDATION_LABEL[consensus.recommendation] ?? consensus.recommendation
    : null;
  const hasTargetRange =
    targetLow != null && targetHigh != null && targetHigh > targetLow;
  // 目标价区间条上的百分比位置（钳制 0-100）
  const rangePos = (v: number): number =>
    hasTargetRange
      ? Math.min(
          100,
          Math.max(0, ((v - (targetLow as number)) / ((targetHigh as number) - (targetLow as number))) * 100)
        )
      : 0;
  const upside =
    targetMid != null && refPrice != null ? targetMid / refPrice - 1 : null;

  // 报表只展示最近 4 期（年度）
  const balanceRows = balance.slice(0, 4);
  const cashFlowRows = cashFlow.slice(0, 4);

  // ── 技术指标派生值（最新一根） ──
  const latestTech =
    technicals.length > 0 ? technicals[technicals.length - 1] : null;
  // 现价为最新一根收盘价，BOLL 位置 = (现价-下轨)/(上轨-下轨)，钳制 0-100
  const techPrice =
    historical.length > 0 ? historical[historical.length - 1].close : null;
  const hasBoll =
    latestTech?.boll_upper != null &&
    latestTech?.boll_lower != null &&
    latestTech.boll_upper > latestTech.boll_lower;
  const bollPos =
    hasBoll && techPrice != null
      ? Math.min(
          100,
          Math.max(
            0,
            ((techPrice - (latestTech?.boll_lower as number)) /
              ((latestTech?.boll_upper as number) -
                (latestTech?.boll_lower as number))) *
              100
          )
        )
      : null;

  return (
    <div className="px-4 lg:px-6">
      {/* 标题区 */}
      <header className="mb-6 flex flex-wrap items-end justify-between gap-3 border-b border-border pb-3">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold tracking-wide">{displayName}</h1>
            <Badge variant="secondary">{symbol}</Badge>
          </div>
          {subtitle && (
            <p className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              {subtitle}
            </p>
          )}
        </div>
        {lastPrice != null && (
          <div className="text-right">
            <div className="tab-nums text-3xl font-bold">
              {fmtPrice(lastPrice)}
            </div>
            {changePct != null && (
              <div
                className={`tab-nums text-sm ${
                  changePct >= 0 ? "text-up" : "text-down"
                }`}
              >
                {fmtPct(changePct)}
              </div>
            )}
            {priceAsOf && (
              <p className="mt-1 text-[10px] text-muted-foreground">
                {priceAsOf}
              </p>
            )}
            {changeAsOf && (
              <p className="text-[10px] text-muted-foreground">
                {changeAsOf}
              </p>
            )}
          </div>
        )}
      </header>

      {/* 非精选标的兜底提示：有 K 线但无 profile（按需回源也拿不到）时说明覆盖范围 */}
      {!profile && historical.length > 0 && (
        <p className="mb-6 text-xs text-muted-foreground">
          该标的为全市场扩展覆盖：K线、技术指标可用；基本面、新闻等深度数据可能缺失
        </p>
      )}

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {/* TradingView K 线图（占 2 列） */}
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="text-sm">K 线走势（TradingView）</CardTitle>
            </CardHeader>
            <CardContent>
              <TradingViewChart
                data={historical
                  .filter(
                    (d) =>
                      d.open != null &&
                      d.high != null &&
                      d.low != null &&
                      d.close != null
                  )
                  .map((d) => ({
                    time: d.date,
                    open: d.open,
                    high: d.high,
                    low: d.low,
                    close: d.close,
                  }))}
                maData={technicals.map((t) => ({
                  time: t.date,
                  ma5: t.ma5,
                  ma20: t.ma20,
                  ma60: t.ma60,
                }))}
                height={420}
              />
            </CardContent>
          </Card>

          {/* 基本面指标 */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">关键指标</CardTitle>
            </CardHeader>
            <CardContent>
              <MetricRow
                label="市值"
                value={fmtBigNumber(metrics?.market_cap, financialCurrency)}
              />
              <MetricRow
                label="市盈率 (P/E)"
                value={fmtRatio(metrics?.pe_ratio)}
              />
              <MetricRow
                label="远期 P/E"
                value={fmtRatio(metrics?.forward_pe)}
              />
              <MetricRow
                label="PEG 比率"
                value={fmtRatio(metrics?.peg_ratio)}
              />
              <MetricRow
                label="EV/EBITDA"
                value={fmtRatio(metrics?.enterprise_to_ebitda)}
              />
              <MetricRow
                label="利润率"
                value={
                  metrics?.profit_margins != null
                    ? `${(metrics.profit_margins * 100).toFixed(2)}%`
                    : "—"
                }
              />
              <MetricRow
                label="ROE"
                value={
                  metrics?.return_on_equity != null
                    ? `${(metrics.return_on_equity * 100).toFixed(2)}%`
                    : "—"
                }
              />
              <MetricRow
                label="营收增长"
                value={
                  metrics?.revenue_growth != null
                    ? `${(metrics.revenue_growth * 100).toFixed(2)}%`
                    : "—"
                }
                accent
              />
              <MetricRow
                label="盈利增长"
                value={
                  metrics?.earnings_growth != null
                    ? `${(metrics.earnings_growth * 100).toFixed(2)}%`
                    : "—"
                }
                accent
              />
              <MetricRow
                label="股息率"
                value={
                  metrics?.dividend_yield != null
                    ? `${(metrics.dividend_yield * 100).toFixed(2)}%`
                    : "—"
                }
              />
              <MetricRow
                label="Beta"
                value={fmtRatio(metrics?.beta)}
              />
              <MetricRow
                label="负债权益比"
                value={fmtRatio(metrics?.debt_to_equity)}
              />
            </CardContent>
          </Card>
        </div>

        {/* 技术指标（最新一根，backend 本地计算） */}
        <Card className="mt-4">
          <CardHeader>
            <CardTitle className="text-sm">
              技术指标{latestTech ? `（${latestTech.date}）` : ""}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {latestTech ? (
              <div className="grid grid-cols-1 gap-x-8 md:grid-cols-3">
                <div>
                  <MetricRow label="DIF" value={fmtSigned(latestTech.dif)} accent />
                  <MetricRow label="DEA" value={fmtSigned(latestTech.dea)} accent />
                  <MetricRow
                    label="MACD 柱"
                    value={fmtSigned(latestTech.macd)}
                    accent
                  />
                </div>
                <div>
                  <MetricRow label="RSI 6" value={fmtRatio(latestTech.rsi6)} />
                  <MetricRow label="RSI 14" value={fmtRatio(latestTech.rsi14)} />
                  <MetricRow label="MA5 / MA20 / MA60"
                    value={
                      latestTech.ma5 != null
                        ? `${fmtRatio(latestTech.ma5)} / ${fmtRatio(
                            latestTech.ma20
                          )} / ${fmtRatio(latestTech.ma60)}`
                        : "—"
                    }
                  />
                </div>
                <div>
                  <MetricRow
                    label="BOLL 上轨"
                    value={fmtRatio(latestTech.boll_upper)}
                  />
                  <MetricRow
                    label="BOLL 中轨"
                    value={fmtRatio(latestTech.boll_mid)}
                  />
                  <MetricRow
                    label="BOLL 下轨"
                    value={fmtRatio(latestTech.boll_lower)}
                  />
                  {bollPos != null && (
                    <div className="pt-2">
                      <Progress value={bollPos} className="h-1.5 bg-panel-2" />
                      <div className="mt-2 flex justify-between text-[10px] text-muted-foreground">
                        <span>下轨</span>
                        <Tooltip>
                          <TooltipTrigger className="tab-nums cursor-help">
                            现价位置 {bollPos.toFixed(0)}%
                          </TooltipTrigger>
                          <TooltipContent>
                            现价在 BOLL 下轨与上轨之间的相对位置（0% = 下轨，100% = 上轨）
                          </TooltipContent>
                        </Tooltip>
                        <span>上轨</span>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <EmptyState title="暂无技术指标数据" />
            )}
          </CardContent>
        </Card>

        {/* 分析师共识 */}
        <Card className="mt-4">
          <CardHeader>
            <CardTitle className="text-sm">分析师共识</CardTitle>
          </CardHeader>
          <CardContent>
            {recoLabel || targetMid != null ? (
              <div className="flex flex-col gap-4">
                <div className="flex flex-wrap items-center gap-3">
                  {recoLabel && <Badge variant="secondary">{recoLabel}</Badge>}
                  {consensus?.recommendation_mean != null && (
                    <span className="tab-nums text-xs text-muted-foreground">
                      Yahoo Finance 评级均值{" "}
                      {consensus.recommendation_mean.toFixed(1)}
                      （1 = 强力买入，5 = 强力卖出）
                    </span>
                  )}
                  {consensus?.number_of_analysts != null && (
                    <span className="tab-nums text-xs text-muted-foreground">
                      {consensus.number_of_analysts} 位分析师
                    </span>
                  )}
                  {consensus?.currency && (
                    <span className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                      {consensus.currency}
                    </span>
                  )}
                </div>
                {hasTargetRange && (
                  <div>
                    {/* 可比参考价在目标区间的位置；共识/低/高刻度见下方文字行 */}
                    <Progress
                      value={refPrice != null ? rangePos(refPrice) : 0}
                      className="h-1.5 bg-panel-2"
                    />
                    <div className="mt-2 flex justify-between text-[10px] text-muted-foreground">
                      <span className="tab-nums">低 {fmtPrice(targetLow)}</span>
                      {targetMid != null && (
                        <Tooltip>
                          <TooltipTrigger className="tab-nums cursor-help">
                            共识 {fmtPrice(targetMid)}
                          </TooltipTrigger>
                          <TooltipContent>分析师共识目标价</TooltipContent>
                        </Tooltip>
                      )}
                      <span className="tab-nums">高 {fmtPrice(targetHigh)}</span>
                    </div>
                  </div>
                )}
                {upside != null && refPrice != null && (
                  <div className="text-xs text-muted-foreground">
                    <Tooltip>
                      <TooltipTrigger className="cursor-help">
                        {refPriceLabel}{" "}
                        <span className="tab-nums">{fmtPrice(refPrice)}</span>
                      </TooltipTrigger>
                      <TooltipContent>
                        {hasTargetRange
                          ? `${refPriceLabel}在目标价区间内的位置 ${rangePos(refPrice).toFixed(0)}%`
                          : usesDisplayedConsensusPrice
                            ? "当前展示价，货币与共识目标价一致"
                            : "分析师共识记录中的当前价"}
                      </TooltipContent>
                    </Tooltip>
                    ，较共识目标价{" "}
                    <span
                      className={`tab-nums ${
                        upside >= 0 ? "text-up" : "text-down"
                      }`}
                    >
                      {fmtPct(upside)}
                    </span>
                  </div>
                )}
              </div>
            ) : (
              <EmptyState title="暂无分析师共识数据" />
            )}
          </CardContent>
        </Card>

        {/* 最新公告（仅 A 股，东财源） */}
        {isAShare && (
          <Card className="mt-4">
            <CardHeader>
              <CardTitle className="text-sm">最新公告</CardTitle>
            </CardHeader>
            <CardContent>
              {announcements.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-28">日期</TableHead>
                      <TableHead className="w-28">类型</TableHead>
                      <TableHead>标题</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {announcements.slice(0, 20).map((item, i) => (
                      <TableRow key={i}>
                        <TableCell className="tab-nums text-muted-foreground">
                          {item.publish_date ?? "—"}
                        </TableCell>
                        <TableCell>
                          {item.category ? (
                            <Badge
                              variant="outline"
                              className={
                                HOT_ANNOUNCEMENT_CATEGORIES.includes(
                                  item.category
                                )
                                  ? "border-accent/50 text-accent"
                                  : "border-border text-muted-foreground"
                              }
                            >
                              {item.category}
                            </Badge>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                        <TableCell className="font-medium">
                          {item.url ? (
                            <a
                              href={item.url}
                              target="_blank"
                              rel="noreferrer"
                              className="hover:text-accent hover:underline"
                            >
                              {item.title}
                            </a>
                          ) : (
                            item.title
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <EmptyState title="暂无公告数据" />
              )}
            </CardContent>
          </Card>
        )}

        {/* 券商研报（仅 A 股，东财源） */}
        {isAShare && (
          <Card className="mt-4">
            <CardHeader>
              <CardTitle className="text-sm">券商研报</CardTitle>
            </CardHeader>
            <CardContent>
              {researchReports.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-28">日期</TableHead>
                      <TableHead className="w-28">机构</TableHead>
                      <TableHead className="w-20">评级</TableHead>
                      <TableHead>标题</TableHead>
                      <TableHead className="w-48">盈利预测</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {researchReports.slice(0, 20).map((item, i) => (
                      <TableRow key={i}>
                        <TableCell className="tab-nums text-muted-foreground">
                          {item.publish_date ?? "—"}
                        </TableCell>
                        <TableCell className="text-fg-dim">
                          {item.org ?? "—"}
                        </TableCell>
                        <TableCell>
                          {item.rating ? (
                            <Badge
                              variant="outline"
                              className={ratingBadgeClass(item.rating)}
                            >
                              {item.rating}
                            </Badge>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                        <TableCell className="font-medium">
                          {item.url ? (
                            <a
                              href={item.url}
                              target="_blank"
                              rel="noreferrer"
                              className="hover:text-accent hover:underline"
                            >
                              {item.title}
                            </a>
                          ) : (
                            item.title
                          )}
                        </TableCell>
                        <TableCell className="tab-nums text-fg-dim">
                          {item.forecast_year != null &&
                          item.eps_forecast != null
                            ? `${item.forecast_year}E EPS ${item.eps_forecast.toFixed(
                                2
                              )} / PE ${
                                item.pe_forecast != null
                                  ? item.pe_forecast.toFixed(1)
                                  : "—"
                              }`
                            : "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <EmptyState title="暂无研报数据" />
              )}
            </CardContent>
          </Card>
        )}

        {/* 财报模块 */}
        <Card className="mt-4">
          <CardHeader>
            <CardTitle className="text-sm">利润表（年度，SEC 源）</CardTitle>
          </CardHeader>
          <CardContent>
            {income.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>年度</TableHead>
                    <TableHead className="text-right">总营收</TableHead>
                    <TableHead className="text-right">毛利</TableHead>
                    <TableHead className="text-right">营业利润</TableHead>
                    <TableHead className="text-right">净利润</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {income.map((item, i) => (
                    <TableRow key={i}>
                      <TableCell className="font-medium">
                        {item.fiscal_year ?? "—"}
                      </TableCell>
                      <TableCell className="text-right tab-nums">
                        {fmtBigNumber(item.total_revenue, financialCurrency)}
                      </TableCell>
                      <TableCell className="text-right tab-nums">
                        {fmtBigNumber(item.gross_profit, financialCurrency)}
                      </TableCell>
                      <TableCell className="text-right tab-nums">
                        {fmtBigNumber(item.operating_income, financialCurrency)}
                      </TableCell>
                      <TableCell className="text-right tab-nums">
                        {fmtBigNumber(item.net_income, financialCurrency)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <EmptyState
                title="无财报数据"
                description="SEC 源不覆盖此标的"
              />
            )}
          </CardContent>
        </Card>

        {/* 资产负债表 / 现金流量表（年度，最近 4 期） */}
        <Card className="mt-4">
          <CardHeader>
            <CardTitle className="text-sm">
              资产负债表 / 现金流量表（年度）
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="balance">
              <TabsList>
                <TabsTrigger value="balance">资产负债表</TabsTrigger>
                <TabsTrigger value="cashflow">现金流量表</TabsTrigger>
              </TabsList>
              <TabsContent value="balance" className="mt-4">
                {balanceRows.length > 0 ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>期末日</TableHead>
                        <TableHead className="text-right">总资产</TableHead>
                        <TableHead className="text-right">总负债</TableHead>
                        <TableHead className="text-right">股东权益</TableHead>
                        <TableHead className="text-right">货币资金</TableHead>
                        <TableHead className="text-right">总债务</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {balanceRows.map((item, i) => (
                        <TableRow key={i}>
                          <TableCell className="font-medium">
                            {item.fiscal_date ?? "—"}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtBigNumber(item.total_assets, financialCurrency)}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtBigNumber(
                              item.total_liabilities,
                              financialCurrency
                            )}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtBigNumber(item.total_equity, financialCurrency)}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtBigNumber(
                              item.cash_and_equivalents,
                              financialCurrency
                            )}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtBigNumber(item.total_debt, financialCurrency)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <EmptyState title="暂无资产负债表数据" />
                )}
              </TabsContent>
              <TabsContent value="cashflow" className="mt-4">
                {cashFlowRows.length > 0 ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>期末日</TableHead>
                        <TableHead className="text-right">经营现金流</TableHead>
                        <TableHead className="text-right">投资现金流</TableHead>
                        <TableHead className="text-right">筹资现金流</TableHead>
                        <TableHead className="text-right">资本开支</TableHead>
                        <TableHead className="text-right">自由现金流</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {cashFlowRows.map((item, i) => (
                        <TableRow key={i}>
                          <TableCell className="font-medium">
                            {item.fiscal_date ?? "—"}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtBigNumber(
                              item.operating_cash_flow,
                              financialCurrency
                            )}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtBigNumber(
                              item.investing_cash_flow,
                              financialCurrency
                            )}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtBigNumber(
                              item.financing_cash_flow,
                              financialCurrency
                            )}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtBigNumber(
                              item.capital_expenditure,
                              financialCurrency
                            )}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtBigNumber(item.free_cash_flow, financialCurrency)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <EmptyState title="暂无现金流量表数据" />
                )}
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>

        {/* 公司简介 */}
        {profile?.description && (
          <Card className="mt-4">
            <CardHeader>
              <CardTitle className="text-sm">公司简介</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm leading-relaxed text-fg-dim">
                {profile.description}
              </p>
            </CardContent>
          </Card>
        )}
    </div>
  );
}
