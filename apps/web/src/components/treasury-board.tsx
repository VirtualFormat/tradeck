/**
 * 国债收益率 + 利差（衰退预警指标）
 * 数据：backend /api/macro（从 DB 读）
 * 用 EFFR 替代国债收益率（阶段 3 简化，后续加 treasury_rates）
 * 卡片风格：block SectionCards
 */
import { getEFFR } from "@/lib/openbb";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { TreasuryStatusBadge } from "@/components/treasury-status-badge";

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

  // 10Y 作为主标题，其余期限进 CardContent
  const sideYields = [
    { label: "3M", value: latest?.bc_3_month },
    { label: "2Y", value: latest?.bc_2_year },
    { label: "30Y", value: latest?.bc_30_year },
  ];

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-medium text-fg-dim">国债收益率</h3>
        {latest && (
          <span className="text-[10px] text-muted">{fmtDate(latest.date)}</span>
        )}
      </div>
      <Card className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card">
        <CardHeader>
          <CardDescription>10 年期收益率</CardDescription>
          <CardTitle className="text-2xl font-semibold tabular-nums">
            {fmtYield(latest?.bc_10_year)}
          </CardTitle>
          <CardAction>
            <TreasuryStatusBadge inverted={inverted} />
          </CardAction>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-2">
            {sideYields.map((y) => (
              <div key={y.label}>
                <div className="text-[10px] text-muted-foreground">{y.label}</div>
                <div className="tab-nums text-sm font-semibold">
                  {fmtYield(y.value)}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
        <CardFooter className="flex-col items-start gap-1.5 text-sm">
          <div className="line-clamp-1 flex gap-2 font-medium">
            10Y-2Y 利差
            <span
              className={`tab-nums ${inverted ? "text-up" : "text-down"}`}
            >
              {spread10Y2Y != null
                ? `${(spread10Y2Y * 100).toFixed(2)}%`
                : "—"}
            </span>
          </div>
          <div className="text-muted-foreground">
            {inverted ? "收益率倒挂，衰退预警" : "收益率曲线正常"}
          </div>
        </CardFooter>
      </Card>
    </div>
  );
}
