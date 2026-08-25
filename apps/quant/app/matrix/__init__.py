"""市场矩阵：时间 × 标的列存，选股/回测/挖掘共享缓存。"""

from app.matrix.enriched import EnrichedMatrix, enrich
from app.matrix.market import MarketMatrix, build

__all__ = ["MarketMatrix", "build", "EnrichedMatrix", "enrich"]
