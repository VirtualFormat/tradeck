"""盘后拉日 K 线（TickFlow universe + 分市场行情源，写入 daily_prices）

分工（2026-08 起）：CN 日K 主源为同花顺 Market Dump（hithink_dump job）；
HK/US 用 TickFlow universe 获取标的目录、OpenBB/yfinance（Oracle ARM 海外节点）
批量拉行情。TickFlow Key 无 batch K线权限，不能再用于 HK/US 行情本身。

策略借鉴 TickFlow SDK：universe 拿清单 → 100 只/片批量拉 → 并发闸 + 分片失败隔离。
- 每日增量：近 5 天 UPSERT（港 08:30 UTC、美股 21:30 UTC，各自收盘后）
- 首次全量初始化：近 250 天（约一年），启动时检测到数据量不足自动触发一次
进度经 app.jobs.progress 上报，前端轮询 /api/system/jobs 展示。
"""
from __future__ import annotations

import logging
from datetime import date

from app.datasource import openbb_kline_source, tickflow_source
from app.db import get_pool
from app.jobs import progress
from app.quality import quality_gate

logger = logging.getLogger(__name__)


# 日K 覆盖的 TickFlow universe（标的池）→ 写库 market
_UNIVERSES = [
    ("CN_Equity_A", "CN"),
    ("HK_Equity", "HK"),
    ("US_Equity", "US"),
]

_INCREMENTAL_COUNT = 5  # 每日增量天数（UPSERT 覆盖周末/节假日缺口）
_FULL_COUNT = 250  # 全量初始化天数（约一年）

# 全量初始化判定：不仅看总行数，还要求三市各自有足够历史行和近期交易日覆盖，
# 避免历史行数足够但增量任务长期漏跑时被旧数据掩盖。
FULL_KLINE_MIN_ROWS = {
    "CN": 850_000,
    "HK": 500_000,
    "US": 1_500_000,
}
FULL_KLINE_MAX_AGE_DAYS = {
    "CN": 2,
    "HK": 2,
    "US": 3,
}

# UPSERT 单批行数上限（全量初始化单个 universe 可达百万行，分批写）
_UPSERT_BATCH = 50_000

_FULL_JOB_ID = "daily_kline_full"
_INC_JOB_ID = "daily_kline"


def _to_canonical(tf_symbol: str, market: str) -> str:
    """TickFlow symbol → tradeck 规范：美股去 .US 后缀（AAPL.US→AAPL），其余原样。"""
    if market == "US" and tf_symbol.endswith(".US"):
        return tf_symbol[:-3]
    return tf_symbol


async def _upsert_klines(klines: dict[str, list[dict]], market: str) -> int:
    """批量 UPSERT 一个 universe 的日K（跳 null close）。返回写入条数。"""
    dict_rows = []
    for tf_sym, krows in klines.items():
        symbol = _to_canonical(tf_sym, market)
        for r in krows:
            if r.get("close") is None:
                continue
            dict_rows.append(
                {
                    "symbol": symbol,
                    "market": market,
                    "date": r["date"],
                    "open": r["open"],
                    "high": r["high"],
                    "low": r["low"],
                    "close": r["close"],
                    "volume": r["volume"],
                    "amount": r.get("amount"),
                }
            )
    if not dict_rows:
        return 0
    # 写库前过质量闸：被拦的行不进 UPSERT（修复/拦截/落库由质量层处理）
    accepted = await quality_gate("daily_prices", dict_rows)
    if not accepted:
        return 0
    rows = [
        (d["symbol"], d["market"], d["date"], d["open"], d["high"],
         d["low"], d["close"], d["volume"], d["amount"])
        for d in accepted
    ]
    pool = await get_pool()
    async with pool.acquire() as conn:
        for i in range(0, len(rows), _UPSERT_BATCH):
            await conn.executemany(
                """
                INSERT INTO daily_prices
                    (symbol, market, date, open, high, low, close, volume, amount)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (symbol, date) DO UPDATE SET
                    open = EXCLUDED.open, high = EXCLUDED.high,
                    low = EXCLUDED.low, close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    amount = EXCLUDED.amount
                """,
                rows[i : i + _UPSERT_BATCH],
            )
    return len(rows)


async def _backfill_names(tf_symbols: list[str], market: str) -> int:
    """用 TickFlow instruments 补/校准标的名。

    CN/HK：以 instruments 中文名为准（覆盖 yfinance 英文名），全量校准；
    US：只补缺失行（已有 yfinance 英文名不动）。
    """
    pool = await get_pool()
    if market in ("CN", "HK"):
        targets = list(tf_symbols)
    else:
        canonical = [_to_canonical(s, market) for s in tf_symbols]
        async with pool.acquire() as conn:
            existing = await conn.fetch(
                "SELECT symbol FROM equity_profiles WHERE symbol = ANY($1)", canonical
            )
        existing_set = {r["symbol"] for r in existing}
        targets = [
            s for s in tf_symbols if _to_canonical(s, market) not in existing_set
        ]
    if not targets:
        return 0
    names = await tickflow_source.get_instrument_names(targets)
    if not names:
        return 0
    rows = [(_to_canonical(s, market), n) for s, n in names.items()]
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO equity_profiles (symbol, name, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (symbol) DO UPDATE SET name = EXCLUDED.name, updated_at = NOW()
            """,
            rows,
        )
    return len(rows)


async def run_daily_kline_job(
    full: bool = False,
    markets: tuple[str, ...] | None = None,
    trigger: str = "schedule",
) -> int:
    """日K job：TickFlow universe 全市场批量拉取。

    full=True 全量初始化（近 250 天，幂等可重入——重复执行靠 UPSERT 收敛）；
    否则每日增量（近 5 天）。markets 过滤要跑的 universe（cron 错峰用），None 为全部。
    """
    count = _FULL_COUNT if full else _INCREMENTAL_COUNT
    label = "日K 全量初始化" if full else "日K 每日更新"
    job_id = _FULL_JOB_ID if full else _INC_JOB_ID
    # 防重入（uvicorn --reload / 手动触发时全量任务可能已在跑）
    if progress.is_running(job_id):
        logger.info(f"=== {label} already running, skip ===")
        return 0
    logger.info(f"=== {label} start (count={count}) ===")
    run_started_at = progress.job_start(job_id, label, 0, trigger=trigger)
    processed = 0
    written = 0
    try:
        todo = [
            (universe, market)
            for universe, market in _UNIVERSES
            if markets is None or market in markets
        ]
        universe_symbols: list[tuple[str, str, list[str]]] = []
        total = 0
        for universe_id, market in todo:
            syms = await tickflow_source.get_universe_symbols(universe_id)
            if not syms:
                logger.warning(f"universe {universe_id} empty, skipped")
                continue
            universe_symbols.append((universe_id, market, syms))
            total += len(syms)
        if not total:
            logger.warning(f"=== {label}: no symbols, abort ===")
            progress.job_done(job_id, "未获取到可用标的", run_started_at)
            return 0

        progress.job_set_total(job_id, total, run_started_at)
        for universe_id, market, syms in universe_symbols:
            base = processed

            def on_chunk(done: int, _total: int, _base: int = base) -> None:
                progress.job_update(job_id, _base + done, run_started_at)

            klines = await openbb_kline_source.get_daily_klines_batch(
                syms, market=market, count=count, on_chunk=on_chunk
            )
            written += await _upsert_klines(klines, market)
            await _backfill_names(syms, market)
            processed += len(syms)
            progress.job_update(job_id, processed, run_started_at)
            logger.info(
                f"{label}: {universe_id} done ({len(syms)} symbols, {len(klines)} with data)"
            )
        progress.job_done(job_id, f"写入 {written} 行", run_started_at)
        logger.info(f"=== {label} done: {written} rows ===")
    except Exception as e:  # noqa: BLE001
        progress.job_error(job_id, str(e)[:200], run_started_at)
        raise
    return written


async def needs_full_init() -> bool:
    """任一市场历史量不足或最新 K 过旧 → 需要全量初始化。"""
    return bool(await markets_needing_full_init())


async def markets_needing_full_init() -> tuple[str, ...]:
    """返回历史行数不足或最新 K 过旧、需要全量补齐的市场。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT market, count(*) AS rows, max(date) AS latest_date
            FROM daily_prices
            GROUP BY market
            """
        )
    stats = {
        r["market"]: (int(r["rows"]), r["latest_date"])
        for r in rows
    }
    return tuple(
        market
        for market, minimum in FULL_KLINE_MIN_ROWS.items()
        if stats.get(market, (0, None))[0] < minimum
        or stats.get(market, (0, None))[1] is None
        or (date.today() - stats[market][1]).days > FULL_KLINE_MAX_AGE_DAYS[market]
    )
