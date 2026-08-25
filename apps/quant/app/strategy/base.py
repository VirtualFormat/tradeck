"""策略协议 — 策略 = 单 Python 文件 + 顶层 META 字面量 + 信号计算函数。

与 tick-stock-panel 的双后端（polars_expr 选股 / matrix_native 回测）不同，
tradeck 统一为**信号矩阵产出**：一个策略同时喂选股（取最后一日信号 + 评分）
与回测（全历史信号进 engine/matcher），无双后端历史包袱。

策略文件约定（手写与 AI 生成共用）：
- META：顶层字面量 dict（见 loader.META_SCHEMA 校验）。
- compute(enriched, params) -> StrategySignals：策略唯一入口，纯函数。
- 铁律：策略只读注入的 EnrichedMatrix，禁网络/DB/文件写（AI 安全闸强制，
  手写策略 review 把关）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.matrix import EnrichedMatrix


@dataclass
class StrategySignals:
    """策略计算输出：与矩阵同形状 (dates × symbols) 的信号 + 评分。

    entry/exit 为 bool 矩阵（True=当日收盘产生信号）；score 为当日评分
    （选股排序用，通常只在信号日有意义，其余可 NaN）。
    """
    entry: np.ndarray
    exit: np.ndarray
    score: np.ndarray


@dataclass
class StrategyContext:
    """一次策略调用的输入（不可变，策略只读）。"""
    enriched: EnrichedMatrix
    params: dict = field(default_factory=dict)

    @property
    def shape(self) -> tuple[int, int]:
        return self.enriched.base.shape


def empty_signals(shape: tuple[int, int]) -> StrategySignals:
    """全 False / 全 NaN 的空信号（策略降级或热身期用）。"""
    return StrategySignals(
        entry=np.zeros(shape, dtype=bool),
        exit=np.zeros(shape, dtype=bool),
        score=np.full(shape, np.nan),
    )
