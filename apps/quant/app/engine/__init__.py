"""回测引擎：动态复权 + 撮合 + 绩效统计。"""

from app.engine.adjust import forward_adjust
from app.engine.limits import limit_pct
from app.engine.matcher import MatcherConfig, SimResult, Trade, simulate
from app.engine.stats import compute

__all__ = ["forward_adjust", "limit_pct", "MatcherConfig", "SimResult", "Trade", "simulate", "compute"]
