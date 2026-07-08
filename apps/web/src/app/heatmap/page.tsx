/**
 * 热力图组件
 * 路由：/heatmap
 * 数据：gainers + losers 合并，按涨跌幅排序
 * 色块大小代表成交量，颜色代表涨跌（红涨绿跌）
 */
import Link from "next/link";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface HeatmapItem {
  symbol: string;
  name: string | null;
  price: number | null;
  change: number | null;
  percent_change: number | null;
  volume: number | null;
}

async function fetchHeatmapData(): Promise<HeatmapItem[]> {
  const OPENBB_API_URL =
    process.env.OPENBB_API_URL ?? "http://localhost:6900";

  try {
    // 并行拉涨幅榜 + 跌幅榜（各 50 条）
    const [gainersRes, losersRes] = await Promise.all([
      fetch(
        `${OPENBB_API_URL}/api/v1/equity/discovery/gainers?provider=yfinance`,
        { next: { revalidate: 60 }, headers: { Accept: "application/json" } }
      ),
      fetch(
        `${OPENBB_API_URL}/api/v1/equity/discovery/losers?provider=yfinance`,
        { next: { revalidate: 60 }, headers: { Accept: "application/json" } }
      ),
    ]);

    const parseResults = async (res: Response): Promise<HeatmapItem[]> => {
      if (!res.ok) return [];
      const text = await res.text();
      if (!text) return [];
      try {
        const data = JSON.parse(text);
        return data.results ?? [];
      } catch {
        return [];
      }
    };

    const [gainers, losers] = await Promise.all([
      parseResults(gainersRes),
      parseResults(losersRes),
    ]);

    // 合并 + 按绝对涨跌幅排序（取前 60 个最活跃的）
    const merged = [...gainers.slice(0, 30), ...losers.slice(0, 30)];
    merged.sort((a, b) => {
      const absA = Math.abs(a.percent_change ?? 0);
      const absB = Math.abs(b.percent_change ?? 0);
      return absB - absA;
    });

    return merged.slice(0, 60);
  } catch (err) {
    console.error("fetchHeatmapData failed:", err);
    return [];
  }
}

// 根据涨跌幅选颜色（红涨绿跌）
function getColor(pct: number | null): { bg: string; text: string } {
  if (pct == null) {
    return { bg: "var(--panel-2)", text: "var(--muted)" };
  }
  const abs = Math.abs(pct);
  if (abs >= 0.15) {
    // 大涨/大跌 >15%
    return pct > 0
      ? { bg: "rgba(240,85,107,0.9)", text: "#fff" }
      : { bg: "rgba(32,205,141,0.9)", text: "#fff" };
  }
  if (abs >= 0.08) {
    return pct > 0
      ? { bg: "rgba(240,85,107,0.7)", text: "#fff" }
      : { bg: "rgba(32,205,141,0.7)", text: "#fff" };
  }
  if (abs >= 0.03) {
    return pct > 0
      ? { bg: "rgba(240,85,107,0.4)", text: "var(--fg)" }
      : { bg: "rgba(32,205,141,0.4)", text: "var(--fg)" };
  }
  return { bg: "rgba(107,114,128,0.2)", text: "var(--fg-dim)" };
}

// 根据成交量决定色块大小
function getSizeClass(volume: number | null): string {
  if (volume == null) return "col-span-1 row-span-1";
  if (volume >= 50_000_000) return "col-span-2 row-span-2"; // 超大
  if (volume >= 10_000_000) return "col-span-2 row-span-1"; // 大
  return "col-span-1 row-span-1"; // 普通
}

function fmtPct(pct: number | null): string {
  if (pct == null) return "—";
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${(pct * 100).toFixed(1)}%`;
}

function fmtPrice(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 1000) return v.toFixed(0);
  if (v >= 100) return v.toFixed(1);
  return v.toFixed(2);
}

export async function Heatmap() {
  const items = await fetchHeatmapData();

  if (items.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg border border-border bg-panel text-muted">
        等待热力图数据...
      </div>
    );
  }

  return (
    <div
      className="grid gap-1"
      style={{
        gridTemplateColumns: "repeat(auto-fill, minmax(100px, 1fr))",
        gridAutoRows: "60px",
      }}
    >
      {items.map((item) => {
        const color = getColor(item.percent_change);
        const sizeClass = getSizeClass(item.volume);
        return (
          <Link
            key={item.symbol}
            href={`/stocks/${item.symbol}`}
            className={`${sizeClass} group relative flex flex-col justify-between overflow-hidden rounded-md p-2 transition-transform hover:scale-105 hover:z-10`}
            style={{ backgroundColor: color.bg, color: color.text }}
            title={`${item.name ?? ""} · ${fmtPrice(item.price)} · ${fmtPct(item.percent_change)}`}
          >
            <div className="flex items-start justify-between">
              <span className="truncate text-xs font-bold">
                {item.symbol}
              </span>
              <span className="text-[9px] tab-nums">
                {fmtPct(item.percent_change)}
              </span>
            </div>
            <div className="text-[10px] tab-nums opacity-80">
              {fmtPrice(item.price)}
            </div>
          </Link>
        );
      })}
    </div>
  );
}

export default async function HeatmapPage() {
  return (
    <>
        <header className="mb-6 border-b border-border pb-3">
          <h1 className="text-lg font-semibold">市场热力图</h1>
          <p className="text-[10px] uppercase tracking-[0.18em] text-muted">
            Market Heatmap · gainers + losers · yfinance
          </p>
        </header>

        <Card className="mb-4">
          <CardContent className="pt-4">
            <div className="flex flex-wrap items-center gap-4 text-[10px] text-muted">
              <span>图例：</span>
              <span className="flex items-center gap-1">
                <span
                  className="inline-block h-3 w-3 rounded"
                  style={{ backgroundColor: "rgba(240,85,107,0.9)" }}
                />
                大涨 &gt;15%
              </span>
              <span className="flex items-center gap-1">
                <span
                  className="inline-block h-3 w-3 rounded"
                  style={{ backgroundColor: "rgba(240,85,107,0.4)" }}
                />
                小涨 3-8%
              </span>
              <span className="flex items-center gap-1">
                <span
                  className="inline-block h-3 w-3 rounded"
                  style={{ backgroundColor: "rgba(107,114,128,0.2)" }}
                />
                平 &lt;3%
              </span>
              <span className="flex items-center gap-1">
                <span
                  className="inline-block h-3 w-3 rounded"
                  style={{ backgroundColor: "rgba(32,205,141,0.4)" }}
                />
                小跌 3-8%
              </span>
              <span className="flex items-center gap-1">
                <span
                  className="inline-block h-3 w-3 rounded"
                  style={{ backgroundColor: "rgba(32,205,141,0.9)" }}
                />
                大跌 &gt;15%
              </span>
              <span className="ml-4">色块大小 = 成交量</span>
            </div>
          </CardContent>
        </Card>

        <Heatmap />
    </>
  );
}
