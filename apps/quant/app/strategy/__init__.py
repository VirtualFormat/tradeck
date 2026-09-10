"""策略体系：META 规范 + 加载器 + 内置策略。"""

from app.strategy.base import StrategyContext, StrategySignals, empty_signals
from app.strategy.composite import (
    MAX_COMPOSITE_CHILDREN,
    CompositeChildResult,
    merge_screen_results,
    merge_signal_matrices,
)
from app.strategy.loader import StrategyDef, StrategyRegistry

__all__ = [
    "StrategyContext", "StrategySignals", "empty_signals",
    "StrategyDef", "StrategyRegistry",
    "MAX_COMPOSITE_CHILDREN", "CompositeChildResult",
    "merge_screen_results", "merge_signal_matrices",
]
