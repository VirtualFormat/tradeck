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
  fetchEarningsCalendar,
  fetchEconomicCalendar,
} from "@/lib/openbb";
import { fmtMacroPct, fmtBigUSD } from "@/lib/format";
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
import { MacroTrendChart } from "@/components/macro-trend-chart";
import { EmptyState } from "@/components/empty-state";

// 强制动态渲染：生产构建下不做静态预渲染，每次请求实时从 backend 取数（宏观/日历数据有时效性）
export const dynamic = "force-dynamic";

function fmtDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  return d.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit" });
}

/** 日历用短日期：07-30 周四 */
function fmtCalDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const d = new Date(`${dateStr}T00:00:00`);
  return d.toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
  });
}

/** 财报披露时段：BMO 盘前 / AMC 盘后 / 其他未知 */
function fmtSession(session: string | null): string {
  if (session === "BMO") return "盘前";
  if (session === "AMC") return "盘后";
  return "—";
}

/** 重要性着色：高=红（重点关注）、中=警告色、其他=灰 */
function importanceClass(importance: string | null): string {
  if (importance === "高" || importance === "high") return "text-up";
  if (importance === "中" || importance === "medium") return "text-warn";
  return "text-muted-foreground";
}

function MacroCard({
  title,
  latestValue,
  latestDate,
  change,
  chartData,
  color,
  formatType,
}: {
  title: string;
  latestValue: string;
  latestDate: string;
  change: string | null;
  chartData: { date: string; value: number }[];
  color: string;
  formatType: "pct" | "bigValue";
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
            <div className="text-[10px] text-muted-foreground">{latestDate}</div>
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
          <MacroTrendChart data={chartData} color={color} formatType={formatType} />
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
  const [cpi, unemployment, gdp, effr, sofr, earnings, econEvents] =
    await Promise.all([
      getCPI("oecd", 60).catch(() => []),
      getUnemployment("oecd", 60).catch(() => []),
      getGDPNominal("oecd", 40).catch(() => []),
      getEFFR("federal_reserve", 250).catch(() => []),
      getSOFR("federal_reserve", 250).catch(() => []),
      fetchEarningsCalendar(14).catch(() => []),
      fetchEconomicCalendar(7).catch(() => []),
    ]);

  // 取最新值
  const latestCPI = cpi.length > 0 ? cpi[cpi.length - 1] : null;
  const latestUnemp = unemployment.length > 0 ? unemployment[unemployment.length - 1] : null;
  const latestGDP = gdp.length > 0 ? gdp[gdp.length - 1] : null;
  const latestEFFR = effr.length > 0 ? effr[effr.length - 1] : null;
  const latestSOFR = sofr.length > 0 ? sofr[sofr.length - 1] : null;

  return (
    <div className="px-4 lg:px-6">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {/* CPI */}
          <MacroCard
            title="CPI 消费者价格指数"
            latestValue={latestCPI ? fmtMacroPct(latestCPI.value) : "—"}
            latestDate={fmtDate(latestCPI?.date)}
            change={calcChange(cpi)}
            chartData={cpi.map((d) => ({ date: d.date, value: d.value }))}
            color="var(--up)"
            formatType="pct"
          />

          {/* 失业率 */}
          <MacroCard
            title="失业率"
            latestValue={latestUnemp ? fmtMacroPct(latestUnemp.value) : "—"}
            latestDate={fmtDate(latestUnemp?.date)}
            change={calcChange(unemployment)}
            chartData={unemployment.map((d) => ({ date: d.date, value: d.value }))}
            color="var(--warn)"
            formatType="pct"
          />

          {/* GDP */}
          <MacroCard
            title="GDP 名义（美国）"
            latestValue={latestGDP ? fmtBigUSD(latestGDP.value) : "—"}
            latestDate={fmtDate(latestGDP?.date)}
            change={calcChange(gdp)}
            chartData={gdp.map((d) => ({ date: d.date, value: d.value }))}
            color="var(--accent)"
            formatType="bigValue"
          />

          {/* EFFR */}
          <MacroCard
            title="EFFR 联邦基金有效利率"
            latestValue={latestEFFR ? fmtMacroPct(latestEFFR.rate) : "—"}
            latestDate={fmtDate(latestEFFR?.date)}
            change={calcChange(effr.map((d) => ({ value: d.rate })))}
            chartData={effr.map((d) => ({ date: d.date, value: d.rate }))}
            color="var(--down)"
            formatType="pct"
          />

          {/* SOFR */}
          <MacroCard
            title="SOFR 担保隔夜融资利率"
            latestValue={latestSOFR ? fmtMacroPct(latestSOFR.rate) : "—"}
            latestDate={fmtDate(latestSOFR?.date)}
            change={calcChange(sofr.map((d) => ({ value: d.rate })))}
            chartData={sofr.map((d) => ({ date: d.date, value: d.rate }))}
            color="var(--down)"
            formatType="pct"
          />
        </div>

      {/* 日历区块：财报日历 + 宏观数据日历（源不可用时显示暂无数据，属预期降级） */}
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* 财报日历 */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">财报日历（未来 14 天）</CardTitle>
          </CardHeader>
          <CardContent>
            {earnings.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>日期</TableHead>
                    <TableHead>代码</TableHead>
                    <TableHead>时段</TableHead>
                    <TableHead className="text-right">EPS 预期</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {earnings.map((item) => (
                    <TableRow key={`${item.symbol}-${item.report_date}`}>
                      <TableCell className="tab-nums whitespace-nowrap">
                        {fmtCalDate(item.report_date)}
                      </TableCell>
                      <TableCell>
                        <Link
                          href={`/stocks/${item.symbol}`}
                          className="font-medium hover:text-accent"
                        >
                          {item.symbol}
                        </Link>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {fmtSession(item.session)}
                      </TableCell>
                      <TableCell className="text-right tab-nums">
                        {item.eps_estimate != null
                          ? item.eps_estimate.toFixed(2)
                          : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>

        {/* 宏观数据日历 */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">宏观数据日历（未来 7 天）</CardTitle>
          </CardHeader>
          <CardContent>
            {econEvents.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>日期</TableHead>
                    <TableHead>时间</TableHead>
                    <TableHead>国家</TableHead>
                    <TableHead>事件</TableHead>
                    <TableHead>重要性</TableHead>
                    <TableHead className="text-right">预期</TableHead>
                    <TableHead className="text-right">前值</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {econEvents.map((item, idx) => (
                    <TableRow key={`${item.event_date}-${item.event_name}-${idx}`}>
                      <TableCell className="tab-nums whitespace-nowrap">
                        {fmtCalDate(item.event_date)}
                      </TableCell>
                      <TableCell className="tab-nums text-muted-foreground">
                        {item.event_time ?? "—"}
                      </TableCell>
                      <TableCell className="whitespace-nowrap">
                        {item.country ?? "—"}
                      </TableCell>
                      <TableCell>{item.event_name}</TableCell>
                      <TableCell className={importanceClass(item.importance)}>
                        {item.importance ?? "—"}
                      </TableCell>
                      <TableCell className="text-right tab-nums">
                        {item.forecast ?? "—"}
                      </TableCell>
                      <TableCell className="text-right tab-nums text-muted-foreground">
                        {item.previous ?? "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
