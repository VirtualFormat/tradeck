"""银河星耀数智 AmazingData 进程隔离门面。

AmazingData/tgw 是闭源同步 SDK，网络调用可能永久阻塞，native 扩展也可能
直接崩溃。它不能在 collector 进程内 import 或通过 ``asyncio.to_thread``
执行：线程超时后无法杀死，仍会占用单点登录和线程池。

本门面把 SDK 完整隔离在一个长期存活的 spawn 子进程中：
- 子进程独占唯一登录连接，所有请求串行执行；
- 调用有硬超时，超时/崩溃时终止整个 worker，collector 不受影响；
- 下一次请求自动启动干净 worker 并重新登录；
- 未安装 wheel、非 x86-64、未配置凭证时返回空结果。
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import multiprocessing
import platform
from datetime import date, datetime, timedelta
from multiprocessing.connection import Connection
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_START_TIMEOUT = 20.0
_QUERY_TIMEOUT = 45.0
_CACHE_PATH = "/tmp/amazingdata-cache"
_worker_lock = asyncio.Lock()
_worker_process: multiprocessing.Process | None = None
_worker_connection: Connection | None = None


def _configured() -> bool:
    return bool(
        settings.AD_USERNAME
        and settings.AD_PASSWORD
        and settings.AD_HOST
        and settings.AD_PORT
    )


def available() -> bool:
    """本机架构、wheel 和凭证均满足时返回 True；不 import native SDK。"""
    return (
        settings.AMAZINGDATA_ENABLED
        and
        platform.machine().lower() in {"x86_64", "amd64"}
        and importlib.util.find_spec("AmazingData") is not None
        and _configured()
    )


def _to_ad_code(symbol: str) -> str:
    """tradeck symbol → AmazingData 代码。"""
    sym = symbol.strip().upper()
    if sym.endswith(".SS"):
        return sym[:-3] + ".SH"
    return sym


def _yyyymmdd(value: Any) -> int:
    """date/datetime/str → SDK 使用的 YYYYMMDD 整数。"""
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.year * 10000 + value.month * 100 + value.day
    return int(str(value).replace("-", "")[:8])


def _records(df: Any) -> list[dict[str, Any]]:
    """DataFrame → 可跨进程传输的基础类型记录。"""
    if df is None or getattr(df, "empty", True):
        return []
    rows: list[dict[str, Any]] = []
    for index, row in df.iterrows():
        item = {str(key): value for key, value in row.items()}
        item["_index"] = index
        rows.append(item)
    return rows


def _worker_main(connection: Connection, credentials: dict[str, Any]) -> None:
    """子进程入口：唯一允许 import/call AmazingData 的位置。"""
    import os

    os.makedirs(_CACHE_PATH, exist_ok=True)
    market_data: Any = None
    base_data: Any = None
    info_data: Any = None
    try:
        import AmazingData as ad  # type: ignore

        ad.login(**credentials)
        connection.send({"ok": True, "event": "ready"})
    except BaseException as exc:
        try:
            connection.send({"ok": False, "error": f"login failed: {exc!r}"})
        finally:
            connection.close()
        return

    def get_market_data() -> Any:
        nonlocal market_data, base_data
        if market_data is not None:
            return market_data
        if base_data is None:
            base_data = ad.BaseData()
        calendar = base_data.get_calendar(data_type="str", market="SH")
        if not calendar:
            raise RuntimeError(
                "get_calendar 未返回交易日历；需核查账号授权、服务端状态和 SDK 版本"
            )
        market_data = ad.MarketData(sorted(int(item) for item in calendar))
        return market_data

    try:
        while True:
            request = connection.recv()
            operation = request.get("operation")
            if operation == "shutdown":
                connection.send({"ok": True, "data": None})
                break
            try:
                if operation == "code_list":
                    if base_data is None:
                        base_data = ad.BaseData()
                    data = base_data.get_code_list(
                        security_type=request.get("security_type", "EXTRA_STOCK_A")
                    )
                elif operation in {"daily_kline", "minute_kline"}:
                    code = request["code"]
                    period = (
                        ad.constant.Period.day.value
                        if operation == "daily_kline"
                        else ad.constant.Period.min1.value
                    )
                    result = get_market_data().query_kline(
                        [code],
                        begin_date=request["begin_date"],
                        end_date=request["end_date"],
                        period=period,
                    )
                    data = _records(result.get(code) if isinstance(result, dict) else None)
                elif operation == "quote":
                    code = request["code"]
                    result = get_market_data().query_snapshot(
                        [code],
                        begin_date=request["date"],
                        end_date=request["date"],
                    )
                    data = _records(result.get(code) if isinstance(result, dict) else None)
                elif operation == "income":
                    if info_data is None:
                        info_data = ad.InfoData()
                    code = request["code"]
                    # begin_date/end_date 是「指定区间」参数组；按手册 4.4，不能
                    # 再与 local_path/is_local 缓存参数组混用。
                    result = info_data.get_income(
                        [code],
                        begin_date=request["begin_date"],
                        end_date=request["end_date"],
                    )
                    frame = result.get(code) if isinstance(result, dict) else result
                    data = _records(frame)
                elif operation == "announcements":
                    if info_data is None:
                        info_data = ad.InfoData()
                    # 公告接口同样使用指定日期区间模式；code_list 必须是列表。
                    result = info_data.get_announcement_stock_list(
                        [request["code"]],
                        begin_date=request["begin_date"],
                        end_date=request["end_date"],
                    )
                    data = _records(result)
                elif operation in {"adjust_factor", "backward_factor"}:
                    if base_data is None:
                        base_data = ad.BaseData()
                    method = (
                        base_data.get_adj_factor
                        if operation == "adjust_factor"
                        else base_data.get_backward_factor
                    )
                    # 因子接口只有缓存参数组；is_local=False 强制服务端刷新。
                    result = method(
                        request["codes"],
                        local_path=_CACHE_PATH,
                        is_local=False,
                    )
                    data = _records(result)
                else:
                    raise ValueError(f"unsupported operation: {operation!r}")
                connection.send({"ok": True, "data": data})
            except BaseException as exc:
                connection.send({"ok": False, "error": repr(exc)})
    except (EOFError, BrokenPipeError):
        pass
    finally:
        try:
            ad.logout(credentials["username"])
        except BaseException:
            pass
        connection.close()


def _worker_credentials() -> dict[str, Any]:
    return {
        "username": settings.AD_USERNAME,
        "password": settings.AD_PASSWORD,
        "host": settings.AD_HOST,
        "port": int(settings.AD_PORT),
    }


def _terminate_worker() -> None:
    """同步终止 worker；可安全重复调用。"""
    global _worker_process, _worker_connection
    connection, process = _worker_connection, _worker_process
    _worker_connection = None
    _worker_process = None
    if connection is not None:
        try:
            connection.close()
        except OSError:
            pass
    if process is None:
        return
    if process.is_alive():
        process.terminate()
        process.join(timeout=2.0)
    if process.is_alive():
        process.kill()
        process.join(timeout=2.0)
    else:
        process.join(timeout=0.1)


async def _receive(connection: Connection, timeout: float) -> dict[str, Any]:
    """等待 pipe 响应但不阻塞事件循环。"""
    ready = await asyncio.to_thread(connection.poll, timeout)
    if not ready:
        raise TimeoutError(f"AmazingData worker timeout after {timeout:.0f}s")
    return await asyncio.to_thread(connection.recv)


async def _ensure_worker() -> bool:
    """启动并握手 worker。调用方须持有 ``_worker_lock``。"""
    global _worker_process, _worker_connection
    if (
        _worker_process is not None
        and _worker_process.is_alive()
        and _worker_connection is not None
    ):
        return True
    _terminate_worker()
    if not available():
        return False

    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=True)
    process = context.Process(
        target=_worker_main,
        args=(child, _worker_credentials()),
        name="amazingdata-worker",
        daemon=True,
    )
    process.start()
    child.close()
    _worker_process = process
    _worker_connection = parent
    try:
        response = await _receive(parent, _START_TIMEOUT)
    except (EOFError, OSError, TimeoutError) as exc:
        logger.warning("AmazingData worker 启动失败: %s", exc)
        _terminate_worker()
        return False
    if not response.get("ok"):
        logger.warning("AmazingData worker 登录失败: %s", response.get("error"))
        _terminate_worker()
        return False
    logger.info("AmazingData worker 已启动并登录")
    return True


async def _request(
    operation: str,
    *,
    timeout: float = _QUERY_TIMEOUT,
    **payload: Any,
) -> Any:
    """串行调用隔离 worker；超时/崩溃即杀进程并返回 None。"""
    async with _worker_lock:
        if not await _ensure_worker():
            return None
        assert _worker_connection is not None
        try:
            _worker_connection.send({"operation": operation, **payload})
            response = await _receive(_worker_connection, timeout)
        except (BrokenPipeError, EOFError, OSError, TimeoutError) as exc:
            logger.warning("AmazingData %s 隔离调用失败: %s", operation, exc)
            _terminate_worker()
            return None
        if not response.get("ok"):
            logger.warning("AmazingData %s 返回失败: %s", operation, response.get("error"))
            return None
        return response.get("data")


async def shutdown() -> None:
    """collector 关闭时回收 worker。"""
    async with _worker_lock:
        _terminate_worker()


async def get_code_list(
    security_type: str = "EXTRA_STOCK_A",
) -> list[str]:
    """取证券代码表。该接口不依赖交易日历，可用于健康检查/覆盖校验。"""
    data = await _request("code_list", security_type=security_type)
    return [str(item) for item in data or []]


async def get_daily_kline(symbol: str, count: int = 365) -> list[dict]:
    """拉单只日 K。失败/超时返回 []。"""
    code = _to_ad_code(symbol)
    end = date.today()
    begin = end - timedelta(days=int(count * 1.6))
    data = await _request(
        "daily_kline",
        code=code,
        begin_date=_yyyymmdd(begin),
        end_date=_yyyymmdd(end),
    )
    rows: list[dict] = []
    for original in data or []:
        item = dict(original)
        index = item.pop("_index", None)
        raw_day = item.pop("kline_time", None) or index
        if isinstance(raw_day, datetime):
            day = raw_day.date()
        elif isinstance(raw_day, date):
            day = raw_day
        else:
            try:
                day = date.fromisoformat(str(raw_day)[:10])
            except (TypeError, ValueError):
                day = None
        if day is None or item.get("close") is None:
            continue
        rows.append({"date": day, **item})
    return rows[-count:]


async def get_minute_kline(
    symbol: str,
    begin: date | str,
    end: date | str,
) -> list[dict]:
    """拉单只 1 分钟 K。失败/超时返回 []。"""
    data = await _request(
        "minute_kline",
        timeout=90.0,
        code=_to_ad_code(symbol),
        begin_date=_yyyymmdd(begin),
        end_date=_yyyymmdd(end),
    )
    rows: list[dict] = []
    for original in data or []:
        item = dict(original)
        raw_time = item.pop("kline_time", None) or item.pop("_index", None)
        if raw_time is None or item.get("close") is None:
            continue
        rows.append({"datetime": raw_time, **item})
    return rows


async def get_quote(symbol: str) -> dict | None:
    """取单只当日最新快照。失败/超时返回 None。"""
    data = await _request(
        "quote", code=_to_ad_code(symbol), date=_yyyymmdd(date.today())
    )
    if not data:
        return None
    row = data[-1]
    return {
        "last": row.get("last"),
        "pre_close": row.get("pre_close"),
        "open": row.get("open"),
        "high": row.get("high"),
        "low": row.get("low"),
        "volume": row.get("volume"),
        "amount": row.get("amount"),
        "bid_price": row.get("bid_price1"),
        "ask_price": row.get("ask_price1") or row.get("offer_price1"),
    }


async def get_income(symbol: str, begin: str, end: str) -> list[dict]:
    """利润表。失败/超时返回 []。"""
    return await _request(
        "income",
        code=_to_ad_code(symbol),
        begin_date=_yyyymmdd(begin),
        end_date=_yyyymmdd(end),
    ) or []


async def get_announcements(symbol: str, begin: str, end: str) -> list[dict]:
    """上市公司公告明细。失败/超时返回 []。"""
    return await _request(
        "announcements",
        code=_to_ad_code(symbol),
        begin_date=_yyyymmdd(begin),
        end_date=_yyyymmdd(end),
    ) or []


async def get_adjustment_factors(
    symbol: str,
    *,
    kind: str = "backward",
) -> list[dict]:
    """取单只复权因子。

    kind="backward" 对应 ``get_backward_factor``（累计后复权因子）；
    kind="single" 对应 ``get_adj_factor``（单次复权因子）。失败返回 []。
    """
    if kind not in {"backward", "single"}:
        raise ValueError("kind 必须是 backward / single")
    code = _to_ad_code(symbol)
    operation = "backward_factor" if kind == "backward" else "adjust_factor"
    data = await _request(operation, timeout=90.0, codes=[code])
    rows: list[dict] = []
    for item in data or []:
        factor = item.get(code)
        if factor is None or factor != factor:  # None / NaN
            continue
        raw_day = item.get("_index")
        day = raw_day.date() if isinstance(raw_day, datetime) else raw_day
        rows.append({"date": day, "factor": float(factor)})
    return rows
