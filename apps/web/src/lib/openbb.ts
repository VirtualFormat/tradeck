/**
 * API 客户端
 * - 全部走 backend（从 DB 读，< 50ms），管道迁移已完成
 * - 失败降级返回空数组，页面永远可渲染
 */

// Backend API（从 DB 读，< 50ms）
const BACKEND_API_URL =
  process.env.BACKEND_API_URL ?? "http://localhost:8080";

const BACKEND = BACKEND_API_URL;

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
  /** 报价快照更新时间（quote_snapshots.updated_at，ISO 字符串） */
  updated_at?: string | null;
}

export interface HistoricalPrice {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// ─── Backend API（从 DB 读，< 50ms） ──────────────────────

async function backendFetch<T>(path: string): Promise<T> {
  const url = `${BACKEND}${path}`;
  try {
    const res = await fetch(url, {
      headers: { Accept: "application/json" },
    });
    if (!res.ok) {
      console.warn(`backend ${path} failed: ${res.status}`);
      return [] as unknown as T;
    }
    const text = await res.text();
    if (!text) return [] as unknown as T;
    return JSON.parse(text) as T;
  } catch (err) {
    console.warn(`backend ${path} error:`, err);
    return [] as unknown as T;
  }
}

// ─── 已迁移到 backend 的 API ─────────────────────────────

export async function getEquityQuote(
  symbol: string
): Promise<EquityQuote | null> {
  const quotes = await backendFetch<EquityQuote[]>(
    `/api/quotes?symbols=${encodeURIComponent(symbol)}`
  );
  return quotes[0] ?? null;
}

export async function getEquityQuotes(
  symbols: string[]
): Promise<EquityQuote[]> {
  return backendFetch<EquityQuote[]>(
    `/api/quotes?symbols=${encodeURIComponent(symbols.join(","))}`
  );
}

export async function getEquityHistorical(
  symbol: string,
  startDate: string,
  endDate: string
): Promise<HistoricalPrice[]> {
  const data = await backendFetch<HistoricalPrice[]>(
    `/api/historical?symbol=${encodeURIComponent(
      symbol
    )}&start_date=${startDate}&end_date=${endDate}`
  );
  // 过滤当日未收盘的 null close 行（真实数据源会产生）
  return data.filter((p) => p.close != null);
}

export async function getIndexHistorical(
  symbol: string,
  startDate: string,
  endDate: string
): Promise<HistoricalPrice[]> {
  const data = await backendFetch<HistoricalPrice[]>(
    `/api/indices?symbol=${encodeURIComponent(
      symbol
    )}&start_date=${startDate}&end_date=${endDate}`
  );
  // 过滤当日未收盘的 null close 行（真实数据源会产生）
  return data.filter((p) => p.close != null);
}

// ─── 技术指标（backend 本地计算，按日期升序） ─────────────

export interface TechnicalIndicator {
  date: string;
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  ma60: number | null;
  ema12: number | null;
  ema26: number | null;
  dif: number | null;
  dea: number | null;
  macd: number | null;
  rsi6: number | null;
  rsi14: number | null;
  boll_upper: number | null;
  boll_mid: number | null;
  boll_lower: number | null;
}

export async function fetchTechnicals(
  symbol: string,
  days: number = 120
): Promise<TechnicalIndicator[]> {
  return backendFetch<TechnicalIndicator[]>(
    `/api/technicals?symbol=${encodeURIComponent(symbol)}&days=${days}`
  );
}

// ─── 公司信息 / 基本面（backend DB） ─────────────────────

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
  symbol: string
): Promise<EquityProfile | null> {
  return backendFetch<EquityProfile | null>(
    `/api/profile?symbol=${encodeURIComponent(symbol)}`
  );
}

export async function getFundamentalMetrics(
  symbol: string
): Promise<FundamentalMetrics | null> {
  return backendFetch<FundamentalMetrics | null>(
    `/api/fundamentals/metrics?symbol=${encodeURIComponent(symbol)}`
  );
}

export async function getIncomeStatements(
  symbol: string,
  provider: string = "sec",
  period: string = "annual",
  limit: number = 3
): Promise<IncomeStatement[]> {
  return backendFetch<IncomeStatement[]>(
    `/api/fundamentals/income?symbol=${encodeURIComponent(symbol)}&limit=${limit}`
  );
}

// ─── 分析师共识 + 资产负债表/现金流量表（backend DB） ───────

export interface AnalystConsensus {
  symbol: string;
  snapshot_date: string | null;
  recommendation: string | null;
  recommendation_mean: number | null;
  number_of_analysts: number | null;
  target_high: number | null;
  target_low: number | null;
  target_consensus: number | null;
  target_median: number | null;
  current_price: number | null;
  currency: string | null;
}

export interface BalanceSheet {
  symbol: string;
  period: string;
  fiscal_date: string | null;
  total_assets: number | null;
  total_liabilities: number | null;
  total_equity: number | null;
  total_current_assets: number | null;
  total_current_liabilities: number | null;
  cash_and_equivalents: number | null;
  inventories: number | null;
  accounts_receivable: number | null;
  total_debt: number | null;
  retained_earnings: number | null;
}

export interface CashFlowStatement {
  symbol: string;
  period: string;
  fiscal_date: string | null;
  operating_cash_flow: number | null;
  investing_cash_flow: number | null;
  financing_cash_flow: number | null;
  capital_expenditure: number | null;
  free_cash_flow: number | null;
  net_income: number | null;
  depreciation_amortization: number | null;
  share_repurchase: number | null;
  dividends_paid: number | null;
}

export async function getAnalystConsensus(
  symbol: string
): Promise<AnalystConsensus | null> {
  return backendFetch<AnalystConsensus | null>(
    `/api/analyst/consensus?symbol=${encodeURIComponent(symbol)}`
  );
}

export async function getBalanceSheets(
  symbol: string,
  period?: string
): Promise<BalanceSheet[]> {
  const p = period ? `&period=${encodeURIComponent(period)}` : "";
  return backendFetch<BalanceSheet[]>(
    `/api/fundamentals/balance?symbol=${encodeURIComponent(symbol)}${p}`
  );
}

export async function getCashFlowStatements(
  symbol: string,
  period?: string
): Promise<CashFlowStatement[]> {
  const p = period ? `&period=${encodeURIComponent(period)}` : "";
  return backendFetch<CashFlowStatement[]>(
    `/api/fundamentals/cash?symbol=${encodeURIComponent(symbol)}${p}`
  );
}

// ─── 新闻（已迁移到 backend） ─────────────────────────────

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
  limit: number = 20
): Promise<NewsArticle[]> {
  return backendFetch<NewsArticle[]>(
    `/api/news?symbol=${encodeURIComponent(symbol)}&limit=${limit}`
  );
}

export async function getAggregatedNews(
  symbols: string[],
  perSymbol: number = 5
): Promise<NewsArticle[]> {
  const results = await Promise.all(
    symbols.map((s) => getCompanyNews(s, perSymbol).catch(() => []))
  );
  const merged = results.flat();
  merged.sort((a, b) => {
    const da = a.date ? new Date(a.date).getTime() : 0;
    const db = b.date ? new Date(b.date).getTime() : 0;
    return db - da;
  });
  return merged;
}

// ─── 宏观数据（已迁移到 backend） ──────────────────────────

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
  const data = await backendFetch<{date: string; value: number}[]>(
    `/api/macro?name=CPI&limit=${limit}`
  );
  return data;
}

export async function getUnemployment(
  provider: string = "oecd",
  limit: number = 12
): Promise<MacroSeries[]> {
  return backendFetch<{date: string; value: number}[]>(
    `/api/macro?name=Unemployment&limit=${limit}`
  );
}

export async function getGDPNominal(
  provider: string = "oecd",
  limit: number = 20
): Promise<MacroSeries[]> {
  return backendFetch<{date: string; value: number}[]>(
    `/api/macro?name=GDP_Nominal&limit=${limit}`
  );
}

export async function getEFFR(
  provider: string = "federal_reserve",
  limit: number = 12
): Promise<RateSeries[]> {
  const data = await backendFetch<{date: string; value: number}[]>(
    `/api/macro?name=EFFR&limit=${limit}`
  );
  return data.map((r) => ({ date: r.date, rate: r.value }));
}

export async function getSOFR(
  provider: string = "federal_reserve",
  limit: number = 12
): Promise<RateSeries[]> {
  const data = await backendFetch<{date: string; value: number}[]>(
    `/api/macro?name=SOFR&limit=${limit}`
  );
  return data.map((r) => ({ date: r.date, rate: r.value }));
}

// ─── 日历（财报 + 宏观数据，已迁移到 backend） ─────────────

export interface EarningsCalendarItem {
  symbol: string;
  report_date: string | null;
  session: string | null;
  eps_estimate: number | null;
  source: string | null;
}

export interface EconomicCalendarItem {
  event_date: string | null;
  event_time: string | null;
  country: string | null;
  event_name: string | null;
  importance: string | null;
  actual: string | null;
  forecast: string | null;
  previous: string | null;
  source: string | null;
}

export async function fetchEarningsCalendar(
  days: number = 14
): Promise<EarningsCalendarItem[]> {
  return backendFetch<EarningsCalendarItem[]>(
    `/api/calendar/earnings?days=${days}`
  );
}

export async function fetchEconomicCalendar(
  days: number = 7
): Promise<EconomicCalendarItem[]> {
  return backendFetch<EconomicCalendarItem[]>(
    `/api/calendar/economic?days=${days}`
  );
}

// ─── A 股公告 / 券商研报 / 市场宽度（backend DB） ───────────

export interface Announcement {
  symbol: string;
  title: string;
  category: string | null;
  publish_date: string;
  url: string | null;
}

export interface ResearchReport {
  symbol: string;
  title: string;
  org: string | null;
  rating: string | null;
  industry: string | null;
  eps_forecast: number | null;
  pe_forecast: number | null;
  forecast_year: number | null;
  publish_date: string;
  url: string | null;
}

export interface MarketBreadth {
  date: string;
  market: string;
  up_count: number | null;
  down_count: number | null;
  flat_count: number | null;
  limit_up_count: number | null;
  limit_down_count: number | null;
  real_limit_up_count: number | null;
  real_limit_down_count: number | null;
  suspended_count: number | null;
  activity_rate: number | null;
}

/** A 股公告（按发布日期倒序；不带 symbol 返回 tracked 全体） */
export async function fetchAnnouncements(
  symbol?: string,
  days: number = 30
): Promise<Announcement[]> {
  const symbolQuery = symbol
    ? `&symbol=${encodeURIComponent(symbol)}`
    : "";
  return backendFetch<Announcement[]>(
    `/api/announcements?days=${days}${symbolQuery}`
  );
}

/** 单只 A 股券商研报（按发布日期倒序） */
export async function fetchResearchReports(
  symbol: string,
  days: number = 90
): Promise<ResearchReport[]> {
  return backendFetch<ResearchReport[]>(
    `/api/research?symbol=${encodeURIComponent(symbol)}&days=${days}`
  );
}

/** 市场宽度时间序列（按日期升序，末元素即最新快照） */
export async function fetchMarketBreadth(
  days: number = 60
): Promise<MarketBreadth[]> {
  return backendFetch<MarketBreadth[]>(`/api/breadth?days=${days}`);
}

// ─── 全球宏观（/global 页） ───────────────────────────────

/** 跨资产总览行（股指/商品/汇率/波动率/债券） */
export interface CrossAssetItem {
  symbol: string;
  name: string;
  category: "equity_index" | "commodity" | "fx" | "volatility" | "bond";
  close: number | null;
  chg_1d: number | null;
  chg_1w: number | null;
  chg_1m: number | null;
  chg_3m: number | null;
  chg_1y: number | null;
  dist_ma200: number | null;
}

/** 美债收益率曲线点（值为 %） */
export interface YieldCurvePoint {
  tenor: string;
  months: number;
  latest: number | null;
  ago_1m: number | null;
  ago_1y: number | null;
}

/** 10Y-2Y 利差点（bp） */
export interface YieldSpreadPoint {
  date: string;
  spread_bp: number;
}

/** 市场内部结构比值（RSP/SPY 等） */
export interface MarketInternal {
  pair: string;
  label: string;
  note: string;
  current: number;
  chg_1m: number | null;
  chg_3m: number | null;
  series: { date: string; ratio: number }[];
}

/** 跨资产总览（按 category 固定顺序：股指/商品/汇率/波动率/债券） */
export async function fetchCrossAssets(): Promise<CrossAssetItem[]> {
  return backendFetch<CrossAssetItem[]>("/api/cross-assets");
}

/** 美债收益率曲线（11 期限：最新 / 1 月前 / 1 年前） */
export async function fetchYieldCurve(): Promise<YieldCurvePoint[]> {
  return backendFetch<YieldCurvePoint[]>("/api/yield-curve");
}

/** 10Y-2Y 利差时间序列（bp，按日期升序） */
export async function fetchYieldSpread(
  days: number = 365
): Promise<YieldSpreadPoint[]> {
  return backendFetch<YieldSpreadPoint[]>(
    `/api/yield-curve/spread?days=${days}`
  );
}

/** 市场内部结构（4 组比值，series 按日期升序） */
export async function fetchMarketInternals(
  days: number = 180
): Promise<MarketInternal[]> {
  return backendFetch<MarketInternal[]>(`/api/market-internals?days=${days}`);
}

// ─── 系统任务进度（/api/system/jobs） ─────────────────────

export interface JobProgress {
  job: string;
  label: string;
  status: "running" | "done" | "error";
  processed: number;
  total: number;
  percent: number;
  note: string;
  started_at: string;
  finished_at: string | null;
}
