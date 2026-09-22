"""quant HTTP 服务 — 策略/选股/回测/AI 生成/挖掘的统一出口（web 经 Next 代理消费）。

设计（docs/QUANT-BACKTEST.md 阶段 E）：
- 轻量 FastAPI，单进程（与引擎纪律一致），仅经 data-api 读数，绝不直连 DB。
- 消费方身份：出站调 data-api 时带 X-Service-Token（见 data/client）。
- 优雅降级：策略执行/数据缺失返回空结果，不 500；参数错返回 4xx。
- 多用户骨架（G4）：X-User-Id 头贯穿到策略目录/候选库/信号表（命名空间隔离），
  缺省回落 QUANT_DEFAULT_USER；重计算（回测）走 spawn 子进程池（app.worker）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.ai.validator import validate_strategy_code
from app.config import settings
from app.mining import load_candidates, publish_candidate, run_mining
from app.mining.runtime import save_candidate
from app.runner import (
    _fetch_benchmark,
    _fetch_names,
    migrate_legacy_strategy_dirs,
    user_strategy_dirs,
)
from app.screener import screen
from app.strategy import StrategyRegistry
from app.tasks import UnknownTaskError, get_registry as get_task_registry
from app.worker import (
    BacktestCancelledError,
    BacktestWorkerError,
    CancelToken,
    run_backtest_in_worker,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="tradeck quant", version="0.2.0")

# 用户 id 白名单：防目录穿越（users/{uid}/ 直接拼路径）与 loader 任意路径 exec_module。
# 内网阶段虽不鉴权，但 id 形态必须先收口，别等鉴权阶段才堵这个洞。
_USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


@app.on_event("startup")
def _startup() -> None:
    """启动一次性维护：旧全局策略目录迁移到 default 用户命名空间（幂等）。"""
    try:
        migrate_legacy_strategy_dirs()
    except Exception as e:  # 迁移失败不阻塞服务（只记日志，下次启动重试）
        logger.warning("策略目录迁移失败（不阻塞启动）：%s", e)


def current_user_id(x_user_id: str | None = Header(default=None, alias="X-User-Id")) -> str:
    """解析用户身份：X-User-Id 头缺省/空白时回落 QUANT_DEFAULT_USER（G4 不鉴权）。"""
    uid = (x_user_id or "").strip()
    if not uid:
        return settings.QUANT_DEFAULT_USER
    if not _USER_ID_RE.fullmatch(uid):
        raise HTTPException(status_code=400, detail=f"非法 user_id：{uid!r}")
    return uid


def _registry(user_id: str) -> StrategyRegistry:
    """每次请求重建注册表（策略文件热加载；注册表本身轻量，扫描三层目录）。"""
    return StrategyRegistry(user_strategy_dirs(user_id))


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/strategies")
def list_strategies(user_id: str = Depends(current_user_id)) -> list[dict]:
    """列出全部策略（含 params schema，供前端自动生成参数表单）。"""
    reg = _registry(user_id)
    out = []
    for s in reg.all():
        out.append({
            "id": s.strategy_id,
            "name": s.name,
            "description": s.meta.get("description", ""),
            "tags": s.meta.get("tags", []),
            "source": s.source,
            "params": s.params_schema,
            "stop_loss": s.stop_loss,
            "max_hold_days": s.max_hold_days,
        })
    return out


@app.get("/api/strategies/{strategy_id}/code")
def get_strategy_code(strategy_id: str, user_id: str = Depends(current_user_id)) -> dict:
    """读取策略源码（AI 工作台「加载已有策略」）。

    builtin 策略文件在镜像内随包发布，读源码只用于展示/另存底稿，不构成写路径。
    """
    try:
        sdef = _registry(user_id).get(strategy_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    try:
        code = sdef.file_path.read_text(encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"策略文件读取失败：{e}")
    return {
        "id": sdef.strategy_id,
        "name": sdef.name,
        "source": sdef.source,
        "code": code,
    }


class _SymbolRequest(BaseModel):
    symbols: list[str] | None = Field(default=None, max_length=500)
    # symbols 为空（None）时按 universe 档位展开（默认 tracked 100 只）；
    # symbols 非空时 universe 忽略（互斥，显式优先）。
    universe: str | None = Field(default=None, pattern="^(tracked|cn|us|hk|all)$")
    start: date | None = None
    end: date | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class ScreenRequest(_SymbolRequest):
    strategy_id: str
    limit: int = Field(default=100, ge=1, le=500)


@app.post("/api/screen")
async def api_screen(req: ScreenRequest, user_id: str = Depends(current_user_id)) -> dict:
    """选股：返回最新交易日截面入选标的（score 降序）。

    冷启动修复：screen() 是同步函数只读本地缓存，故先经 matrix.build_async
    暖缓存（缺失标的回源补拉落盘），补拉失败按全 NaN 列降级，不影响出参。
    """
    from app.universe import resolve_universe
    reg = _registry(user_id)
    try:
        symbols = await resolve_universe(req.symbols, req.universe)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    from datetime import timedelta

    from app.matrix import build_async
    from app.screener.executor import _SCREEN_WINDOW_DAYS
    _screen_end = req.end or date.today()
    await build_async(symbols, _screen_end - timedelta(days=_SCREEN_WINDOW_DAYS), _screen_end)
    try:
        res = screen(req.strategy_id, symbols, end_date=req.end,
                     params=req.params or None, registry=reg)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    rows = [
        {"symbol": r.symbol, "name": r.name, "score": r.score,
         "entry": r.signals["entry"], "exit": r.signals["exit"], "market": r.market}
        for r in res.rows[: req.limit]
    ]
    return {"strategy_id": res.strategy_id, "as_of": res.as_of.isoformat(),
            "rows": rows, "total": res.total, "unadjusted": res.unadjusted}


class BacktestRequest(_SymbolRequest):
    strategy_id: str
    start: date  # 回测必填起点
    # 回测模式：position（默认，组合模拟：现金统一池 + max_positions）/
    # full（全量模拟：全部买入信号独立执行，评估选股质量，样本口径非账户净值）
    sim_mode: str = Field(default="position", pattern="^(position|full)$")
    initial_capital: float = Field(default=1_000_000.0, gt=0)
    max_positions: int = Field(default=10, ge=1, le=100)
    commission_pct: float | None = Field(default=None, ge=0, le=0.01)  # 佣金率覆盖（小数）
    stamp_tax_pct: float | None = Field(default=None, ge=0, le=0.01)  # 印花税率覆盖（小数）
    slippage_bps: float | None = Field(default=None, ge=0, le=500)   # 滑点覆盖（bps）
    # 分钟口径（阶段 H1，透传 MatcherConfig）：minute_fill=信号成交日分钟K 优化成交价；
    # exit_fill 卖出成交价口径 open_t+1（默认）/ close_t / signal_next_minute（盘中触发）
    minute_fill: bool = False
    exit_fill: str = Field(default="open_t+1", pattern="^(open_t\\+1|close_t|signal_next_minute)$")


@app.post("/api/backtest")
async def api_backtest(req: BacktestRequest, user_id: str = Depends(current_user_id)) -> dict:
    """回测：数据→矩阵→复权→策略→撮合→统计（G4 起走 spawn 子进程池，主进程不崩）。"""
    from app.engine import MatcherConfig
    from app.universe import resolve_universe
    reg = _registry(user_id)
    if req.strategy_id not in {s.strategy_id for s in reg.all()}:
        raise HTTPException(status_code=404, detail=f"策略不存在 {req.strategy_id!r}")
    try:
        symbols = await resolve_universe(req.symbols, req.universe)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    cfg = MatcherConfig(
        initial_capital=req.initial_capital,
        max_positions=req.max_positions,
        commission_pct=req.commission_pct,
        stamp_tax_pct=req.stamp_tax_pct,
        slippage_bps=req.slippage_bps,
        minute_fill=req.minute_fill,
        exit_fill=req.exit_fill,
    )
    end = req.end or date.today()
    # 冷启动修复：worker 子进程只读本地缓存不做网络 IO（既有纪律），
    # 日K 缺失标的必须在这里（主进程）经 build_async 补拉落盘，
    # 否则缓存目录为空时子进程回测全员全 NaN 零成交；失败降级不阻塞。
    from app.matrix import build_async
    await build_async(symbols, req.start, end)
    benchmark = await _fetch_benchmark(symbols, req.start, end)
    names = await _fetch_names(symbols)
    try:
        return await run_backtest_in_worker(
            symbols, req.strategy_id, req.start, end,
            params=req.params or None, config=cfg, user_id=user_id, benchmark=benchmark,
            names=names, sim_mode=req.sim_mode,
        )
    except BacktestWorkerError as e:
        # 子进程失败 → 结构化错误（不 500；与全局优雅降级口径一致）
        logger.warning("回测 worker 失败：%s", e)
        return {"error": str(e), "stats": None, "trades": [], "equity_curve": []}


# ---------------------------------------------------------------------------
# 任务化回测 API（进度 / 停止 / 断线重连）
#
# 与 POST /api/backtest 的差异：同步版一次性等结果（连接挂住整个回测时长，
# 断线即丢失）；任务版登记后立即返回 task_id，客户端轮询
# GET /api/backtest/task/{id} 拿逐日进度与终态结果——任务存在进程内注册表
# （app.tasks），脱离连接独立存活，掉线后重连轮询即可恢复（断线重连语义）；
# 取消走 POST .../cancel（幂等，父进程 terminate 子进程，语义见 app.worker）。
# ---------------------------------------------------------------------------


async def _run_backtest_task(
    task_id: str,
    symbols: list[str],
    strategy_id: str,
    start: date,
    end: date,
    params: dict | None,
    cfg,
    user_id: str,
    benchmark: dict | None,
    names: dict[str, str] | None,
    sim_mode: str = "position",
) -> None:
    """后台执行协程：跑 worker 池回测并把进度/终态写回任务注册表。"""
    registry = get_task_registry()
    token = CancelToken()
    registry.attach_cancel_token(task_id, token)
    registry.mark_running(task_id)
    try:
        result = await run_backtest_in_worker(
            symbols, strategy_id, start, end,
            params=params, config=cfg, user_id=user_id, benchmark=benchmark,
            names=names, sim_mode=sim_mode,
            progress_cb=lambda p: registry.set_progress(task_id, p),
            cancel_token=token,
        )
    except BacktestCancelledError:
        # cancel() 已把状态置为 cancelled（终态不可逆）；此分支是兜底
        registry.mark_cancelled(task_id)
    except BacktestWorkerError as e:
        logger.warning("任务化回测 worker 失败（task=%s）：%s", task_id, e)
        registry.mark_failed(task_id, str(e))
    except Exception as e:  # 预拉等主进程侧异常同样结构化入终态，绝不泄漏到事件循环
        logger.exception("任务化回测主流程异常（task=%s）", task_id)
        registry.mark_failed(task_id, f"回测主流程异常：{e}")
    else:
        registry.mark_done(task_id, result)


@app.post("/api/backtest/run", status_code=202)
async def api_backtest_run(req: BacktestRequest,
                           user_id: str = Depends(current_user_id)) -> dict:
    """任务化回测：登记任务 + 后台跑 worker 池，立即返回 {"task_id"}。

    预拉（benchmark/names/分钟K）在登记前完成（与同步版同口径：失败即 4xx/降级，
    不留半成品任务）；真正的重计算在后台协程，客户端经 task 接口轮询。
    """
    from app.engine import MatcherConfig
    from app.universe import resolve_universe
    reg = _registry(user_id)
    if req.strategy_id not in {s.strategy_id for s in reg.all()}:
        raise HTTPException(status_code=404, detail=f"策略不存在 {req.strategy_id!r}")
    try:
        symbols = await resolve_universe(req.symbols, req.universe)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    cfg = MatcherConfig(
        initial_capital=req.initial_capital,
        max_positions=req.max_positions,
        commission_pct=req.commission_pct,
        stamp_tax_pct=req.stamp_tax_pct,
        slippage_bps=req.slippage_bps,
        minute_fill=req.minute_fill,
        exit_fill=req.exit_fill,
    )
    end = req.end or date.today()
    # 冷启动修复：登记前在主进程暖日K 缓存（与分钟K 预拉同模式：
    # 主进程回源落盘，worker 子进程只读缓存）；失败降级不阻塞任务登记。
    from app.matrix import build_async
    await build_async(symbols, req.start, end)
    benchmark = await _fetch_benchmark(symbols, req.start, end)
    names = await _fetch_names(symbols)
    # 分钟K 预拉落本地缓存（子进程只读缓存不补拉网络，见 worker._load_minute_cache）；
    # 与 run_backtest_async 同口径：分钟通路故障降级日K，不阻塞任务登记。
    # 全量模拟（sim_mode=full）无分钟口径，跳过预拉。
    if req.sim_mode != "full" and (
        cfg.minute_fill or cfg.exit_fill == "signal_next_minute"
    ):
        from app.data.client_minute import get_minute_bars
        try:
            await get_minute_bars(symbols, req.start, end, use_cache=True)
        except Exception as e:
            logger.warning("任务化回测分钟K 预拉失败，分钟口径降级日K：%s", e)

    registry = get_task_registry()
    task = registry.create()
    asyncio.create_task(
        _run_backtest_task(
            task.task_id, symbols, req.strategy_id, req.start, end,
            req.params or None, cfg, user_id, benchmark, names,
            sim_mode=req.sim_mode,
        )
    )
    return {"task_id": task.task_id}


@app.get("/api/backtest/task/{task_id}")
def api_backtest_task_poll(task_id: str, user_id: str = Depends(current_user_id)) -> dict:
    """轮询任务：{status, progress, result?, error?}（断线重连接口）。

    pending/running 带最新逐日进度；done 带完整结果（与 POST /api/backtest
    响应同结构）；failed 带结构化错误；任务不存在/TTL 过期 → 404。
    """
    try:
        return get_task_registry().poll(task_id)
    except UnknownTaskError:
        raise HTTPException(status_code=404, detail=f"回测任务不存在：{task_id!r}")


@app.post("/api/backtest/task/{task_id}/cancel")
def api_backtest_task_cancel(
    task_id: str, user_id: str = Depends(current_user_id)
) -> dict:
    """幂等取消：终态任务返回现状（200）；运行中任务置取消标记并转 cancelled。"""
    try:
        task = get_task_registry().cancel(task_id)
    except UnknownTaskError:
        raise HTTPException(status_code=404, detail=f"回测任务不存在：{task_id!r}")
    return get_task_registry().snapshot(task)


class AIGenerateRequest(BaseModel):
    description: str = Field(min_length=4, max_length=2000)
    # 可选：基于现有策略代码做调整（AI 工作台「选中/导入 → LLM 调整」模式）
    base_code: str | None = Field(default=None, max_length=50_000)


class AITweakRequest(BaseModel):
    """AI 调整请求：以 code 为底稿，按 description 让 LLM 改写。"""
    code: str = Field(min_length=20, max_length=50_000)
    description: str = Field(min_length=4, max_length=2000)


# ---------------------------------------------------------------------------
# 任务化 AI 生成 API（进度 / 断线重连 / 取消）
#
# 动机：AI 生成是「请求-等 LLM 跑完-一次性返回」，Kimi K3 生成长代码常超 60s
# （实测 56s+），nginx/CF 任一环超时都会把连接砍成 504/524。任务化后 POST 秒回
# task_id，LLM 调用在后台协程，客户端轮询拿终态结果——任务脱离连接独立存活，
# 掉线重连轮询即恢复（与任务化回测同语义，复用 BacktestTaskRegistry）。
# 未配置 AI 时登记前直接 200 返回错误（不产生任务，前端按原降级路径展示）。
# ---------------------------------------------------------------------------


async def _run_ai_generate_task(task_id: str, description: str, base_code: str | None = None) -> None:
    """后台执行协程：调 LLM 生成 + 校验（含 repair 重试），终态写回注册表。"""
    from app.ai.generator import AIStrategyGenerator
    registry = get_task_registry()
    token = CancelToken()
    registry.attach_cancel_token(task_id, token)
    registry.mark_running(task_id)
    try:
        if token.is_set():
            registry.mark_cancelled(task_id)
            return
        gen = AIStrategyGenerator()
        result = await gen.generate(description, base_code=base_code)
        # LLM 调用结束后才看到取消标记（协作式取消：不打断进行中的 HTTP 调用，
        # 只丢弃结果——AI 生成无副作用，丢弃即安全）
        if token.is_set():
            registry.mark_cancelled(task_id)
            return
    except Exception as e:  # 绝不把异常泄漏到事件循环
        logger.exception("任务化 AI 生成异常（task=%s）", task_id)
        registry.mark_failed(task_id, f"生成主流程异常：{e}")
        return
    # LLM/校验失败是业务终态（generator 永不抛异常，valid=False 带 error），
    # 不算任务系统故障：done + result.valid=false，前端按原样展示错误文案
    registry.mark_done(task_id, result)


@app.post("/api/ai/generate", status_code=202)
async def api_ai_generate(req: AIGenerateRequest):
    """任务化 AI 生成：登记任务 + 后台跑 LLM，立即返回 {"task_id"}。

    客户端轮询 GET /api/ai/task/{id} 拿终态结果（result 结构与旧同步版一致：
    {valid, code, meta, error}）；取消走 POST /api/ai/task/{id}/cancel（协作式）。
    """
    from app.ai.generator import AIStrategyGenerator
    if not AIStrategyGenerator().enabled:
        return JSONResponse({"valid": False, "error": "AI 未配置（AI_API_KEY 为空）"}, status_code=200)
    task = get_task_registry().create()
    asyncio.create_task(_run_ai_generate_task(task.task_id, req.description, base_code=req.base_code))
    return {"task_id": task.task_id}


@app.post("/api/ai/tweak", status_code=202)
async def api_ai_tweak(req: AITweakRequest):
    """任务化 AI 调整：以请求体 code 为底稿，按 description 让 LLM 改写。

    与 /api/ai/generate 同一任务语义（登记 → 轮询 → 协作式取消），
    区别仅在 prompt 组装：generate 从零生成，tweak 基于现有代码修改。
    """
    from app.ai.generator import AIStrategyGenerator
    if not AIStrategyGenerator().enabled:
        return JSONResponse({"valid": False, "error": "AI 未配置（AI_API_KEY 为空）"}, status_code=200)
    task = get_task_registry().create()
    asyncio.create_task(_run_ai_generate_task(task.task_id, req.description, base_code=req.code))
    return {"task_id": task.task_id}


@app.get("/api/ai/task/{task_id}")
def api_ai_task_poll(task_id: str) -> dict:
    """轮询 AI 生成任务：done 带 result（{valid, code, meta, error}），failed 带 error。"""
    try:
        return get_task_registry().poll(task_id)
    except UnknownTaskError:
        raise HTTPException(status_code=404, detail=f"生成任务不存在：{task_id!r}")


@app.post("/api/ai/task/{task_id}/cancel")
def api_ai_task_cancel(task_id: str) -> dict:
    """幂等取消：运行中任务置取消标记并转 cancelled；终态任务返回现状。"""
    try:
        task = get_task_registry().cancel(task_id)
    except UnknownTaskError:
        raise HTTPException(status_code=404, detail=f"生成任务不存在：{task_id!r}")
    return get_task_registry().snapshot(task)


class AISaveRequest(BaseModel):
    code: str = Field(min_length=20, max_length=50_000)


@app.post("/api/ai/save")
def api_ai_save(req: AISaveRequest, user_id: str = Depends(current_user_id)) -> dict:
    """把 AI 生成且校验通过的策略代码落盘到用户命名空间的 strategies/ai/。

    安全闸：落盘前再过一遍 validator（不信任上游生成结果，接口可被独立调用），
    通过才写盘；文件名取 META["id"]（validator 已保证 ai_ 前缀字面量），
    写后试加载验证可执行。幂等：同 id 覆盖更新。注册表每次请求重建，落盘即热生效。
    """
    result = validate_strategy_code(req.code)
    if not result["valid"]:
        raise HTTPException(status_code=422, detail=f"安全校验未通过：{result['error']}")
    sid = str(result["meta"]["id"])
    # 双保险：文件名只取白名单形态（validator 已保证 ai_ 前缀 + 合法字符）
    if not re.fullmatch(r"ai_[A-Za-z0-9_]{1,60}", sid):
        raise HTTPException(status_code=422, detail=f"策略 id 形态非法：{sid!r}")
    ai_dir = user_strategy_dirs(user_id)["ai"]
    ai_dir.mkdir(parents=True, exist_ok=True)
    path = ai_dir / f"{sid}.py"
    path.write_text(req.code, encoding="utf-8")
    # 落盘后试加载：坏了立即删文件回滚，不留半截策略在注册表里
    try:
        _registry(user_id).get(sid)
    except Exception as e:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"落盘后加载失败（已回滚）：{e}")
    logger.info("AI 策略已保存：%s（user=%s, %s）", sid, user_id, path)
    return {"saved": True, "strategy_id": sid, "name": result["meta"].get("name", sid)}


def _save_strategy_file(user_id: str, code: str, overwrite_id: str | None = None) -> dict:
    """统一策略落盘：validator 全量校验 → 按 id 前缀归位目录 → 写盘 → 试加载。

    - ai_ 前缀进 strategies/ai/，其余进 strategies/custom/（文件名 = META.id）。
    - builtin 策略在镜像内随包发布，永远只读：overwrite_id 命中 builtin 一律 409。
    - overwrite_id 非空且与 META.id 不同时删除旧文件（重命名 = 移动）。
    - 幂等：同 id 覆盖更新；落盘后试加载失败即回滚，不留半截策略。
    """
    result = validate_strategy_code(code)
    if not result["valid"]:
        raise HTTPException(status_code=422, detail=f"安全校验未通过：{result['error']}")
    sid = str(result["meta"]["id"])
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", sid):
        raise HTTPException(status_code=422, detail=f"策略 id 形态非法：{sid!r}")

    dirs = user_strategy_dirs(user_id)
    if overwrite_id:
        try:
            target = _registry(user_id).get(overwrite_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"待覆盖的策略不存在：{overwrite_id!r}")
        if target.source == "builtin":
            raise HTTPException(
                status_code=409,
                detail=f"内置策略 {overwrite_id!r} 只读，请改 META.id 另存为新策略",
            )

    dest_dir = dirs["ai"] if sid.startswith("ai_") else dirs["custom"]
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{sid}.py"
    # 已有同名策略在其他目录（如 ai → custom 前缀变更）时拒绝静默双写，
    # 避免注册表 id 冲突（同 id 两文件会让整个注册表加载报错）。
    for other in (dirs["custom"], dirs["ai"]):
        other_path = other / f"{sid}.py"
        if other_path != path and other_path.exists():
            raise HTTPException(
                status_code=409,
                detail=f"策略 id {sid!r} 已存在于 {other.name}/ 目录，请先删除或改名",
            )

    # 先把既有文件挪到 .bak 占位再写新文件：注册表按 *.py glob 扫描，.bak 不可见；
    # 试加载失败时整体回滚（删新文件、还原旧文件），同 id 覆盖也不丢旧策略。
    # 需要保护的既有文件：目标路径同名文件（同 id 覆盖）+ overwrite_id 指向的旧文件
    # （重命名场景，overwrite 校验已保证其非 builtin）。
    backup_path: Path | None = None
    existing = path if path.exists() else None
    if existing is None and overwrite_id and overwrite_id != sid:
        existing = _registry(user_id).get(overwrite_id).file_path
    if existing is not None:
        backup_path = existing.with_name(existing.name + ".bak")
        existing.rename(backup_path)

    path.write_text(code, encoding="utf-8")
    try:
        _registry(user_id).get(sid)
    except Exception as e:
        path.unlink(missing_ok=True)
        if backup_path is not None:
            try:
                # 剥掉 .bak 还原（Path 无 removesuffix，拼路径避免 with_suffix 歧义）
                backup_path.rename(backup_path.with_name(backup_path.name[:-4]))
            except OSError:
                logger.error("策略旧文件还原失败：%s", backup_path)
        raise HTTPException(status_code=422, detail=f"落盘后加载失败（已回滚）：{e}")
    if backup_path is not None:
        backup_path.unlink(missing_ok=True)
    logger.info(
        "策略已保存：%s（user=%s, %s, overwrite=%s）",
        sid, user_id, path, overwrite_id or "-",
    )
    return {"saved": True, "strategy_id": sid, "name": result["meta"].get("name", sid)}


class StrategySaveRequest(BaseModel):
    code: str = Field(min_length=20, max_length=50_000)
    # 可选：声明本次保存是覆盖/重命名哪个已有策略（AI 工作台编辑保存路径）
    overwrite_id: str | None = Field(default=None, max_length=64)


@app.post("/api/strategies/save")
def api_strategy_save(req: StrategySaveRequest, user_id: str = Depends(current_user_id)) -> dict:
    """AI 工作台统一保存入口：导入/手动编辑/AI 调整后的代码都经此落盘。

    与 /api/ai/save 的区别：不强制 ai_ 前缀（非 ai_ 进 custom/ 目录），
    支持 overwrite_id 声明覆盖/重命名已有策略（builtin 除外）。
    """
    return _save_strategy_file(user_id, req.code, overwrite_id=req.overwrite_id)


@app.get("/api/mining/candidates")
def list_candidates(user_id: str = Depends(current_user_id)) -> list[dict]:
    """候选库列表（pending/published/rejected）。"""
    df = load_candidates(user_id)
    if df.is_empty():
        return []
    return json.loads(df.write_json())


class PublishRequest(BaseModel):
    candidate_id: str


@app.post("/api/mining/publish")
def api_publish(req: PublishRequest, user_id: str = Depends(current_user_id)) -> dict:
    """发布候选为独立策略（唯一发布入口；未达门槛拒绝）。"""
    ok, msg = publish_candidate(req.candidate_id, user_id)
    if not ok:
        return {"published": False, "reason": msg}
    return {"published": True, "reason": msg}


class MiningRequest(_SymbolRequest):
    horizon: int = Field(default=5, ge=1, le=20)
    max_size: int = Field(default=3, ge=1, le=4)
    n_outer: int = Field(default=3, ge=2, le=5)


@app.post("/api/mining/run")
async def api_mining_run(req: MiningRequest, user_id: str = Depends(current_user_id)) -> dict:
    """跑因子挖掘：返回因子 IC + 候选（不入库，入库由前端确认后调 candidates/save）。"""
    from datetime import timedelta
    from app.universe import resolve_universe
    end = req.end or date.today()
    start = req.start or (end - timedelta(days=250))
    try:
        symbols = await resolve_universe(req.symbols, req.universe)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # build/run_mining 是纯 CPU 同步段：全市场矩阵构建分钟级，直接 await 会
    # 卡死事件循环（健康检查一起挂），必须甩到线程池
    return await asyncio.to_thread(_mining_sync, symbols, start, end, req, user_id)


def _mining_sync(
    symbols: list[str], start: date, end: date, req: MiningRequest, user_id: str
) -> dict:
    """mining 同步段（build → enrich → run_mining），由 api_mining_run 经 to_thread 调用。"""
    from app.matrix import build, enrich

    matrix = build(symbols, start, end)
    if not matrix.dates:
        return {"candidates": [], "factor_ics": {}, "kept_factors": [], "error": "无缓存数据"}
    result = run_mining(enrich(matrix), horizon=req.horizon,
                        max_size=req.max_size, n_outer=req.n_outer,
                        user_id=user_id)
    cands = []
    for c in result.candidates:
        ok, reasons = _gate_of(c)
        cands.append({
            "combo": list(c.combo), "directions": c.directions,
            "valid_folds": c.valid_folds, "oos_sharpe": c.oos_sharpe,
            "oos_max_drawdown": c.oos_max_drawdown, "oos_trades": c.oos_trades,
            "positive_fold_ratio": c.positive_fold_ratio,
            "gate_pass": ok, "gate_reasons": reasons,
            # I2 统计：候选 DSR 通缩夏普（多重试验校正后的夏普显著性）
            "dsr": (result.candidate_dsr or {}).get("+".join(c.combo)),
        })
    return {
        "n_factors": result.n_factors, "kept_factors": result.kept_factors,
        "factor_ics": result.factor_ics, "n_folds": result.n_folds,
        "candidates": cands,
        # I2 统计检验透出：因子 IC 的 NW t/p/BH-FDR q；DSR 试验数
        "factor_ic_stats": result.factor_ic_stats or {},
        "n_trials": result.n_trials,
    }


def _gate_of(c) -> tuple[bool, list[str]]:
    from app.mining import core
    return core.evaluate_gate(c)


class SaveCandidateRequest(BaseModel):
    combo: list[str]
    directions: dict[str, int]
    valid_folds: int = 0
    oos_sharpe: float = 0.0
    oos_max_drawdown: float = 0.0
    oos_trades: int = 0
    positive_fold_ratio: float = 0.0


@app.post("/api/mining/candidates/save")
def api_save_candidate(req: SaveCandidateRequest, user_id: str = Depends(current_user_id)) -> dict:
    """候选入库（pending；发布仍需过门槛 + 显式确认）。"""
    from app.mining import core
    c = core.CandidateResult(combo=tuple(req.combo), directions=req.directions)
    c.folds = [
        core.FoldResult(fold_index=i, combo=c.combo, oos_sharpe=req.oos_sharpe,
                        oos_return=1.0, oos_max_drawdown=req.oos_max_drawdown,
                        oos_trades=req.oos_trades, oos_positive=True)
        for i in range(req.valid_folds)
    ]
    cid = save_candidate(c, user_id)
    return {"candidate_id": cid}


# ---------------------------------------------------------------------------
# 阶段 J4：因子编辑器 API
#
# 契约假设（factors 模块由 J1-J3 并行开发，见 docs/QUANT-BACKTEST.md 阶段 J）：
#   app.factors.api 提供五个门面函数（全部按 user_id 命名空间隔离）：
#     list_factors(user_id) -> list[dict]   全部可见因子（builtin + 用户 uf_*/cf_*），
#         每项含 FactorSpec 元数据：id/label/group/formula/kind/version/direction/status
#     create_factor(user_id, spec: dict) -> dict
#     compile_preview(user_id, formula: str, kind: str,
#                     members: list | None = None) -> dict
#         {ok, errors: [{code, message, position?}], preview?: {mean, std, min, max,
#          valid_ratio, sample_values: [{date, value}]}}
#     update_factor(user_id, factor_id, patch: dict) -> dict   公式变更 version+1
#     delete_factor(user_id, factor_id) -> dict
# 未就位时所有 /api/factors* 返回 503 + 明确提示（不 import 崩溃、不 500）。
# ---------------------------------------------------------------------------

_FACTOR_STATUSES = ("draft", "active", "watch", "retired")
_FACTOR_ID_RE = re.compile(r"^(uf|cf)_[A-Za-z0-9][A-Za-z0-9_-]{0,62}$")


class _FactorMember(BaseModel):
    """复合因子成员：id 引用 uf/base/virtual 因子，权重最终归一化。"""

    id: str = Field(min_length=1, max_length=64)
    weight: float = Field(default=1.0)


class FactorCreateRequest(BaseModel):
    id: str = Field(min_length=3, max_length=64)
    label: str = Field(min_length=1, max_length=64)
    group: str = Field(default="自定义", max_length=32)
    kind: str = Field(pattern="^(uf|cf)$")  # uf=DSL 因子 / cf=复合因子
    formula: str = Field(default="", max_length=2000)
    members: list[_FactorMember] | None = Field(default=None, max_length=8)
    direction: int = Field(default=1)  # 1 高好 / -1 低好


class FactorUpdateRequest(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=64)
    group: str | None = Field(default=None, max_length=32)
    formula: str | None = Field(default=None, max_length=2000)
    members: list[_FactorMember] | None = Field(default=None, max_length=8)
    direction: int | None = None
    status: str | None = None  # draft/active/watch/retired


class FactorCompilePreviewRequest(BaseModel):
    formula: str = Field(default="", max_length=2000)
    kind: str = Field(default="uf", pattern="^(uf|cf)$")
    members: list[_FactorMember] | None = Field(default=None, max_length=8)


def _factor_api_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="因子注册表模块（app.factors）未就位，J1-J3 并行开发中",
    )


def _factors_api():
    """惰性加载因子门面；未实现或缺函数时 503（优雅降级，启动不受影响）。"""
    try:
        from app.factors import api as factors_api  # type: ignore
    except Exception:
        raise _factor_api_unavailable()
    for fn in ("list_factors", "create_factor", "compile_preview",
               "update_factor", "delete_factor"):
        if not callable(getattr(factors_api, fn, None)):
            raise _factor_api_unavailable()
    return factors_api


def _validate_factor_payload(kind: str, formula: str,
                             members: list[_FactorMember] | None,
                             direction: int) -> None:
    """入参结构性校验（编译语义校验由 DSL 编译器负责，错误码 E001-E016）。"""
    if kind == "uf":
        if not formula.strip():
            raise HTTPException(status_code=422, detail="DSL 因子必须提供 formula")
    else:  # cf 复合因子
        if not members:
            raise HTTPException(status_code=422, detail="复合因子必须提供成员列表")
        member_ids = [m.id for m in members]
        if len(set(member_ids)) != len(member_ids):
            raise HTTPException(status_code=422, detail="复合因子成员不可重复")
        if any(m.weight <= 0 for m in members):
            raise HTTPException(status_code=422, detail="成员权重必须为正数")
    if direction not in (1, -1):
        raise HTTPException(status_code=422, detail="direction 仅支持 1（高好）或 -1（低好）")


def _spec_of(req: FactorCreateRequest) -> dict:
    return {
        "id": req.id,
        "label": req.label,
        "group": req.group,
        "kind": req.kind,
        "formula": req.formula,
        "members": ([m.model_dump() for m in req.members]
                    if req.members is not None else None),
        "direction": req.direction,
    }


@app.get("/api/factors")
def list_factors(user_id: str = Depends(current_user_id)) -> list[dict]:
    """因子列表：builtin（base/virtual）+ 当前用户的 uf_*/cf_* 自定义因子。"""
    try:
        return list(_factors_api().list_factors(user_id))
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("因子列表读取失败：%s", e)
        return []  # 优雅降级：读失败返回空列表而不是 500


@app.post("/api/factors", status_code=201)
def create_factor(req: FactorCreateRequest,
                  user_id: str = Depends(current_user_id)) -> dict:
    """创建自定义因子：DSL 公式编译验证 → 落盘 → 注册（初始状态 draft）。"""
    if not _FACTOR_ID_RE.fullmatch(req.id):
        raise HTTPException(
            status_code=422,
            detail="id 须以 uf_ 或 cf_ 前缀开头，仅含字母/数字/下划线/连字符",
        )
    expected_prefix = f"{req.kind}_"
    if not req.id.startswith(expected_prefix):
        raise HTTPException(
            status_code=422, detail=f"{req.kind} 因子的 id 必须以 {expected_prefix} 开头"
        )
    _validate_factor_payload(req.kind, req.formula, req.members, req.direction)
    try:
        return dict(_factors_api().create_factor(user_id, _spec_of(req)))
    except HTTPException:
        raise
    except ValueError as e:  # 编译错误/重复 id 等参数级错误 → 400
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/factors/compile-preview")
def compile_preview(req: FactorCompilePreviewRequest,
                    user_id: str = Depends(current_user_id)) -> dict:
    """编译诊断 + 样例数据即时预览（不持久化）。

    返回 {ok, errors: [{code, message, position?}], preview?: {mean, std, min, max,
    valid_ratio, sample_values: [{date, value}]}}；编译失败 ok=false 且 errors 非空，
    HTTP 仍 200（诊断是成功响应，不是异常）。
    """
    if req.kind == "uf" and not req.formula.strip():
        raise HTTPException(status_code=422, detail="formula 不能为空")
    try:
        members = ([m.model_dump() for m in req.members]
                   if req.members is not None else None)
        return dict(_factors_api().compile_preview(
            user_id, req.formula, req.kind, members=members))
    except HTTPException:
        raise
    except Exception as e:  # 编译器红线是结构化错误码，裸异常兜底按未知错误透出
        logger.warning("编译预览失败：%s", e)
        return {"ok": False,
                "errors": [{"code": "E000", "message": f"编译器内部错误：{e}"}],
                "preview": None}


@app.put("/api/factors/{factor_id}")
def update_factor(factor_id: str, req: FactorUpdateRequest,
                  user_id: str = Depends(current_user_id)) -> dict:
    """更新自定义因子（公式/成员变更 version+1；状态机 draft→active→watch→retired）。"""
    if not _FACTOR_ID_RE.fullmatch(factor_id):
        raise HTTPException(status_code=400, detail=f"非法因子 id：{factor_id!r}")
    patch = req.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status_code=422, detail="没有可更新的字段")
    if "status" in patch and patch["status"] not in _FACTOR_STATUSES:
        raise HTTPException(status_code=422,
                            detail=f"非法状态：{patch['status']!r}")
    if "members" in patch and patch["members"] is not None:
        members = [_FactorMember(**m) for m in patch["members"]]
        _validate_factor_payload("cf", "", members, patch.get("direction", 1))
    if "direction" in patch and patch["direction"] not in (1, -1):
        raise HTTPException(status_code=422, detail="direction 仅支持 1（高好）或 -1（低好）")
    try:
        return dict(_factors_api().update_factor(user_id, factor_id, patch))
    except HTTPException:
        raise
    except ValueError as e:
        # 门面对不存在的因子抛 ValueError("因子不存在: ...")，此处区分为 404
        if "不存在" in str(e):
            raise HTTPException(status_code=404, detail=f"因子不存在 {factor_id!r}")
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/factors/{factor_id}")
def delete_factor(factor_id: str, user_id: str = Depends(current_user_id)) -> dict:
    """删除自定义因子（仅 uf_*/cf_* 用户因子；builtin 不可删）。"""
    if not _FACTOR_ID_RE.fullmatch(factor_id):
        raise HTTPException(status_code=400,
                            detail=f"内置因子不可删除：{factor_id!r}")
    try:
        _factors_api().delete_factor(user_id, factor_id)
        return {"deleted": True, "id": factor_id}
    except HTTPException:
        raise
    except KeyError:
        raise HTTPException(status_code=404, detail=f"因子不存在 {factor_id!r}")


# ---------------------------------------------------------------------------
# 阶段 M1：参数优化 / 敏感性 / walk-forward API（runner 三入口的 HTTP 透出）
#
# 三个端点共享的纪律：
# - universe 展开与 api_screen/api_backtest 同口径（resolve_universe，显式 symbols 优先）。
# - objective 校验前置在路由层（VALID_OBJECTIVES 白名单，非法直接 422），
#   其他参数错误由 optimizer/walkforward 抛 ValueError 统一转 422，detail 带原因。
# - 未知策略等引擎侧 KeyError 转 404；其余异常结构化 500（不走全局兜底，
#   与因子 API 的 except 分层一致）。
# - run_optimize/run_sensitivity/run_walkforward 内部已自选 worker 池/进程内
#   执行路径（按组合数），路由层直接 await，不重复造派发逻辑。
# ---------------------------------------------------------------------------


class _OptimizeBaseRequest(_SymbolRequest):
    """优化系端点公共入参：复用 _SymbolRequest 的 symbols/universe/start/end 定义。"""

    strategy_id: str
    start: date  # 优化必填起点（覆盖 _SymbolRequest 的可选 start）
    end: date  # 优化必填终点（不回退 today，网格扫描区间须显式）
    param_grid: dict[str, Any]
    objective: str = "sharpe"
    direction: str | None = Field(default=None, pattern="^(min|max)$")
    base_params: dict[str, Any] = Field(default_factory=dict)


class OptimizeRequest(_OptimizeBaseRequest):
    pass


class SensitivityRequest(_OptimizeBaseRequest):
    param_id: str = Field(min_length=1, max_length=64)  # 被扰动的参数


class WalkForwardRequest(_OptimizeBaseRequest):
    train_days: int = Field(default=252, ge=1, le=3650)  # 日历天数（非交易日）
    test_days: int = Field(default=63, ge=1, le=3650)
    step_days: int = Field(default=63, ge=1, le=3650)


def _validate_objective(objective: str) -> None:
    """优化目标白名单前置校验：非法值 422（detail 列出合法集供排查）。"""
    from app.engine.optimizer import VALID_OBJECTIVES
    if objective not in VALID_OBJECTIVES:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的优化目标 {objective!r}，可选：{sorted(VALID_OBJECTIVES)}",
        )


async def _run_optimize_route(
    req: _OptimizeBaseRequest, user_id: str, runner_fn_name: str, **extra_kwargs
) -> dict:
    """优化系路由公共骨架：universe 展开 → 校验 → 调 runner → 错误分层转换。"""
    from app import runner as quant_runner
    from app.universe import resolve_universe

    _validate_objective(req.objective)
    try:
        symbols = await resolve_universe(req.symbols, req.universe)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # 前置校验（同步、无网络）：grid 非法/组合爆炸/分钟频策略等尽早 4xx，
    # 不做无谓的暖缓存补拉；与 runner 入口校验同源（validate_optimize_request）。
    try:
        quant_runner.validate_optimize_request(
            _registry(user_id), req.strategy_id, req.param_grid,
            param_id=extra_kwargs.get("param_id"),
        )
    except KeyError as e:  # 未知策略 → 404
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:  # grid 非法/组合爆炸/分钟频策略等 → 422
        raise HTTPException(status_code=422, detail=str(e))
    # 冷启动修复：worker 子进程与进程内串行都只读本地日K 缓存，
    # 缺失标的必须在这里（主进程）经 build_async 补拉落盘，
    # 否则缓存目录为空时全部组合零成交；补拉失败降级不阻塞（runner 层照常跑）。
    from app.matrix import build_async
    await build_async(symbols, req.start, req.end)
    runner_fn = getattr(quant_runner, runner_fn_name)
    try:
        return await runner_fn(
            symbols,
            req.strategy_id,
            req.start,
            req.end,
            req.param_grid,
            objective=req.objective,
            direction=req.direction,
            base_params=req.base_params or None,
            registry=_registry(user_id),
            user_id=user_id,
            **extra_kwargs,
        )
    except HTTPException:
        raise
    except KeyError as e:  # 未知策略等引擎侧查找失败 → 404
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:  # 参数错误（grid 非法/组合爆炸/param_id 缺失等）→ 422
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # 其余异常结构化 500，不走全局兜底
        logger.exception("%s 执行异常", runner_fn_name)
        raise HTTPException(status_code=500, detail=f"{runner_fn_name} 执行异常：{e}")


@app.post("/api/optimize")
async def api_optimize(req: OptimizeRequest,
                       user_id: str = Depends(current_user_id)) -> dict:
    """参数网格扫描：遍历组合各跑一次回测，按 objective 排名返回最优参数。"""
    return await _run_optimize_route(req, user_id, "run_optimize")


@app.post("/api/sensitivity")
async def api_sensitivity(req: SensitivityRequest,
                          user_id: str = Depends(current_user_id)) -> dict:
    """敏感性分析：固定其他参数，对 param_id 单参数扰动扫目标指标曲线。"""
    return await _run_optimize_route(req, user_id, "run_sensitivity",
                                     param_id=req.param_id)


@app.post("/api/walkforward")
async def api_walkforward(req: WalkForwardRequest,
                          user_id: str = Depends(current_user_id)) -> dict:
    """Walk-forward：滚动训练/测试折，样本外拼接净值（train/test/step 为日历天数）。"""
    return await _run_optimize_route(
        req, user_id, "run_walkforward",
        train_days=req.train_days, test_days=req.test_days, step_days=req.step_days,
    )
