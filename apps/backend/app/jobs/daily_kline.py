"""盘后拉日 K 线（TickFlow universe 全市场批量，写入 daily_prices）

策略借鉴 TickFlow SDK：universe 拿清单 → 100 只/片批量拉 → 并发闸 + 分片失败隔离。
- 每日增量：近 5 天 UPSERT（A/港 08:30 UTC、美股 21:30 UTC，各自收盘后）
- 首次全量初始化：近 250 天（约一年），启动时检测到数据量不足自动触发一次
进度经 app.jobs.progress 上报，前端轮询 /api/system/jobs 展示。
"""
from __future__ import annotations

import logging

from app.datasource import tickflow_source
from app.db import get_pool
from app.jobs import progress

logger = logging.getLogger(__name__)


# 跟踪的股票（100 只）——报价/基本面/新闻/日历等 job 的精选样本。
# 日K 覆盖已扩至全市场（见 _UNIVERSES），本列表不再限制日K 范围。
TRACKED_SYMBOLS = [
    # ── 美股科技（30）──
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "NFLX",
    "AMD", "INTC", "AVGO", "QCOM", "ADBE", "CRM", "ORCL", "CSCO",
    "ACN", "IBM", "NOW", "UBER", "LYFT", "SNAP", "PINS", "SHOP",
    "SQ", "PYPL", "COIN", "PLTR", "SNOW", "ZM",
    # ── 美股金融/消费/医疗（20）──
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "V", "MA", "AXP",
    "WMT", "COST", "HD", "MCD", "NKE", "SBUX", "DIS", "KO", "PEP", "PG",
    # ── 美股能源/工业（10）──
    "XOM", "CVX", "COP", "SLB", "EOG", "BA", "CAT", "GE", "HON", "UPS",
    # ── A 股（30）──（沪市用 .SH，与 TickFlow/业界一致）
    "600519.SH", "601318.SH", "600036.SH", "000858.SZ", "002594.SZ",
    "300750.SZ", "601012.SH", "600900.SH", "000001.SZ", "601166.SH",
    "600276.SH", "601398.SH", "000333.SZ", "600030.SH", "601888.SH",
    "600031.SH", "000651.SZ", "002415.SZ", "300059.SZ", "600009.SH",
    "601628.SH", "600585.SH", "000568.SZ", "002714.SZ", "600436.SH",
    "603259.SH", "601857.SH", "600028.SH", "601088.SH", "600019.SH",
    # ── 港股（10）──（5 位补零，与 TickFlow/业界一致）
    "00700.HK", "09988.HK", "01810.HK", "03690.HK", "09618.HK",
    "00005.HK", "01299.HK", "00883.HK", "00939.HK", "02318.HK",
]

# 日K 覆盖的 TickFlow universe（标的池）→ 写库 market
_UNIVERSES = [
    ("CN_Equity_A", "CN"),
    ("HK_Equity", "HK"),
    ("US_Equity", "US"),
]

_INCREMENTAL_COUNT = 5  # 每日增量天数（UPSERT 覆盖周末/节假日缺口）
_FULL_COUNT = 250  # 全量初始化天数（约一年）

# 全量初始化判定：daily_prices 低于此行数视为未初始化
FULL_KLINE_MIN_ROWS = 1_000_000

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
    rows = []
    for tf_sym, krows in klines.items():
        symbol = _to_canonical(tf_sym, market)
        for r in krows:
            if r.get("close") is None:
                continue
            rows.append(
                (symbol, market, r["date"], r["open"], r["high"],
                 r["low"], r["close"], r["volume"])
            )
    if not rows:
        return 0
    pool = await get_pool()
    async with pool.acquire() as conn:
        for i in range(0, len(rows), _UPSERT_BATCH):
            await conn.executemany(
                """
                INSERT INTO daily_prices (symbol, market, date, open, high, low, close, volume)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (symbol, date) DO UPDATE SET
                    open = EXCLUDED.open, high = EXCLUDED.high,
                    low = EXCLUDED.low, close = EXCLUDED.close,
                    volume = EXCLUDED.volume
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
    full: bool = False, markets: tuple[str, ...] | None = None
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

    todo = [(u, m) for u, m in _UNIVERSES if markets is None or m in markets]
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
        return 0

    progress.job_start(job_id, label, total)
    processed = 0
    written = 0
    try:
        for universe_id, market, syms in universe_symbols:
            base = processed

            def on_chunk(done: int, _total: int, _base: int = base) -> None:
                progress.job_update(job_id, _base + done)

            klines = await tickflow_source.get_daily_klines_batch(
                syms, count=count, on_chunk=on_chunk
            )
            written += await _upsert_klines(klines, market)
            await _backfill_names(syms, market)
            processed += len(syms)
            progress.job_update(job_id, processed)
            logger.info(
                f"{label}: {universe_id} done ({len(syms)} symbols, {len(klines)} with data)"
            )
        progress.job_done(job_id, f"写入 {written} 行")
        logger.info(f"=== {label} done: {written} rows ===")
    except Exception as e:  # noqa: BLE001
        progress.job_error(job_id, str(e)[:200])
        raise
    return written


async def needs_full_init() -> bool:
    """daily_prices 数据量低于阈值 → 需要全量初始化（启动时调用）。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        n = await conn.fetchval("SELECT count(*) FROM daily_prices")
    return (n or 0) < FULL_KLINE_MIN_ROWS
