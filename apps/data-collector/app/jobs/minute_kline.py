"""分钟K 采集 job（4.2a-0 冷层先行）：每日拉当日分钟K，直写冷层 Parquet。

链路：findb 1min（findb_source）→ quality_gate（minute_bars 质量闸）→
      ColdStorage 写 Parquet 落冷层（year/market 分区 + 文件内 (symbol,ts) 排序）。

数据源（2026-08-25 起 yfinance → findb）：
- findb：A股/港股/美股 1min 全市场 + 全历史（A股 2002 年起）+ amount 成交额，
  无 yfinance 的 7 天窗口限制（历史缺口可补）。findb bars 为单 code 接口，
  逐标的拉取。复权默认原始价（adjust 空，复权经 adj_factor 另算）。
- A股分钟K 由此接入（此前 yfinance 不支持 A股、akshare 东财本地被封）。

纪律：ts 统一存 UTC epoch 秒；每日幂等（重跑覆盖同分区文件）；
findb 限流/写锁自动退避（findb_source 内置）；失败优雅降级记日志。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.cold_storage import get_cold_storage
from app.quality import quality_gate

logger = logging.getLogger(__name__)

# 缺口检测窗口（天）：每日采集当日后，顺带检测近 N 天缺口并补拉。
# findb 全历史可拉（无 yfinance 的 7 天窗口），窗口设为采集效率与及时性的平衡。
_GAP_LOOKBACK_DAYS = 7


def _minute_symbols() -> dict[str, list[str]]:
    """按市场分组待采标的（US/HK/CN 三市场，findb 均支持）。"""
    from app.constants import TRACKED_SYMBOLS
    from app.markets import pick_market

    groups: dict[str, list[str]] = {"US": [], "HK": [], "CN": []}
    for s in TRACKED_SYMBOLS:
        m = pick_market(s)
        if m not in groups:
            continue
        # 健壮性：港股规范码须为 5 位（findb 用 5 位补零，与规范一致）。
        if m == "HK":
            code = s.split(".")[0]
            if len(code) != 5:
                logger.warning(f"minute_kline 跳过非法港股代码（非 5 位）: {s}")
                continue
        groups[m].append(s)
    return groups


# 各市场交易所时区（findb datetime 为交易所本地时间，转 UTC epoch 用）
_MARKET_TZ = {
    "CN": "Asia/Shanghai",
    "HK": "Asia/Hong_Kong",
    "US": "America/New_York",
}


def _to_findb_code(symbol: str, market: str) -> str:
    """规范 symbol → findb code。findb 用：A股 600036.SH/000001.SZ/920839.BJ、
    港股 00700.HK（5 位补零）、美股 AAPL.US（裸码 + .US 后缀）。"""
    if market == "US" and "." not in symbol:
        return f"{symbol}.US"
    return symbol  # CN（.SH/.SZ/.BJ）与 HK（5 位）与规范一致


async def _fetch_1m_symbol(
    symbol: str, market: str, day: date | None
) -> list[dict[str, Any]]:
    """拉单标的 findb 1min，返回 findb 原始行（含 datetime/ohlc/volume/amount）。

    findb bars 单 code；day=None 拉最近（order=desc limit=当日分钟数上限），
    指定 day 拉该天（start=end=day，findb 全历史可拉，无 7 天窗口限制）。
    """
    from app.datasource import findb_source

    code = _to_findb_code(symbol, market)
    if day is None:
        # 当日：拉最近一批（A股 240 根/日、美股 390 根/日，取上限 400 覆盖）
        return await findb_source.fetch_bars(
            code, freq="1min", order="desc", limit=400
        )
    return await findb_source.fetch_bars(
        code,
        freq="1min",
        start=day.isoformat(),
        end=day.isoformat(),
        order="asc",
        limit=400,
    )


def _v(x: Any) -> float | None:
    """NaN/None → None，否则转 float（避免 NaN 进 Parquet）。"""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _findb_rows_to_minute(
    bars: list[dict[str, Any]], symbol: str, market: str
) -> list[dict[str, Any]]:
    """findb 1min 行（datetime 交易所本地时间）→ 分钟K dict 行（ts UTC epoch 秒）。"""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(_MARKET_TZ.get(market, "UTC"))
    rows: list[dict[str, Any]] = []
    for b in bars:
        close = _v(b.get("close"))
        if close is None:
            continue
        # findb datetime 如 2026-08-24T15:00:00（交易所本地，无 tz）→ UTC epoch
        dt_str = b.get("datetime") or b.get("date")
        try:
            naive = datetime.fromisoformat(str(dt_str).replace("Z", ""))
            epoch = int(naive.replace(tzinfo=tz).timestamp())
        except (ValueError, TypeError):
            continue
        rows.append(
            {
                "symbol": symbol,
                "market": market,
                "ts": epoch,
                "open": _v(b.get("open")),
                "high": _v(b.get("high")),
                "low": _v(b.get("low")),
                "close": close,
                "volume": _v(b.get("volume")),
                "amount": _v(b.get("amount")),  # findb 有成交额（yfinance 无）
            }
        )
    return rows


async def fetch_and_store_minute_kline(
    market: str, symbols: list[str], day: date
) -> int:
    """拉单市场某天分钟K → 质量闸 → 冷层。返回落冷层条数。

    day 为要采集的交易日（采当日传当天，补拉缺口传历史某天）。
    """
    if not symbols:
        return 0

    # ① 拉取（findb 逐标的并发；单标的失败不影响其他，优雅降级）。
    # day 传给 _fetch_1m_symbol 决定拉当日还是历史某天（补拉，findb 全历史可拉）。
    rows: list[dict[str, Any]] = []
    fetch_results = await asyncio.gather(
        *(_fetch_1m_symbol(sym, market, day) for sym in symbols),
        return_exceptions=True,
    )
    for sym, res in zip(symbols, fetch_results):
        if isinstance(res, Exception):
            logger.warning(f"minute_kline {market} {sym} 拉取失败: {res}")
            continue
        rows.extend(_findb_rows_to_minute(res, sym, market))

    if not rows:
        logger.warning(f"minute_kline {market} {day} 无数据（{len(symbols)} 只）")
        return 0

    # ② 质量闸（OHLC 自洽 + 非负；分钟K 不落库表，quarantine 留痕于 quality 层）
    accepted = await quality_gate("minute_bars", rows)
    if not accepted:
        return 0

    # ③ 冷层：year/market/date 分区 + 文件内 (symbol,ts) 排序；幂等覆盖当日文件。
    # 分区日期用数据真实交易日（yfinance index 的首个交易日，交易所时区），
    # 不用入参 day——misfire 补跑跨 UTC 日界时 day 可能错位，数据日期才是准的。
    trade_date = _trade_date_of(rows) or day
    key = (
        f"minute_bars/year={trade_date.year}/market={market}/"
        f"date={trade_date.isoformat()}/part-000.parquet"
    )
    cs = get_cold_storage()
    try:
        await asyncio.to_thread(cs.write_parquet, key, accepted, sort_by=["symbol", "ts"])
    except Exception as e:  # noqa: BLE001 — 冷层写失败降级记日志，不连带阻塞其他市场
        logger.error(
            f"minute_kline {market} 写冷层失败（{len(accepted)} 行 → {key}）："
            f"{type(e).__name__}: {e}"
        )
        return 0
    logger.info(f"minute_kline {market} {trade_date}: {len(accepted)} rows → {key}")
    return len(accepted)


def _trade_date_of(rows: list[dict[str, Any]]) -> date | None:
    """从已落行的 ts（UTC epoch 秒）推导数据的真实交易日（取众数日的 UTC 日期）。

    分钟K 单行 ts 是 UTC；同一交易日内的行 UTC 日期一致（US/HK 盘后数据）。
    用于冷层分区 key，比信任入参 day 更抗 misfire 跨日界错位。
    """
    if not rows:
        return None
    days = [
        datetime.fromtimestamp(r["ts"], tz=timezone.utc).date()
        for r in rows
        if r.get("ts") is not None
    ]
    if not days:
        return None
    return max(set(days), key=days.count)


async def detect_missing_days(
    market: str, lookback_days: int, today: date
) -> tuple[list[date], bool]:
    """缺口检测：近 lookback_days 天内，该市场缺哪些交易日的冷层分区。

    用冷层 list_keys 列已有分区，对比「应有的近期日期」找缺口。
    候选集剔除周末（周六/周日全球休市，yfinance 必返回空，列为缺口会常态化
    刷屏、淹没真缺口）。节假日不预判（无交易日历）——补拉空转，但量级小。

    返回 (缺口日期列表升序, 检测是否成功)。检测失败（冷层不可达）返回
    ([], False)——调用方据此区分「无缺口」与「检测失败」，失败需显式告警
    （漏采即永久丢失，检测失败 = 缺口检测形同虚设，不能静默）。
    """
    try:
        cs = get_cold_storage()
    except Exception:  # noqa: BLE001 — 配置非法也算检测失败
        logger.exception(f"minute_kline {market} 缺口检测初始化冷层失败")
        return [], False
    try:
        keys = await asyncio.to_thread(cs.list_keys, f"minute_bars/")
    except Exception:  # noqa: BLE001
        logger.exception(f"minute_kline {market} 缺口检测列分区失败")
        return [], False

    # 已有分区的 (market, date) 集合
    have: set[date] = set()
    prefix = f"minute_bars/year="
    marker = f"/market={market}/date="
    for k in keys:
        if not k.startswith(prefix) or marker not in k:
            continue
        try:
            dstr = k.split(marker, 1)[1].split("/", 1)[0]
            have.add(date.fromisoformat(dstr))
        except (IndexError, ValueError):
            continue

    # 近 lookback_days 天（不含今日——今日由本轮正常采集覆盖）中缺失的；
    # 剔除周末（weekday() 5=周六 6=周日）
    missing = []
    for i in range(1, lookback_days + 1):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        if d not in have:
            missing.append(d)
    return sorted(missing), True


async def backfill_missing_days(market: str, symbols: list[str], today: date) -> int:
    """补拉近 7 天缺口（yfinance 1m 窗口内可救）。返回补回的分区数。

    每个缺口日独立降级：补拉失败（限流/该天非交易日无数据）记日志跳过，
    不影响其他缺口日。幂等（补拉覆盖同分区）。
    检测失败（冷层不可达）显式告警（ERROR），不误报为「无缺口」——
    漏采即永久丢失，检测失败 = 缺口检测形同虚设，必须可被发现。
    """
    if not symbols:
        return 0
    missing, detect_ok = await detect_missing_days(market, _GAP_LOOKBACK_DAYS, today)
    if not detect_ok:
        # 显式告警（区别于日常 noise）：连续出现说明冷层挂了，缺口在悄悄累积
        logger.error(
            f"minute_kline {market} 缺口检测失败（冷层不可达），本轮无法确认缺口"
        )
        return 0
    if not missing:
        return 0
    logger.info(f"minute_kline {market} 检测到 {len(missing)} 个缺口日（已剔周末）: {missing}")

    filled = 0
    for d in missing:
        try:
            n = await fetch_and_store_minute_kline(market, symbols, d)
            if n > 0:
                filled += 1
                logger.info(f"minute_kline {market} 补拉 {d}: {n} rows")
            else:
                # 区分「该天无数据」（节假日/滑出窗口）与「补拉失败」（异常）：
                # fetch_and_store 返回 0 是正常空转（不写假数据），记 info 而非 exception
                logger.info(f"minute_kline {market} 补拉 {d}: 该天无数据（节假日或窗口外）")
        except Exception:  # noqa: BLE001 — 单缺口日失败不影响其他
            logger.exception(f"minute_kline {market} 补拉 {d} 失败，跳过")
    return filled


async def run_minute_kline_job(day: date | None = None) -> dict[str, int]:
    """每日分钟K 采集：US/HK 各市场采当日。返回各市场落冷层条数。"""
    logger.info("=== minute kline job start ===")
    day = day or datetime.now(timezone.utc).date()
    groups = _minute_symbols()
    counts: dict[str, int] = {}
    for market, symbols in groups.items():
        # 每市场独立降级：一个市场失败（拉取/质量/写冷层）不影响另一市场
        try:
            counts[market] = await fetch_and_store_minute_kline(market, symbols, day)
        except Exception:  # noqa: BLE001 — 双保险（fetch_and_store 内部已分层降级）
            logger.exception(f"minute_kline {market} 未捕获异常，跳过本市场")
            counts[market] = 0

    # 第二阶段：缺口检测 + 窗口期内补拉（漏采即永久丢失，近 7 天可救）。
    # 与当日采集同样按市场隔离降级。
    for market, symbols in groups.items():
        try:
            filled = await backfill_missing_days(market, symbols, day)
            if filled:
                logger.info(f"minute_kline {market} 补回 {filled} 个缺口日")
        except Exception:  # noqa: BLE001
            logger.exception(f"minute_kline {market} 缺口补拉失败")

    logger.info(
        "=== minute kline job done: "
        + ", ".join(f"{m}={c}" for m, c in counts.items())
        + " ==="
    )
    return counts
