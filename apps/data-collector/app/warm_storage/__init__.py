"""温层存储（ClickHouse）：分钟K 在线窗口（近 1 年）的薄客户端与写入封装。

组成：
- ClickHouseClient：CH 原生 HTTP 接口（8123）+ httpx 薄封装，永不抛异常
- minute_bars：tradeck.minute_bars 的幂等写入（先删后插，按日分区）

用法（接线侧，如分钟K job 在 PG/冷层写完后双写）：
    rows, err = await write_minute_bars(market, trade_day, bars)

启用开关：CLICKHOUSE_ENABLED=1 才真正连接 CH（默认关闭，优雅降级——
CH 未就绪环境返回 (0, 摘要)，不影响 PG/冷层主链路）。

设计见 docs/DATA-STORAGE-TIERED.md「温层：ClickHouse」一节。
建表 SQL 与 service 接线在 compose 任务，本包只按契约写客户端。
"""
from app.warm_storage.clickhouse_client import ClickHouseClient
from app.warm_storage.minute_bars import (
    COLUMNS,
    INSERT_CHUNK_SIZE,
    TABLE,
    delete_market_day,
    insert_market_day,
    replace_market_day,
    serialize_rows,
)

__all__ = [
    "ClickHouseClient",
    "COLUMNS",
    "INSERT_CHUNK_SIZE",
    "TABLE",
    "delete_market_day",
    "insert_market_day",
    "replace_market_day",
    "serialize_rows",
    "get_warm_client",
    "reset_warm_client",
    "write_minute_bars",
]

_client: ClickHouseClient | None = None


def get_warm_client() -> ClickHouseClient:
    """按 config 的 CLICKHOUSE_URL / CLICKHOUSE_DATABASE 返回客户端单例。"""
    global _client
    if _client is None:
        from app.config import settings

        _client = ClickHouseClient(settings.CLICKHOUSE_URL, settings.CLICKHOUSE_DATABASE)
    return _client


def reset_warm_client() -> None:
    """清缓存单例（测试切换配置用）。"""
    global _client
    _client = None


async def write_minute_bars(
    market: str, day, rows: list[dict]
) -> tuple[int, str]:
    """温层写入唯一入口：幂等写某市场某日的分钟K。

    优雅降级三态（均返回 (0, 非空摘要)，绝不抛异常）：
    - CLICKHOUSE_ENABLED != "1"：未启用，跳过
    - ping 失败：CH 不可达
    - replace 删/插失败：写入失败
    成功返回 (写入行数, "")。
    """
    from app.config import settings

    if settings.CLICKHOUSE_ENABLED != "1":
        return 0, "CLICKHOUSE_ENABLED 未置 1，温层写入跳过"

    client = get_warm_client()
    if not await client.ping():
        return 0, "ClickHouse ping 失败（不可达或非 200）"
    return await replace_market_day(client, market, day, rows)
