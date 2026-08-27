"""数据任务目录与统一运行入口。

所有手动同步必须通过白名单目录触发；统一负责防重入、进度记录与异常收口。
日 K 自带按标的进度上报，其他任务按一次运行记为 0 → 100%。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from numbers import Real
from typing import Awaitable, Callable, Literal

from app.jobs import progress
from app.jobs.adjust_factors import run_adjust_factors_job
from app.jobs.akshare_news import run_akshare_news_job
from app.jobs.analyst_consensus import run_analyst_consensus_job
from app.jobs.announcements import run_announcements_job
from app.jobs.board_heat import run_board_heat_job
from app.jobs.board_map import run_board_map_job
from app.jobs.board_sentiment import run_board_sentiment_job
from app.jobs.cleanup import run_cleanup_job
from app.jobs.daily_kline import run_daily_kline_job
from app.jobs.earnings_calendar import run_earnings_calendar_job
from app.jobs.economic_calendar import run_economic_calendar_job
from app.jobs.fund_flow import run_fund_flow_job
from app.jobs.fundamentals import run_fundamentals_job
from app.jobs.hithink_dump import run_hithink_daily_k_dump_job
from app.jobs.indices import run_indices_job
from app.jobs.macro import run_macro_job
from app.jobs.macro_assets import run_macro_assets_job
from app.jobs.minute_kline import run_minute_kline_job
from app.jobs.market_breadth import run_market_breadth_job
from app.jobs.market_breadth_global import run_market_breadth_global_job
from app.jobs.movers import fetch_and_store_cn_movers, run_movers_job
from app.jobs.news import run_news_job
from app.jobs.news_score import run_news_score_job
from app.jobs.realtime_quotes import run_realtime_quotes_job
from app.jobs.research_reports import run_research_reports_job
from app.jobs.technical_indicators import run_technical_indicators_job

logger = logging.getLogger(__name__)

JobCallable = Callable[[], Awaitable[object]]


@dataclass(frozen=True)
class JobHealthQuery:
    """任务专属数据切片；字段全部由代码白名单定义，不接收请求输入。"""

    name: str
    table: str
    where: str = "TRUE"
    latest_column: str | None = None
    latest_kind: Literal["date", "datetime"] | None = None
    max_age_hours: int | None = None
    label: str | None = None


@dataclass(frozen=True)
class JobDefinition:
    id: str
    label: str
    description: str
    source: str
    schedule: str
    tables: tuple[str, ...]
    runner: JobCallable
    managed_progress: bool = False
    allow_manual: bool = True
    concurrency_group: str | None = None
    classify_result: bool = True
    maintenance: bool = False
    health_queries: tuple[JobHealthQuery, ...] = ()


async def _movers_cn() -> int:
    return await fetch_and_store_cn_movers()


async def _hithink_daily_k_dump_full() -> int:
    """同花顺全量日K 包装（registry 无参 runner 约定；APScheduler 友好）。"""
    return await run_hithink_daily_k_dump_job(full=True)


JOB_DEFINITIONS = (
    JobDefinition(
        "daily_kline",
        "日 K 每日更新",
        "CN 同花顺增量；HK/US 用 TickFlow universe + OpenBB/yfinance 近 5 日 UPSERT",
        "hithink / OpenBB-yfinance",
        "A/港 08:30；美股 21:30 UTC",
        ("daily_prices", "equity_profiles"),
        run_daily_kline_job,
        managed_progress=True,
        concurrency_group="daily_kline",
    ),
    JobDefinition(
        "daily_kline_full",
        "日 K 全量初始化",
        "HK/US 用 TickFlow universe + OpenBB/yfinance 补齐近 250 个交易日",
        "OpenBB-yfinance",
        "启动时按市场缺口自动触发",
        ("daily_prices", "equity_profiles"),
        run_daily_kline_job,
        managed_progress=True,
        concurrency_group="daily_kline",
    ),
    JobDefinition(
        "realtime_quotes",
        "实时报价",
        "跟踪标的最新报价快照",
        "akshare / yfinance",
        "每 30 分钟",
        ("quote_snapshots",),
        run_realtime_quotes_job,
        health_queries=(
            JobHealthQuery("A 股报价", "quote_snapshots", "market = 'CN'"),
            JobHealthQuery("港股报价", "quote_snapshots", "market = 'HK'"),
            JobHealthQuery("美股报价", "quote_snapshots", "market = 'US'"),
        ),
    ),
    JobDefinition(
        "indices",
        "指数与商品历史",
        "全球指数、波动率与商品历史行情",
        "yfinance",
        "各市场收盘后分批更新",
        ("index_prices",),
        run_indices_job,
    ),
    JobDefinition(
        "movers",
        "美股涨跌榜",
        "美股涨幅、跌幅与活跃榜快照",
        "yfinance",
        "每 5 分钟",
        ("movers_cache",),
        run_movers_job,
        health_queries=(
            JobHealthQuery("美股榜单", "movers_cache", "market = 'US'"),
        ),
    ),
    JobDefinition(
        "movers_cn",
        "A 股涨跌榜",
        "基于日 K 全市场数据生成 A 股榜单",
        "本地计算",
        "每天 09:10 UTC",
        ("movers_cache",),
        _movers_cn,
        health_queries=(
            JobHealthQuery("A 股榜单", "movers_cache", "market = 'CN'"),
        ),
    ),
    JobDefinition(
        "news",
        "海外新闻",
        "跟踪标的海外新闻聚合",
        "yfinance",
        "每 30 分钟",
        ("news_articles",),
        run_news_job,
        health_queries=(
            JobHealthQuery(
                "海外新闻",
                "news_articles",
                "symbol IS NOT NULL AND symbol !~ '[.](SH|SS|SZ|BJ)$'",
            ),
        ),
    ),
    JobDefinition(
        "akshare_news",
        "A 股新闻",
        "跟踪 A 股的东方财富新闻",
        "akshare",
        "每 30 分钟",
        ("news_articles",),
        run_akshare_news_job,
        health_queries=(
            JobHealthQuery(
                "A 股新闻",
                "news_articles",
                "symbol ~ '[.](SH|SS|SZ|BJ)$'",
            ),
        ),
    ),
    JobDefinition(
        "news_score",
        "新闻情绪打分",
        "对新增新闻进行本地关键词情绪评分",
        "本地规则",
        "每 30 分钟",
        ("news_articles",),
        run_news_score_job,
        health_queries=(
            JobHealthQuery(
                "已打分新闻",
                "news_articles",
                "scored_at IS NOT NULL",
                latest_column="scored_at",
                latest_kind="datetime",
                max_age_hours=36,
                label="最近打分时间",
            ),
        ),
    ),
    JobDefinition(
        "macro",
        "宏观指标",
        "CPI、GDP、失业率与基准利率",
        "OECD / Federal Reserve",
        "每天 06:00 UTC",
        ("macro_indicators",),
        run_macro_job,
    ),
    JobDefinition(
        "adjust_factors",
        "复权因子",
        "findb 前/后复权因子（跟踪标的最近约 250 个交易日）",
        "findb",
        "每日",
        ("adjust_factors",),
        run_adjust_factors_job,
    ),
    JobDefinition(
        "hithink_daily_k_dump_full",
        "同花顺 A 股日K 全量",
        "同花顺 Market Dump 全市场约 10 年日K（~945 万行/170MB），耗时数分钟；"
        "首次全量初始化（启动缺口检测或手动触发），此后每日增量由 "
        "hithink_daily_k_dump 补齐",
        "hithink-finance",
        "启动缺口自动 / 手动",
        ("daily_prices",),
        _hithink_daily_k_dump_full,
        allow_manual=True,
        concurrency_group="daily_kline",
    ),
    JobDefinition(
        "hithink_daily_k_dump",
        "同花顺 A 股日K 增量",
        "同花顺 Market Dump 全市场近 10 交易日日K UPSERT（原始未复权价）；"
        "CN 日K 每日主源（TickFlow 仅覆盖 HK/US）",
        "hithink-finance",
        "A/港盘后 08:30 UTC",
        ("daily_prices",),
        run_hithink_daily_k_dump_job,
        concurrency_group="daily_kline",
        health_queries=(
            JobHealthQuery("A 股日K", "daily_prices", "market = 'CN'"),
        ),
    ),
    JobDefinition(
        "minute_kline",
        "分钟K 采集（冷层）",
        "US/HK 当日 1m 分钟K → quality_gate → 冷层 Parquet（year/market/date 分区）；A股待付费源",
        "yfinance 1m",
        "每交易日盘后",
        (),  # 不落库表，直写冷层 Parquet；质量留痕于 data_quality_* 表
        run_minute_kline_job,
    ),
    JobDefinition(
        "economic_calendar",
        "宏观数据日历",
        "未来宏观数据发布事件",
        "FRED / akshare",
        "每天 06:30 UTC",
        ("economic_calendar",),
        run_economic_calendar_job,
    ),
    JobDefinition(
        "earnings_calendar",
        "财报日历",
        "跟踪美股与港股的未来财报日期",
        "yfinance",
        "每天 12:00 UTC",
        ("earnings_calendar",),
        run_earnings_calendar_job,
    ),
    JobDefinition(
        "fundamentals",
        "公司与财务数据",
        "公司资料、指标、利润表、资产负债表与现金流量表",
        "SEC / yfinance",
        "每周一 07:00 UTC",
        (
            "equity_profiles",
            "fundamental_metrics",
            "income_statements",
            "balance_sheets",
            "cash_flow_statements",
        ),
        run_fundamentals_job,
    ),
    JobDefinition(
        "analyst_consensus",
        "分析师共识",
        "评级、分析师数量与目标价快照",
        "yfinance",
        "每天 21:00 UTC",
        ("analyst_consensus",),
        run_analyst_consensus_job,
    ),
    JobDefinition(
        "board_heat",
        "板块行情热度",
        "A 股概念与行业板块行情",
        "findb",  # 同花顺概念指数（ths_index）+ 申万行业（sw_industry/sw_daily）
        "每天 09:05 UTC",
        ("board_heat",),
        run_board_heat_job,
    ),
    JobDefinition(
        "board_map",
        "板块归属映射",
        "从板块成分股反解股票归属",
        "akshare",
        "每周一 08:00 UTC",
        ("symbol_board_map",),
        run_board_map_job,
    ),
    JobDefinition(
        "board_sentiment",
        "板块舆情聚合",
        "按板块聚合新闻数量与情绪热度",
        "本地计算",
        "每 30 分钟",
        ("board_sentiment",),
        run_board_sentiment_job,
    ),
    JobDefinition(
        "fund_flow",
        "个股资金流向",
        "A 股主力资金流即时榜",
        "findb",  # stock_fund_flow 主力净流入榜（原 akshare 东财即时榜退役）
        "每小时 25 分",
        ("fund_flow",),
        run_fund_flow_job,
    ),
    JobDefinition(
        "technical_indicators",
        "技术指标",
        "从日 K 本地计算均线、MACD、RSI 与布林带",
        "本地计算",
        "每天 09:00 / 22:00 UTC",
        ("technical_indicators",),
        run_technical_indicators_job,
    ),
    JobDefinition(
        "announcements",
        "A 股公告",
        "跟踪 A 股的全市场公告过滤结果",
        "akshare",
        "每天 10:30 UTC",
        ("announcements",),
        run_announcements_job,
    ),
    JobDefinition(
        "research_reports",
        "A 股券商研报",
        "跟踪 A 股近 90 天券商研报",
        "akshare",
        "每周一 09:00 UTC",
        ("research_reports",),
        run_research_reports_job,
    ),
    JobDefinition(
        "market_breadth",
        "A 股市场宽度",
        "涨跌家数、涨跌停与活跃度",
        "akshare",
        "每 30 分钟",
        ("market_breadth",),
        run_market_breadth_job,
        health_queries=(
            JobHealthQuery(
                "A 股宽度",
                "market_breadth",
                "market = 'CN' AND source = 'legu'",
            ),
        ),
    ),
    JobDefinition(
        "market_breadth_global",
        "美港市场宽度",
        "从全市场日 K 计算美股与港股涨跌家数",
        "本地计算",
        "每天 09:05 / 22:05 UTC",
        ("market_breadth",),
        run_market_breadth_global_job,
        health_queries=(
            JobHealthQuery(
                "美股宽度",
                "market_breadth",
                "market = 'US' AND source = 'daily_kline'",
            ),
            JobHealthQuery(
                "港股宽度",
                "market_breadth",
                "market = 'HK' AND source = 'daily_kline'",
            ),
        ),
    ),
    JobDefinition(
        "macro_assets",
        "宏观资产与收益率曲线",
        "美元、离岸人民币、ETF 与美国国债收益率",
        "yfinance / Federal Reserve",
        "每天 21:30 UTC",
        ("macro_asset_prices", "yield_curve_rates"),
        run_macro_assets_job,
    ),
    JobDefinition(
        "cleanup",
        "过期数据清理",
        "按 TTL 清理快照与历史缓存",
        "本地维护",
        "每天 03:00 UTC",
        (
            "movers_cache",
            "board_heat",
            "board_sentiment",
            "fund_flow",
            "news_articles",
        ),
        run_cleanup_job,
        allow_manual=False,
        classify_result=False,
        maintenance=True,
    ),
)

_JOB_MAP = {job.id: job for job in JOB_DEFINITIONS}
_active_jobs: set[str] = set()
_active_groups: set[str] = set()


def _group_key(job: JobDefinition) -> str:
    return job.concurrency_group or job.id


def _reserve_job(job: JobDefinition) -> bool:
    group = _group_key(job)
    if (
        job.id in _active_jobs
        or group in _active_groups
        or progress.is_running(job.id)
    ):
        return False
    _active_jobs.add(job.id)
    _active_groups.add(group)
    return True


def _release_job(job: JobDefinition) -> None:
    _active_jobs.discard(job.id)
    _active_groups.discard(_group_key(job))


def get_job_definition(job_id: str) -> JobDefinition | None:
    return _JOB_MAP.get(job_id)


def job_catalog() -> list[dict]:
    """返回前端展示所需的任务元数据。"""
    return [
        {
            "id": job.id,
            "label": job.label,
            "description": job.description,
            "source": job.source,
            "schedule": job.schedule,
            "tables": list(job.tables),
            "allow_manual": job.allow_manual,
            "maintenance": job.maintenance,
            "health_queries": [
                {
                    "name": query.name,
                    "table": query.table,
                    "where": query.where,
                    "latest_column": query.latest_column,
                    "latest_kind": query.latest_kind,
                    "max_age_hours": query.max_age_hours,
                    "label": query.label,
                }
                for query in job.health_queries
            ],
        }
        for job in JOB_DEFINITIONS
    ]


def _numeric_result_items(result: object) -> list[tuple[str, float]]:
    if not isinstance(result, dict):
        return []
    return [
        (str(key), float(value))
        for key, value in result.items()
        if isinstance(value, Real) and not isinstance(value, bool)
    ]


def _format_count(value: float) -> str:
    return f"{int(value):,}" if value.is_integer() else f"{value:,.2f}"


def _result_outcome(job: JobDefinition, result: object) -> tuple[str, str]:
    """将 runner 的显式写入量转换为任务结果。"""
    if isinstance(result, bool):
        return "done", "同步完成"
    if isinstance(result, int):
        if job.classify_result and result == 0:
            return "empty", "处理 0 行，未获取到新数据"
        return "done", f"处理 {result:,} 行"

    numeric = _numeric_result_items(result)
    if numeric:
        total = sum(value for _, value in numeric)
        if not job.classify_result:
            return "done", f"处理 {_format_count(total)} 行"
        zero_items = [name for name, value in numeric if value == 0]
        positive_items = [name for name, value in numeric if value > 0]
        negative_items = [name for name, value in numeric if value < 0]
        if all(value == 0 for _, value in numeric):
            return "empty", "处理 0 行，所有数据分项均为空"
        if (positive_items and (zero_items or negative_items)) or negative_items:
            missing = zero_items + negative_items
            detail = "、".join(missing[:4])
            suffix = f"；无数据分项：{detail}" if detail else ""
            return "partial", f"部分数据完成，合计处理 {_format_count(total)} 行{suffix}"
        if total == 0:
            return "empty", "处理 0 行，未获取到新数据"
        return "done", f"处理 {_format_count(total)} 行"
    if result is None and job.classify_result:
        return "empty", "任务未返回处理数量，按空结果处理"
    return "done", "同步完成"


def _record_outcome(
    job: JobDefinition,
    result: object,
    started_at: str | None,
) -> None:
    status, note = _result_outcome(job, result)
    if job.managed_progress:
        if status != "done":
            progress.job_reclassify(job.id, status, note)
        return
    if status == "empty":
        progress.job_empty(job.id, note, started_at)
    elif status == "partial":
        progress.job_partial(job.id, note, started_at)
    else:
        progress.job_done(job.id, note, started_at)


async def run_registered_job(
    job_id: str,
    trigger: str = "schedule",
    markets: tuple[str, ...] | None = None,
) -> object:
    """执行白名单任务，并统一写入进度注册表。"""
    job = get_job_definition(job_id)
    if job is None:
        raise KeyError(job_id)
    if not _reserve_job(job):
        logger.info("job %s already running, skipped", job_id)
        return 0
    run_started_at: str | None = None
    try:
        if not job.managed_progress:
            run_started_at = progress.job_start(
                job.id, job.label, 1, trigger=trigger
            )
        if job.id == "daily_kline":
            result = await run_daily_kline_job(markets=markets, trigger=trigger)
        elif job.id == "daily_kline_full":
            result = await run_daily_kline_job(
                full=True, markets=markets, trigger=trigger
            )
        elif job.id == "indices":
            result = await run_indices_job(markets=markets)
        else:
            result = await job.runner()
        if not job.managed_progress or not (
            isinstance(result, int) and result == 0 and progress.is_running(job.id)
        ):
            _record_outcome(job, result, run_started_at)
        return result
    except Exception as exc:  # noqa: BLE001
        if not job.managed_progress:
            progress.job_error(job.id, str(exc)[:200], run_started_at)
        logger.exception("job %s failed", job.id)
        raise
    finally:
        _release_job(job)


def is_job_active(job_id: str) -> bool:
    return job_id in _active_jobs or progress.is_running(job_id)


def launch_registered_job(job_id: str) -> bool:
    """后台触发一次手动同步。返回 False 表示任务不存在/不可手动执行/正在运行。"""
    job = get_job_definition(job_id)
    if job is None or not job.allow_manual or not _reserve_job(job):
        return False

    async def run_reserved() -> None:
        run_started_at: str | None = None
        try:
            if not job.managed_progress:
                run_started_at = progress.job_start(
                    job.id, job.label, 1, trigger="manual"
                )
            if job.id == "daily_kline":
                result = await run_daily_kline_job(trigger="manual")
            elif job.id == "daily_kline_full":
                result = await run_daily_kline_job(full=True, trigger="manual")
            else:
                result = await job.runner()
            if not job.managed_progress or not (
                isinstance(result, int) and result == 0 and progress.is_running(job.id)
            ):
                _record_outcome(job, result, run_started_at)
        except Exception as exc:  # noqa: BLE001
            if not job.managed_progress:
                progress.job_error(job.id, str(exc)[:200], run_started_at)
            logger.exception("manual job %s failed", job.id)
        finally:
            _release_job(job)

    asyncio.create_task(run_reserved())
    return True
