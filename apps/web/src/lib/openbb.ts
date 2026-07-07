/**
 * OpenBB Platform API 客户端
 * 后端地址通过环境变量配置（docker-compose 里 OPENBB_API_URL）
 */
const OPENBB_API_URL =
  process.env.OPENBB_API_URL ?? "http://localhost:6900";

export { OPENBB_API_URL };

const BASE = `${OPENBB_API_URL}/api/v1`;

/**
 * 按市场自动选 provider（基于测速结果）
 * - A 股（.SS/.SZ/.BJ）：akshare（350ms，比 yfinance 快 7 倍）
 * - 美股/港股/其他：yfinance
 */
function pickProvider(symbol: string): string {
  const sym = symbol.toUpperCase();
  if (sym.endsWith(".SS") || sym.endsWith(".SZ") || sym.endsWith(".BJ")) {
    return "akshare";
  }
  return "yfinance";
}

/** 按数据类型的缓存时间（秒） */
const CACHE = {
  quote: 30,        // 行情：30s
  historical: 300,  // K 线：5 分钟
  discovery: 300,   // 涨跌榜：5 分钟
  profile: 3600,    // 公司信息：1 小时
  fundamental: 3600, // 财报：1 小时
  macro: 3600,      // 宏观：1 小时
} as const;

export interface EquityQuote {
  symbol: string;
  name: string | null;
  last_price: number | null;
  change: number | null;
  change_percent: number | null;
  currency: string | null;
  volume: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  prev_close: number | null;
  exchange: string | null;
}

export interface HistoricalPrice {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// 手动内存缓存（避免 Next.js Server Component fetch 缓存机制限制超时）
const memCache = new Map<string, { data: unknown; ts: number }>();

export async function fetchJSON<T>(
  path: string,
  init?: RequestInit,
  revalidate: number = CACHE.quote
): Promise<T> {
  const url = `${BASE}${path}`;

  // 检查内存缓存
  const cached = memCache.get(url);
  if (cached && Date.now() - cached.ts < revalidate * 1000) {
    return cached.data as T;
  }

  try {
    // Promise.race 超时（Next.js Server Component 的 fetch 不支持 AbortController）
    const res = (await Promise.race([
      fetch(url, {
        ...init,
        cache: "no-store", // 不用 Next.js 缓存，自己控制
        headers: { Accept: "application/json", ...init?.headers },
      }),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), 5000)),
    ])) as Response | null;

    if (!res) {
      console.warn(`OpenBB ${path} timeout (5s), returning empty`);
      // 超时返回空，但如果有旧缓存就用旧的
      if (cached) return cached.data as T;
      return { results: [] } as unknown as T;
    }

    if (!res.ok) {
      throw new Error(`OpenBB API ${path} failed: ${res.status}`);
    }
    const text = await res.text();
    let data: T;
    if (!text) {
      data = { results: [] } as unknown as T;
    } else {
      try {
        data = JSON.parse(text) as T;
      } catch {
        data = { results: [] } as unknown as T;
      }
    }

    // 写缓存
    memCache.set(url, { data, ts: Date.now() });

    return data;
  } catch (err) {
    if (err instanceof Error && (err.message.includes("ECONNRESET") || err.message.includes("fetch failed"))) {
      console.warn(`OpenBB ${path} reset, returning empty`);
      if (cached) return cached.data as T;
      return { results: [] } as unknown as T;
    }
    throw err;
  }
}

export interface OpenBBResponse<T> {
  results: T[];
  warnings?: { message: string }[];
}

export async function getEquityQuote(
  symbol: string,
  provider?: string
): Promise<EquityQuote | null> {
  const p = provider ?? pickProvider(symbol);
  const data = await fetchJSON<OpenBBResponse<EquityQuote>>(
    `/equity/price/quote?provider=${p}&symbol=${encodeURIComponent(symbol)}`,
    undefined,
    CACHE.quote
  );
  return data.results[0] ?? null;
}

export async function getEquityQuotes(
  symbols: string[],
  provider?: string
): Promise<EquityQuote[]> {
  // 多 symbol 时按市场分组（akshare 只支持 A 股）
  const akshareSyms = symbols.filter((s) => pickProvider(s) === "akshare");
  const yfinanceSyms = symbols.filter((s) => pickProvider(s) === "yfinance");
  const results: EquityQuote[] = [];

  if (akshareSyms.length > 0) {
    const data = await fetchJSON<OpenBBResponse<EquityQuote>>(
      `/equity/price/quote?provider=akshare&symbol=${encodeURIComponent(akshareSyms.join(","))}`,
      undefined,
      CACHE.quote
    );
    results.push(...data.results);
  }
  if (yfinanceSyms.length > 0) {
    const data = await fetchJSON<OpenBBResponse<EquityQuote>>(
      `/equity/price/quote?provider=yfinance&symbol=${encodeURIComponent(yfinanceSyms.join(","))}`,
      undefined,
      CACHE.quote
    );
    results.push(...data.results);
  }
  return results;
}

export async function getEquityHistorical(
  symbol: string,
  startDate: string,
  endDate: string,
  provider?: string
): Promise<HistoricalPrice[]> {
  const p = provider ?? pickProvider(symbol);
  // 先试首选 provider，空结果时降级到另一个
  const fallback = p === "akshare" ? "yfinance" : "akshare";

  const data = await fetchJSON<OpenBBResponse<HistoricalPrice>>(
    `/equity/price/historical?provider=${p}&symbol=${encodeURIComponent(
      symbol
    )}&start_date=${startDate}&end_date=${endDate}`,
    undefined,
    CACHE.historical
  );
  if (data.results.length > 0) return data.results;

  // 降级
  const fallbackData = await fetchJSON<OpenBBResponse<HistoricalPrice>>(
    `/equity/price/historical?provider=${fallback}&symbol=${encodeURIComponent(
      symbol
    )}&start_date=${startDate}&end_date=${endDate}`,
    undefined,
    CACHE.historical
  );
  return fallbackData.results;
}

export async function getIndexHistorical(
  symbol: string,
  startDate: string,
  endDate: string,
  provider: string = "yfinance"
): Promise<HistoricalPrice[]> {
  const data = await fetchJSON<OpenBBResponse<HistoricalPrice>>(
    `/index/price/historical?provider=${provider}&symbol=${encodeURIComponent(
      symbol
    )}&start_date=${startDate}&end_date=${endDate}`,
    undefined,
    CACHE.historical
  );
  return data.results;
}

// ─── 个股详情相关 ────────────────────────────────────────

export interface EquityProfile {
  symbol: string;
  name: string | null;
  sector: string | null;
  industry: string | null;
  market_cap: number | null;
  currency: string | null;
  exchange: string | null;
  description: string | null;
  ceo: string | null;
  employees: number | null;
  website: string | null;
}

export interface FundamentalMetrics {
  symbol: string;
  market_cap: number | null;
  pe_ratio: number | null;
  forward_pe: number | null;
  peg_ratio: number | null;
  enterprise_to_ebitda: number | null;
  earnings_growth: number | null;
  revenue_growth: number | null;
  dividend_yield: number | null;
  beta: number | null;
  profit_margins: number | null;
  return_on_equity: number | null;
  debt_to_equity: number | null;
  current_ratio: number | null;
}

export interface IncomeStatement {
  fiscal_year: number | null;
  total_revenue: number | null;
  net_income: number | null;
  gross_profit: number | null;
  operating_income: number | null;
  research_and_development: number | null;
  ebitda: number | null;
}

export async function getEquityProfile(
  symbol: string,
  provider: string = "yfinance"
): Promise<EquityProfile | null> {
  const data = await fetchJSON<OpenBBResponse<EquityProfile>>(
    `/equity/profile?provider=${provider}&symbol=${encodeURIComponent(symbol)}`,
    undefined,
    CACHE.profile
  );
  return data.results[0] ?? null;
}

export async function getFundamentalMetrics(
  symbol: string,
  provider: string = "yfinance"
): Promise<FundamentalMetrics | null> {
  const data = await fetchJSON<OpenBBResponse<FundamentalMetrics>>(
    `/equity/fundamental/metrics?provider=${provider}&symbol=${encodeURIComponent(symbol)}`,
    undefined,
    CACHE.fundamental
  );
  return data.results[0] ?? null;
}

export async function getIncomeStatements(
  symbol: string,
  provider: string = "sec",
  period: string = "annual",
  limit: number = 3
): Promise<IncomeStatement[]> {
  const data = await fetchJSON<OpenBBResponse<IncomeStatement>>(
    `/equity/fundamental/income?provider=${provider}&symbol=${encodeURIComponent(
      symbol
    )}&period=${period}&limit=${limit}`,
    undefined,
    CACHE.fundamental
  );
  return data.results;
}

// ─── 新闻 ──────────────────────────────────────────────────

export interface NewsArticle {
  symbol: string;
  title: string;
  url: string;
  text: string | null;
  summary: string | null;
  publisher: string | null;
  date: string | null;
  source: string | null;
  symbols: string | null;
}

export async function getCompanyNews(
  symbol: string,
  limit: number = 20,
  provider: string = "yfinance"
): Promise<NewsArticle[]> {
  const data = await fetchJSON<OpenBBResponse<NewsArticle>>(
    `/news/company?provider=${provider}&symbol=${encodeURIComponent(
      symbol
    )}&limit=${limit}`,
    undefined,
    CACHE.historical // 5 分钟
  );
  return data.results;
}

/** 多 symbol 并行拉新闻 + 合并按时间排序 */
export async function getAggregatedNews(
  symbols: string[],
  perSymbol: number = 5
): Promise<NewsArticle[]> {
  const results = await Promise.all(
    symbols.map((s) => getCompanyNews(s, perSymbol).catch(() => []))
  );
  const merged = results.flat();
  // 按日期降序
  merged.sort((a, b) => {
    const da = a.date ? new Date(a.date).getTime() : 0;
    const db = b.date ? new Date(b.date).getTime() : 0;
    return db - da;
  });
  return merged;
}

// ─── 宏观数据 ──────────────────────────────────────────────

export interface MacroSeries {
  date: string;
  value: number;
  country?: string;
}

export interface RateSeries {
  date: string;
  rate: number;
}

export async function getCPI(
  provider: string = "oecd",
  limit: number = 12
): Promise<MacroSeries[]> {
  const data = await fetchJSON<OpenBBResponse<MacroSeries>>(
    `/economy/cpi?provider=${provider}&limit=${limit}`,
    undefined,
    CACHE.macro
  );
  return data.results;
}

export async function getUnemployment(
  provider: string = "oecd",
  limit: number = 12
): Promise<MacroSeries[]> {
  const data = await fetchJSON<OpenBBResponse<MacroSeries>>(
    `/economy/unemployment?provider=${provider}&limit=${limit}`,
    undefined,
    CACHE.macro
  );
  return data.results;
}

export async function getGDPNominal(
  provider: string = "oecd",
  limit: number = 20
): Promise<MacroSeries[]> {
  const data = await fetchJSON<OpenBBResponse<MacroSeries>>(
    `/economy/gdp/nominal?provider=${provider}&limit=${limit}`,
    undefined,
    CACHE.macro
  );
  return data.results;
}

export async function getEFFR(
  provider: string = "federal_reserve",
  limit: number = 12
): Promise<RateSeries[]> {
  const data = await fetchJSON<OpenBBResponse<RateSeries>>(
    `/fixedincome/rate/effr?provider=${provider}&limit=${limit}`,
    undefined,
    CACHE.macro
  );
  return data.results.map((r) => ({ date: r.date, rate: r.rate }));
}

export async function getSOFR(
  provider: string = "federal_reserve",
  limit: number = 12
): Promise<RateSeries[]> {
  const data = await fetchJSON<OpenBBResponse<RateSeries>>(
    `/fixedincome/rate/sofr?provider=${provider}&limit=${limit}`,
    undefined,
    CACHE.macro
  );
  return data.results.map((r) => ({ date: r.date, rate: r.rate }));
}
