/**
 * 批量报价 API 路由
 * GET /api/quotes?symbols=AAPL,MSFT,NVDA
 * 代理 OpenBB equity/price/quote（支持多 symbol）
 * 加 30 秒内存缓存避免重复调 OpenBB（yfinance 慢，1.4s/次）
 */
import { NextRequest, NextResponse } from "next/server";

const OPENBB_API_URL =
  process.env.OPENBB_API_URL ?? "http://localhost:6900";

interface QuoteItem {
  symbol: string;
  name: string | null;
  last_price: number | null;
  change: number | null;
  change_percent: number | null;
  volume: number | null;
  exchange: string | null;
}

// 内存缓存（30 秒，避免 yfinance 重复调用）
const CACHE_TTL = 30_000; // 30s
const cache = new Map<string, { data: QuoteItem[]; ts: number }>();

export async function GET(request: NextRequest) {
  const symbols = request.nextUrl.searchParams.get("symbols") ?? "";

  if (!symbols) {
    return NextResponse.json([]);
  }

  // 检查缓存
  const cached = cache.get(symbols);
  if (cached && Date.now() - cached.ts < CACHE_TTL) {
    return NextResponse.json(cached.data);
  }

  try {
    const res = await fetch(
      `${OPENBB_API_URL}/api/v1/equity/price/quote?provider=yfinance&symbol=${encodeURIComponent(symbols)}`,
      {
        headers: { Accept: "application/json" },
        cache: "no-store",
      }
    );
    if (!res.ok) {
      return NextResponse.json([]);
    }
    const text = await res.text();
    if (!text) return NextResponse.json([]);
    const data = JSON.parse(text);
    const results: QuoteItem[] = (data.results ?? []).map((r: Record<string, unknown>) => ({
      symbol: r.symbol as string,
      name: (r.name as string) ?? null,
      last_price: (r.last_price as number) ?? null,
      change: (r.change as number) ?? null,
      change_percent: (r.change_percent as number) ?? null,
      volume: (r.volume as number) ?? null,
      exchange: (r.exchange as string) ?? null,
    }));

    // 写缓存
    cache.set(symbols, { data: results, ts: Date.now() });

    return NextResponse.json(results);
  } catch (err) {
    console.error(`Quotes failed:`, err);
    return NextResponse.json([]);
  }
}
