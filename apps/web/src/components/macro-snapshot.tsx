/**
 * 宏观速览（首页用）
 * 显示 CPI + EFFR + 失业率 三个关键指标
 * 卡片风格套用 shadcn block SectionCards，mini LineChart 展示历史序列
 */
import { getCPI, getEFFR, getUnemployment } from "@/lib/openbb";
import { fmtPct, fmtDataMonth } from "@/lib/format";
import Link from "next/link";
import { MacroCard } from "@/components/macro-card";

async function fetchMacroSnapshot() {
  const [cpi, effr, unemp] = await Promise.all([
    getCPI("oecd", 60).catch(() => []),
    getEFFR("federal_reserve", 250).catch(() => []),
    getUnemployment("oecd", 60).catch(() => []),
  ]);
  return {
    cpi: cpi.length > 0 ? cpi[cpi.length - 1] : null,
    cpiPrev: cpi.length > 1 ? cpi[cpi.length - 2] : null,
    cpiHist: cpi.map((p) => ({ date: p.date, value: p.value })),
    effr: effr.length > 0 ? effr[effr.length - 1] : null,
    effrPrev: effr.length > 1 ? effr[effr.length - 2] : null,
    effrHist: effr.map((p) => ({ date: p.date, value: p.rate })),
    unemp: unemp.length > 0 ? unemp[unemp.length - 1] : null,
    unempPrev: unemp.length > 1 ? unemp[unemp.length - 2] : null,
    unempHist: unemp.map((p) => ({ date: p.date, value: p.value })),
  };
}

function fmtDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  return d.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

/** 计算环比变化（百分比），返回带符号字符串如 "+1.23%" / "-0.5%" */
function calcChange(
  latest: number | null | undefined,
  prev: number | null | undefined
): string | null {
  if (latest == null || prev == null || prev === 0) return null;
  const diff = latest - prev;
  const pct = (diff / prev) * 100;
  const sign = diff >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

export async function MacroSnapshot() {
  const macro = await fetchMacroSnapshot();
  // 数据月份：以 CPI 最新一期为准（与 /macro 页「2026年6月」格式一致）
  const monthLabel = fmtDataMonth(macro.cpi?.date);

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <h3 className="text-xs font-medium text-fg-dim">宏观速览</h3>
          {monthLabel && (
            <span className="text-xs text-muted-foreground">{monthLabel}</span>
          )}
        </div>
        <Link href="/macro" className="text-[10px] text-muted-foreground hover:text-fg">
          更多 →
        </Link>
      </div>
      <div className="grid grid-cols-1 gap-3">
        <MacroCard
          label="CPI 消费者价格指数"
          value={macro.cpi ? fmtPct(macro.cpi.value) : "—"}
          change={calcChange(macro.cpi?.value, macro.cpiPrev?.value)}
          date={fmtDate(macro.cpi?.date)}
          href="/macro"
          hist={macro.cpiHist}
        />
        <MacroCard
          label="EFFR 联邦基金有效利率"
          value={macro.effr ? fmtPct(macro.effr.rate) : "—"}
          change={calcChange(macro.effr?.rate, macro.effrPrev?.rate)}
          date={fmtDate(macro.effr?.date)}
          href="/macro"
          hist={macro.effrHist}
        />
        <MacroCard
          label="失业率"
          value={macro.unemp ? fmtPct(macro.unemp.value) : "—"}
          change={calcChange(macro.unemp?.value, macro.unempPrev?.value)}
          date={fmtDate(macro.unemp?.date)}
          href="/macro"
          hist={macro.unempHist}
        />
      </div>
    </div>
  );
}
