"""回测引擎：动态复权 + 撮合 + 绩效统计。"""

from app.engine.adjust import forward_adjust
from app.engine.limits import limit_pct
from app.engine.matcher import MatcherConfig, MinuteLoader, SimResult, Trade, simulate
from app.engine.minute_fill import resolve_minute_fill
from app.engine.minute_trigger import (
    MINUTE_EXIT_TRIGGER_SIGNALS,
    build_minute_exit_reference,
    resolve_minute_exit_trigger,
    unsupported_minute_exit_signals,
)
from app.engine.stats import compute

__all__ = [
    "forward_adjust", "limit_pct", "MatcherConfig", "MinuteLoader", "SimResult",
    "Trade", "simulate", "compute",
    "resolve_minute_fill", "MINUTE_EXIT_TRIGGER_SIGNALS",
    "build_minute_exit_reference", "resolve_minute_exit_trigger",
    "unsupported_minute_exit_signals",
]
