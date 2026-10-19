"""MCP 工具定义（名称与 docs/MCP.md「工具」表一致）。

每个工具的固定前置（_caller）：
1. 身份：get_access_token() 取 PAT 校验结果，user_id 只来自令牌（subject = u<id>），工具参数里没有用户字段；
2. 配额：每令牌每分钟调用数（全部工具合计，滑动窗口）；
3. scope：strategy:read / strategy:write / backtest，不足返回工具错误（不在 SDK 层全局 required_scopes，
   否则只读令牌连 list_tools 都会被 403）。

工具错误统一抛 ToolError（SDK 转成 isError=true 的 CallToolResult，文案对 agent 可见）；
其余异常被 SDK 视为崩溃，只回通用文案，细节留服务端日志。
输出统一为紧凑 JSON 文本（structured_output=False：避免 structuredContent 与文本重复一份，
也让 ≤10KB 摘要的体积约束直接作用在线上文本上）。
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Literal

import anyio
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from app.auth import PatVerifier, token_hash
from app.config import Settings
from app.quant_client import (
    QuantClient,
    QuantClientError,
    QuantTimeoutError,
    QuantUnavailableError,
    truncate,
)
from app.quota import SlidingWindowLimiter, retry_hint
from app.results import dumps, paginate, section_items, summarize

logger = logging.getLogger(__name__)

SCOPE_READ = "strategy:read"
SCOPE_WRITE = "strategy:write"
SCOPE_BACKTEST = "backtest"

# 策略 id 口径与 quant _save_strategy_file 一致；task_id 为 uuid4().hex
STRATEGY_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
TASK_ID_RE = re.compile(r"^[0-9a-f]{32}$")
# 标的代码白名单：与 tradb data-api 的 symbol 校验同口径（大写字母/数字/点/横杠，≤20）。
# 必须在 mcp 侧拦：quant 以 symbol 直接拼本地缓存文件名（symbol=<code>.parquet 及
# 停牌水位 sidecar），含 "/" 的 symbol 会让补拉失败后的水位标记写到缓存目录之外。
SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,20}$")
# universe 档位（quant _SymbolRequest 的子集）：all 全市场矩阵曾 OOM（2026-09-22），MCP 一律禁用
ALLOWED_UNIVERSES = ("hs300", "csi500", "tracked", "cn", "us", "hk")
# symbols 与 universe 都留空时的默认档位：显式下发（与 quant universe._DEFAULT_TIER、web 默认一致），
# 不依赖 quant 默认值，保证工具说明与实际行为一致
DEFAULT_UNIVERSE = "hs300"
MAX_SYMBOLS = 500
MAX_WAIT_SECONDS = 50
POLL_INTERVAL_SECONDS = 2.0
TERMINAL_STATUSES = ("done", "failed", "cancelled")

UNAVAILABLE_MESSAGE = "quant 服务暂不可用，请稍后重试"
TIMEOUT_MESSAGE = (
    "quant 处理超时（请求可能仍在后台执行）：保存类操作请先用 list_strategies 确认结果再决定是否重试；"
    "回测提交请稍后重试（若提示活跃任务已满，说明上一次提交仍在后台运行，请等待其结束）"
)
TASK_NOT_FOUND_MESSAGE = "任务不存在（可能已过期或服务重启），请重新提交 run_backtest"

_READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)

StrategyId = Annotated[
    str, Field(description="策略 id（list_strategies 返回的 id，如 ma_golden_cross）")
]
TaskId = Annotated[
    str, Field(description="run_backtest 返回的 task_id（32 位小写十六进制）")
]
StrategyCode = Annotated[
    str, Field(description="完整策略 Python 源码（单文件，含顶层 META 与 compute）")
]


INSTRUCTIONS_TEMPLATE = """tradeck 量化策略服务：上传 Python 策略，在 A 股 / 港股 / 美股日K 上任务化回测。

推荐流程：
1. 先调 get_strategy_guide 阅读策略协议（META 字段、compute 签名、可用指标字段、NaN 与上下穿写法）；
   需要参考时用 list_strategies / get_strategy_code 查看已有策略。
2. 策略代码的 import 只允许 polars / numpy / datetime（及 __future__），以及
   from app.strategy.base import StrategySignals、from app.matrix import EnrichedMatrix；
   其余 import、文件 / 网络访问、危险内置函数、下划线属性访问一律被安全闸拒绝。
3. 先 validate_strategy 校验（不落盘，返回 valid / error，按 error 修改后重试），通过后再 save_strategy 保存；
   覆盖或改名自己已有的策略时传 overwrite_id（内置策略只读）。
4. run_backtest 提交后立即返回 task_id（回测是分钟级任务）；随后用
   get_backtest_result(task_id, wait_seconds=30) 轮询，直到 status 为 done / failed / cancelled。
   默认返回摘要；逐笔交易、分标的统计、完整净值用 section=trades|per_symbol|equity 配合 offset/limit 分页获取。
5. 配额：每个令牌每分钟最多 {rate} 次工具调用；每个用户每小时最多提交 {backtests} 次回测；
   universe 不支持 all（全市场），请用 hs300 / csi500 / tracked / cn / us / hk 或显式 symbols（≤{max_symbols} 只）。
"""


@dataclass(frozen=True)
class _Caller:
    """一次工具调用的身份（只来自 PAT 校验结果）。"""

    user_id: str
    scopes: tuple[str, ...]


@contextmanager
def _quant_errors(not_found: str | None = None) -> Iterator[None]:
    """quant 客户端异常 → 工具错误：4xx 透出 detail（已截断 2KB），超时/5xx/网络 → 通用文案。"""
    try:
        yield
    except QuantClientError as e:
        if e.status == 404 and not_found:
            raise ToolError(not_found) from None
        raise ToolError(f"quant 拒绝请求（HTTP {e.status}）：{e.detail}") from None
    except QuantTimeoutError:
        # 须先于父类 QuantUnavailableError：超时时服务端可能仍在处理，文案不同
        raise ToolError(TIMEOUT_MESSAGE) from None
    except QuantUnavailableError:
        raise ToolError(UNAVAILABLE_MESSAGE) from None


def _check_symbols(symbols: list[str] | None) -> list[str]:
    """标的清单：去空白、转大写、按白名单校验、保序去重，再校验数量上限。"""
    out: list[str] = []
    seen: set[str] = set()
    for raw in symbols or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        sym = raw.strip().upper()
        if not SYMBOL_RE.fullmatch(sym):
            raise ToolError(
                f"symbols 含非法代码 {raw[:40]!r}：只允许字母/数字/点/横杠（≤20 字符），"
                "如 600519.SH / 00700.HK / AAPL"
            )
        if sym not in seen:
            seen.add(sym)
            out.append(sym)
    if len(out) > MAX_SYMBOLS:
        raise ToolError(f"symbols 过多：{len(out)} 只，上限 {MAX_SYMBOLS} 只")
    return out


def _check_strategy_id(value: str, field: str = "strategy_id") -> str:
    value = (value or "").strip()
    if not STRATEGY_ID_RE.fullmatch(value):
        raise ToolError(
            f"{field} 非法：须为字母开头的字母/数字/下划线，长度 ≤64（收到 {value[:80]!r}）"
        )
    return value


def _check_task_id(value: str) -> str:
    value = (value or "").strip()
    if not TASK_ID_RE.fullmatch(value):
        raise ToolError(f"task_id 非法：须为 32 位小写十六进制（收到 {value[:80]!r}）")
    return value


def _task_view(snapshot: Any) -> dict:
    """任务快照去掉 result（结果走摘要/分页），failed 的 error 截断 2KB。"""
    if not isinstance(snapshot, dict):
        raise ToolError(UNAVAILABLE_MESSAGE)
    out = {
        k: snapshot.get(k)
        for k in (
            "task_id",
            "status",
            "progress",
            "created_at",
            "started_at",
            "finished_at",
        )
    }
    if snapshot.get("error"):
        out["error"] = truncate(str(snapshot["error"]))
    return out


def build_server(
    settings: Settings,
    verifier: PatVerifier,
    quant: QuantClient,
    *,
    sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> MCPServer:
    """构造 MCPServer 并注册全部工具（sleep/clock 可注入，测试不真等）。"""
    mcp = MCPServer(
        "tradeck",
        title="tradeck 量化策略",
        instructions=INSTRUCTIONS_TEMPLATE.format(
            rate=settings.rate_per_minute,
            backtests=settings.backtests_per_hour,
            max_symbols=MAX_SYMBOLS,
        ),
        website_url=settings.public_base,
        token_verifier=verifier,
        # 两参数必须同时传（SDK 校验）；issuer 指向签发 PAT 的 tradeck 站点。
        # validate_token_resource=True：verifier 把 resource 设为本服务 resource url，SDK 逐请求比对。
        # 不设 required_scopes：scope 在各工具内按需校验（见模块 docstring）。
        auth=AuthSettings(
            issuer_url=settings.public_base,
            resource_server_url=settings.resource_url,
            validate_token_resource=True,
        ),
    )
    call_limiter = SlidingWindowLimiter(settings.rate_per_minute, 60.0, clock)
    backtest_limiter = SlidingWindowLimiter(settings.backtests_per_hour, 3600.0, clock)

    def _caller(scope: str) -> _Caller:
        token = get_access_token()
        if token is None:
            # RequireAuthMiddleware 已在 HTTP 层挡掉无令牌请求，这里是纵深防御
            raise ToolError("未认证：请在 Authorization 头携带 Bearer tdk_pat_… 令牌")
        user_id = token.subject or token.client_id
        wait = call_limiter.hit(token_hash(token.token))
        if wait is not None:
            raise ToolError(
                f"调用过于频繁：每个令牌每分钟最多 {settings.rate_per_minute} 次，请 {retry_hint(wait)}后重试"
            )
        if scope not in token.scopes:
            have = "、".join(token.scopes) or "无"
            raise ToolError(
                f"令牌缺少 {scope} 权限（当前 scope：{have}），请在 tradeck「API 令牌」页签发包含该 scope 的令牌"
            )
        return _Caller(user_id=user_id, scopes=tuple(token.scopes))

    def _check_code(code: str) -> str:
        size = len((code or "").encode("utf-8"))
        if size == 0:
            raise ToolError("code 不能为空")
        if size > settings.max_code_bytes:
            raise ToolError(
                f"策略代码过大：{size} 字节，上限 {settings.max_code_bytes} 字节"
            )
        return code

    # ------------------------------------------------------------------
    # 策略（strategy:read / strategy:write）
    # ------------------------------------------------------------------

    @mcp.tool(title="读取策略开发指南", annotations=_READ_ONLY, structured_output=False)
    async def get_strategy_guide() -> str:
        """返回策略开发精简指南（Markdown）：单文件协议、import 白名单、META 字段、compute 签名、
        可用指标字段与常见坑。写策略前必读。"""
        caller = _caller(SCOPE_READ)
        with _quant_errors():
            return await quant.strategy_guide(caller.user_id)

    @mcp.tool(title="列出策略", annotations=_READ_ONLY, structured_output=False)
    async def list_strategies() -> str:
        """列出当前用户可用的全部策略（内置 builtin + 本人 custom/ai），含参数 schema、止损与最长持有天数；
        load_errors 为本人策略文件的加载错误（文件名、来源、错误信息），便于修复后重新保存。"""
        caller = _caller(SCOPE_READ)
        with _quant_errors():
            strategies = await quant.list_strategies(caller.user_id)
        out: dict[str, Any] = {"strategies": strategies}
        # 错误列表是附加信息：取失败不拖垮主结果（优雅降级，标注不可用）
        try:
            out["load_errors"] = await quant.strategy_errors(caller.user_id)
        except (QuantClientError, QuantUnavailableError) as e:
            logger.warning(
                "策略加载错误列表获取失败（user=%s）：%s",
                caller.user_id,
                type(e).__name__,
            )
            out["load_errors"] = []
            out["load_errors_unavailable"] = True
        return dumps(out)

    @mcp.tool(title="读取策略源码", annotations=_READ_ONLY, structured_output=False)
    async def get_strategy_code(strategy_id: StrategyId) -> str:
        """读取指定策略的完整 Python 源码（内置策略可作为编写范例；另存需改 META.id）。"""
        caller = _caller(SCOPE_READ)
        sid = _check_strategy_id(strategy_id)
        with _quant_errors():
            return dumps(await quant.strategy_code(caller.user_id, sid))

    @mcp.tool(
        title="校验策略代码",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=False,
    )
    async def validate_strategy(code: StrategyCode) -> str:
        """校验策略代码但不保存：安全闸静态检查 + 沙箱试加载试跑。返回 {valid, error, meta}；
        valid=false 时按 error 修改代码后重试。保存前务必先通过本校验。"""
        caller = _caller(SCOPE_WRITE)
        body = _check_code(code)
        with _quant_errors():
            res = await quant.validate_strategy(caller.user_id, body)
        if isinstance(res, dict) and res.get("error"):
            res = {**res, "error": truncate(str(res["error"]))}
        return dumps(res)

    @mcp.tool(
        title="保存策略",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=False,
    )
    async def save_strategy(
        code: StrategyCode,
        overwrite_id: Annotated[
            str | None,
            Field(
                description="覆盖/改名本人已有策略时传其原 id；新建留空。内置策略不可覆盖"
            ),
        ] = None,
    ) -> str:
        """保存策略到当前用户的策略库（文件名 = META.id；ai_ 前缀归 ai 目录，其余归 custom）。
        同 id 再次保存即覆盖更新；保存后 web 端「策略」列表可见。返回 {saved, strategy_id, name}。"""
        caller = _caller(SCOPE_WRITE)
        body = _check_code(code)
        oid = _check_strategy_id(overwrite_id, "overwrite_id") if overwrite_id else None
        with _quant_errors():
            return dumps(await quant.save_strategy(caller.user_id, body, oid))

    # ------------------------------------------------------------------
    # 回测（backtest）
    # ------------------------------------------------------------------

    @mcp.tool(
        title="提交回测",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
        structured_output=False,
    )
    async def run_backtest(
        strategy_id: StrategyId,
        start: Annotated[date, Field(description="回测起始日 YYYY-MM-DD")],
        end: Annotated[
            date | None, Field(description="回测结束日 YYYY-MM-DD，留空为今天")
        ] = None,
        symbols: Annotated[
            list[str] | None,
            Field(
                description=f"显式标的列表（规范格式：600519.SH / 00700.HK / AAPL，自动转大写），≤{MAX_SYMBOLS} 只；"
                "非空时忽略 universe"
            ),
        ] = None,
        universe: Annotated[
            str | None,
            Field(
                description="标的池档位：hs300 / csi500 / tracked / cn / us / hk（不支持 all）；"
                f"与 symbols 都留空时默认 {DEFAULT_UNIVERSE}（沪深300）"
            ),
        ] = None,
        params: Annotated[
            dict[str, Any] | None,
            Field(description="策略参数覆盖（键为 META.params 的 id），留空用默认值"),
        ] = None,
        sim_mode: Annotated[
            Literal["position", "full"],
            Field(
                description="position=组合模拟（统一资金池 + max_positions）；full=全量模拟（评估选股质量）"
            ),
        ] = "position",
        initial_capital: Annotated[
            float, Field(gt=0, allow_inf_nan=False, description="初始资金")
        ] = 1_000_000,
        max_positions: Annotated[
            int, Field(ge=1, le=100, description="最大同时持仓数")
        ] = 10,
        commission_pct: Annotated[
            float | None,
            Field(
                ge=0,
                le=0.01,
                description="佣金率覆盖（小数，如 0.0003），留空用市场默认",
            ),
        ] = None,
        stamp_tax_pct: Annotated[
            float | None,
            Field(ge=0, le=0.01, description="印花税率覆盖（小数），留空用市场默认"),
        ] = None,
        slippage_bps: Annotated[
            float | None, Field(ge=0, le=500, description="滑点覆盖（bps），留空用默认")
        ] = None,
    ) -> str:
        """提交任务化回测，立即返回 {task_id}；随后用 get_backtest_result 轮询结果（回测是分钟级任务）。"""
        caller = _caller(SCOPE_BACKTEST)
        sid = _check_strategy_id(strategy_id)
        if end is not None and end < start:
            raise ToolError(f"end（{end}）早于 start（{start}）")
        uni = (universe or "").strip().lower() or None
        if uni == "all":
            raise ToolError(
                "不支持 universe=all（全市场回测内存开销过大）：请改用 hs300 / csi500 / tracked / cn / us / hk 或显式 symbols"
            )
        if uni is not None and uni not in ALLOWED_UNIVERSES:
            raise ToolError(
                f"universe 非法：{uni[:40]!r}，可选 {' / '.join(ALLOWED_UNIVERSES)}"
            )
        syms = _check_symbols(symbols)
        payload: dict[str, Any] = {
            "strategy_id": sid,
            "start": start.isoformat(),
            "end": end.isoformat() if end else None,
            "symbols": syms or None,
            "universe": None if syms else (uni or DEFAULT_UNIVERSE),
            "params": params or {},
            "sim_mode": sim_mode,
            "initial_capital": initial_capital,
            "max_positions": max_positions,
            "commission_pct": commission_pct,
            "stamp_tax_pct": stamp_tax_pct,
            "slippage_bps": slippage_bps,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        try:
            # params 是自由结构：NaN / Infinity 能过 SDK 入参解析，却无法编码成标准 JSON 发给 quant
            # （否则在 HTTP 客户端里抛 ValueError，agent 只看到通用崩溃文案且白耗一次回测配额）
            json.dumps(payload, allow_nan=False)
        except ValueError:
            raise ToolError(
                "参数含 NaN / Infinity 等非法数值（JSON 不支持），请改为有限数值"
            ) from None
        # 回测提交配额（按提交尝试计：本地校验通过即计数，quant 侧拒绝也不退还）
        wait = backtest_limiter.hit(caller.user_id)
        if wait is not None:
            raise ToolError(
                f"回测提交过于频繁：每个用户每小时最多 {settings.backtests_per_hour} 次，请 {retry_hint(wait)}后重试"
            )
        with _quant_errors():
            res = await quant.run_backtest(caller.user_id, payload)
        task_id = res.get("task_id") if isinstance(res, dict) else None
        if not isinstance(task_id, str):
            raise ToolError(UNAVAILABLE_MESSAGE)
        logger.info(
            "回测已提交：task=%s strategy=%s user=%s", task_id, sid, caller.user_id
        )
        return dumps(
            {
                "task_id": task_id,
                "status": "pending",
                "next": "用 get_backtest_result(task_id, wait_seconds=30) 轮询，直到 status 为 done / failed / cancelled",
            }
        )

    @mcp.tool(title="获取回测结果", annotations=_READ_ONLY, structured_output=False)
    async def get_backtest_result(
        task_id: TaskId,
        wait_seconds: Annotated[
            int,
            Field(
                ge=0,
                le=MAX_WAIT_SECONDS,
                description=f"最多等待秒数（0-{MAX_WAIT_SECONDS}）：任务未结束时每 2 秒查询一次，结束即返回",
            ),
        ] = 0,
        section: Annotated[
            Literal["summary", "trades", "per_symbol", "equity"],
            Field(
                description="summary=摘要（默认，≤10KB）；trades=逐笔交易；per_symbol=分标的统计；equity=逐日净值"
            ),
        ] = "summary",
        offset: Annotated[
            int, Field(ge=0, description="分页起点（section 非 summary 时有效）")
        ] = 0,
        limit: Annotated[int, Field(ge=1, le=200, description="每页条数 1-200")] = 50,
    ) -> str:
        """查询回测任务：未结束返回 status/progress；done 返回结果摘要或指定分区的分页明细
        {total, offset, limit, items}；failed 返回 error。"""
        caller = _caller(SCOPE_BACKTEST)
        tid = _check_task_id(task_id)
        deadline = clock() + wait_seconds
        with _quant_errors(not_found=TASK_NOT_FOUND_MESSAGE):
            snap = await quant.backtest_task(caller.user_id, tid)
            while (
                isinstance(snap, dict)
                and snap.get("status") not in TERMINAL_STATUSES
                and clock() < deadline
            ):
                await sleep(min(POLL_INTERVAL_SECONDS, max(deadline - clock(), 0.0)))
                snap = await quant.backtest_task(caller.user_id, tid)
        out = _task_view(snap)
        status = out.get("status")
        if status not in TERMINAL_STATUSES:
            out["hint"] = (
                "任务仍在运行，稍后再次调用 get_backtest_result（可设 wait_seconds 等待）"
            )
            return dumps(out)
        if status != "done":
            return dumps(out)
        result = snap.get("result")
        if section == "summary":
            out["summary"] = summarize(result)
            return dumps(out)
        out["section"] = section
        out.update(paginate(section_items(result, section), offset, limit))
        return dumps(out)

    @mcp.tool(
        title="取消回测",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=False,
    )
    async def cancel_backtest(task_id: TaskId) -> str:
        """取消回测任务（幂等：已结束的任务返回其最终状态）。"""
        caller = _caller(SCOPE_BACKTEST)
        tid = _check_task_id(task_id)
        with _quant_errors(not_found=TASK_NOT_FOUND_MESSAGE):
            snap = await quant.cancel_backtest(caller.user_id, tid)
        return dumps(_task_view(snap))

    return mcp
