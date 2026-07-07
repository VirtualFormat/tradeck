/**
 * 国债收益率 + 利差（衰退预警指标）
 * 数据：federal_reserve treasury_rates
 * 10Y-2Y 利差倒挂 = 衰退预警
 */
import { fetchJSON } from "@/lib/openbb";

interface TreasuryRate {
  date: string;
  bc_3_month: number | null;
  bc_2_year: number | null;
  bc_10_year: number | null;
  bc_30_year: number | null;
}

async function fetchTreasuryRates(): Promise<TreasuryRate | null> {
  const OPENBB_API_URL = process.env.OPENBB_API_URL ?? "http://localhost:6900";
  try {
    const res = await fetch(
      `${OPENBB_API_URL}/api/v1/economy/treasury_rates?provider=federal_reserve`,
      { next: { revalidate: 3600 }, headers: { Accept: "application/json" } }
    );
    if (!res.ok) return null;
    const text = await res.text();
    if (!text) return null;
    const data = JSON.parse(text);
    const results = data.results ?? [];
    return results.length > 0 ? results[results.length - 1] : null;
  } catch {
    return null;
  }
}

function fmtYield(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

function fmtDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  return d.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

export async function TreasuryBoard() {
  const latest = await fetchTreasuryRates();

  const spread10Y2Y =
    latest?.bc_10_year != null && latest?.bc_2_year != null
      ? latest.bc_10_year - latest.bc_2_year
      : null;
  const inverted = spread10Y2Y != null && spread10Y2Y < 0;

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-medium text-fg-dim">国债收益率</h3>
        {latest && (
          <span className="text-[10px] text-muted">{fmtDate(latest.date)}</span>
        )}
      </div>
      <div className="rounded-md border border-border bg-panel-2 px-3 py-2">
        <div className="grid grid-cols-4 gap-2">
          <div>
            <div className="text-[10px] text-muted">2Y</div>
            <div className="tab-nums text-sm font-semibold">
              {fmtYield(latest?.bc_2_year)}
            </div>
          </div>
          <div>
            <div className="text-[10px] text-muted">10Y</div>
            <div className="tab-nums text-sm font-semibold">
              {fmtYield(latest?.bc_10_year)}
            </div>
          </div>
          <div>
            <div className="text-[10px] text-muted">30Y</div>
            <div className="tab-nums text-sm font-semibold">
              {fmtYield(latest?.bc_30_year)}
            </div>
          </div>
          <div>
            <div className="text-[10px] text-muted">3M</div>
            <div className="tab-nums text-sm font-semibold">
              {fmtYield(latest?.bc_3_month)}
            </div>
          </div>
        </div>
        {/* 10Y-2Y 利差（衰退预警） */}
        <div className="mt-3 flex items-center justify-between border-t border-border/40 pt-2">
          <span className="text-[10px] text-muted">10Y-2Y 利差</span>
          <div className="flex items-center gap-2">
            {inverted && (
              <span className="rounded-sm bg-up/20 px-1.5 py-0.5 text-[9px] text-up">
                倒挂
              </span>
            )}
            <span
              className={`tab-nums text-sm font-semibold ${
                inverted ? "text-up" : "text-down"
              }`}
            >
              {spread10Y2Y != null
                ? `${(spread10Y2Y * 100).toFixed(2)}%`
                : "—"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
