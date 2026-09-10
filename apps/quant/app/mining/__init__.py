"""因子挖掘：RankIC / 去重 / beam 组合 / 防泄漏嵌套样本外 / 统计检验 / 候选库（发布显式确认纪律）。"""

from app.mining import core
from app.mining import stats
from app.mining.factors import (
    FACTOR_META, active_user_factors, factor_catalog, user_factor_meta,
)
from app.mining.runtime import (
    MiningRunResult, load_candidates, publish_candidate, run_mining, save_candidate,
)

__all__ = [
    "core", "stats", "FACTOR_META", "factor_catalog", "MiningRunResult",
    "active_user_factors", "user_factor_meta",
    "run_mining", "save_candidate", "load_candidates", "publish_candidate",
]
