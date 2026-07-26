/**
 * 个股详情页
 * 路由：/stocks/[symbol]
 * 数据：OpenBB API（profile + metrics + income + historical）
 */
import { notFound } from "next/navigation";
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

function fmtBigNumber(value: number | null | undefined): string {
  if (value == null) return "—";
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  return `${sign}$${abs.toLocaleString("en-US")}`;
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
  const { symbol } = await params;
  if (!symbol) notFound();

  // A 股判断（profile/metrics 不支持 akshare，yfinance 调 A 股太慢 15s+）
  const isAShare = /\.(SS|SZ|BJ)$/.test(symbol.toUpperCase());

  // 并行拉取所有数据
  // A 股：只调 akshare historical（140ms 稳定），跳过 profile/metrics（yfinance 太慢）
  // 美股：调 yfinance profile + metrics + sec income + yfinance historical
  // 共识/资产负债表/现金流量表：全部读 backend DB（<50ms），各市场都可调，无数据走空态
  // 公告/研报：仅 A 股（东财源），同样读 backend DB
  const [profile, metrics, income, historical, consensus, balance, cashFlow, technicals, announcements, researchReports] =
    await Promise.all([
      isAShare ? Promise.resolve(null) : getEquityProfile(symbol).catch(() => null),
      isAShare ? Promise.resolve(null) : getFundamentalMetrics(symbol).catch(() => null),
      isAShare ? Promise.resolve([]) : getIncomeStatements(symbol).catch(() => []),
      getEquityHistorical(
        symbol,
        new Date(Date.now() - 180 * 24 * 60 * 60 * 1000)
          .toISOString()
          .slice(0, 10),
        new Date().toISOString().slice(0, 10)
      ).catch(() => []),
      getAnalystConsensus(symbol).catch(() => null),
      getBalanceSheets(symbol, "annual").catch(() => []),
      getCashFlowStatements(symbol, "annual").catch(() => []),
      fetchTechnicals(symbol, 120).catch(() => []),
      isAShare ? fetchAnnouncements(symbol, 30).catch(() => []) : Promise.resolve([]),
      isAShare ? fetchResearchReports(symbol, 90).catch(() => []) : Promise.resolve([]),
    ]);

  const displayName = profile?.name ?? symbol;
  const lastPrice =
    historical.length > 0 ? historical[historical.length - 1].close : null;
  const prevClose =
    historical.length > 1 ? historical[historical.length - 2].close : null;
  const changePct =
    lastPrice && prevClose ? (lastPrice - prevClose) / prevClose : null;
  const subtitle = [profile?.exchange, profile?.currency, profile?.sector]
    .filter(Boolean)
    .join(" · ");

  // ── 分析师共识派生值 ──
  const targetLow = consensus?.target_low ?? null;
  const targetHigh = consensus?.target_high ?? null;
  const targetMid = consensus?.target_consensus ?? null;
  const refPrice = consensus?.current_price ?? lastPrice;
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
    targetMid != null && refPrice ? targetMid / refPrice - 1 : null;

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
        {lastPrice && (
          <div className="text-right">
            <div className="tab-nums text-3xl font-bold">
              {fmtPrice(lastPrice)}
            </div>
            {changePct && (
              <div
                className={`tab-nums text-sm ${
                  changePct >= 0 ? "text-up" : "text-down"
                }`}
              >
                {fmtPct(changePct)}
              </div>
            )}
          </div>
        )}
      </header>

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
                value={fmtBigNumber(metrics?.market_cap)}
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
                      综合评分 {consensus.recommendation_mean.toFixed(1)} / 5
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
                    {/* 现价在目标价 low-high 区间的位置；共识/低/高刻度见下方文字行 */}
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
                        现价{" "}
                        <span className="tab-nums">{fmtPrice(refPrice)}</span>
                      </TooltipTrigger>
                      <TooltipContent>
                        {hasTargetRange
                          ? `现价在目标价区间内的位置 ${rangePos(refPrice).toFixed(0)}%`
                          : "当前最新价"}
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
                        {fmtBigNumber(item.total_revenue)}
                      </TableCell>
                      <TableCell className="text-right tab-nums">
                        {fmtBigNumber(item.gross_profit)}
                      </TableCell>
                      <TableCell className="text-right tab-nums">
                        {fmtBigNumber(item.operating_income)}
                      </TableCell>
                      <TableCell className="text-right tab-nums">
                        {fmtBigNumber(item.net_income)}
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
                            {fmtBigNumber(item.total_assets)}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtBigNumber(item.total_liabilities)}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtBigNumber(item.total_equity)}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtBigNumber(item.cash_and_equivalents)}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtBigNumber(item.total_debt)}
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
                            {fmtBigNumber(item.operating_cash_flow)}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtBigNumber(item.investing_cash_flow)}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtBigNumber(item.financing_cash_flow)}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtBigNumber(item.capital_expenditure)}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtBigNumber(item.free_cash_flow)}
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
