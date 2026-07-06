/**
 * OpenBB Platform API 客户端
 * 后端地址通过环境变量配置（docker-compose 里 OPENBB_API_URL）
 */
const OPENBB_API_URL =
  process.env.OPENBB_API_URL ?? "http://localhost:6900";

const BASE = `${OPENBB_API_URL}/api/v1`;

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

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${BASE}${path}`;
  const res = await fetch(url, {
    ...init,
    // Next.js 缓存：30 秒内复用相同请求（行情数据 30s 刷新够用）
    next: { revalidate: 30 },
    headers: { Accept: "application/json", ...init?.headers },
  });
  if (!res.ok) {
    throw new Error(`OpenBB API ${path} failed: ${res.status}`);
  }
  // 某些 OpenBB 端点返回 200 但空 body，res.json() 会抛 "Unexpected end of JSON input"
  const text = await res.text();
  if (!text) {
    return { results: [] } as unknown as T;
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    return { results: [] } as unknown as T;
  }
}

interface OpenBBResponse<T> {
  results: T[];
  warnings?: { message: string }[];
}

export async function getEquityQuote(
  symbol: string,
  provider: string = "yfinance"
): Promise<EquityQuote | null> {
  const data = await fetchJSON<OpenBBResponse<EquityQuote>>(
    `/equity/price/quote?provider=${provider}&symbol=${encodeURIComponent(symbol)}`
  );
  return data.results[0] ?? null;
}

export async function getEquityQuotes(
  symbols: string[],
  provider: string = "yfinance"
): Promise<EquityQuote[]> {
  const symbolStr = symbols.join(",");
  const data = await fetchJSON<OpenBBResponse<EquityQuote>>(
    `/equity/price/quote?provider=${provider}&symbol=${encodeURIComponent(symbolStr)}`
  );
  return data.results;
}

export async function getEquityHistorical(
  symbol: string,
  startDate: string,
  endDate: string,
  provider: string = "yfinance"
): Promise<HistoricalPrice[]> {
  const data = await fetchJSON<OpenBBResponse<HistoricalPrice>>(
    `/equity/price/historical?provider=${provider}&symbol=${encodeURIComponent(
      symbol
    )}&start_date=${startDate}&end_date=${endDate}`
  );
  return data.results;
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
    )}&start_date=${startDate}&end_date=${endDate}`
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
    `/equity/profile?provider=${provider}&symbol=${encodeURIComponent(symbol)}`
  );
  return data.results[0] ?? null;
}

export async function getFundamentalMetrics(
  symbol: string,
  provider: string = "yfinance"
): Promise<FundamentalMetrics | null> {
  const data = await fetchJSON<OpenBBResponse<FundamentalMetrics>>(
    `/equity/fundamental/metrics?provider=${provider}&symbol=${encodeURIComponent(symbol)}`
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
    )}&period=${period}&limit=${limit}`
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
    )}&limit=${limit}`
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
    `/economy/cpi?provider=${provider}&limit=${limit}`
  );
  return data.results;
}

export async function getUnemployment(
  provider: string = "oecd",
  limit: number = 12
): Promise<MacroSeries[]> {
  const data = await fetchJSON<OpenBBResponse<MacroSeries>>(
    `/economy/unemployment?provider=${provider}&limit=${limit}`
  );
  return data.results;
}

export async function getGDPNominal(
  provider: string = "oecd",
  limit: number = 20
): Promise<MacroSeries[]> {
  const data = await fetchJSON<OpenBBResponse<MacroSeries>>(
    `/economy/gdp/nominal?provider=${provider}&limit=${limit}`
  );
  return data.results;
}

export async function getEFFR(
  provider: string = "federal_reserve",
  limit: number = 12
): Promise<RateSeries[]> {
  const data = await fetchJSON<OpenBBResponse<RateSeries>>(
    `/fixedincome/rate/effr?provider=${provider}&limit=${limit}`
  );
  return data.results.map((r) => ({ date: r.date, rate: r.rate }));
}

export async function getSOFR(
  provider: string = "federal_reserve",
  limit: number = 12
): Promise<RateSeries[]> {
  const data = await fetchJSON<OpenBBResponse<RateSeries>>(
    `/fixedincome/rate/sofr?provider=${provider}&limit=${limit}`
  );
  return data.results.map((r) => ({ date: r.date, rate: r.rate }));
}
