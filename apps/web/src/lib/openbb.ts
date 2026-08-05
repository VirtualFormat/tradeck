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

export interface BoardHeatItem {
  name: string;
  code?: string | null;
  change_percent: number | null;
  market_cap: number | null;
  turnover_rate: number | null;
  leader_stock: string | null;
  leader_change: number | null;
  snapshot_date?: string | null;
  source?: "eastmoney" | "ths" | null;
  size_basis?: "market_cap" | "turnover" | null;
}

export interface FundFlowItem {
  symbol: string;
  name: string | null;
  price: number | null;
  change_percent: number | null;
  turnover_rate: number | null;
  net_amount: number | null;
  snapshot_date?: string | null;
  /** 榜单更新时间（fund_flow.updated_at，5 分钟级即时榜） */
  updated_at?: string | null;
}

/** 板块热力日快照（仅 A 股，默认返回最近快照日）。 */
export async function fetchBoardHeat(
  type: "industry" | "concept" = "industry",
  date?: string,
  limit: number = 80,
  order: "change" | "market_cap" = "change"
): Promise<BoardHeatItem[]> {
  const params = new URLSearchParams({
    type,
    limit: String(limit),
    order,
  });
  if (date) params.set("date", date);
  return backendFetch<BoardHeatItem[]>(
    `/api/boards/heat?${params.toString()}`
  );
}

/** 个股主力资金日快照（仅 A 股，默认返回最近快照日）。 */
export async function fetchFundFlow(
  direction: "in" | "out",
  date?: string,
  limit: number = 10
): Promise<FundFlowItem[]> {
  const params = new URLSearchParams({
    direction,
    limit: String(limit),
  });
  if (date) params.set("date", date);
  return backendFetch<FundFlowItem[]>(`/api/fundflow?${params.toString()}`);
}

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

// ─── 首页异动榜（RSC 预取，Client 仅切换已传入数据） ─────────

export type MoversMarket = "cn" | "us" | "hk";
export type MoversType = "gainers" | "losers" | "active" | "turnover";

export interface MoversItem {
  symbol: string;
  name: string | null;
  price: number | null;
  change: number | null;
  percent_change: number | null;
  volume: number | null;
  /** 成交额近似值：最新价 × 成交量，仅活跃榜展示 */
  amount: number | null;
  /** 估算换手小数（成交额近似值 / 总市值），仅换手榜返回 */
  turnover: number | null;
  /** movers_cache 日快照日期；港股跟踪标的报价没有此字段 */
  snapshot_date: string | null;
  /** quote_snapshots 更新时间；当前报价/换手榜使用 */
  updated_at: string | null;
}

export type MoversPrimaryData = Record<
  Exclude<MoversType, "turnover">,
  MoversItem[]
>;

// 港股异动榜暂时只覆盖这些跟踪标的；CN/US 已走 movers_cache 全市场榜。
const DASHBOARD_HK_SYMBOLS = [
  "00700.HK",
  "09988.HK",
  "00005.HK",
  "01299.HK",
  "00883.HK",
  "00939.HK",
  "00388.HK",
  "02318.HK",
  "00941.HK",
  "01810.HK",
  "03690.HK",
  "09618.HK",
];

function quoteToMoversItem(quote: EquityQuote): MoversItem {
  const amount =
    quote.last_price != null && quote.volume != null
      ? quote.last_price * quote.volume
      : null;

  return {
    symbol: quote.symbol,
    name: quote.name,
    price: quote.last_price,
    change: quote.change,
    percent_change: quote.change_percent,
    volume: quote.volume,
    amount,
    turnover: null,
    snapshot_date: null,
    updated_at: quote.updated_at ?? null,
  };
}

function normalizeMoversItem(item: Partial<MoversItem>): MoversItem {
  const amount =
    item.amount ??
    (item.price != null && item.volume != null
      ? item.price * item.volume
      : null);

  return {
    symbol: item.symbol ?? "",
    name: item.name ?? null,
    price: item.price ?? null,
    change: item.change ?? null,
    percent_change: item.percent_change ?? null,
    volume: item.volume ?? null,
    amount,
    turnover: item.turnover ?? null,
    snapshot_date: item.snapshot_date ?? null,
    updated_at: item.updated_at ?? null,
  };
}

function compareNullable(
  a: number | null,
  b: number | null,
  direction: "asc" | "desc"
): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return direction === "asc" ? a - b : b - a;
}

/**
 * 首页涨幅/跌幅/活跃榜。
 * - CN/US：movers_cache 全市场榜，支持 date 日快照。
 * - HK：使用跟踪标的当前报价，date 不适用。
 */
export async function fetchMovers(
  type: Exclude<MoversType, "turnover">,
  market: MoversMarket,
  date?: string,
  limit: number = 6
): Promise<MoversItem[]> {
  if (market === "hk") {
    const quotes = await getEquityQuotes(DASHBOARD_HK_SYMBOLS);
    const items = quotes.map(quoteToMoversItem);

    items.sort((a, b) => {
      if (type === "gainers") {
        return compareNullable(a.percent_change, b.percent_change, "desc");
      }
      if (type === "losers") {
        return compareNullable(a.percent_change, b.percent_change, "asc");
      }
      return compareNullable(a.amount, b.amount, "desc");
    });

    return items.slice(0, limit);
  }

  const dateQuery = date ? `&date=${encodeURIComponent(date)}` : "";
  const data = await backendFetch<Partial<MoversItem>[]>(
    `/api/movers?type=${type}&market=${market.toUpperCase()}&limit=${limit}${dateQuery}`
  );
  if (!Array.isArray(data)) return [];
  return data
    .map(normalizeMoversItem)
    .filter((item) => item.symbol)
    .slice(0, limit);
}

/** 首页三类主榜一次取齐；港股仅发起一次批量报价请求。 */
export async function fetchMoversPrimaryData(
  market: MoversMarket,
  date?: string,
  limit: number = 6
): Promise<MoversPrimaryData> {
  if (market !== "hk") {
    const [gainers, losers, active] = await Promise.all([
      fetchMovers("gainers", market, date, limit),
      fetchMovers("losers", market, date, limit),
      fetchMovers("active", market, date, limit),
    ]);
    return { gainers, losers, active };
  }

  const items = (await getEquityQuotes(DASHBOARD_HK_SYMBOLS)).map(
    quoteToMoversItem
  );
  const sorted = (
    field: "percent_change" | "amount",
    direction: "asc" | "desc"
  ) =>
    [...items]
      .sort((a, b) => compareNullable(a[field], b[field], direction))
      .slice(0, limit);

  return {
    gainers: sorted("percent_change", "desc"),
    losers: sorted("percent_change", "asc"),
    active: sorted("amount", "desc"),
  };
}

/**
 * 首页换手榜。该接口使用当前 quote_snapshots + equity_profiles，
 * 不支持历史 date；调用方必须标注“当前”。
 */
export async function fetchMoversTurnover(
  market: MoversMarket,
  limit: number = 6
): Promise<MoversItem[]> {
  const backendMarket = market.toUpperCase();
  // quote_snapshots 仅是报价覆盖集，不是全市场；港股多取一些后再按
  // 跟踪集合过滤，避免逐标的 profile 请求拖慢默认涨幅榜。
  const requestLimit = market === "hk" ? 100 : limit;
  const data = await backendFetch<Partial<MoversItem>[]>(
    `/api/movers/turnover?market=${backendMarket}&limit=${requestLimit}`
  );
  if (!Array.isArray(data)) return [];
  const normalized = data
    .map(normalizeMoversItem)
    .filter((item) => item.symbol);

  if (market === "hk") {
    const tracked = new Set(DASHBOARD_HK_SYMBOLS);
    return normalized
      .filter((item) => tracked.has(item.symbol))
      .slice(0, limit);
  }

  return normalized
    .slice(0, limit);
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
  _provider: string = "sec",
  _period: string = "annual",
  limit: number = 3
): Promise<IncomeStatement[]> {
  void _provider;
  void _period;
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
  _provider: string = "oecd",
  limit: number = 12
): Promise<MacroSeries[]> {
  void _provider;
  const data = await backendFetch<{date: string; value: number}[]>(
    `/api/macro?name=CPI&limit=${limit}`
  );
  return data;
}

export async function getUnemployment(
  _provider: string = "oecd",
  limit: number = 12
): Promise<MacroSeries[]> {
  void _provider;
  return backendFetch<{date: string; value: number}[]>(
    `/api/macro?name=Unemployment&limit=${limit}`
  );
}

export async function getGDPNominal(
  _provider: string = "oecd",
  limit: number = 20
): Promise<MacroSeries[]> {
  void _provider;
  return backendFetch<{date: string; value: number}[]>(
    `/api/macro?name=GDP_Nominal&limit=${limit}`
  );
}

export async function getEFFR(
  _provider: string = "federal_reserve",
  limit: number = 12
): Promise<RateSeries[]> {
  void _provider;
  const data = await backendFetch<{date: string; value: number}[]>(
    `/api/macro?name=EFFR&limit=${limit}`
  );
  return data.map((r) => ({ date: r.date, rate: r.value }));
}

export async function getSOFR(
  _provider: string = "federal_reserve",
  limit: number = 12
): Promise<RateSeries[]> {
  void _provider;
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

/** 三市对比总览行（CN/US/HK 市场宽度最新快照，up_ratio 后端算好） */
export interface MarketSummary {
  market: string;
  date: string | null;
  up: number;
  down: number;
  flat: number;
  /** 涨跌停：仅 CN 非 null（legu 口径）；US/HK 为 null（日K 自算无此项） */
  limit_up: number | null;
  limit_down: number | null;
  total: number;
  /** 上涨占比 = up / (up + down)，平盘不计入分母；分母为 0 时 null */
  up_ratio: number | null;
}

/** 三市对比总览（CN/US/HK 各取最新一行；date 传入则查历史快照） */
export async function fetchMarketSummary(
  date?: string
): Promise<MarketSummary[]> {
  const dateQuery = date ? `?date=${encodeURIComponent(date)}` : "";
  return backendFetch<MarketSummary[]>(`/api/market-summary${dateQuery}`);
}

// ─── 全球宏观（/global 页） ───────────────────────────────

/** 跨资产总览行（股指/商品/汇率/波动率/债券） */
export interface CrossAssetItem {
  symbol: string;
  name: string;
  category: "equity_index" | "commodity" | "fx" | "volatility" | "bond";
  latest_date?: string | null;
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
  latest_date?: string | null;
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
  trigger: "schedule" | "startup" | "manual";
  status: "running" | "done" | "error";
  processed: number;
  total: number;
  percent: number;
  note: string;
  started_at: string;
  finished_at: string | null;
}

export interface DataJob {
  id: string;
  label: string;
  description: string;
  source: string;
  schedule: string;
  tables: string[];
  allow_manual: boolean;
  status: "idle" | "running" | "done" | "error";
  last_run: JobProgress | null;
  next_run_at: string | null;
}

export interface DataTableStat {
  name: string;
  row_count: number;
  total_bytes: number;
}

export interface DailyMarketStat {
  market: "CN" | "HK" | "US";
  row_count: number;
  latest_date: string | null;
}

export interface DataSystemSnapshot {
  jobs: DataJob[];
  tables: DataTableStat[];
  daily_markets: DailyMarketStat[];
  summary: {
    job_count: number;
    running_count: number;
    error_count: number;
    table_count: number;
    total_rows: number;
    total_bytes: number;
  };
}
