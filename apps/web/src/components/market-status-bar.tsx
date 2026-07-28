/**
 * 市场状态带（Server Component）：拉三市指数最新交易日，传给 client 状态条
 */
import { getIndexHistorical } from "@/lib/openbb";
import { MarketStatusStrip } from "@/components/market-status-strip";

/** 指数最新 K 线日期（YYYY-MM-DD → MM-DD）；失败返回 null（降级不显日期） */
async function latestIndexDate(symbol: string): Promise<string | null> {
  try {
    const end = new Date().toISOString().slice(0, 10);
    const start = new Date(Date.now() - 10 * 86400_000).toISOString().slice(0, 10);
    const rows = await getIndexHistorical(symbol, start, end);
    const d = rows[rows.length - 1]?.date;
    return d ? d.slice(5) : null;
  } catch {
    return null;
  }
}

export async function MarketStatusBar() {
  const [us, hk, cn] = await Promise.all([
    latestIndexDate("^GSPC"),
    latestIndexDate("^HSI"),
    latestIndexDate("000001.SS"),
  ]);
  return <MarketStatusStrip dates={{ US: us, HK: hk, CN: cn }} />;
}
