"""APScheduler 定时任务注册"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.jobs.daily_kline import markets_needing_full_init
from app.jobs.registry import run_registered_job

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

_KLINE_MARKETS = ("CN", "HK", "US")
_DAILY_MARKET_JOB_OPTIONS = {
    "coalesce": True,
    "max_instances": 1,
    # 主机短暂休眠或事件循环受阻时仍补跑盘后任务，避免直接等到下一交易日。
    "misfire_grace_time": 6 * 60 * 60,
}


# cron 错峰包装（APScheduler 只识别 coroutine function，lambda 返回协程不会被 await，必须用 async def）
async def _daily_kline_cn_hk() -> None:
    # CN 日K 主源为同花顺 dump（一次请求全市场近 10 交易日），HK 仍走 TickFlow
    await run_registered_job("hithink_daily_k_dump")
    await run_registered_job("daily_kline", markets=("HK",))
    await run_registered_job("movers_cn")


async def _daily_kline_us() -> None:
    await run_registered_job("daily_kline", markets=("US",))


async def _daily_cn_movers() -> None:
    await run_registered_job("movers_cn")


async def _realtime_quotes() -> None:
    await run_registered_job("realtime_quotes")


async def _indices_cn() -> None:
    await run_registered_job("indices", markets=("CN",))


async def _indices_hk_asia() -> None:
    await run_registered_job("indices", markets=("HK", "JP"))


async def _indices_eu() -> None:
    await run_registered_job("indices", markets=("EU",))


async def _indices_us() -> None:
    await run_registered_job("indices", markets=("US", "VOL"))


async def _movers() -> None:
    await run_registered_job("movers")


async def _news() -> None:
    await run_registered_job("news")


async def _macro() -> None:
    await run_registered_job("macro")


async def _adjust_factors() -> None:
    await run_registered_job("adjust_factors")


async def _economic_calendar() -> None:
    await run_registered_job("economic_calendar")


async def _earnings_calendar() -> None:
    await run_registered_job("earnings_calendar")


async def _fundamentals() -> None:
    await run_registered_job("fundamentals")


async def _analyst_consensus() -> None:
    await run_registered_job("analyst_consensus")


async def _board_heat() -> None:
    await run_registered_job("board_heat")


async def _akshare_news() -> None:
    await run_registered_job("akshare_news")


async def _news_score() -> None:
    await run_registered_job("news_score")


async def _board_map() -> None:
    await run_registered_job("board_map")


async def _board_sentiment() -> None:
    await run_registered_job("board_sentiment")


async def _fund_flow() -> None:
    await run_registered_job("fund_flow")


async def _technical_indicators() -> None:
    await run_registered_job("technical_indicators")


async def _daily_valuation() -> None:
    await run_registered_job("daily_valuation")


async def _instrument_names() -> None:
    await run_registered_job("instrument_names")


async def _announcements() -> None:
    await run_registered_job("announcements")


async def _research_reports() -> None:
    await run_registered_job("research_reports")


async def _market_breadth() -> None:
    await run_registered_job("market_breadth")


async def _market_breadth_global() -> None:
    await run_registered_job("market_breadth_global")


async def _macro_assets() -> None:
    await run_registered_job("macro_assets")


async def _minute_kline() -> None:
    await run_registered_job("minute_kline")


async def _minute_delta_compact() -> None:
    await run_registered_job("minute_delta_compact")


async def _cleanup() -> None:
    await run_registered_job("cleanup")


async def start_scheduler() -> None:
    """启动调度器 + 立即触发一次所有 job（首次启动）"""
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = AsyncIOScheduler()

    # 日 K 线：CN 同花顺 dump；HK/US 用 TickFlow universe + Oracle OpenBB/yfinance。
    # A 股/港股 08:30 UTC、美股 21:30 UTC。
    _scheduler.add_job(
        _daily_kline_cn_hk,
        CronTrigger(hour=8, minute=30, timezone="UTC"),
        id="daily_kline_cn_hk",
        replace_existing=True,
        **_DAILY_MARKET_JOB_OPTIONS,
    )
    _scheduler.add_job(
        _daily_kline_us,
        CronTrigger(hour=21, minute=30, timezone="UTC"),
        id="daily_kline_us",
        replace_existing=True,
        **_DAILY_MARKET_JOB_OPTIONS,
    )

    # 实时报价：每 30 分钟（错峰 0,30，避开其他 akshare job）
    _scheduler.add_job(
        _realtime_quotes,
        CronTrigger(minute="0,30", timezone="UTC"),
        id="realtime_quotes",
        replace_existing=True,
    )

    # 指数历史按当地收盘拆分，避免 A/港股等到北京时间次日才更新。
    # JP 与 HK 同批；VIX、商品和 BTC 跟随 US 批次。纽约时区会自动处理夏令时。
    _scheduler.add_job(
        _indices_cn,
        CronTrigger(hour=8, minute=0, timezone="UTC"),
        id="indices_cn",
        replace_existing=True,
        **_DAILY_MARKET_JOB_OPTIONS,
    )
    _scheduler.add_job(
        _indices_hk_asia,
        CronTrigger(hour=8, minute=45, timezone="UTC"),
        id="indices_hk_asia",
        replace_existing=True,
        **_DAILY_MARKET_JOB_OPTIONS,
    )
    _scheduler.add_job(
        _indices_eu,
        CronTrigger(hour=18, minute=0, timezone="UTC"),
        id="indices_eu",
        replace_existing=True,
        **_DAILY_MARKET_JOB_OPTIONS,
    )
    _scheduler.add_job(
        _indices_us,
        CronTrigger(hour=17, minute=30, timezone="America/New_York"),
        id="indices_us",
        replace_existing=True,
        **_DAILY_MARKET_JOB_OPTIONS,
    )

    # 涨跌榜：每 5 分钟
    _scheduler.add_job(
        _movers,
        CronTrigger(minute="*/5", timezone="UTC"),
        id="movers",
        replace_existing=True,
    )
    _scheduler.add_job(
        _daily_cn_movers,
        CronTrigger(hour=9, minute=10, timezone="UTC"),
        id="movers_cn",
        replace_existing=True,
    )

    # 新闻：每 30 分钟
    _scheduler.add_job(
        _news,
        CronTrigger(minute="*/30", timezone="UTC"),
        id="news",
        replace_existing=True,
    )

    # 宏观数据：每天 06:00 UTC
    _scheduler.add_job(
        _macro,
        CronTrigger(hour=6, minute=0, timezone="UTC"),
        id="macro",
        replace_existing=True,
    )

    # 复权因子每日增量：09:30 UTC（日K 08:30 之后）。只通过同花顺单标的
    # REST 扫短窗口，局部重算受影响标的；全市场事件 dump 仅手动初始化一次。
    _scheduler.add_job(
        _adjust_factors,
        CronTrigger(hour=9, minute=30, timezone="UTC"),
        id="adjust_factors",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    # A 股日级估值：同花顺 100 只/批，全市场约 55 请求；错开日K与复权任务。
    _scheduler.add_job(
        _daily_valuation,
        CronTrigger(hour=9, minute=15, timezone="UTC"),
        id="daily_valuation",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    # 证券中文名称同步：每天 07:00 UTC（A 股盘前；名称变动低频，日频足够）
    _scheduler.add_job(
        _instrument_names,
        CronTrigger(hour=7, minute=0, timezone="UTC"),
        id="instrument_names",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    # 宏观数据日历：每天 06:30 UTC（FRED → 百度兜底，两源都允许失败）
    _scheduler.add_job(
        _economic_calendar,
        CronTrigger(hour=6, minute=30, timezone="UTC"),
        id="economic_calendar",
        replace_existing=True,
    )

    # 财报日历：每天 12:00 UTC（yfinance 直调，tracked 美股/港股）
    _scheduler.add_job(
        _earnings_calendar,
        CronTrigger(hour=12, minute=0, timezone="UTC"),
        id="earnings_calendar",
        replace_existing=True,
    )

    # 财报/公司信息/资产负债表/现金流量表：每周一 07:00 UTC
    _scheduler.add_job(
        _fundamentals,
        CronTrigger(day_of_week="mon", hour=7, minute=0, timezone="UTC"),
        id="fundamentals",
        replace_existing=True,
    )

    # 分析师共识/目标价：每天 21:00 UTC
    _scheduler.add_job(
        _analyst_consensus,
        CronTrigger(hour=21, minute=0, timezone="UTC"),
        id="analyst_consensus",
        replace_existing=True,
    )

    # 板块行情热度：每 30 分钟（错峰 5,35）
    _scheduler.add_job(
        _board_heat,
        # findb 逐板块拉日线，原每 30 分钟会产生约 400 请求并持续 429；
        # 板块日线盘中无需高频，降为每日 A 股盘后一次。
        CronTrigger(hour=9, minute=5, timezone="UTC"),
        id="board_heat",
        replace_existing=True,
    )

    # A 股东财新闻：每 30 分钟（错峰 10,40）
    _scheduler.add_job(
        _akshare_news,
        CronTrigger(minute="10,40", timezone="UTC"),
        id="akshare_news",
        replace_existing=True,
    )

    # 新闻情绪打分：每 30 分钟（幂等，只打新增）
    _scheduler.add_job(
        _news_score,
        CronTrigger(minute="*/30", timezone="UTC"),
        id="news_score",
        replace_existing=True,
    )

    # 板块归属映射：每周一 08:00 UTC（成分低频变化）
    _scheduler.add_job(
        _board_map,
        CronTrigger(day_of_week="mon", hour=8, minute=0, timezone="UTC"),
        id="board_map",
        replace_existing=True,
    )

    # 板块舆情聚合：每 30 分钟（错峰 20,50，须在 board_heat 后读 DB）
    _scheduler.add_job(
        _board_sentiment,
        CronTrigger(minute="20,50", timezone="UTC"),
        id="board_sentiment",
        replace_existing=True,
    )

    # 个股资金流向榜：每 5 分钟（交易时段有效，空结果不写库）
    _scheduler.add_job(
        _fund_flow,
        # findb 免费/个人配额无法承受每 5 分钟；降为每小时，避免与板块任务互相挤占。
        CronTrigger(minute=25, timezone="UTC"),
        id="fund_flow",
        replace_existing=True,
    )

    # 技术指标：每天 09:00 / 22:00 UTC（日 K job 之后，本地计算）
    _scheduler.add_job(
        _technical_indicators,
        CronTrigger(hour=22, minute=0, timezone="UTC"),
        id="technical_indicators_us",
        replace_existing=True,
    )
    _scheduler.add_job(
        _technical_indicators,
        CronTrigger(hour=9, minute=0, timezone="UTC"),
        id="technical_indicators_cn",
        replace_existing=True,
    )

    # A 股公告：每天 10:30 UTC（东财全市场公告过滤 tracked；当天空则试前一自然日）
    _scheduler.add_job(
        _announcements,
        CronTrigger(hour=10, minute=30, timezone="UTC"),
        id="announcements",
        replace_existing=True,
    )

    # A 股券商研报：每周一 09:00 UTC（30 只串行限速，只留近 90 天）
    _scheduler.add_job(
        _research_reports,
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="UTC"),
        id="research_reports",
        replace_existing=True,
    )

    # 市场宽度：每 30 分钟（错峰 15,45；legu 实时快照，UPSERT 当天行）
    _scheduler.add_job(
        _market_breadth,
        CronTrigger(minute="15,45", timezone="UTC"),
        id="market_breadth",
        replace_existing=True,
    )

    # US/HK 市场宽度（日K 自算）：每天 09:05 与 22:05 UTC（各自日K job 后 35 分钟）
    _scheduler.add_job(
        _market_breadth_global,
        CronTrigger(hour=9, minute=5, timezone="UTC"),
        id="market_breadth_global_cn_hk",
        replace_existing=True,
    )
    _scheduler.add_job(
        _market_breadth_global,
        CronTrigger(hour=22, minute=5, timezone="UTC"),
        id="market_breadth_global_us",
        replace_existing=True,
    )

    # 宏观资产/收益率曲线：每天 21:30 UTC（美元指数/离岸人民币/ETF + treasury_rates）
    _scheduler.add_job(
        _macro_assets,
        CronTrigger(hour=21, minute=30, timezone="UTC"),
        id="macro_assets",
        replace_existing=True,
    )

    # 数据清理：每天 03:00 UTC
    _scheduler.add_job(
        _cleanup,
        CronTrigger(hour=3, minute=0, timezone="UTC"),
        id="cleanup",
        replace_existing=True,
    )

    # 分钟K 采集（冷层）：美股盘后纽约 17:45（日K/宏观资产之后）；一次任务
    # 按 CN/HK/US 顺序循环追赶 findb 基线后的全部已知交易日缺口。
    _scheduler.add_job(
        _minute_kline,
        CronTrigger(hour=17, minute=45, timezone="America/New_York"),
        id="minute_kline",
        replace_existing=True,
        **_DAILY_MARKET_JOB_OPTIONS,
    )
    _scheduler.add_job(
        _minute_delta_compact,
        CronTrigger(day=2, hour=4, minute=30, timezone="UTC"),
        id="minute_delta_compact",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=12 * 60 * 60,
    )

    _scheduler.start()
    logger.info("Scheduler started")

    # 首次启动立即触发一轮（后台任务，不阻塞 API 就绪；页面优雅降级，数据随后补齐）
    asyncio.create_task(_initial_fetch())


async def _initial_fetch() -> None:
    """启动后后台跑一轮所有 job（首启不用等 cron）"""
    logger.info("=== initial fetch ===")
    # 日K 放后台串行预热：健康市场先增量，缺口市场再全量，避免任一市场
    # 需要全量时把其他市场的启动增量一起跳过。
    full_markets = await markets_needing_full_init()
    daily_kline_task = asyncio.create_task(
        _initial_daily_kline_fetch(full_markets)
    )
    await run_registered_job("indices", trigger="startup")
    await run_registered_job("realtime_quotes", trigger="startup")
    await run_registered_job("movers", trigger="startup")
    await run_registered_job("macro", trigger="startup")
    await run_registered_job("economic_calendar", trigger="startup")
    await run_registered_job("earnings_calendar", trigger="startup")
    await run_registered_job("news", trigger="startup")
    # findb 板块日线为逐板块请求，启动即跑会与报价/资金流争抢配额；按每日 cron 即可。
    await run_registered_job("akshare_news", trigger="startup")
    await run_registered_job("news_score", trigger="startup")
    # findb 资金流按小时 cron；启动预热不额外抢占配额。
    await run_registered_job("board_map", trigger="startup")
    await run_registered_job("board_sentiment", trigger="startup")
    await run_registered_job("fundamentals", trigger="startup")
    await run_registered_job("analyst_consensus", trigger="startup")
    await run_registered_job("announcements", trigger="startup")
    await run_registered_job("research_reports", trigger="startup")
    await run_registered_job("market_breadth", trigger="startup")
    await run_registered_job("macro_assets", trigger="startup")
    await run_registered_job("cleanup", trigger="startup")

    try:
        await daily_kline_task
    except Exception:  # noqa: BLE001 — 日K失败不阻断其余预热，依赖任务本轮跳过
        logger.exception("initial daily kline fetch failed; dependent jobs skipped")
    else:
        # 这三项都读取 daily_prices，必须在启动日K写库完成后执行。
        await run_registered_job("technical_indicators", trigger="startup")
        await run_registered_job("market_breadth_global", trigger="startup")
        await run_registered_job("movers_cn", trigger="startup")
    logger.info("=== initial fetch done ===")


async def _initial_daily_kline_fetch(full_markets: tuple[str, ...]) -> None:
    """启动预热：健康市场增量与缺口市场全量均不遗漏。

    CN 日K 主源为同花顺 dump（健康 → 10 日增量；缺口 → 10 年全量），
    HK/US 用 TickFlow universe + OpenBB/yfinance（增量 5 天 / 全量 250 天）。
    """
    # CN 由同花顺覆盖，从 TickFlow 的 markets 里剥出来单独走 hithink dump
    tf_incremental = tuple(
        market for market in _KLINE_MARKETS
        if market not in full_markets and market != "CN"
    )
    tf_full = tuple(market for market in full_markets if market != "CN")

    if "CN" in full_markets:
        await run_registered_job("hithink_daily_k_dump_full", trigger="startup")
    else:
        await run_registered_job("hithink_daily_k_dump", trigger="startup")

    if tf_incremental:
        await run_registered_job(
            "daily_kline", trigger="startup", markets=tf_incremental
        )
    if tf_full:
        await run_registered_job(
            "daily_kline_full", trigger="startup", markets=tf_full
        )


def scheduler_jobs_snapshot() -> dict[str, dict]:
    """返回调度任务的下一次运行时间；同一业务多 cron 时取最近一次。"""
    if _scheduler is None:
        return {}

    aliases = {
        "daily_kline_cn_hk": "daily_kline",
        "daily_kline_us": "daily_kline",
        "indices_cn": "indices",
        "indices_hk_asia": "indices",
        "indices_eu": "indices",
        "indices_us": "indices",
        "technical_indicators_cn": "technical_indicators",
        "technical_indicators_us": "technical_indicators",
        "market_breadth_global_cn_hk": "market_breadth_global",
        "market_breadth_global_us": "market_breadth_global",
    }
    selected: dict[str, tuple[str, datetime | None]] = {}
    for scheduled in _scheduler.get_jobs():
        business_id = aliases.get(scheduled.id, scheduled.id)
        next_run = scheduled.next_run_time
        current = selected.get(business_id)
        if (
            current is None
            or (
                next_run is not None
                and (
                    current[1] is None
                    or next_run < current[1]
                )
            )
        ):
            selected[business_id] = (scheduled.id, next_run)
    return {
        business_id: {
            "scheduler_id": scheduler_id,
            "next_run_at": next_run.isoformat() if next_run else None,
        }
        for business_id, (scheduler_id, next_run) in selected.items()
    }


async def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
