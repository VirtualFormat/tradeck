-- tradeck 数据库初始化（阶段 1：3 张表）
-- postgres 容器启动时自动执行

-- 日 K 线（所有市场）
CREATE TABLE IF NOT EXISTS daily_prices (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    market CHAR(2) NOT NULL,            -- US / CN / HK
    date DATE NOT NULL,
    open DECIMAL(12,4),
    high DECIMAL(12,4),
    low DECIMAL(12,4),
    close DECIMAL(12,4),
    volume BIGINT,
    amount DECIMAL(24,4),
    UNIQUE(symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_daily_prices_symbol_date ON daily_prices(symbol, date DESC);

-- 实时报价快照（每只股票最新一条）
CREATE TABLE IF NOT EXISTS quote_snapshots (
    symbol VARCHAR(20) PRIMARY KEY,
    name VARCHAR(100),
    last_price DECIMAL(12,4),
    change DECIMAL(12,4),
    change_percent DECIMAL(8,6),
    volume BIGINT,
    market CHAR(2),
    data_as_of TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 指数历史
CREATE TABLE IF NOT EXISTS index_prices (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    market VARCHAR(10) NOT NULL,        -- US / CN / HK / JP / EU / VOL
    date DATE NOT NULL,
    close DECIMAL(12,4),
    volume BIGINT,
    UNIQUE(symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_index_prices_symbol_date ON index_prices(symbol, date DESC);

-- 涨跌榜缓存（按日快照，同日重跑覆盖当天）
CREATE TABLE IF NOT EXISTS movers_cache (
    id BIGSERIAL PRIMARY KEY,
    type VARCHAR(20) NOT NULL,          -- gainers / losers / active
    market CHAR(2) NOT NULL,
    rank INT NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    name VARCHAR(100),
    price DECIMAL(12,4),
    percent_change DECIMAL(8,6),
    volume BIGINT,
    amount DECIMAL(24,4),
    snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_movers_type_market ON movers_cache(type, market);
CREATE INDEX IF NOT EXISTS idx_movers_date ON movers_cache(snapshot_date, type, market);
CREATE UNIQUE INDEX IF NOT EXISTS uq_movers_cache_business_key
    ON movers_cache(type, market, rank, symbol, snapshot_date);

-- 新闻
CREATE TABLE IF NOT EXISTS news_articles (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20),
    title TEXT NOT NULL,
    url TEXT UNIQUE,
    summary TEXT,
    publisher VARCHAR(100),
    published_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    sentiment DECIMAL(4,3),              -- 情绪分 -1..1（关键词/LLM 打分）
    scored_at TIMESTAMPTZ                -- 打分时间（幂等，NULL=待打分）
);
CREATE INDEX IF NOT EXISTS idx_news_symbol ON news_articles(symbol);
CREATE INDEX IF NOT EXISTS idx_news_published ON news_articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_unscored ON news_articles(id) WHERE sentiment IS NULL;

-- 宏观指标
CREATE TABLE IF NOT EXISTS macro_indicators (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    date DATE NOT NULL,
    value DECIMAL(20,6),
    UNIQUE(name, date)
);

-- 财报
CREATE TABLE IF NOT EXISTS income_statements (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    fiscal_year INT,
    total_revenue DECIMAL(18,2),
    net_income DECIMAL(18,2),
    gross_profit DECIMAL(18,2),
    operating_income DECIMAL(18,2),
    UNIQUE(symbol, fiscal_year)
);

-- 公司信息
CREATE TABLE IF NOT EXISTS equity_profiles (
    symbol VARCHAR(20) PRIMARY KEY,
    name VARCHAR(100),
    sector VARCHAR(50),
    industry VARCHAR(50),
    market_cap BIGINT,
    currency VARCHAR(10),
    exchange VARCHAR(50),
    description TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 基本面指标
CREATE TABLE IF NOT EXISTS fundamental_metrics (
    symbol VARCHAR(20) PRIMARY KEY,
    market_cap BIGINT,
    pe_ratio DECIMAL(12,4),
    forward_pe DECIMAL(12,4),
    peg_ratio DECIMAL(12,4),
    enterprise_to_ebitda DECIMAL(12,4),
    earnings_growth DECIMAL(8,6),
    revenue_growth DECIMAL(8,6),
    dividend_yield DECIMAL(8,6),
    beta DECIMAL(8,4),
    profit_margins DECIMAL(8,6),
    return_on_equity DECIMAL(8,6),
    debt_to_equity DECIMAL(12,4),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 板块行情热度（概念/行业板块，按日快照）
CREATE TABLE IF NOT EXISTS board_heat (
    id BIGSERIAL PRIMARY KEY,
    board_type VARCHAR(10) NOT NULL,    -- concept / industry
    name VARCHAR(50) NOT NULL,
    code VARCHAR(20),
    change_percent DECIMAL(8,4),
    market_cap BIGINT,
    turnover_rate DECIMAL(8,4),
    leader_stock VARCHAR(50),
    leader_change DECIMAL(8,4),
    snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(board_type, name, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_board_heat_type ON board_heat(board_type, change_percent DESC);
CREATE INDEX IF NOT EXISTS idx_board_heat_date ON board_heat(snapshot_date, board_type);

-- 股票 ↔ 板块归属映射（东财成分股接口反解）
CREATE TABLE IF NOT EXISTS symbol_board_map (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    board_type VARCHAR(10) NOT NULL,    -- concept / industry
    board_name VARCHAR(50) NOT NULL,
    board_code VARCHAR(20),
    UNIQUE(symbol, board_type, board_name)
);
CREATE INDEX IF NOT EXISTS idx_board_map_board ON symbol_board_map(board_type, board_name);
CREATE INDEX IF NOT EXISTS idx_board_map_symbol ON symbol_board_map(symbol);

-- 板块舆情热度（聚合 job 按日快照）
CREATE TABLE IF NOT EXISTS board_sentiment (
    board_type VARCHAR(10) NOT NULL,
    board_name VARCHAR(50) NOT NULL,
    news_count_24h INT DEFAULT 0,
    sentiment_avg DECIMAL(5,3),
    hot_score DECIMAL(8,3),
    snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(board_type, board_name, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_board_sentiment_date ON board_sentiment(snapshot_date, board_type);

-- 个股资金流向榜（东财即时榜，按日快照）
CREATE TABLE IF NOT EXISTS fund_flow (
    symbol VARCHAR(20) NOT NULL,
    name VARCHAR(50),
    price DECIMAL(12,4),
    change_percent DECIMAL(8,4),
    turnover_rate DECIMAL(8,4),
    amount_in BIGINT,          -- 流入资金（元）
    amount_out BIGINT,         -- 流出资金（元）
    net_amount BIGINT,         -- 净额（元，正=净流入）
    amount_total BIGINT,       -- 成交额
    snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_fund_flow_net ON fund_flow(net_amount DESC);
CREATE INDEX IF NOT EXISTS idx_fund_flow_date ON fund_flow(snapshot_date, net_amount DESC);

-- 分析师共识/目标价（按日快照，同日重跑覆盖当天）
CREATE TABLE IF NOT EXISTS analyst_consensus (
    symbol VARCHAR(20) NOT NULL,
    snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
    recommendation VARCHAR(20),          -- strong_buy / buy / hold / sell 等
    recommendation_mean DECIMAL(8,4),    -- 1=强力买入 … 5=卖出
    number_of_analysts INT,
    target_high DECIMAL(12,4),
    target_low DECIMAL(12,4),
    target_consensus DECIMAL(12,4),
    target_median DECIMAL(12,4),
    current_price DECIMAL(12,4),
    currency VARCHAR(10),
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (symbol, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_analyst_consensus_symbol ON analyst_consensus(symbol, snapshot_date DESC);

-- 资产负债表（年报+季报，yfinance 源）
CREATE TABLE IF NOT EXISTS balance_sheets (
    symbol VARCHAR(20) NOT NULL,
    period VARCHAR(10) NOT NULL,        -- annual / quarter
    fiscal_date DATE NOT NULL,
    total_assets DECIMAL(18,2),
    total_liabilities DECIMAL(18,2),
    total_equity DECIMAL(18,2),
    total_current_assets DECIMAL(18,2),
    total_current_liabilities DECIMAL(18,2),
    cash_and_equivalents DECIMAL(18,2),
    inventories DECIMAL(18,2),
    accounts_receivable DECIMAL(18,2),
    total_debt DECIMAL(18,2),
    retained_earnings DECIMAL(18,2),
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (symbol, period, fiscal_date)
);
CREATE INDEX IF NOT EXISTS idx_balance_sheets_symbol ON balance_sheets(symbol, fiscal_date DESC);

-- 现金流量表（年报+季报，yfinance 源）
CREATE TABLE IF NOT EXISTS cash_flow_statements (
    symbol VARCHAR(20) NOT NULL,
    period VARCHAR(10) NOT NULL,        -- annual / quarter
    fiscal_date DATE NOT NULL,
    operating_cash_flow DECIMAL(18,2),
    investing_cash_flow DECIMAL(18,2),
    financing_cash_flow DECIMAL(18,2),
    capital_expenditure DECIMAL(18,2),
    free_cash_flow DECIMAL(18,2),
    net_income DECIMAL(18,2),
    depreciation_amortization DECIMAL(18,2),
    share_repurchase DECIMAL(18,2),
    dividends_paid DECIMAL(18,2),
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (symbol, period, fiscal_date)
);
CREATE INDEX IF NOT EXISTS idx_cash_flow_symbol ON cash_flow_statements(symbol, fiscal_date DESC);

-- 财报日历（tracked 标的未来财报披露日，yfinance 直调）
CREATE TABLE IF NOT EXISTS earnings_calendar (
    symbol VARCHAR(20) NOT NULL,
    report_date DATE NOT NULL,
    session VARCHAR(10),                 -- BMO 盘前 / AMC 盘后 / -- 未知
    eps_estimate DECIMAL(12,4),          -- 分析师 EPS 一致预期
    source VARCHAR(20),                  -- yfinance
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (symbol, report_date)
);
CREATE INDEX IF NOT EXISTS idx_earnings_calendar_date ON earnings_calendar(report_date);

-- 宏观数据日历（未来经济数据发布事件，FRED/百度源）
CREATE TABLE IF NOT EXISTS economic_calendar (
    event_date DATE NOT NULL,
    event_time VARCHAR(20),              -- 发布时间（源给字符串就原样存）
    country VARCHAR(50) NOT NULL DEFAULT '',
    event_name TEXT NOT NULL,
    importance VARCHAR(20),              -- 重要性分级（源没有就留空）
    actual TEXT,
    forecast TEXT,                       -- 预期
    previous TEXT,                       -- 前值
    source VARCHAR(20),                  -- fred / baidu
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (event_date, event_name, country)
);
CREATE INDEX IF NOT EXISTS idx_economic_calendar_date ON economic_calendar(event_date);

-- 技术指标（由 daily_prices 本地计算，不调外部数据源）
CREATE TABLE IF NOT EXISTS technical_indicators (
    symbol VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    ma5 DECIMAL(14,4),
    ma10 DECIMAL(14,4),
    ma20 DECIMAL(14,4),
    ma60 DECIMAL(14,4),
    ema12 DECIMAL(14,4),
    ema26 DECIMAL(14,4),
    dif DECIMAL(14,4),
    dea DECIMAL(14,4),
    macd DECIMAL(14,4),
    rsi6 DECIMAL(8,4),
    rsi14 DECIMAL(8,4),
    boll_upper DECIMAL(14,4),
    boll_mid DECIMAL(14,4),
    boll_lower DECIMAL(14,4),
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_technical_indicators_symbol_date ON technical_indicators(symbol, date DESC);

-- A 股公告（东财，直调 akshare；tracked A 股）
CREATE TABLE IF NOT EXISTS announcements (
    symbol VARCHAR(20) NOT NULL,
    title TEXT NOT NULL,
    category VARCHAR(50),                 -- 公告类型（业绩公告/重大事项/风险提示 等）
    publish_date DATE NOT NULL,
    url TEXT,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (symbol, title, publish_date)
);
CREATE INDEX IF NOT EXISTS idx_announcements_date ON announcements(publish_date DESC);

-- A 股券商研报（东财，直调 akshare；tracked A 股，只留最近 90 天）
CREATE TABLE IF NOT EXISTS research_reports (
    symbol VARCHAR(20) NOT NULL,
    title TEXT NOT NULL,
    org VARCHAR(50),                      -- 机构（券商）
    rating VARCHAR(20),                   -- 东财评级（买入/增持/中性 等）
    industry VARCHAR(50),
    eps_forecast DECIMAL(12,4),           -- 最新年份预测每股收益
    pe_forecast DECIMAL(12,4),            -- 最新年份预测市盈率
    forecast_year INT,                    -- 预测年份（列名随年份动态变化）
    publish_date DATE NOT NULL,
    url TEXT,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (symbol, title, publish_date)
);
CREATE INDEX IF NOT EXISTS idx_research_reports_date ON research_reports(publish_date DESC);

-- 市场宽度（A 股，乐咕乐股实时快照，按日 UPSERT 覆盖当天）
CREATE TABLE IF NOT EXISTS market_breadth (
    date DATE NOT NULL,
    market VARCHAR(10) NOT NULL DEFAULT 'CN',
    up_count INT,
    down_count INT,
    flat_count INT,
    limit_up_count INT,
    limit_down_count INT,
    real_limit_up_count INT,              -- 真实涨停（剔除 ST）
    real_limit_down_count INT,            -- 真实跌停（剔除 ST）
    suspended_count INT,
    activity_rate NUMERIC,                -- 活跃度（%，legu 原值如 10.27）
    source VARCHAR(20),
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (date, market)
);
CREATE INDEX IF NOT EXISTS idx_market_breadth_date ON market_breadth(date DESC);

-- 宏观资产价格（美元指数/离岸人民币/ETF，macro_assets job 写入）
CREATE TABLE IF NOT EXISTS macro_asset_prices (
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,              -- fx / etf
    date DATE NOT NULL,
    close NUMERIC,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_macro_asset_prices_date ON macro_asset_prices (date DESC);

-- 美债收益率曲线（federal_reserve 日频，11 个期限宽行）
CREATE TABLE IF NOT EXISTS yield_curve_rates (
    date DATE PRIMARY KEY,
    month_1 NUMERIC, month_3 NUMERIC, month_6 NUMERIC,
    year_1 NUMERIC, year_2 NUMERIC, year_3 NUMERIC, year_5 NUMERIC,
    year_7 NUMERIC, year_10 NUMERIC, year_20 NUMERIC, year_30 NUMERIC,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 数据质量层（app/quality/，collector 独占写）─────────────────
-- 被拦数据留痕（quarantine）：原始 payload + 原因 + 严重级，供审计
CREATE TABLE IF NOT EXISTS data_quality_rejects (
    id BIGSERIAL PRIMARY KEY,
    source_table VARCHAR(50) NOT NULL,      -- 目标表名
    symbol VARCHAR(20),                     -- 标的（无 symbol 的表为 null）
    raw_payload JSONB NOT NULL,             -- 原始未归一的行
    reject_reason TEXT NOT NULL,
    severity VARCHAR(4) NOT NULL,           -- P0 / P1 / P2
    rejected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dq_rejects_table_time
    ON data_quality_rejects(source_table, rejected_at DESC);

-- 复权因子（findb adj_factor 同步，collector 独占写）：
-- 支撑「存原始价 + 复权因子、参数返回 qfq/hfq」的复权体系
CREATE TABLE IF NOT EXISTS adjust_factors (
    symbol VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    qfq NUMERIC(20,8),                  -- 前复权因子（以最新日基准）
    hfq NUMERIC(20,8),                  -- 后复权因子（以最早日基准）
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_adjust_factors_symbol_date ON adjust_factors(symbol, date DESC);

-- 质量度量（按表按日聚合）：总数/合格/拦截/修复/质量分，供可观测
CREATE TABLE IF NOT EXISTS data_quality_metrics (
    table_name VARCHAR(50) NOT NULL,
    date DATE NOT NULL,
    total INT NOT NULL DEFAULT 0,
    accepted INT NOT NULL DEFAULT 0,
    rejected INT NOT NULL DEFAULT 0,
    repaired INT NOT NULL DEFAULT 0,
    quality_score NUMERIC(6,4),             -- 合格数/总数，0-1
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (table_name, date)
);
CREATE INDEX IF NOT EXISTS idx_dq_metrics_date ON data_quality_metrics(date DESC);
