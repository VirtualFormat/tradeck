"""市场宽度（A 股涨跌家数，乐咕乐股实时快照，直调 akshare，写入 market_breadth）

按日快照模型：同日重跑 UPSERT 覆盖当天行。
legu 接口实测返回 12 项（item/value 两列）：上涨/涨停/真实涨停/st st*涨停/
下跌/跌停/真实跌停/st st*跌停/平盘/停牌/活跃度/统计日期。
st st*涨停/跌停 不单独建列（真实涨停已剔 ST）；legu 无成交额字段。
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.datasource import call_akshare
from app.db import get_pool

logger = logging.getLogger(__name__)

# legu item → market_breadth 列（精确匹配，避免「真实涨停」误命中「涨停」）
_ITEM_MAP = {
    "上涨": "up_count",
    "下跌": "down_count",
    "平盘": "flat_count",
    "涨停": "limit_up_count",
    "跌停": "limit_down_count",
    "真实涨停": "real_limit_up_count",
    "真实跌停": "real_limit_down_count",
    "停牌": "suspended_count",
}


def _i(v: Any) -> int | None:
    try:
        return int(float(str(v).strip().rstrip("%"))) if v is not None else None
    except (TypeError, ValueError):
        return None


def _f(v: Any) -> Decimal | None:
    """活跃度数值 → Decimal（float 传 NUMERIC 无标度列会存二进制长尾，Decimal 精确）"""
    if v is None:
        return None
    try:
        return Decimal(str(v).strip().rstrip("%"))
    except InvalidOperation:
        return None


def _parse_stat_date(v: Any) -> date | None:
    """legu 统计日期（如 2026-07-24 或 20260724）→ date，失败返回 None"""
    if not v:
        return None
    s = str(v).strip().replace("-", "")[:8]
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, TypeError):
        return None


async def run_market_breadth_job() -> int:
    """定时任务：拉 legu 市场活跃度快照（每 30 分钟），UPSERT 当天行"""
    logger.info("=== market breadth job start ===")
    import akshare as ak

    def fetch():
        return ak.stock_market_activity_legu()

    try:
        df = await call_akshare(fetch)
    except Exception as e:
        logger.warning(f"akshare market breadth failed: {e}")
        return 0
    if df is None or df.empty:
        logger.warning("market breadth 为空（非交易时段或接口受限），保留旧快照")
        return 0

    values: dict[str, int | Decimal | None] = {}
    stat_date: date | None = None
    for _, r in df.iterrows():
        item = str(r.get("item") or "").strip()
        col = _ITEM_MAP.get(item)
        if col:
            values[col] = _i(r.get("value"))
        elif item == "活跃度":
            values["activity_rate"] = _f(r.get("value"))
        elif item == "统计日期":
            stat_date = _parse_stat_date(r.get("value"))
    if not values:
        logger.warning("market breadth 无有效项，跳过写库")
        return 0

    # 以 legu 统计日期为准，拿不到则用当天（同日重跑覆盖同一行）
    snapshot_date = stat_date or date.today()

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO market_breadth
                (date, market, up_count, down_count, flat_count,
                 limit_up_count, limit_down_count,
                 real_limit_up_count, real_limit_down_count,
                 suspended_count, activity_rate, source, fetched_at)
            VALUES ($1, 'CN', $2, $3, $4, $5, $6, $7, $8, $9, $10, 'legu', NOW())
            ON CONFLICT (date, market) DO UPDATE SET
                up_count = EXCLUDED.up_count,
                down_count = EXCLUDED.down_count,
                flat_count = EXCLUDED.flat_count,
                limit_up_count = EXCLUDED.limit_up_count,
                limit_down_count = EXCLUDED.limit_down_count,
                real_limit_up_count = EXCLUDED.real_limit_up_count,
                real_limit_down_count = EXCLUDED.real_limit_down_count,
                suspended_count = EXCLUDED.suspended_count,
                activity_rate = EXCLUDED.activity_rate,
                source = EXCLUDED.source,
                fetched_at = NOW()
            """,
            snapshot_date,
            values.get("up_count"),
            values.get("down_count"),
            values.get("flat_count"),
            values.get("limit_up_count"),
            values.get("limit_down_count"),
            values.get("real_limit_up_count"),
            values.get("real_limit_down_count"),
            values.get("suspended_count"),
            values.get("activity_rate"),
        )
    logger.info("=== market breadth job done: 1 rows ===")
    return 1
