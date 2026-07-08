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
