/**
 * 大宗商品 + 外汇速览
 * 数据：yfinance（GC=F 金 / CL=F 油 / BTC-USD 加密）
 */
import { getIndexHistorical } from "@/lib/openbb";

interface CommodityQuote {
  symbol: string;
  name: string;
  price: number | null;
  changePct: number | null;
  unit: string;
}

const COMMODITIES = [
  { symbol: "GC=F", name: "黄金", unit: "USD/oz" },
  { symbol: "CL=F", name: "原油", unit: "USD/bbl" },
  { symbol: "SI=F", name: "白银", unit: "USD/oz" },
  { symbol: "BTC-USD", name: "比特币", unit: "USD" },
];

async function fetchCommodity(symbol: string): Promise<{ price: number | null; changePct: number | null }> {
  try {
    const end = new Date();
    const start = new Date(end.getTime() - 3 * 24 * 60 * 60 * 1000);
    const fmt = (d: Date) => d.toISOString().slice(0, 10);
    const hist = await getIndexHistorical(symbol, fmt(start), fmt(end), "yfinance");
    if (hist.length === 0) return { price: null, changePct: null };
    const last = hist[hist.length - 1];
    const prev = hist.length > 1 ? hist[hist.length - 2] : last;
    return {
      price: last.close,
      changePct: prev.close > 0 ? (last.close - prev.close) / prev.close : 0,
    };
  } catch {
    return { price: null, changePct: null };
  }
}

function fmtPrice(v: number | null, unit: string): string {
  if (v == null) return "—";
  if (v >= 1000) return `${v.toFixed(0)} ${unit}`;
  return `${v.toFixed(2)} ${unit}`;
}

function fmtPct(pct: number | null): string {
  if (pct == null) return "—";
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${(pct * 100).toFixed(2)}%`;
}

export async function CommoditiesBoard() {
  const commodities = await Promise.all(
    COMMODITIES.map(async (c) => {
      const { price, changePct } = await fetchCommodity(c.symbol);
      return { ...c, price, changePct };
    })
  );

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-medium text-fg-dim">大宗商品</h3>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {commodities.map((c) => {
          const up = (c.changePct ?? 0) >= 0;
          return (
            <div
              key={c.symbol}
              className="rounded-md border border-border bg-panel-2 px-3 py-2"
            >
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-muted">{c.name}</span>
                <span
                  className={`tab-nums text-[10px] ${
                    up ? "text-up" : "text-down"
                  }`}
                >
                  {up ? "▲" : "▼"} {fmtPct(c.changePct)}
                </span>
              </div>
              <div className="mt-1 tab-nums text-sm font-semibold">
                {fmtPrice(c.price, c.unit)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
