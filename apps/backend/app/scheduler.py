"""APScheduler 定时任务注册"""
from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.jobs.cleanup import run_cleanup_job
from app.jobs.board_heat import run_board_heat_job
from app.jobs.board_map import run_board_map_job
from app.jobs.board_sentiment import run_board_sentiment_job
from app.jobs.akshare_news import run_akshare_news_job
from app.jobs.fund_flow import run_fund_flow_job
from app.jobs.news_score import run_news_score_job
from app.jobs.daily_kline import needs_full_init, run_daily_kline_job
from app.jobs.analyst_consensus import run_analyst_consensus_job
from app.jobs.fundamentals import run_fundamentals_job
from app.jobs.indices import run_indices_job
from app.jobs.macro import run_macro_job
from app.jobs.movers import run_movers_job
from app.jobs.news import run_news_job
from app.jobs.earnings_calendar import run_earnings_calendar_job
from app.jobs.economic_calendar import run_economic_calendar_job
from app.jobs.announcements import run_announcements_job
from app.jobs.research_reports import run_research_reports_job
from app.jobs.market_breadth import run_market_breadth_job
from app.jobs.market_breadth_global import run_market_breadth_global_job
from app.jobs.realtime_quotes import run_realtime_quotes_job
from app.jobs.technical_indicators import run_technical_indicators_job
from app.jobs.macro_assets import run_macro_assets_job

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


# cron 错峰包装（APScheduler 只识别 coroutine function，lambda 返回协程不会被 await，必须用 async def）
async def _daily_kline_cn_hk() -> None:
    await run_daily_kline_job(markets=("CN", "HK"))


async def _daily_kline_us() -> None:
    await run_daily_kline_job(markets=("US",))


async def start_scheduler() -> None:
    """启动调度器 + 立即触发一次所有 job（首次启动）"""
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = AsyncIOScheduler()

    # 日 K 线（TickFlow universe 全市场批量）：A 股/港股 08:30 UTC、美股 21:30 UTC（各自收盘后）
    _scheduler.add_job(
        _daily_kline_cn_hk,
        CronTrigger(hour=8, minute=30, timezone="UTC"),
        id="daily_kline_cn_hk",
        replace_existing=True,
    )
    _scheduler.add_job(
        _daily_kline_us,
        CronTrigger(hour=21, minute=30, timezone="UTC"),
        id="daily_kline_us",
        replace_existing=True,
    )

    # 实时报价：每 30 分钟（错峰 0,30，避开其他 akshare job）
    _scheduler.add_job(
        run_realtime_quotes_job,
        CronTrigger(minute="0,30", timezone="UTC"),
        id="realtime_quotes",
        replace_existing=True,
    )

    # 指数历史：每天 17:00 UTC
    _scheduler.add_job(
        run_indices_job,
        CronTrigger(hour=17, minute=0, timezone="UTC"),
        id="indices",
        replace_existing=True,
    )

    # 涨跌榜：每 5 分钟
    _scheduler.add_job(
        run_movers_job,
        CronTrigger(minute="*/5", timezone="UTC"),
        id="movers",
        replace_existing=True,
    )

    # 新闻：每 30 分钟
    _scheduler.add_job(
        run_news_job,
        CronTrigger(minute="*/30", timezone="UTC"),
        id="news",
        replace_existing=True,
    )

    # 宏观数据：每天 06:00 UTC
    _scheduler.add_job(
        run_macro_job,
        CronTrigger(hour=6, minute=0, timezone="UTC"),
        id="macro",
        replace_existing=True,
    )

    # 宏观数据日历：每天 06:30 UTC（FRED → 百度兜底，两源都允许失败）
    _scheduler.add_job(
        run_economic_calendar_job,
        CronTrigger(hour=6, minute=30, timezone="UTC"),
        id="economic_calendar",
        replace_existing=True,
    )

    # 财报日历：每天 12:00 UTC（yfinance 直调，tracked 美股/港股）
    _scheduler.add_job(
        run_earnings_calendar_job,
        CronTrigger(hour=12, minute=0, timezone="UTC"),
        id="earnings_calendar",
        replace_existing=True,
    )

    # 财报/公司信息/资产负债表/现金流量表：每周一 07:00 UTC
    _scheduler.add_job(
        run_fundamentals_job,
        CronTrigger(day_of_week="mon", hour=7, minute=0, timezone="UTC"),
        id="fundamentals",
        replace_existing=True,
    )

    # 分析师共识/目标价：每天 21:00 UTC
    _scheduler.add_job(
        run_analyst_consensus_job,
        CronTrigger(hour=21, minute=0, timezone="UTC"),
        id="analyst_consensus",
        replace_existing=True,
    )

    # 板块行情热度：每 30 分钟（错峰 5,35）
    _scheduler.add_job(
        run_board_heat_job,
        CronTrigger(minute="5,35", timezone="UTC"),
        id="board_heat",
        replace_existing=True,
    )

    # A 股东财新闻：每 30 分钟（错峰 10,40）
    _scheduler.add_job(
        run_akshare_news_job,
        CronTrigger(minute="10,40", timezone="UTC"),
        id="akshare_news",
        replace_existing=True,
    )

    # 新闻情绪打分：每 30 分钟（幂等，只打新增）
    _scheduler.add_job(
        run_news_score_job,
        CronTrigger(minute="*/30", timezone="UTC"),
        id="news_score",
        replace_existing=True,
    )

    # 板块归属映射：每周一 08:00 UTC（成分低频变化）
    _scheduler.add_job(
        run_board_map_job,
        CronTrigger(day_of_week="mon", hour=8, minute=0, timezone="UTC"),
        id="board_map",
        replace_existing=True,
    )

    # 板块舆情聚合：每 30 分钟（错峰 20,50，须在 board_heat 后读 DB）
    _scheduler.add_job(
        run_board_sentiment_job,
        CronTrigger(minute="20,50", timezone="UTC"),
        id="board_sentiment",
        replace_existing=True,
    )

    # 个股资金流向榜：每 5 分钟（交易时段有效，空结果不写库）
    _scheduler.add_job(
        run_fund_flow_job,
        CronTrigger(minute="*/5", timezone="UTC"),
        id="fund_flow",
        replace_existing=True,
    )

    # 技术指标：每天 09:00 / 22:00 UTC（日 K job 之后，本地计算）
    _scheduler.add_job(
        run_technical_indicators_job,
        CronTrigger(hour=22, minute=0, timezone="UTC"),
        id="technical_indicators_us",
        replace_existing=True,
    )
    _scheduler.add_job(
        run_technical_indicators_job,
        CronTrigger(hour=9, minute=0, timezone="UTC"),
        id="technical_indicators_cn",
        replace_existing=True,
    )

    # A 股公告：每天 10:30 UTC（东财全市场公告过滤 tracked；当天空则试前一自然日）
    _scheduler.add_job(
        run_announcements_job,
        CronTrigger(hour=10, minute=30, timezone="UTC"),
        id="announcements",
        replace_existing=True,
    )

    # A 股券商研报：每周一 09:00 UTC（30 只串行限速，只留近 90 天）
    _scheduler.add_job(
        run_research_reports_job,
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="UTC"),
        id="research_reports",
        replace_existing=True,
    )

    # 市场宽度：每 30 分钟（错峰 15,45；legu 实时快照，UPSERT 当天行）
    _scheduler.add_job(
        run_market_breadth_job,
        CronTrigger(minute="15,45", timezone="UTC"),
        id="market_breadth",
        replace_existing=True,
    )

    # US/HK 市场宽度（日K 自算）：每天 09:05 与 22:05 UTC（各自日K job 后 35 分钟）
    _scheduler.add_job(
        run_market_breadth_global_job,
        CronTrigger(hour=9, minute=5, timezone="UTC"),
        id="market_breadth_global_cn_hk",
        replace_existing=True,
    )
    _scheduler.add_job(
        run_market_breadth_global_job,
        CronTrigger(hour=22, minute=5, timezone="UTC"),
        id="market_breadth_global_us",
        replace_existing=True,
    )

    # 宏观资产/收益率曲线：每天 21:30 UTC（美元指数/离岸人民币/ETF + treasury_rates）
    _scheduler.add_job(
        run_macro_assets_job,
        CronTrigger(hour=21, minute=30, timezone="UTC"),
        id="macro_assets",
        replace_existing=True,
    )

    # 数据清理：每天 03:00 UTC
    _scheduler.add_job(
        run_cleanup_job,
        CronTrigger(hour=3, minute=0, timezone="UTC"),
        id="cleanup",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("Scheduler started")

    # 首次启动立即触发一轮（后台任务，不阻塞 API 就绪；页面优雅降级，数据随后补齐）
    asyncio.create_task(_initial_fetch())


async def _initial_fetch() -> None:
    """启动后后台跑一轮所有 job（首启不用等 cron）"""
    logger.info("=== initial fetch ===")
    # 日K：未初始化（daily_prices < 100 万行）则全量拉一次——放最前，与其余预热并行（~30-60 分钟）
    if await needs_full_init():
        asyncio.create_task(run_daily_kline_job(full=True))
    await run_indices_job()
    await run_realtime_quotes_job()
    await run_movers_job()
    await run_macro_job()
    await run_economic_calendar_job()
    await run_earnings_calendar_job()
    await run_news_job()
    await run_board_heat_job()
    await run_akshare_news_job()
    await run_news_score_job()
    await run_fund_flow_job()
    await run_board_map_job()
    await run_board_sentiment_job()
    await run_fundamentals_job()
    await run_analyst_consensus_job()
    if not await needs_full_init():
        await run_daily_kline_job()
    await run_technical_indicators_job()
    await run_announcements_job()
    await run_research_reports_job()
    await run_market_breadth_job()
    await run_market_breadth_global_job()
    await run_macro_assets_job()
    await run_cleanup_job()
    logger.info("=== initial fetch done ===")


async def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
