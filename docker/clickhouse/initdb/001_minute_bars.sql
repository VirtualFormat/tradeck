-- 温层 ClickHouse 初始化：分钟K 在线窗口表
-- 由官方 clickhouse-server 镜像 entrypoint 首次启动时执行（/docker-entrypoint-initdb.d/*.sql）
-- ts 纪律：分钟K 时间戳统一存 UTC（交易所本地时间在写入前换算）
CREATE DATABASE IF NOT EXISTS tradeck;

CREATE TABLE IF NOT EXISTS tradeck.minute_bars (
    symbol   LowCardinality(String),
    market   LowCardinality(FixedString(2)),  -- US/CN/HK
    ts       DateTime,
    open     Float64,
    high     Float64,
    low      Float64,
    close    Float64,
    volume   UInt64,
    amount   Float64
) ENGINE = MergeTree
PARTITION BY toYYYYMMDD(ts)  -- 按日分区：日级「先删后插」幂等（ALTER DELETE）与
                             -- TTL 清理都落在单日分区上是轻操作；不分区则 25 亿行/年
                             -- 表做全分区 mutation，不可接受
ORDER BY (symbol, ts)
TTL ts + INTERVAL 1 YEAR DELETE;  -- 在线窗口 1 年；归档管道先行迁冷层，TTL 兜底防超占
