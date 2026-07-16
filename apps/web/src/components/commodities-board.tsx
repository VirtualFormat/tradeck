/**
 * 大宗商品 + 外汇速览
 * 数据：yfinance（GC=F 金 / CL=F 油 / SI=F 银 / BTC-USD 加密）
 * 卡片风格：block SectionCards，mini AreaChart 展示近 7 日走势
 */
import { getIndexHistorical } from "@/lib/openbb";
import { CommodityCard } from "@/components/commodity-card";

interface CommodityQuote {
  symbol: string;
  name: string;
  price: number | null;
  changePct: number | null;
  unit: string;
  hist: { date: string; value: number }[];
}

const COMMODITIES = [
  { symbol: "GC=F", name: "黄金", unit: "USD/oz" },
  { symbol: "CL=F", name: "原油", unit: "USD/bbl" },
  { symbol: "SI=F", name: "白银", unit: "USD/oz" },
  { symbol: "BTC-USD", name: "比特币", unit: "USD" },
];

async function fetchCommodity(
  symbol: string
): Promise<{
  price: number | null;
  changePct: number | null;
  hist: { date: string; value: number }[];
}> {
  try {
    const end = new Date();
    const start = new Date(end.getTime() - 14 * 24 * 60 * 60 * 1000);
    const fmt = (d: Date) => d.toISOString().slice(0, 10);
    const hist = await getIndexHistorical(symbol, fmt(start), fmt(end));
    if (hist.length === 0) return { price: null, changePct: null, hist: [] };
    const last7 = hist.slice(-7);
    const last = last7[last7.length - 1];
    const prev = last7.length > 1 ? last7[last7.length - 2] : last;
    return {
      price: last.close,
      changePct: prev.close > 0 ? (last.close - prev.close) / prev.close : 0,
      hist: last7.map((p) => ({ date: p.date, value: p.close })),
    };
  } catch {
    return { price: null, changePct: null, hist: [] };
  }
}

function fmtPrice(v: number | null): string {
  if (v == null) return "—";
  if (v >= 1000) return v.toFixed(0);
  return v.toFixed(2);
}

function fmtPct(pct: number | null): string {
  if (pct == null) return "—";
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${(pct * 100).toFixed(2)}%`;
}

export async function CommoditiesBoard() {
  const commodities = await Promise.all(
    COMMODITIES.map(async (c) => {
      const { price, changePct, hist } = await fetchCommodity(c.symbol);
      return { ...c, price, changePct, hist };
    })
  );

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-medium text-fg-dim">大宗商品</h3>
      </div>
      <div className="grid grid-cols-2 gap-4 *:data-[slot=card]:bg-linear-to-t *:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card *:data-[slot=card]:shadow-xs dark:*:data-[slot=card]:bg-card">
        {commodities.map((c) => {
          const up = (c.changePct ?? 0) >= 0;
          return (
            <CommodityCard
              key={c.symbol}
              symbol={c.symbol}
              name={c.name}
              unit={c.unit}
              priceText={fmtPrice(c.price)}
              changePctText={fmtPct(c.changePct)}
              up={up}
              hist={c.hist}
            />
          );
        })}
      </div>
    </div>
  );
}
