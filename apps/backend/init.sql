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
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 指数历史
CREATE TABLE IF NOT EXISTS index_prices (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    market CHAR(2) NOT NULL,
    date DATE NOT NULL,
    close DECIMAL(12,4),
    volume BIGINT,
    UNIQUE(symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_index_prices_symbol_date ON index_prices(symbol, date DESC);

-- 涨跌榜缓存
CREATE TABLE IF NOT EXISTS movers_cache (
    id BIGSERIAL PRIMARY KEY,
    type VARCHAR(20) NOT NULL,          -- gainers / losers / active
    market CHAR(2) NOT NULL,
    rank INT,
    symbol VARCHAR(20),
    name VARCHAR(100),
    price DECIMAL(12,4),
    percent_change DECIMAL(8,6),
    volume BIGINT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_movers_type_market ON movers_cache(type, market);

-- 新闻
CREATE TABLE IF NOT EXISTS news_articles (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20),
    title TEXT NOT NULL,
    url TEXT UNIQUE,
    summary TEXT,
    publisher VARCHAR(100),
    published_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_news_symbol ON news_articles(symbol);
CREATE INDEX IF NOT EXISTS idx_news_published ON news_articles(published_at DESC);

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
