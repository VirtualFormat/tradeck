/** 宏观工作区：指标趋势视图（CPI / 失业率 / GDP / 政策利率）。 */
import {
  getCPI,
  getEFFR,
  getGDPNominal,
  getSOFR,
  getUnemployment,
} from "@/lib/openbb";
import { fmtBigUSD, fmtMacroPct } from "@/lib/format";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { MacroTrendChart } from "@/components/macro-trend-chart";

function fmtMonthDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  return d.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit" });
}

function fmtDailyDate(dateStr: string | null | undefined): string {
  return dateStr ? dateStr.slice(0, 10) : "—";
}

function MacroCard({
  title,
  latestValue,
  latestDate,
  source,
  change,
  changeTone,
  chartData,
  color,
  formatType,
}: {
  title: string;
  latestValue: string;
  latestDate: string;
  source: "OECD" | "Federal Reserve";
  change: string | null;
  changeTone: "up" | "down" | "neutral";
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
            <div className="text-[10px] text-muted-foreground">
              {source} · 截至 {latestDate}
            </div>
          </div>
          {change && (
            <div
              className={`tab-nums text-sm ${
                changeTone === "up"
                  ? "text-up"
                  : changeTone === "down"
                    ? "text-down"
                    : "text-muted-foreground"
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

type ChangeDisplay = {
  text: string | null;
  tone: "up" | "down" | "neutral";
};

function changeTone(diff: number): ChangeDisplay["tone"] {
  return diff > 0 ? "up" : diff < 0 ? "down" : "neutral";
}

function calcRelativeChange(data: { value: number }[]): ChangeDisplay {
  if (data.length < 2) return { text: null, tone: "neutral" };
  const last = data[data.length - 1].value;
  const prev = data[data.length - 2].value;
  const diff = last - prev;
  if (prev === 0) return { text: null, tone: changeTone(diff) };
  const pct = (diff / prev) * 100;
  const sign = pct > 0 ? "+" : "";
  return { text: `${sign}${pct.toFixed(2)}%`, tone: changeTone(diff) };
}

function calcPointChange(data: { value: number }[]): ChangeDisplay {
  if (data.length < 2) return { text: null, tone: "neutral" };
  const last = data[data.length - 1].value;
  const prev = data[data.length - 2].value;
  const diff = last - prev;
  const points = diff * 100;
  const sign = points > 0 ? "+" : "";
  return {
    text: `${sign}${points.toFixed(2)} pp`,
    tone: changeTone(diff),
  };
}

function calcBasisPointChange(data: { value: number }[]): ChangeDisplay {
  if (data.length < 2) return { text: null, tone: "neutral" };
  const last = data[data.length - 1].value;
  const prev = data[data.length - 2].value;
  const diff = last - prev;
  const basisPoints = diff * 10000;
  const sign = basisPoints > 0 ? "+" : "";
  return {
    text: `${sign}${basisPoints.toFixed(0)} bp`,
    tone: changeTone(diff),
  };
}

export async function MacroIndicatorSection() {
  const [cpi, unemployment, gdp, effr, sofr] = await Promise.all([
    getCPI("oecd", 60).catch(() => []),
    getUnemployment("oecd", 60).catch(() => []),
    getGDPNominal("oecd", 40).catch(() => []),
    getEFFR("federal_reserve", 250).catch(() => []),
    getSOFR("federal_reserve", 250).catch(() => []),
  ]);

  const latestCPI = cpi.at(-1) ?? null;
  const latestUnemp = unemployment.at(-1) ?? null;
  const latestGDP = gdp.at(-1) ?? null;
  const latestEFFR = effr.at(-1) ?? null;
  const latestSOFR = sofr.at(-1) ?? null;
  const cpiChange = calcPointChange(cpi);
  const unemploymentChange = calcPointChange(unemployment);
  const gdpChange = calcRelativeChange(gdp);
  const effrChange = calcBasisPointChange(
    effr.map((item) => ({ value: item.rate }))
  );
  const sofrChange = calcBasisPointChange(
    sofr.map((item) => ({ value: item.rate }))
  );

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
      <MacroCard
        title="CPI 消费者价格指数"
        latestValue={latestCPI ? fmtMacroPct(latestCPI.value) : "—"}
        latestDate={fmtMonthDate(latestCPI?.date)}
        source="OECD"
        change={cpiChange.text}
        changeTone={cpiChange.tone}
        chartData={cpi.map((d) => ({ date: d.date, value: d.value }))}
        color="var(--up)"
        formatType="pct"
      />

      <MacroCard
        title="失业率"
        latestValue={latestUnemp ? fmtMacroPct(latestUnemp.value) : "—"}
        latestDate={fmtMonthDate(latestUnemp?.date)}
        source="OECD"
        change={unemploymentChange.text}
        changeTone={unemploymentChange.tone}
        chartData={unemployment.map((d) => ({ date: d.date, value: d.value }))}
        color="var(--warn)"
        formatType="pct"
      />

      <MacroCard
        title="GDP 名义（美国）"
        latestValue={latestGDP ? fmtBigUSD(latestGDP.value) : "—"}
        latestDate={fmtMonthDate(latestGDP?.date)}
        source="OECD"
        change={gdpChange.text}
        changeTone={gdpChange.tone}
        chartData={gdp.map((d) => ({ date: d.date, value: d.value }))}
        color="var(--accent)"
        formatType="bigValue"
      />

      <MacroCard
        title="EFFR 联邦基金有效利率"
        latestValue={latestEFFR ? fmtMacroPct(latestEFFR.rate) : "—"}
        latestDate={fmtDailyDate(latestEFFR?.date)}
        source="Federal Reserve"
        change={effrChange.text}
        changeTone={effrChange.tone}
        chartData={effr.map((d) => ({ date: d.date, value: d.rate }))}
        color="var(--down)"
        formatType="pct"
      />

      <MacroCard
        title="SOFR 担保隔夜融资利率"
        latestValue={latestSOFR ? fmtMacroPct(latestSOFR.rate) : "—"}
        latestDate={fmtDailyDate(latestSOFR?.date)}
        source="Federal Reserve"
        change={sofrChange.text}
        changeTone={sofrChange.tone}
        chartData={sofr.map((d) => ({ date: d.date, value: d.rate }))}
        color="var(--down)"
        formatType="pct"
      />
    </div>
  );
}
