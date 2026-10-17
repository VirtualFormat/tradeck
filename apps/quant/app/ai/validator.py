"""AI 生成代码的 ast 安全闸 —— AI 策略进入 strategy/ai/ 目录前的第一道防线。

设计要点（tradeck 协议版，非 tick-stock-panel 照抄）：
- 白名单而非黑名单：import 只允许策略协议所需的最小集合
  （polars/numpy/datetime + from app.strategy.base / from app.matrix），
  其余一律拒。黑名单挡不住 ctypes/importlib/pickle 等未列出的模块。
- 禁 dunder 读取：保守起见，一切以 __ 开头的属性读取一律拒（含 __name__、
  __doc__ 这类本身无害的）——AI 生成的策略没有任何合法理由读 dunder，
  宁可误伤也不留口子。禁的是「读取」，模块的 __name__ 变量解析本身不受影响
  （Name 节点与 Attribute 不同）。
- 字符串下标拦截：x["__class__"] / x["__bases__"] / x["__subclasses__"] 等
  绕过属性检查的经典逃逸，按字符串常量下标逐个拦。
- 危险调用按名称拦：eval/exec/compile/open/__import__/getattr(动态属性跳板)/
  globals/locals/vars/dir/input/breakpoint/setattr/delattr。
- META 在 ast 层做纯字面量校验（ast.literal_eval，不执行代码），
  必填 id/name，scoring 字段必须落在 loader.ALLOWED_SCORING_FIELDS。
- 必须定义顶层 compute 函数（async 也接受，loader 侧再校验签名）。

已知边界（不是真沙箱）：ast 白名单拦不住「构造超长字符串耗尽内存」这类
纯计算 DoS，也拦不住 numpy 自身的危险子模块被显式 import 之外的间接路径——
真正的隔离要靠后续在受限子进程执行策略（见 docs/QUANT-BACKTEST.md）。
"""
from __future__ import annotations

import ast
import logging
from typing import Any

from app.strategy.loader import ALLOWED_SCORING_FIELDS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# import 白名单
# ---------------------------------------------------------------------------

# 顶层模块白名单：import X / from X import Y 的 X（或 X 的首段）必须在此集合。
# 策略协议只需：polars（矩阵表达式）、numpy（数组计算）、datetime（日期参数）、
# __future__（注解延迟求值）；app.strategy.base / app.matrix 走 from-import 特例。
_ALLOWED_TOP_MODULES = frozenset({"polars", "numpy", "datetime", "__future__"})

# 允许的 from-import 完整模块路径（tradeck 策略协议入口与矩阵协议）。
_ALLOWED_FROM_MODULES = frozenset({"app.strategy.base", "app.matrix"})

# ---------------------------------------------------------------------------
# 危险名称清单
# ---------------------------------------------------------------------------

# 按名称拦截的危险内建调用（跳板函数 getattr/setattr 一并拦掉：
# getattr(x, "_"*2+"class"+"__") 能绕过静态 dunder 检查）。
_FORBIDDEN_CALL_NAMES = frozenset({
    "eval", "exec", "compile", "__import__", "open", "input",
    "globals", "locals", "vars", "dir", "getattr", "setattr", "delattr",
    "breakpoint", "exit", "quit", "help",
})

# 保守起见，一切下划线前缀（_ 或 __ 开头）的属性读取/字符串下标都拒：
# 策略代码无合法用途访问内部属性，且 Python 名称改写也保护 __class 这类
# 单下双下混合写法（类内 __class 会被改写为 _ClassName__class）。
def _is_dunder(s: str) -> bool:
    return s.startswith("_")


# ---------------------------------------------------------------------------
# 单项检查
# ---------------------------------------------------------------------------


def _check_imports(tree: ast.Module) -> str | None:
    """import 白名单检查；返回错误描述或 None。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                if top not in _ALLOWED_TOP_MODULES:
                    return (
                        f"禁止 import {alias.name}：不在策略安全白名单"
                        f"（仅允许 polars / numpy / datetime）"
                    )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.split(".", 1)[0] in _ALLOWED_TOP_MODULES:
                continue
            if mod in _ALLOWED_FROM_MODULES:
                continue
            return (
                f"禁止 from {mod or '(相对导入)'} import：不在策略安全白名单"
                f"（仅允许 from app.strategy.base / from app.matrix）"
            )
    return None


def _check_dangerous_calls(tree: ast.Module) -> str | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _FORBIDDEN_CALL_NAMES:
                return f"禁止调用 {func.id}()：策略不得执行动态代码或访问系统资源"
            # getattr 的属性写法已在 dunder 检查里拦；这里补 type(x)(...) 这类
            # 无名称调用不拦——它本身不构成逃逸，逃逸口在 dunder/下标。
    return None


def _check_dunder_escape(tree: ast.Module) -> str | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _is_dunder(node.attr):
            return f"禁止访问内部属性 {node.attr}：策略不允许反射遍历逃逸"
        if isinstance(node, ast.Subscript):
            sl = node.slice
            if (
                isinstance(sl, ast.Constant)
                and isinstance(sl.value, str)
                and _is_dunder(sl.value)
            ):
                return (
                    f"禁止下标访问 {sl.value!r}：策略不允许反射遍历逃逸"
                )
    return None


def _find_top_level_assign(tree: ast.Module, name: str) -> ast.expr | None:
    """找顶层 name = ... / name: dict = ... 的赋值表达式（找不到返 None）。"""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return node.value
    return None


def _check_meta(tree: ast.Module) -> tuple[str | None, dict]:
    """META 字面量校验；返回 (错误描述或 None, 解析出的 meta dict)。"""
    value = _find_top_level_assign(tree, "META")
    if value is None:
        return "缺少顶层 META = {...} 字面量 dict（AI 策略元数据必填）", {}
    if not isinstance(value, ast.Dict):
        return "META 必须是顶层字面量 dict（不得用函数调用或变量拼接）", {}
    try:
        meta = ast.literal_eval(value)
    except (ValueError, SyntaxError) as e:
        return f"META 必须是纯字面量（不含表达式/变量引用）：{e}", {}
    if not isinstance(meta, dict):
        return "META 必须解析为 dict", {}
    for key in ("id", "name"):
        v = meta.get(key)
        if not isinstance(v, str) or not v.strip():
            return f"META 缺少必填键 {key!r}（非空字符串）", meta
    scoring = meta.get("scoring", {})
    if scoring is not None:
        if not isinstance(scoring, dict):
            return "META.scoring 必须是 dict（字段名 → 权重）", meta
        bad = sorted(set(scoring) - ALLOWED_SCORING_FIELDS)
        if bad:
            return (
                f"META.scoring 含白名单外字段 {bad}；"
                f"允许字段：{sorted(ALLOWED_SCORING_FIELDS)}"
            ), meta
    return None, meta


def _check_compute(tree: ast.Module) -> str | None:
    """必须定义顶层 compute 函数（同步或异步均可，loader 侧做最终签名校验）。"""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "compute":
            return None
    return "缺少策略入口函数 compute(enriched, params) -> StrategySignals"


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def validate_strategy_code(code: str) -> dict[str, Any]:
    """校验 AI 生成的策略代码。永不抛异常，返回结构化结果。

    返回 {"valid": bool, "error": str | None, "meta": dict}：
    - valid=True 时代码过了全部静态检查（可进入 strategy/ai/ 目录）；
    - valid=False 时 error 为可读的中文错误描述，meta 可能为部分解析结果。
    """
    if not isinstance(code, str) or not code.strip():
        return {"valid": False, "error": "代码为空", "meta": {}}

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {
            "valid": False,
            "error": f"Python 语法错误（第 {e.lineno} 行）：{e.msg}",
            "meta": {},
        }

    for check in (_check_imports, _check_dangerous_calls, _check_dunder_escape):
        error = check(tree)
        if error is not None:
            return {"valid": False, "error": error, "meta": {}}

    error, meta = _check_meta(tree)
    if error is not None:
        return {"valid": False, "error": error, "meta": meta}

    error = _check_compute(tree)
    if error is not None:
        return {"valid": False, "error": error, "meta": meta}

    return {"valid": True, "error": None, "meta": meta}
