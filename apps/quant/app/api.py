"""quant HTTP 服务 — 策略/选股/回测/AI 生成/挖掘的统一出口（web 经 Next 代理消费）。

设计（docs/QUANT-BACKTEST.md 阶段 E）：
- 轻量 FastAPI，单进程（与引擎纪律一致），仅经 data-api 读数，绝不直连 DB。
- 消费方身份：出站调 data-api 时带 X-Service-Token（见 data/client）。
- 优雅降级：策略执行/数据缺失返回空结果，不 500；参数错返回 4xx。
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.mining import load_candidates, publish_candidate, run_mining
from app.mining.runtime import save_candidate
from app.runner import _default_strategy_dirs, run_backtest_async
from app.screener import screen
from app.strategy import StrategyRegistry

logger = logging.getLogger(__name__)

app = FastAPI(title="tradeck quant", version="0.1.0")


def _registry() -> StrategyRegistry:
    """每次请求重建注册表（策略文件热加载；注册表本身轻量，扫描三层目录）。"""
    return StrategyRegistry(_default_strategy_dirs())


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/strategies")
def list_strategies() -> list[dict]:
    """列出全部策略（含 params schema，供前端自动生成参数表单）。"""
    reg = _registry()
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
def api_screen(req: ScreenRequest) -> dict:
    """选股：返回最新交易日截面入选标的（score 降序）。"""
    reg = _registry()
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


@app.post("/api/backtest")
async def api_backtest(req: BacktestRequest) -> dict:
    """回测：数据→矩阵→复权→策略→撮合→统计。"""
    from app.engine import MatcherConfig
    reg = _registry()
    if req.strategy_id not in {s.strategy_id for s in reg.all()}:
        raise HTTPException(status_code=404, detail=f"策略不存在 {req.strategy_id!r}")
    cfg = MatcherConfig(initial_capital=req.initial_capital, max_positions=req.max_positions)
    end = req.end or date.today()
    return await run_backtest_async(req.symbols, req.strategy_id, req.start, end,
                                    params=req.params or None, config=cfg, registry=reg)


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
def list_candidates() -> list[dict]:
    """候选库列表（pending/published/rejected）。"""
    df = load_candidates()
    if df.is_empty():
        return []
    return json.loads(df.write_json())


class PublishRequest(BaseModel):
    candidate_id: str


@app.post("/api/mining/publish")
def api_publish(req: PublishRequest) -> dict:
    """发布候选为独立策略（唯一发布入口；未达门槛拒绝）。"""
    ok, msg = publish_candidate(req.candidate_id)
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
        })
    return {
        "n_factors": result.n_factors, "kept_factors": result.kept_factors,
        "factor_ics": result.factor_ics, "n_folds": result.n_folds,
        "candidates": cands,
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
def api_save_candidate(req: SaveCandidateRequest) -> dict:
    """候选入库（pending；发布仍需过门槛 + 显式确认）。"""
    from app.mining import core
    c = core.CandidateResult(combo=tuple(req.combo), directions=req.directions)
    c.folds = [
        core.FoldResult(fold_index=i, combo=c.combo, oos_sharpe=req.oos_sharpe,
                        oos_return=1.0, oos_max_drawdown=req.oos_max_drawdown,
                        oos_trades=req.oos_trades, oos_positive=True)
        for i in range(req.valid_folds)
    ]
    cid = save_candidate(c)
    return {"candidate_id": cid}
