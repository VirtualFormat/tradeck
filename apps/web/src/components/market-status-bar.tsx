/**
 * 市场状态带（Server Component）：拉三市指数最新交易日，传给 client 状态条
 */
import { getIndexHistorical } from "@/lib/openbb";
import { MarketStatusStrip } from "@/components/market-status-strip";

/** 指数最新 K 线日期（YYYY-MM-DD）；失败返回 null，由状态条显示待更新 */
async function latestIndexDate(symbol: string): Promise<string | null> {
  try {
    const end = new Date().toISOString().slice(0, 10);
    const start = new Date(Date.now() - 10 * 86400_000).toISOString().slice(0, 10);
    const rows = await getIndexHistorical(symbol, start, end);
    return rows.reduce<string | null>((latest, row) => {
      const date = row.date?.slice(0, 10);
      return date && (!latest || date > latest) ? date : latest;
    }, null);
  } catch {
    return null;
  }
}

/** 各市场对应的指数符号（取最新交易日） */
const INDEX_SYMBOL: Record<"US" | "HK" | "CN", string> = {
  US: "^GSPC",
  HK: "^HSI",
  CN: "000001.SS",
};

export async function MarketStatusBar({
  market,
  className,
}: {
  // 传入则只显示该市场（市场页用）；不传三市全显（首页用）
  market?: "US" | "HK" | "CN";
  className?: string;
}) {
  if (market) {
    const d = await latestIndexDate(INDEX_SYMBOL[market]);
    return <MarketStatusStrip dates={{ [market]: d }} className={className} />;
  }
  const [us, hk, cn] = await Promise.all([
    latestIndexDate(INDEX_SYMBOL.US),
    latestIndexDate(INDEX_SYMBOL.HK),
    latestIndexDate(INDEX_SYMBOL.CN),
  ]);
  return (
    <MarketStatusStrip
      dates={{ US: us, HK: hk, CN: cn }}
      className={className}
    />
  );
}
