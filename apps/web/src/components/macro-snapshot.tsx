/**
 * 宏观速览（首页用）
 * 显示 CPI + EFFR + 失业率 三个关键指标
 */
import { getCPI, getEFFR, getUnemployment } from "@/lib/openbb";
import { fmtPct } from "@/lib/format";
import Link from "next/link";

async function fetchMacroSnapshot() {
  const [cpi, effr, unemp] = await Promise.all([
    getCPI().catch(() => []),
    getEFFR().catch(() => []),
    getUnemployment().catch(() => []),
  ]);
  return {
    cpi: cpi.length > 0 ? cpi[cpi.length - 1] : null,
    effr: effr.length > 0 ? effr[effr.length - 1] : null,
    unemp: unemp.length > 0 ? unemp[unemp.length - 1] : null,
  };
}

function MacroItem({
  label,
  value,
  date,
  href,
}: {
  label: string;
  value: string;
  date: string;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="block rounded-md border border-border bg-panel-2 px-3 py-2 transition-colors hover:border-accent/50"
    >
      <div className="text-[10px] uppercase tracking-wider text-muted">
        {label}
      </div>
      <div className="mt-1 tab-nums text-base font-semibold">{value}</div>
      <div className="text-[9px] text-muted">{date}</div>
    </Link>
  );
}

function fmtDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  return d.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

export async function MacroSnapshot() {
  const macro = await fetchMacroSnapshot();

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-medium text-fg-dim">宏观速览</h3>
        <Link href="/macro" className="text-[10px] text-muted hover:text-fg">
          更多 →
        </Link>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <MacroItem
          label="CPI"
          value={macro.cpi ? fmtPct(macro.cpi.value) : "—"}
          date={fmtDate(macro.cpi?.date)}
          href="/macro"
        />
        <MacroItem
          label="EFFR"
          value={macro.effr ? fmtPct(macro.effr.rate) : "—"}
          date={fmtDate(macro.effr?.date)}
          href="/macro"
        />
        <MacroItem
          label="失业率"
          value={macro.unemp ? fmtPct(macro.unemp.value) : "—"}
          date={fmtDate(macro.unemp?.date)}
          href="/macro"
        />
      </div>
    </div>
  );
}
