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
  type EquityProfile,
  type FundamentalMetrics,
  type IncomeStatement,
  type HistoricalPrice,
} from "@/lib/openbb";
import { fmtPrice, fmtPct, fmtVolume } from "@/lib/format";
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
import { Badge } from "@/components/ui/badge";

// 简易 K 线图（SVG，不依赖 TradingView）
function MiniChart({ data }: { data: HistoricalPrice[] }) {
  if (data.length < 2) {
    return (
      <div className="flex h-64 items-center justify-center text-muted">
        无历史数据
      </div>
    );
  }

  const width = 800;
  const height = 300;
  const padding = 40;
  const chartW = width - padding * 2;
  const chartH = height - padding * 2;

  const prices = data.map((d) => d.close);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const span = max - min || 1;

  const points = data
    .map((d, i) => {
      const x = padding + (i / (data.length - 1)) * chartW;
      const y = padding + chartH - ((d.close - min) / span) * chartH;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const up = data[data.length - 1].close >= data[0].close;
  const strokeColor = up ? "var(--up)" : "var(--down)";

  // 日期标签（首尾）
  const firstDate = data[0].date;
  const lastDate = data[data.length - 1].date;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-64"
      preserveAspectRatio="none"
    >
      {/* 网格线 */}
      {[0, 0.25, 0.5, 0.75, 1].map((t) => (
        <line
          key={t}
          x1={padding}
          y1={padding + t * chartH}
          x2={width - padding}
          y2={padding + t * chartH}
          stroke="var(--border)"
          strokeWidth="0.5"
          strokeDasharray="2,4"
        />
      ))}
      {/* 价格线 */}
      <polyline
        points={points}
        fill="none"
        stroke={strokeColor}
        strokeWidth="2"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      {/* 日期标签 */}
      <text
        x={padding}
        y={height - 10}
        fill="var(--muted)"
        fontSize="11"
        fontFamily="monospace"
      >
        {firstDate}
      </text>
      <text
        x={width - padding - 60}
        y={height - 10}
        fill="var(--muted)"
        fontSize="11"
        fontFamily="monospace"
      >
        {lastDate}
      </text>
    </svg>
  );
}

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
        <span className="text-xs text-muted">{label}</span>
        <span className="tab-nums text-sm text-muted">—</span>
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
      <span className="text-xs text-muted">{label}</span>
      <span className={`tab-nums text-sm ${colorClass}`}>{value}</span>
    </div>
  );
}

function fmtBigNumber(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
  if (value >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (value >= 1e6) return `$${(value / 1e6).toFixed(2)}M`;
  return `$${value.toLocaleString("en-US")}`;
}

function fmtRatio(value: number | null | undefined): string {
  if (value == null) return "—";
  return value.toFixed(2);
}

export default async function StockDetailPage({
  params,
}: {
  params: Promise<{ symbol: string }>;
}) {
  const { symbol } = await params;
  if (!symbol) notFound();

  // 并行拉取所有数据
  const [profile, metrics, income, historical] = await Promise.all([
    getEquityProfile(symbol).catch(() => null),
    getFundamentalMetrics(symbol).catch(() => null),
    getIncomeStatements(symbol).catch(() => []),
    getEquityHistorical(
      symbol,
      new Date(Date.now() - 180 * 24 * 60 * 60 * 1000)
        .toISOString()
        .slice(0, 10),
      new Date().toISOString().slice(0, 10)
    ).catch(() => []),
  ]);

  const displayName = profile?.name ?? symbol;
  const lastPrice =
    historical.length > 0 ? historical[historical.length - 1].close : null;
  const prevClose =
    historical.length > 1 ? historical[historical.length - 2].close : null;
  const changePct =
    lastPrice && prevClose ? (lastPrice - prevClose) / prevClose : null;

  return (
    <>
      {/* 标题区 */}
      <header className="mb-6 flex items-start justify-between border-b border-border pb-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold">{displayName}</h1>
            <Badge variant="secondary">{symbol}</Badge>
          </div>
          <div className="mt-1 flex items-center gap-3 text-xs text-muted">
            {profile?.exchange && <span>{profile.exchange}</span>}
            {profile?.currency && <span>{profile.currency}</span>}
            {profile?.sector && <span>{profile.sector}</span>}
          </div>
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
          {/* K 线图（占 2 列） */}
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="text-sm">价格走势（6 个月）</CardTitle>
            </CardHeader>
            <CardContent>
              <MiniChart data={historical} />
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
              <div className="py-8 text-center text-muted">
                无财报数据（SEC 源不覆盖此标的）
              </div>
            )}
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
    </>
  );
}
