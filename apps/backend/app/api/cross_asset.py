"""跨资产总览 + 美债收益率曲线 + 市场内部结构（/global 页数据源）

- GET /api/cross-assets      跨资产总览（股指/商品/汇率/波动率/债券）
- GET /api/yield-curve       美债收益率曲线（最新 / 1 月前 / 1 年前）
- GET /api/yield-curve/spread  10Y-2Y 利差时间序列（bp）
- GET /api/market-internals  市场内部结构比值（RSP/SPY 等 4 组）
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Query
from app.db import get_pool

router = APIRouter()

# ── 跨资产总览的标的定义（按 category 固定顺序输出）──
# (symbol, 名称, category, 来源表)
CROSS_ASSETS = [
    ("^GSPC", "标普500", "equity_index", "index_prices"),
    ("^IXIC", "纳指", "equity_index", "index_prices"),
    ("^DJI", "道指", "equity_index", "index_prices"),
    ("000001.SS", "上证", "equity_index", "index_prices"),
    ("399006.SZ", "创业板指", "equity_index", "index_prices"),
    ("^HSI", "恒指", "equity_index", "index_prices"),
    ("^N225", "日经", "equity_index", "index_prices"),
    ("^STOXX50E", "欧洲50", "equity_index", "index_prices"),
    ("GC=F", "黄金", "commodity", "index_prices"),
    ("CL=F", "WTI原油", "commodity", "index_prices"),
    ("HG=F", "铜", "commodity", "index_prices"),
    ("SI=F", "白银", "commodity", "index_prices"),
    ("BTC-USD", "比特币", "commodity", "index_prices"),
    ("DX-Y.NYB", "美元指数", "fx", "macro_asset_prices"),
    ("USDCNH", "离岸人民币", "fx", "macro_asset_prices"),
    ("^VIX", "VIX恐慌指数", "volatility", "index_prices"),
]

# 变化率参考窗口（天数）
_CHG_WINDOWS = {"chg_1w": 7, "chg_1m": 30, "chg_3m": 91, "chg_1y": 365}

# 收益率曲线期限：(字段名, 展示标签, 月数)
YIELD_TENORS = [
    ("month_1", "1M", 1),
    ("month_3", "3M", 3),
    ("month_6", "6M", 6),
    ("year_1", "1Y", 12),
    ("year_2", "2Y", 24),
    ("year_3", "3Y", 36),
    ("year_5", "5Y", 60),
    ("year_7", "7Y", 84),
    ("year_10", "10Y", 120),
    ("year_20", "20Y", 240),
    ("year_30", "30Y", 360),
]

# 市场内部结构比值对
INTERNAL_PAIRS = [
    ("RSP", "SPY", "等权/市值", "升=普涨健康，降=权重股硬拉"),
    ("IWM", "SPY", "小盘/大盘", "升=风险偏好扩散"),
    ("QQQ", "IVE", "成长/价值", "升=成长风格占优"),
    ("XLK", "XLP", "科技/防御", "升=进攻板块领涨"),
]


def _ref_close(series: list[tuple[date, float]], target: date) -> float | None:
    """series 按 date 降序，返回 <= target 的最近一个收盘。"""
    for d, c in series:
        if d <= target:
            return c
    return None


def _pct(cur: float | None, ref: float | None) -> float | None:
    """变化率 %，任一端缺失返回 None。"""
    if cur is None or ref is None or ref == 0:
        return None
    return (cur / ref - 1) * 100


async def _fetch_series(conn, table: str, symbol: str, limit: int = 400) -> list[tuple[date, float]]:
    """拉单标的收盘价序列（date 降序）。table 只允许白名单值，防注入。"""
    if table not in ("index_prices", "macro_asset_prices"):
        return []
    rows = await conn.fetch(
        f"""
        SELECT date, close FROM {table}
        WHERE symbol = $1 AND close IS NOT NULL
        ORDER BY date DESC LIMIT $2
        """,
        symbol,
        limit,
    )
    return [(r["date"], float(r["close"])) for r in rows]


@router.get("/api/cross-assets")
async def get_cross_assets():
    """跨资产总览：最新价 + 1D/1W/1M/3M/1Y 变化率(%) + 距 MA200 偏离(%)。"""
    pool = await get_pool()
    today = date.today()
    result = []

    async with pool.acquire() as conn:
        for symbol, name, category, table in CROSS_ASSETS:
            series = await _fetch_series(conn, table, symbol)
            if not series:
                continue
            latest_date, close = series[0]
            prev = series[1][1] if len(series) > 1 else None
            item = {
                "symbol": symbol,
                "name": name,
                "category": category,
                "close": close,
                "chg_1d": _pct(close, prev),
                "chg_1w": _pct(close, _ref_close(series, latest_date - timedelta(days=_CHG_WINDOWS["chg_1w"]))),
                "chg_1m": _pct(close, _ref_close(series, latest_date - timedelta(days=_CHG_WINDOWS["chg_1m"]))),
                "chg_3m": _pct(close, _ref_close(series, latest_date - timedelta(days=_CHG_WINDOWS["chg_3m"]))),
                "chg_1y": _pct(close, _ref_close(series, latest_date - timedelta(days=_CHG_WINDOWS["chg_1y"]))),
                "dist_ma200": None,
            }
            ma_window = [c for _, c in series[:200]]
            if ma_window:
                ma200 = sum(ma_window) / len(ma_window)
                if ma200:
                    item["dist_ma200"] = (close / ma200 - 1) * 100
            result.append(item)

        # ── 债券段：美债 10Y / 2Y / 10Y-2Y 利差（chg 为相对 N 天前的差值）──
        yc_rows = await conn.fetch(
            """
            SELECT date, year_2, year_10 FROM yield_curve_rates
            WHERE year_10 IS NOT NULL
            ORDER BY date DESC LIMIT 400
            """
        )
        if yc_rows:
            yc = [(r["date"], float(r["year_10"]), float(r["year_2"]) if r["year_2"] is not None else None) for r in yc_rows]
            latest_date = yc[0][0]

            def _yc_ref(idx: int, target: date):
                """<= target 最近一行的 year_10/year_2（idx: 1=10Y, 2=2Y）。"""
                for row in yc:
                    if row[0] <= target:
                        return row[idx]
                return None

            def _bond_item(symbol: str, name: str, value_fn):
                cur = value_fn(yc[0][1], yc[0][2])
                if cur is None:
                    return None
                item = {
                    "symbol": symbol,
                    "name": name,
                    "category": "bond",
                    "close": cur,
                    "chg_1d": None,
                    "chg_1w": None,
                    "chg_1m": None,
                    "chg_3m": None,
                    "chg_1y": None,
                    "dist_ma200": None,
                }
                # 1D：前一有数据行
                if len(yc) > 1:
                    prev = value_fn(yc[1][1], yc[1][2])
                    item["chg_1d"] = None if prev is None else cur - prev
                for key, days in _CHG_WINDOWS.items():
                    ref_10 = _yc_ref(1, latest_date - timedelta(days=days))
                    ref_2 = _yc_ref(2, latest_date - timedelta(days=days))
                    ref = value_fn(ref_10, ref_2)
                    item[key] = None if ref is None else cur - ref
                return item

            # 10Y / 2Y：close 单位 %（小数值 ×100），chg 为百分点差
            for sym, name, col in (("US10Y", "美债10Y", 1), ("US2Y", "美债2Y", 2)):
                it = _bond_item(sym, name, lambda y10, y2, c=col: (y10 if c == 1 else y2) * 100 if (y10 if c == 1 else y2) is not None else None)
                if it:
                    result.append(it)
            # 利差：close 单位 bp（(10Y-2Y) ×10000），chg 为 bp 差
            it = _bond_item(
                "US10Y2Y",
                "10Y-2Y利差",
                lambda y10, y2: (y10 - y2) * 10000 if y10 is not None and y2 is not None else None,
            )
            if it:
                result.append(it)

    return result


@router.get("/api/yield-curve")
async def get_yield_curve():
    """美债收益率曲线：11 期限 × (最新 / 30 天前 / 365 天前)，单位 %（库中小数值 ×100）。"""
    pool = await get_pool()
    cols = ", ".join(t[0] for t in YIELD_TENORS)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT date, {cols} FROM yield_curve_rates ORDER BY date DESC LIMIT 400"
        )
    if not rows:
        return []

    latest = rows[0]
    today = latest["date"]

    def _row_before(target: date):
        for r in rows:
            if r["date"] <= target:
                return r
        return None

    ago_1m = _row_before(today - timedelta(days=30))
    ago_1y = _row_before(today - timedelta(days=365))

    def _val(row, col):
        if row is None or row[col] is None:
            return None
        return float(row[col]) * 100

    return [
        {
            "tenor": label,
            "months": months,
            "latest": _val(latest, col),
            "ago_1m": _val(ago_1m, col),
            "ago_1y": _val(ago_1y, col),
        }
        for col, label, months in YIELD_TENORS
    ]


@router.get("/api/yield-curve/spread")
async def get_yield_spread(days: int = Query(365, ge=1, le=3650)):
    """10Y-2Y 利差时间序列（bp，按 date 升序）。"""
    pool = await get_pool()
    start = date.today() - timedelta(days=days)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT date, year_2, year_10 FROM yield_curve_rates
            WHERE date >= $1 AND year_10 IS NOT NULL AND year_2 IS NOT NULL
            ORDER BY date ASC
            """,
            start,
        )
    return [
        {
            "date": r["date"].isoformat(),
            "spread_bp": (float(r["year_10"]) - float(r["year_2"])) * 10000,
        }
        for r in rows
    ]


@router.get("/api/market-internals")
async def get_market_internals(days: int = Query(180, ge=30, le=1000)):
    """市场内部结构：4 组比值（日期对齐相除），含 1M/3M 比值变化 %。"""
    pool = await get_pool()
    start = date.today() - timedelta(days=days)
    result = []

    async with pool.acquire() as conn:
        for num, den, label, note in INTERNAL_PAIRS:
            rows = await conn.fetch(
                """
                SELECT a.date AS date, a.close AS num_close, b.close AS den_close
                FROM macro_asset_prices a
                JOIN macro_asset_prices b ON b.symbol = $2 AND b.date = a.date
                WHERE a.symbol = $1 AND a.date >= $3
                  AND a.close IS NOT NULL AND b.close IS NOT NULL AND b.close <> 0
                ORDER BY a.date ASC
                """,
                num,
                den,
                start,
            )
            if not rows:
                continue
            series = [
                {"date": r["date"].isoformat(), "ratio": float(r["num_close"]) / float(r["den_close"])}
                for r in rows
            ]
            # 降序副本用于取参考点
            desc = [(r["date"], float(r["num_close"]) / float(r["den_close"])) for r in reversed(rows)]
            latest_date, current = desc[0]
            result.append(
                {
                    "pair": f"{num}/{den}",
                    "label": label,
                    "note": note,
                    "current": current,
                    "chg_1m": _pct(current, _ref_close(desc, latest_date - timedelta(days=30))),
                    "chg_3m": _pct(current, _ref_close(desc, latest_date - timedelta(days=91))),
                    "series": series,
                }
            )

    return result
