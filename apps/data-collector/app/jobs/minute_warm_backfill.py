"""分钟K 温层历史回填：data pool 冷层 delta 分区 → ClickHouse。

温层（CH minute_bars）只保留近 1 年在线窗口（TTL），本任务把冷层
``bars/minute_delta`` 中近 N 天的日分区批量投影进 CH，供首次启用温层
或温层数据重建时使用。每日新增量由 minute_kline job 双写接管，不走本任务。

幂等：每个日分区经 ``write_minute_bars``（先删后插）写入，重跑无副作用。
降级：任一市场/日失败记日志继续，绝不抛——温层是投影，冷层才是事实源。
手动触发（registry 白名单 + DATA_SYNC_TOKEN），不进 cron 调度。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.jobs.minute_storage import delta_path, read_delta_marker
from app.warm_storage import write_minute_bars
from app.warm_storage.pool_source import read_delta_day_as_utc

logger = logging.getLogger(__name__)

_MARKETS = ("CN", "HK", "US")
# 回填窗口：CH 在线窗口 1 年，回填默认 365 天（经 registry 可调）
_DEFAULT_LOOKBACK_DAYS = 365


async def run_minute_warm_backfill_job(
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
) -> dict[str, int]:
    """把近 lookback_days 天的 delta 分区逐日投影进 CH，返回各市场写入行数。"""
    logger.info("=== minute warm backfill job start: lookback=%d 天 ===", lookback_days)
    through = datetime.now(timezone.utc).date()
    start = through - timedelta(days=lookback_days - 1)
    counts: dict[str, int] = {}
    for market in _MARKETS:
        written_total = 0
        skipped = 0
        day = start
        while day <= through:
            path = delta_path(market, day)
            marker = read_delta_marker(path) if path.exists() else None
            # 只投影已验证为 complete 的分区（冷层覆盖验收通过的数据），
            # partial/无 marker 的跳过——温层只承载质量达标的数据。
            if not marker or marker.get("complete") is not True:
                skipped += 1
                day += timedelta(days=1)
                continue
            try:
                rows = await asyncio.to_thread(read_delta_day_as_utc, path, market, day)
                written, err = await write_minute_bars(market, day, rows)
                if err:
                    logger.warning(
                        "minute_warm_backfill %s %s 温层写入降级: %s", market, day, err
                    )
                else:
                    written_total += written
            except Exception:  # noqa: BLE001 — 单日失败不阻断整体回填
                logger.exception("minute_warm_backfill %s %s 读取/写入失败", market, day)
            day += timedelta(days=1)
        counts[market] = written_total
        logger.info(
            "minute_warm_backfill %s 完成: 写入 %d 行, 跳过非 complete 分区 %d 天",
            market,
            written_total,
            skipped,
        )
    logger.info(
        "=== minute warm backfill job done: %s ===",
        ", ".join(f"{m}={c}" for m, c in counts.items()),
    )
    return counts
