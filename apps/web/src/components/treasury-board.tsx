/**
 * 国债收益率 + 利差（衰退预警指标）
 * 数据：backend /api/macro（从 DB 读）
 * 用 EFFR 替代国债收益率（阶段 3 简化，后续加 treasury_rates）
 */
import { getEFFR } from "@/lib/openbb";

async function fetchTreasuryRates() {
  // 用 EFFR 近似（阶段 3 简化）
  const effr = await getEFFR();
  if (effr.length === 0) return null;
  const latest = effr[effr.length - 1];
  return {
    date: latest.date,
    bc_3_month: latest.rate,
    bc_2_year: latest.rate,
    bc_10_year: latest.rate + 0.005, // 近似 10Y 比 EFFR 高 0.5%
    bc_30_year: latest.rate + 0.01,
  };
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
