-- 为全市场活跃榜补充成交额字段。
-- init.sql 只在新数据卷首次启动时执行；已有数据卷需手动执行本迁移。

ALTER TABLE daily_prices
    ADD COLUMN IF NOT EXISTS amount DECIMAL(24,4);

ALTER TABLE movers_cache
    ADD COLUMN IF NOT EXISTS amount DECIMAL(24,4);
