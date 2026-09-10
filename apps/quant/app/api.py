"""quant HTTP 服务 — 策略/选股/回测/AI 生成/挖掘的统一出口（web 经 Next 代理消费）。

设计（docs/QUANT-BACKTEST.md 阶段 E）：
- 轻量 FastAPI，单进程（与引擎纪律一致），仅经 data-api 读数，绝不直连 DB。
- 消费方身份：出站调 data-api 时带 X-Service-Token（见 data/client）。
- 优雅降级：策略执行/数据缺失返回空结果，不 500；参数错返回 4xx。
- 多用户骨架（G4）：X-User-Id 头贯穿到策略目录/候选库/信号表（命名空间隔离），
  缺省回落 QUANT_DEFAULT_USER；重计算（回测）走 spawn 子进程池（app.worker）。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

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
from app.worker import BacktestWorkerError, run_backtest_in_worker

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


class _SymbolRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=500)
    start: date | None = None
    end: date | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class ScreenRequest(_SymbolRequest):
    strategy_id: str
    limit: int = Field(default=100, ge=1, le=500)


@app.post("/api/screen")
def api_screen(req: ScreenRequest, user_id: str = Depends(current_user_id)) -> dict:
    """选股：返回最新交易日截面入选标的（score 降序）。"""
    reg = _registry(user_id)
    try:
        res = screen(req.strategy_id, req.symbols, end_date=req.end,
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
    initial_capital: float = Field(default=1_000_000.0, gt=0)
    max_positions: int = Field(default=10, ge=1, le=100)
    commission_pct: float | None = Field(default=None, ge=0, le=0.01)  # 佣金率覆盖（小数）


@app.post("/api/backtest")
async def api_backtest(req: BacktestRequest, user_id: str = Depends(current_user_id)) -> dict:
    """回测：数据→矩阵→复权→策略→撮合→统计（G4 起走 spawn 子进程池，主进程不崩）。"""
    from app.engine import MatcherConfig
    reg = _registry(user_id)
    if req.strategy_id not in {s.strategy_id for s in reg.all()}:
        raise HTTPException(status_code=404, detail=f"策略不存在 {req.strategy_id!r}")
    cfg = MatcherConfig(
        initial_capital=req.initial_capital,
        max_positions=req.max_positions,
        commission_pct=req.commission_pct,
    )
    end = req.end or date.today()
    benchmark = await _fetch_benchmark(req.symbols, req.start, end)
    names = await _fetch_names(req.symbols)
    try:
        return await run_backtest_in_worker(
            req.symbols, req.strategy_id, req.start, end,
            params=req.params or None, config=cfg, user_id=user_id, benchmark=benchmark,
            names=names,
        )
    except BacktestWorkerError as e:
        # 子进程失败 → 结构化错误（不 500；与全局优雅降级口径一致）
        logger.warning("回测 worker 失败：%s", e)
        return {"error": str(e), "stats": None, "trades": [], "equity_curve": []}


class AIGenerateRequest(BaseModel):
    description: str = Field(min_length=4, max_length=2000)


@app.post("/api/ai/generate")
async def api_ai_generate(req: AIGenerateRequest):
    """AI 生成策略（轻量 JSON 条件 / 完整策略代码）。未配置 AI 时返回降级说明。"""
    from app.ai.generator import AIStrategyGenerator
    gen = AIStrategyGenerator()
    if not gen.enabled:
        return JSONResponse({"valid": False, "error": "AI 未配置（AI_API_KEY 为空）"}, status_code=200)
    result = await gen.generate(req.description)
    return result


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
def api_mining_run(req: MiningRequest) -> dict:
    """跑因子挖掘：返回因子 IC + 候选（不入库，入库由前端确认后调 candidates/save）。"""
    from datetime import timedelta
    from app.matrix import build, enrich
    end = req.end or date.today()
    start = req.start or (end - timedelta(days=250))
    matrix = build(req.symbols, start, end)
    if not matrix.dates:
        return {"candidates": [], "factor_ics": {}, "kept_factors": [], "error": "无缓存数据"}
    result = run_mining(enrich(matrix), horizon=req.horizon,
                        max_size=req.max_size, n_outer=req.n_outer)
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
