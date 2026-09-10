"""因子体系：注册表（J1）+ DSL 编译器（J2）+ 自定义因子存储（J3）。

设计依据 docs/QUANT-BACKTEST.md v2 §0.5「因子编辑器」；语义照搬
tick-stock-panel backend/app/factors/，编译目标从 Polars Expr 换成
numpy 矩阵（tradeck 引擎是 dates×symbols 二维矩阵，非长表）。
"""

from app.factors.dsl import CompiledFormula, DslError, compile_formula
from app.factors.registry import (
    FactorSpec,
    factor_dependencies,
    get_factor,
    list_factors,
    register_factor,
)

__all__ = [
    "CompiledFormula",
    "DslError",
    "FactorSpec",
    "compile_formula",
    "factor_dependencies",
    "get_factor",
    "list_factors",
    "register_factor",
]
