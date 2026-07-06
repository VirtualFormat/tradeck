/**
 * 宏观数据页
 * 路由：/macro
 * 数据：OpenBB API（oecd + federal_reserve 免费源）
 * - CPI（消费者价格指数）
 * - 失业率
 * - GDP（名义）
 * - EFFR（联邦基金有效利率）
 * - SOFR（担保隔夜融资利率）
 */
import Link from "next/link";
import {
  getCPI,
  getUnemployment,
  getGDPNominal,
  getEFFR,
  getSOFR,
  type MacroSeries,
  type RateSeries,
} from "@/lib/openbb";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

function fmtPct(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

function fmtBigValue(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
  if (value >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  return value.toLocaleString("en-US");
}

function fmtDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  return d.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit" });
}

// 走势图（SVG）
function TrendChart({
  data,
  color,
  formatValue,
}: {
  data: { date: string; value: number }[];
  color: string;
  formatValue: (v: number) => string;
}) {
  if (data.length < 2) {
    return (
      <div className="flex h-32 items-center justify-center text-xs text-muted">
        无历史数据
      </div>
    );
  }

  const width = 400;
  const height = 120;
  const padding = 30;
  const chartW = width - padding * 2;
  const chartH = height - padding * 2;

  const values = data.map((d) => d.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;

  const points = data
    .map((d, i) => {
      const x = padding + (i / (data.length - 1)) * chartW;
      const y = padding + chartH - ((d.value - min) / span) * chartH;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-32"
      preserveAspectRatio="none"
    >
      {[0, 0.5, 1].map((t) => (
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
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      <text x={padding} y={height - 8} fill="var(--muted)" fontSize="9">
        {fmtDate(data[0].date)}
      </text>
      <text
        x={width - padding - 50}
        y={height - 8}
        fill="var(--muted)"
        fontSize="9"
      >
        {fmtDate(data[data.length - 1].date)}
      </text>
    </svg>
  );
}

function MacroCard({
  title,
  latestValue,
  latestDate,
  change,
  chartData,
  color,
  formatValue,
}: {
  title: string;
  latestValue: string;
  latestDate: string;
  change: string | null;
  chartData: { date: string; value: number }[];
  color: string;
  formatValue: (v: number) => string;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-baseline justify-between">
          <div>
            <div className="tab-nums text-2xl font-bold">{latestValue}</div>
            <div className="text-[10px] text-muted">{latestDate}</div>
          </div>
          {change && (
            <div
              className={`tab-nums text-sm ${
                change.startsWith("+") ? "text-up" : "text-down"
              }`}
            >
              {change}
            </div>
          )}
        </div>
        <div className="mt-2">
          <TrendChart data={chartData} color={color} formatValue={formatValue} />
        </div>
      </CardContent>
    </Card>
  );
}

function calcChange(data: { value: number }[]): string | null {
  if (data.length < 2) return null;
  const last = data[data.length - 1].value;
  const prev = data[data.length - 2].value;
  const diff = last - prev;
  const pct = prev !== 0 ? (diff / prev) * 100 : 0;
  const sign = diff >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

export default async function MacroPage() {
  // 并行拉取所有宏观数据
  const [cpi, unemployment, gdp, effr, sofr] = await Promise.all([
    getCPI().catch(() => []),
    getUnemployment().catch(() => []),
    getGDPNominal().catch(() => []),
    getEFFR().catch(() => []),
    getSOFR().catch(() => []),
  ]);

  // 取最新值
  const latestCPI = cpi.length > 0 ? cpi[cpi.length - 1] : null;
  const latestUnemp = unemployment.length > 0 ? unemployment[unemployment.length - 1] : null;
  const latestGDP = gdp.length > 0 ? gdp[gdp.length - 1] : null;
  const latestEFFR = effr.length > 0 ? effr[effr.length - 1] : null;
  const latestSOFR = sofr.length > 0 ? sofr[sofr.length - 1] : null;

  return (
    <>

        <header className="mb-6 border-b border-border pb-3">
          <h1 className="text-lg font-semibold">宏观经济数据</h1>
          <p className="text-[10px] uppercase tracking-[0.18em] text-muted">
            US Macro Indicators · oecd + federal_reserve
          </p>
        </header>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {/* CPI */}
          <MacroCard
            title="CPI 消费者价格指数"
            latestValue={latestCPI ? fmtPct(latestCPI.value) : "—"}
            latestDate={fmtDate(latestCPI?.date)}
            change={calcChange(cpi)}
            chartData={cpi.map((d) => ({ date: d.date, value: d.value }))}
            color="var(--up)"
            formatValue={fmtPct}
          />

          {/* 失业率 */}
          <MacroCard
            title="失业率"
            latestValue={latestUnemp ? fmtPct(latestUnemp.value) : "—"}
            latestDate={fmtDate(latestUnemp?.date)}
            change={calcChange(unemployment)}
            chartData={unemployment.map((d) => ({ date: d.date, value: d.value }))}
            color="var(--warn)"
            formatValue={fmtPct}
          />

          {/* GDP */}
          <MacroCard
            title="GDP 名义（美国）"
            latestValue={latestGDP ? fmtBigValue(latestGDP.value) : "—"}
            latestDate={fmtDate(latestGDP?.date)}
            change={calcChange(gdp)}
            chartData={gdp.map((d) => ({ date: d.date, value: d.value }))}
            color="var(--accent)"
            formatValue={fmtBigValue}
          />

          {/* EFFR */}
          <MacroCard
            title="EFFR 联邦基金有效利率"
            latestValue={latestEFFR ? fmtPct(latestEFFR.rate) : "—"}
            latestDate={fmtDate(latestEFFR?.date)}
            change={calcChange(effr.map((d) => ({ value: d.rate })))}
            chartData={effr.map((d) => ({ date: d.date, value: d.rate }))}
            color="var(--down)"
            formatValue={fmtPct}
          />

          {/* SOFR */}
          <MacroCard
            title="SOFR 担保隔夜融资利率"
            latestValue={latestSOFR ? fmtPct(latestSOFR.rate) : "—"}
            latestDate={fmtDate(latestSOFR?.date)}
            change={calcChange(sofr.map((d) => ({ value: d.rate })))}
            chartData={sofr.map((d) => ({ date: d.date, value: d.rate }))}
            color="var(--down)"
            formatValue={fmtPct}
          />
        </div>
    </>
  );
}
