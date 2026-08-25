"""因子挖掘：RankIC / 去重 / beam 组合 / 嵌套样本外 / 候选库（发布显式确认纪律）。"""

from app.mining import core
from app.mining.factors import FACTOR_META, factor_catalog
from app.mining.runtime import (
    MiningRunResult, load_candidates, publish_candidate, run_mining, save_candidate,
)

__all__ = [
    "core", "FACTOR_META", "factor_catalog", "MiningRunResult",
    "run_mining", "save_candidate", "load_candidates", "publish_candidate",
]
