"""分钟K 采集 job（4.2a-0 冷层先行）：每日拉当日分钟K，直写冷层 Parquet。

链路：yfinance 1m（库直调）→ quality_gate（minute_bars 质量闸）→
      ColdStorage 写 Parquet 落冷层（year/market 分区 + 文件内 (symbol,ts) 排序）。

范围与现状（D1 实测 2026-08-22）：
- US/HK：yfinance 1m（仅近 7 天窗口）——每日采当日，漏采即永久丢失，缺口检测是生死线。
- A股：免费源（TickFlow 分钟K 付费档 / akshare 东财分钟接口本地被封）暂不可采，
  待付费档或 QMT/iFinD（D2/D3/D4）后接入。

纪律：ts 统一存 UTC epoch 秒；每日幂等（重跑覆盖同分区文件）；本地 yfinance
常被限流（已知坑 #5）——限流时优雅降级记日志，环境正常（VPS）时正常采集。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.cold_storage import get_cold_storage
from app.quality import quality_gate

logger = logging.getLogger(__name__)

# 缺口检测窗口（天）：yfinance 1m 仅近 7 天可拉，超出即永久丢失。
# 每日采集当日后，顺带检测近 N 天缺口并补拉（窗口内可救）。
_GAP_LOOKBACK_DAYS = 7


def _minute_symbols() -> dict[str, list[str]]:
    """按市场分组待采标的（仅 US/HK，A股待付费源）。"""
    from app.constants import TRACKED_SYMBOLS
    from app.markets import pick_market

    groups: dict[str, list[str]] = {"US": [], "HK": []}
    for s in TRACKED_SYMBOLS:
        m = pick_market(s)
        if m not in groups:
            continue
        # 健壮性：港股规范码须为 5 位（不足 5 位的原始码经 to_yahoo_symbol 的
        # lstrip('0').zfill(4) 可能产生非法 yahoo ticker，导致查询不到数据）。
        # 规范约定港股 5 位补零，这里断言兜底，异常代码记日志跳过。
        if m == "HK":
            code = s.split(".")[0]
            if len(code) != 5:
                logger.warning(f"minute_kline 跳过非法港股代码（非 5 位）: {s}")
                continue
        groups[m].append(s)
    return groups


def _fetch_1m(symbols: list[str], day: date | None = None) -> Any:
    """同步拉多只标的 1m（yfinance 库直调）。限流/失败抛异常由调用方降级。

    day=None 拉当日（period='1d'）；指定 day 拉该天（start/end 区间，补拉缺口用，
    仅近 7 天窗口内有效）。auto_adjust=False 保留原始 OHLC（复权另算）。
    """
    import yfinance as yf
    from app.markets import to_yahoo_symbol

    yahoo = [to_yahoo_symbol(s) for s in symbols]
    kwargs: dict[str, Any] = {
        "interval": "1m",
        "progress": False,
        "auto_adjust": False,
    }
    if day is None:
        kwargs["period"] = "1d"
    else:
        # yfinance end 为开区间，+1 天才含当日
        kwargs["start"] = day.isoformat()
        kwargs["end"] = (day + timedelta(days=1)).isoformat()
    return yf.download(yahoo, **kwargs)


def _df_to_rows(df: Any, symbols: list[str], market: str, day: date) -> list[dict[str, Any]]:
    """yfinance 多标的 MultiIndex DataFrame → 分钟K dict 行（ts 为 UTC epoch 秒）。"""
    import pandas as pd

    from app.markets import to_yahoo_symbol

    if df is None or len(df) == 0:
        return []

    rows: list[dict[str, Any]] = []
    is_multi = isinstance(df.columns, pd.MultiIndex)

    def _v(x: Any) -> float | None:
        """NaN/None → None，否则转 float（对齐 amount 的 None 语义，避免 NaN 进 Parquet）。"""
        if x is None:
            return None
        try:
            f = float(x)
        except (TypeError, ValueError):
            return None
        return None if pd.isna(f) else f

    # DataFrame 列是 yahoo 格式（港股 4 位、.SH→.SS），需转换后取数；
    # 写库的 symbol 仍是规范格式（行内 sym），仅取数时用 yahoo 格式定位列
    for sym in symbols:
        yahoo_sym = to_yahoo_symbol(sym)
        try:
            sub = df.xs(yahoo_sym, level=1, axis=1) if is_multi else df
        except (KeyError, ValueError):
            continue
        for ts, r in sub.iterrows():
            close = _v(r.get("Close"))
            if close is None:  # 无 close 的分钟K 行无意义，跳过
                continue
            # 时间戳统一 UTC epoch 秒（yfinance 返回带交易所时区的 DatetimeIndex）
            if hasattr(ts, "tz_convert"):
                ts_utc = ts.tz_convert("UTC") if ts.tzinfo else ts.tz_localize("UTC")
                epoch = int(ts_utc.timestamp())
            else:
                epoch = int(pd.Timestamp(ts, tz="UTC").timestamp())
            rows.append(
                {
                    "symbol": sym,
                    "market": market,
                    "ts": epoch,
                    "open": _v(r.get("Open")),
                    "high": _v(r.get("High")),
                    "low": _v(r.get("Low")),
                    "close": close,
                    "volume": _v(r.get("Volume")),
                    "amount": None,  # yfinance 1m 无成交额，留 None
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

    # ① 拉取（限流/失败优雅降级：记日志返回 0，不抛）。day 传给 _fetch_1m
    # 决定拉当日还是历史某天（补拉）。
    try:
        df = await asyncio.to_thread(_fetch_1m, symbols, day)
    except Exception as e:  # noqa: BLE001 — yfinance 限流/网络，优雅降级
        logger.warning(f"minute_kline {market} 拉取失败（{type(e).__name__}: {e}）")
        return 0

    rows = _df_to_rows(df, symbols, market, day)
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
