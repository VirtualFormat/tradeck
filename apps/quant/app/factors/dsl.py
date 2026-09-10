"""因子公式 DSL 编译器（J2）— numpy 矩阵版。

流水线：text → tokenizer → 递归下降解析 → AST → 语义检查 → 依赖/预热推导
→ 编译为对 EnrichedMatrix 求值的矩阵运算函数。编译失败返回结构化错误
（E001-E016），不抛裸异常；语义与算子表照搬 tick-stock-panel factors/dsl.py，
代码生成目标从 Polars Expr 换成 numpy (dates × symbols) 矩阵操作。

矩阵语义约定：
- 时序算子 ts_*：沿 dates 轴（axis 0）对每个 symbol 列做 rolling，
  窗口右端含当日（rolling 语义，只向后看，防未来函数）；ts_delay 只能向后看。
- 截面算子 rank/zscore/winsorize：沿 symbols 轴（axis 1）对当日截面运算。
- 窗口内任一 NaN 则该期 NaN（与 enriched 层口径一致，绝不 0 填充）。

编译期红线（照搬参照）：
- ts_* 负 shift 拒绝（E005，负数即未来函数）；
- 截面算子禁嵌时序窗口内（E009，如 ts_mean(rank(x), 5)）；
- AST 深度 / token 数 / 窗口 / power 指数 / winsorize k 硬上限；
- 除数静态为常量 0 拒绝（E008）；公式必须引用至少一个数据列或因子（E016）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from app.factors.registry import factor_dependencies, get_user_factor

# 基准列白名单：OHLCV 基准列 + enriched 指标列（== 注册表 base 因子全集）
BASE_COLUMNS: frozenset[str] = frozenset(
    {"open", "high", "low", "close", "volume", "amount"}
    | {
        "ma5", "ma10", "ma20", "ma60", "ema12", "ema26",
        "macd_dif", "macd_dea", "macd_hist", "rsi14",
        "boll_upper", "boll_lower",
        "momentum_5d", "momentum_20d", "vol_ratio_5d",
        "high_20d", "low_20d",
    }
)

MAX_AST_DEPTH = 12
MAX_TOKENS = 200
WINDOW_MIN, WINDOW_MAX = 2, 512
DELAY_MAX = 512
POWER_ABS_MAX = 4.0
WINSORIZE_K_RANGE = (1.0, 6.0)

# 算子表：名 -> (表达式参数个数, 常量参数名元组)；常量参数必须是数字字面量（E003）。
OPERATORS: dict[str, tuple[int, tuple[str, ...]]] = {
    "ts_mean": (1, ("n",)),
    "ts_std": (1, ("n",)),
    "ts_sum": (1, ("n",)),
    "ts_max": (1, ("n",)),
    "ts_min": (1, ("n",)),
    "ts_delay": (1, ("n",)),
    "ts_delta": (1, ("n",)),
    "ts_rank": (1, ("n",)),
    "ts_zscore": (1, ("n",)),
    "ts_corr": (2, ("n",)),
    "ts_cov": (2, ("n",)),
    "ts_quantile": (1, ("n", "q")),
    "decay_linear": (1, ("n",)),
    "rank": (1, ()),
    "zscore": (1, ()),
    "winsorize": (1, ("k",)),  # k 可省略，默认 3
    "power": (1, ("c",)),
    "clamp": (1, ("lo", "hi")),
    "if_else": (3, ()),
    "min": (2, ()),
    "max": (2, ()),
    "log": (1, ()),
    "abs": (1, ()),
    "sign": (1, ()),
    "sqrt": (1, ()),
}
TS_OPERATORS = frozenset({
    "ts_mean", "ts_std", "ts_sum", "ts_max", "ts_min", "ts_delay", "ts_delta",
    "ts_rank", "ts_zscore", "ts_corr", "ts_cov", "ts_quantile", "decay_linear",
})
CROSS_OPERATORS = frozenset({"rank", "zscore", "winsorize"})


@dataclass
class DslError:
    code: str
    message: str
    offset: int = 0
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "position": {"offset": self.offset, "line": 1},
            "detail": self.detail,
        }


# 求值函数签名：(matrix, get_col) -> np.ndarray
# matrix 为 EnrichedMatrix（只读），get_col 额外解析复合/自定义因子列。
Evaluator = Callable[[Any, Callable[[str], np.ndarray]], np.ndarray]


@dataclass
class CompiledFormula:
    ok: bool
    errors: list[DslError] = field(default_factory=list)
    evaluator: Evaluator | None = None  # 缺列时抛 KeyError，调用方 fail-closed
    dependencies: frozenset[str] = frozenset()  # 展开到 base 列（矩阵物化层输入清单）
    referenced_factors: frozenset[str] = frozenset()  # 引用的注册因子 id（需物化）
    warmup_bars: int = 1
    cross_sectional: bool = False
    formula_text: str = ""

    def evaluate(self, matrix, get_col=None) -> np.ndarray | None:
        """对 EnrichedMatrix 求值，返回 (dates × symbols) 数组；缺列返回 None（优雅降级）。"""
        if not self.ok or self.evaluator is None:
            return None
        try:
            return self.evaluator(matrix, get_col or _default_get_col(matrix))
        except Exception:
            return None


def _default_get_col(matrix) -> Callable[[str], np.ndarray]:
    def _get(name: str) -> np.ndarray:
        from app.matrix.market import FIELDS

        if name in FIELDS:
            return np.asarray(getattr(matrix.base, name), dtype=np.float64)
        return np.asarray(matrix.indicators[name], dtype=np.float64)

    return _get


# ---------------------------------------------------------------- tokenizer

_TOKEN_RE = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<ident>[A-Za-z_][A-Za-z0-9_]*)|(?P<op>>=|<=|==|!=|[+\-*/><(),]))"
)
_KEYWORDS = frozenset({"and", "or", "not"})


def _tokenize(text: str) -> tuple[list[tuple[str, Any, int]], DslError | None]:
    tokens: list[tuple[str, Any, int]] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if match is None or match.end() == pos:
            rest = text[pos:].strip()
            if not rest:
                break
            return [], DslError("E014", f"语法错误: 无法识别的字符 '{rest[0]}'", offset=pos)
        if match.group("num") is not None:
            tokens.append(("num", float(match.group("num")), match.start("num")))
        elif match.group("ident") is not None:
            tokens.append(("ident", match.group("ident"), match.start("ident")))
        else:
            tokens.append(("op", match.group("op"), match.start("op")))
        pos = match.end()
    return tokens, None


# ------------------------------------------------------------------- parser
# AST 节点: dict(kind, value, children, offset[, _constants])


class _Parser:
    _CMP = frozenset({">", ">=", "<", "<=", "==", "!="})

    def __init__(self, tokens: list[tuple[str, Any, int]], text: str) -> None:
        self.tokens = tokens
        self.text = text
        self.index = 0

    def _peek(self) -> tuple[str, Any, int] | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _next(self) -> tuple[str, Any, int]:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def parse(self) -> tuple[dict | None, DslError | None]:
        if not self.tokens:
            return None, DslError("E014", "语法错误: 表达式为空", offset=0)
        node, error = self._or_expr()
        if error:
            return None, error
        if self._peek() is not None:
            _, value, offset = self._peek()
            return None, DslError("E014", f"语法错误: 多余的记号 '{value}'", offset=offset)
        return node, None

    def _or_expr(self):
        left, error = self._and_expr()
        if error:
            return None, error
        while (token := self._peek()) and token[0] == "ident" and token[1] == "or":
            self._next()
            right, error = self._and_expr()
            if error:
                return None, error
            left = {"kind": "bin", "value": "or", "children": [left, right], "offset": token[2]}
        return left, None

    def _and_expr(self):
        left, error = self._cmp_expr()
        if error:
            return None, error
        while (token := self._peek()) and token[0] == "ident" and token[1] == "and":
            self._next()
            right, error = self._cmp_expr()
            if error:
                return None, error
            left = {"kind": "bin", "value": "and", "children": [left, right], "offset": token[2]}
        return left, None

    def _cmp_expr(self):
        left, error = self._add_expr()
        if error:
            return None, error
        while (token := self._peek()) and token[0] == "op" and token[1] in self._CMP:
            self._next()
            right, error = self._add_expr()
            if error:
                return None, error
            left = {"kind": "bin", "value": token[1], "children": [left, right], "offset": token[2]}
        return left, None

    def _add_expr(self):
        left, error = self._mul_expr()
        if error:
            return None, error
        while (token := self._peek()) and token[0] == "op" and token[1] in ("+", "-"):
            self._next()
            right, error = self._mul_expr()
            if error:
                return None, error
            left = {"kind": "bin", "value": token[1], "children": [left, right], "offset": token[2]}
        return left, None

    def _mul_expr(self):
        left, error = self._unary()
        if error:
            return None, error
        while (token := self._peek()) and token[0] == "op" and token[1] in ("*", "/"):
            self._next()
            right, error = self._unary()
            if error:
                return None, error
            left = {"kind": "bin", "value": token[1], "children": [left, right], "offset": token[2]}
        return left, None

    def _unary(self):
        token = self._peek()
        if token and token[0] == "op" and token[1] == "-":
            self._next()
            operand, error = self._unary()
            if error:
                return None, error
            return {"kind": "unary", "value": "-", "children": [operand], "offset": token[2]}, None
        return self._primary()

    def _primary(self):
        token = self._peek()
        if token is None:
            return None, DslError("E014", "语法错误: 表达式意外结束", offset=len(self.text))
        kind, value, offset = self._next()
        if kind == "num":
            return {"kind": "num", "value": value, "children": [], "offset": offset}, None
        if kind == "ident":
            if value in _KEYWORDS:
                return None, DslError("E014", f"语法错误: 关键字 '{value}' 不能作为操作数", offset=offset)
            nxt = self._peek()
            if nxt and nxt[0] == "op" and nxt[1] == "(":
                return self._call(value, offset)
            return {"kind": "col", "value": value, "children": [], "offset": offset}, None
        if kind == "op" and value == "(":
            inner, error = self._or_expr()
            if error:
                return None, error
            closing = self._peek()
            if not (closing and closing[0] == "op" and closing[1] == ")"):
                return None, DslError("E014", "语法错误: 缺少右括号 ')'", offset=offset)
            self._next()
            return inner, None
        return None, DslError("E014", f"语法错误: 意外的记号 '{value}'", offset=offset)

    def _call(self, name: str, offset: int):
        self._next()  # consume '('
        args: list[dict] = []
        token = self._peek()
        if not (token and token[0] == "op" and token[1] == ")"):
            while True:
                arg, error = self._or_expr()
                if error:
                    return None, error
                args.append(arg)
                token = self._peek()
                if token and token[0] == "op" and token[1] == ",":
                    self._next()
                    continue
                break
        closing = self._peek()
        if not (closing and closing[0] == "op" and closing[1] == ")"):
            return None, DslError("E014", f"语法错误: 函数 '{name}' 缺少右括号", offset=offset)
        self._next()
        return {"kind": "call", "value": name, "children": args, "offset": offset}, None


# ---------------------------------------------------------- semantic checks


def _ast_depth(node: dict) -> int:
    if not node["children"]:
        return 1
    return 1 + max(_ast_depth(child) for child in node["children"])


def _collect_identifiers(node: dict, found: set[str]) -> None:
    if node["kind"] == "col":
        found.add(node["value"])
    for child in node["children"]:
        _collect_identifiers(child, found)


def _const_value(node: dict) -> float | None:
    if node["kind"] == "num":
        return float(node["value"])
    if node["kind"] == "unary" and node["value"] == "-" and node["children"][0]["kind"] == "num":
        return -float(node["children"][0]["value"])
    return None


def _check_call(node: dict, errors: list[DslError]) -> dict[str, float]:
    """检查函数签名与常量参数范围；返回解析出的常量参数表。"""
    name = node["value"]
    args = node["children"]
    if name not in OPERATORS:
        errors.append(DslError("E002", f"未知函数: {name}", offset=node["offset"], detail={"name": name}))
        return {}
    n_expr, const_names = OPERATORS[name]
    has_optional_const = bool(const_names) and name == "winsorize"
    total_min, total_max = n_expr + (0 if has_optional_const else len(const_names)), n_expr + len(const_names)
    if not (total_min <= len(args) <= total_max):
        errors.append(DslError(
            "E003",
            f"函数 {name} 参数数量不符: 期望 {total_min}~{total_max} 个, 实际 {len(args)}",
            offset=node["offset"], detail={"name": name, "args": len(args)},
        ))
        return {}
    constants: dict[str, float] = {}
    for index, const_name in enumerate(const_names):
        if n_expr + index >= len(args):
            break  # 可选常量参数缺省（如 winsorize 的 k），走默认值
        arg = args[n_expr + index]
        value = _const_value(arg)
        if value is None:
            errors.append(DslError(
                "E003", f"函数 {name} 的参数 {const_name} 必须是数字常量",
                offset=arg["offset"], detail={"name": name, "param": const_name},
            ))
            continue
        constants[const_name] = value
    if "n" in constants:
        n_value = constants["n"]
        if n_value != int(n_value):
            errors.append(DslError("E004", "窗口参数必须是整数", offset=node["offset"], detail={"n": n_value}))
        else:
            n_int = int(n_value)
            if n_int < 0 and name in ("ts_delay", "ts_delta"):
                errors.append(DslError(
                    "E005", f"负 shift: {name} 的 n 必须 ≥ 0 (负数即未来函数)",
                    offset=node["offset"], detail={"n": n_int},
                ))
            elif name == "ts_delay" and not (1 <= n_int <= DELAY_MAX):
                errors.append(DslError(
                    "E004", f"ts_delay 的 n 必须在 [1,{DELAY_MAX}] 内",
                    offset=node["offset"], detail={"n": n_int},
                ))
            elif name == "ts_delta" and not (0 <= n_int <= DELAY_MAX):
                errors.append(DslError(
                    "E004", f"ts_delta 的 n 必须在 [0,{DELAY_MAX}] 内",
                    offset=node["offset"], detail={"n": n_int},
                ))
            elif name not in ("ts_delay", "ts_delta") and not (WINDOW_MIN <= n_int <= WINDOW_MAX):
                errors.append(DslError(
                    "E004", f"窗口 n 必须在 [{WINDOW_MIN},{WINDOW_MAX}] 内",
                    offset=node["offset"], detail={"n": n_int},
                ))
    if "q" in constants and not (0.0 < constants["q"] < 1.0):
        errors.append(DslError(
            "E004", "ts_quantile 的 q 必须在 (0,1) 开区间内",
            offset=node["offset"], detail={"q": constants["q"]},
        ))
    if "c" in constants and abs(constants["c"]) > POWER_ABS_MAX:
        errors.append(DslError(
            "E010", f"power 指数 |c| ≤ {POWER_ABS_MAX}",
            offset=node["offset"], detail={"c": constants["c"]},
        ))
    if "k" in constants and not (WINSORIZE_K_RANGE[0] <= constants["k"] <= WINSORIZE_K_RANGE[1]):
        errors.append(DslError(
            "E011", "winsorize 的 k 必须在 [1,6] 内",
            offset=node["offset"], detail={"k": constants["k"]},
        ))
    if "lo" in constants and "hi" in constants and constants["lo"] > constants["hi"]:
        errors.append(DslError("E003", "clamp 的 lo 不能大于 hi", offset=node["offset"]))
    return constants


def _semantic_walk(node: dict, errors: list[DslError], constants_by_call: dict[int, dict]) -> None:
    if node["kind"] == "call":
        constants_by_call[id(node)] = _check_call(node, errors)
        for child in node["children"]:
            _semantic_walk(child, errors, constants_by_call)
        return
    if node["kind"] == "bin" and node["value"] == "/":
        right = node["children"][1]
        if _const_value(right) == 0:
            errors.append(DslError("E008", "静态除零: 分母为常量 0", offset=right["offset"]))
    for child in node["children"]:
        _semantic_walk(child, errors, constants_by_call)


# --------------------------------------------------- numpy 矩阵原语（求值期）
# 全部对 (T, S) 数组运算：时序沿 axis 0，截面沿 axis 1；NaN 传播，绝不 0 填充。


def _safe_div(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """安全除法：分母 NaN 或 0 → NaN（防 inf 污染下游 rolling）。"""
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a / b
    return np.where(np.isnan(b) | (b == 0), np.nan, out)


def _rolling(arr: np.ndarray, n: int, fn: str, q: float | None = None) -> np.ndarray:
    """窗口右端含当日的 rolling（只向后看）；窗口内任一 NaN 或预热期 → NaN。"""
    out = np.full(arr.shape, np.nan)
    if arr.shape[0] < n:
        return out
    w = sliding_window_view(arr, n, axis=0)  # (T-n+1, S, n)
    valid = ~np.isnan(w).any(axis=2)
    with np.errstate(invalid="ignore"):
        if fn == "mean":
            res = w.mean(axis=2)
        elif fn == "std":
            res = w.std(axis=2)  # ddof=0，与 enriched 层口径一致
        elif fn == "sum":
            res = w.sum(axis=2)
        elif fn == "max":
            res = w.max(axis=2)
        elif fn == "min":
            res = w.min(axis=2)
        elif fn == "quantile":
            res = np.quantile(w, q if q is not None else 0.5, axis=2)
        elif fn == "rank":
            # 当期值在窗口内的分位名次（0~1，窗口右端=当期）：<= 当期值的比例
            res = (w <= w[..., -1:]).mean(axis=2)
        else:
            raise AssertionError(fn)
    out[n - 1:] = np.where(valid, res, np.nan)
    return out


def _shift(arr: np.ndarray, n: int) -> np.ndarray:
    """向后看 n 期（n ≥ 0 已由编译期保证）；前 n 行 NaN。"""
    out = np.full(arr.shape, np.nan)
    if n == 0:
        return arr.copy()
    if arr.shape[0] > n:
        out[n:] = arr[:-n]
    return out


def _ts_zscore(arr: np.ndarray, n: int) -> np.ndarray:
    mean = _rolling(arr, n, "mean")
    std = _rolling(arr, n, "std")
    with np.errstate(invalid="ignore", divide="ignore"):
        out = (arr - mean) / std
    return np.where(np.isnan(std) | (std <= 0), np.nan, out)


def _decay_linear(arr: np.ndarray, n: int) -> np.ndarray:
    """线性衰减加权：近端权重大，权重 n, n-1, ..., 1，总权 n(n+1)/2。"""
    out = np.full(arr.shape, np.nan)
    if arr.shape[0] < n:
        return out
    w = sliding_window_view(arr, n, axis=0)  # 窗口内次序: 远 → 近
    valid = ~np.isnan(w).any(axis=2)
    weights = np.arange(1, n + 1, dtype=np.float64)  # 远端 1，近端 n
    with np.errstate(invalid="ignore"):
        res = (w * weights).sum(axis=2) / float(n * (n + 1) / 2)
    out[n - 1:] = np.where(valid, res, np.nan)
    return out


def _ts_corr_cov(a: np.ndarray, b: np.ndarray, n: int, fn: str) -> np.ndarray:
    out = np.full(a.shape, np.nan)
    if a.shape[0] < n:
        return out
    wa = sliding_window_view(a, n, axis=0)
    wb = sliding_window_view(b, n, axis=0)
    valid = ~(np.isnan(wa).any(axis=2) | np.isnan(wb).any(axis=2))
    with np.errstate(invalid="ignore"):
        ma = wa.mean(axis=2, keepdims=True)
        mb = wb.mean(axis=2, keepdims=True)
        da = wa - ma
        db = wb - mb
        cov = (da * db).mean(axis=2)  # 总体口径 ddof=0
        if fn == "cov":
            res = cov
        else:
            va = (da * da).mean(axis=2)
            vb = (db * db).mean(axis=2)
            denom = np.sqrt(va * vb)
            res = np.where(denom > 0, cov / np.where(denom > 0, denom, 1.0), np.nan)
    out[n - 1:] = np.where(valid, res, np.nan)
    return out


def _cross_rank(arr: np.ndarray) -> np.ndarray:
    """当日截面名次（0~1，average 法处理并列）；NaN 标的保持 NaN 且不参与计数。"""
    n_valid = np.sum(~np.isnan(arr), axis=1, keepdims=True)
    order = np.argsort(np.where(np.isnan(arr), np.inf, arr), axis=1)
    ranks = np.empty_like(arr)
    # argsort 双次应用得平均名次前的原始名次（1 起始，NaN 排末位）
    rows = np.arange(arr.shape[0])[:, None]
    ranks[rows, order] = np.arange(1, arr.shape[1] + 1, dtype=np.float64)[None, :]
    # 并列值取平均名次
    with np.errstate(invalid="ignore"):
        pass
    result = np.full(arr.shape, np.nan)
    # 逐行处理并列（S 通常 ≤ 数千，行循环可接受且语义清晰）
    for t in range(arr.shape[0]):
        row = arr[t]
        valid = ~np.isnan(row)
        if not valid.any():
            continue
        vals = row[valid]
        r = np.empty(vals.shape[0], dtype=np.float64)
        sort_idx = np.argsort(vals, kind="stable")
        r[sort_idx] = np.arange(1, len(vals) + 1, dtype=np.float64)
        # 并列平均
        uniq, inv, counts = np.unique(vals, return_inverse=True, return_counts=True)
        sums = np.zeros(len(uniq))
        np.add.at(sums, inv, r)
        r = sums[inv] / counts[inv]
        out_row = np.full(row.shape, np.nan)
        out_row[valid] = r
        result[t] = out_row
    return np.where(n_valid > 0, result / np.where(n_valid > 0, n_valid, 1), np.nan)


def _cross_zscore(arr: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        mean = np.nanmean(arr, axis=1, keepdims=True)
        std = np.nanstd(arr, axis=1, keepdims=True)  # ddof=0
        out = (arr - mean) / std
    return np.where(np.isnan(std) | (std <= 0), np.nan, out)


def _cross_winsorize(arr: np.ndarray, k: float) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        mean = np.nanmean(arr, axis=1, keepdims=True)
        std = np.nanstd(arr, axis=1, keepdims=True)
    lo = mean - k * std
    hi = mean + k * std
    return np.where(np.isnan(std), np.nan, np.clip(arr, lo, hi))


# ------------------------------------------------------------- code generation
# 每个 AST 节点编译为 evaluator 片段：(matrix, get_col) -> np.ndarray。
# 矩阵模型下天然两阶段物化：时序子树求值成中间数组后再做截面运算，
# 无需 Polars 的 over 上下文管理；编译期 E009 红线照常在语义检查阶段拒绝。

_CMP_FN: dict[str, Callable[[np.ndarray, np.ndarray], np.ndarray]] = {
    ">": lambda a, b: (a > b),
    ">=": lambda a, b: (a >= b),
    "<": lambda a, b: (a < b),
    "<=": lambda a, b: (a <= b),
    "==": lambda a, b: (a == b),
    "!=": lambda a, b: (a != b),
}


def _compile_node(node: dict) -> Evaluator | None:
    kind = node["kind"]
    if kind == "num":
        value = float(node["value"])
        return lambda m, g: np.broadcast_to(value, m.base.shape).astype(np.float64).copy()
    if kind == "col":
        name = node["value"]

        def _col(m, g, _name=name):
            return np.asarray(g(_name), dtype=np.float64)

        return _col
    if kind == "unary":
        operand = _compile_node(node["children"][0])
        if operand is None:
            return None
        return lambda m, g: -operand(m, g)
    if kind == "bin":
        left = _compile_node(node["children"][0])
        right = _compile_node(node["children"][1])
        if left is None or right is None:
            return None
        op = node["value"]
        if op == "+":
            return lambda m, g: left(m, g) + right(m, g)
        if op == "-":
            return lambda m, g: left(m, g) - right(m, g)
        if op == "*":
            return lambda m, g: left(m, g) * right(m, g)
        if op == "/":
            return lambda m, g: _safe_div(left(m, g), right(m, g))
        if op in _CMP_FN:
            fn = _CMP_FN[op]
            # 比较产出 1.0/0.0/NaN（NaN 输入保持 NaN，布尔真值化由 if_else/and/or 处理）

            def _cmp(m, g, _fn=fn):
                a, b = left(m, g), right(m, g)
                mask = np.isnan(a) | np.isnan(b)
                return np.where(mask, np.nan, _fn(a, b).astype(np.float64))

            return _cmp
        if op == "and":
            return lambda m, g: np.where(
                np.isnan(left(m, g)) | np.isnan(right(m, g)), np.nan,
                ((left(m, g) != 0) & (right(m, g) != 0)).astype(np.float64),
            )
        if op == "or":
            return lambda m, g: np.where(
                np.isnan(left(m, g)) | np.isnan(right(m, g)), np.nan,
                ((left(m, g) != 0) | (right(m, g) != 0)).astype(np.float64),
            )
        return None
    if kind == "call":
        return _compile_call(node)
    return None


def _compile_call(node: dict) -> Evaluator | None:
    name = node["value"]
    children = node["children"]
    constants: dict[str, float] = node.get("_constants", {})
    n_expr, _ = OPERATORS[name]

    if name in TS_OPERATORS:
        inner = _compile_node(children[0])
        if inner is None:
            return None
        n = int(constants.get("n", 0))
        if name in ("ts_corr", "ts_cov"):
            second = _compile_node(children[1])
            if second is None:
                return None
            fn = "corr" if name == "ts_corr" else "cov"

            def _corr_cov(m, g, _inner=inner, _second=second, _n=n, _fn=fn):
                return _ts_corr_cov(_inner(m, g), _second(m, g), _n, _fn)

            return _corr_cov
        if name == "ts_delay":
            return lambda m, g, _inner=inner, _n=n: _shift(_inner(m, g), _n)
        if name == "ts_delta":
            return lambda m, g, _inner=inner, _n=n: _inner(m, g) - _shift(_inner(m, g), _n)
        if name == "ts_zscore":
            return lambda m, g, _inner=inner, _n=n: _ts_zscore(_inner(m, g), _n)
        if name == "decay_linear":
            return lambda m, g, _inner=inner, _n=n: _decay_linear(_inner(m, g), _n)
        if name == "ts_rank":
            return lambda m, g, _inner=inner, _n=n: _rolling(_inner(m, g), _n, "rank")
        if name == "ts_quantile":
            q = constants.get("q", 0.5)
            return lambda m, g, _inner=inner, _n=n, _q=q: _rolling(_inner(m, g), _n, "quantile", _q)
        fn = name[3:]  # ts_mean → mean 等
        return lambda m, g, _inner=inner, _n=n, _fn=fn: _rolling(_inner(m, g), _n, _fn)

    if name in CROSS_OPERATORS:
        inner = _compile_node(children[0])
        if inner is None:
            return None
        if name == "rank":
            return lambda m, g, _inner=inner: _cross_rank(_inner(m, g))
        if name == "zscore":
            return lambda m, g, _inner=inner: _cross_zscore(_inner(m, g))
        k = constants.get("k", 3.0)
        return lambda m, g, _inner=inner, _k=k: _cross_winsorize(_inner(m, g), _k)

    if name == "if_else":
        cond = _compile_node(children[0])
        then_f = _compile_node(children[1])
        else_f = _compile_node(children[2])
        if cond is None or then_f is None or else_f is None:
            return None

        def _if_else(m, g, _c=cond, _t=then_f, _e=else_f):
            cond_v = _c(m, g)
            # 条件 NaN → 结果 NaN（不知道走哪个分支时不猜）
            return np.where(np.isnan(cond_v), np.nan, np.where(cond_v != 0, _t(m, g), _e(m, g)))

        return _if_else

    args: list[Evaluator | None] = [_compile_node(children[i]) for i in range(n_expr)]
    if any(arg is None for arg in args):
        return None
    first = args[0]
    assert first is not None
    if name == "log":
        def _log(m, g, _f=first):
            x = _f(m, g)
            with np.errstate(invalid="ignore", divide="ignore"):
                return np.where(x > 0, np.log(np.where(x > 0, x, 1.0)), np.nan)
        return _log
    if name == "abs":
        return lambda m, g, _f=first: np.abs(_f(m, g))
    if name == "sign":
        return lambda m, g, _f=first: np.sign(_f(m, g))
    if name == "sqrt":
        def _sqrt(m, g, _f=first):
            x = _f(m, g)
            with np.errstate(invalid="ignore"):
                return np.where(x >= 0, np.sqrt(np.where(x >= 0, x, 0.0)), np.nan)
        return _sqrt
    if name == "power":
        c = constants.get("c", 1.0)
        def _pow(m, g, _f=first, _c=c):
            with np.errstate(invalid="ignore", over="ignore"):
                return np.power(_f(m, g), _c)
        return _pow
    if name == "clamp":
        lo, hi = constants.get("lo"), constants.get("hi")
        return lambda m, g, _f=first, _lo=lo, _hi=hi: np.clip(_f(m, g), _lo, _hi)
    second = args[1]
    assert second is not None
    if name == "min":
        return lambda m, g, _a=first, _b=second: np.fmin(_a(m, g), _b(m, g))
    if name == "max":
        return lambda m, g, _a=first, _b=second: np.fmax(_a(m, g), _b(m, g))
    return None


def compile_formula(text: str, user_id: str | None = None) -> CompiledFormula:
    """编译公式文本；永不抛异常，失败以 errors 表达（fail-closed）。

    user_id 为编译期命名空间上下文：注册因子引用按「builtin 全局 + 当前
    用户私有」解析；不传 user_id 只解析 builtin（兼容旧的单用户调用）。
    """
    if not isinstance(text, str) or not text.strip():
        return CompiledFormula(ok=False, errors=[DslError("E014", "语法错误: 表达式为空")], formula_text=text)

    tokens, tokenize_error = _tokenize(text)
    errors: list[DslError] = [tokenize_error] if tokenize_error else []
    if len(tokens) > MAX_TOKENS:
        errors.append(DslError("E007", f"规模超限: token 数 {len(tokens)} > {MAX_TOKENS}"))
    if errors:
        return CompiledFormula(ok=False, errors=errors, formula_text=text)

    ast, parse_error = _Parser(tokens, text).parse()
    if parse_error:
        return CompiledFormula(ok=False, errors=[parse_error], formula_text=text)

    if _ast_depth(ast) > MAX_AST_DEPTH:
        errors.append(DslError("E006", f"嵌套深度超限: AST 深度 {_ast_depth(ast)} > {MAX_AST_DEPTH}"))

    identifiers: set[str] = set()
    _collect_identifiers(ast, identifiers)
    if not identifiers:
        errors.append(DslError("E016", "常量表达式: 公式必须引用至少一个数据列或因子"))

    for name in sorted(identifiers):
        if name not in BASE_COLUMNS and get_user_factor(name, user_id) is None:
            errors.append(DslError("E001", f"未知标识符: {name}", detail={"name": name}))

    constants_by_call: dict[int, dict] = {}
    _semantic_walk(ast, errors, constants_by_call)

    # 截面算子禁嵌时序窗口（E009）：AST 树上直接判定，矩阵与 Polars 同红线
    def _contains_cross(node: dict) -> bool:
        if node["kind"] == "call" and node["value"] in CROSS_OPERATORS:
            return True
        return any(_contains_cross(child) for child in node["children"])

    def _reject_cross_in_ts(node: dict) -> None:
        if node["kind"] == "call" and node["value"] in TS_OPERATORS:
            for child in node["children"]:
                if _contains_cross(child):
                    errors.append(DslError(
                        "E009",
                        f"截面算子不能嵌在时序窗口内: {node['value']}(...) 的参数含 rank/zscore/winsorize",
                        offset=node["offset"],
                    ))
                    return
        for child in node["children"]:
            _reject_cross_in_ts(child)

    _reject_cross_in_ts(ast)

    dependencies: set[str] = set()
    referenced_factors: set[str] = set()
    warmup = 1
    cross_sectional = False
    for name in identifiers:
        if name in BASE_COLUMNS:
            dependencies.add(name)
            continue
        spec = get_user_factor(name, user_id)
        if spec is None:
            continue
        referenced_factors.add(name)
        dependencies.update(factor_dependencies([name], user_id))
        warmup = max(warmup, spec.warmup_bars)

    for node_constants in constants_by_call.values():
        n_value = node_constants.get("n")
        if n_value is not None and n_value == int(n_value) and int(n_value) > 0:
            warmup = max(warmup, int(n_value) + 1)

    def _find_cross(node: dict) -> None:
        nonlocal cross_sectional
        if node["kind"] == "call" and node["value"] in CROSS_OPERATORS:
            cross_sectional = True
        for child in node["children"]:
            _find_cross(child)

    _find_cross(ast)

    if errors:
        return CompiledFormula(
            ok=False, errors=errors, dependencies=frozenset(dependencies),
            referenced_factors=frozenset(referenced_factors),
            warmup_bars=warmup, cross_sectional=cross_sectional, formula_text=text,
        )

    # 挂常量表（供代码生成读取窗口/指数等常量参数）
    def _attach(node: dict) -> None:
        if node["kind"] == "call":
            node["_constants"] = constants_by_call.get(id(node), {})
        for child in node["children"]:
            _attach(child)

    _attach(ast)

    evaluator = _compile_node(ast)
    if evaluator is None:
        return CompiledFormula(
            ok=False,
            errors=[DslError("E009", "产出类型非法: 无法编译为数值表达式")],
            dependencies=frozenset(dependencies),
            referenced_factors=frozenset(referenced_factors),
            warmup_bars=warmup, cross_sectional=cross_sectional, formula_text=text,
        )

    return CompiledFormula(
        ok=True,
        errors=[],
        evaluator=evaluator,
        dependencies=frozenset(dependencies),
        referenced_factors=frozenset(referenced_factors),
        warmup_bars=warmup,
        cross_sectional=cross_sectional,
        formula_text=text,
    )


@lru_cache(maxsize=256)
def compile_formula_cached(text: str) -> CompiledFormula:
    """带 LRU 缓存的编译入口；CompiledFormula 为不可变值对象，缓存共享安全。"""
    return compile_formula(text)
