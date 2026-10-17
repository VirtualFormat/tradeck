"""轻量 JSON 条件信号 —— 不写代码的 AI 信号路径。

思路（参照 tick-stock-panel 的 custom_signals_ai，字段白名单换成 tradeck 的）：
用户一句自然语言 → LLM 拆成结构化 JSON 条件 → parse_and_validate 校验白名单 →
compile_to_mask 编译成 (dates × symbols) bool 矩阵，与策略信号同形状，
可直接进选股/回测管线，全程不产生可执行代码（比代码生成更安全的降级路径）。

数据模型：
  条件 = {"left": 字段, "op": 运算符, "right": 数字 | "field:字段",
          "leftDays": 0..60, "rightDays": 0..60}
  多条条件之间是「且」关系。leftDays/rightDays 为交易日偏移（0=当日），
  用数组 shift 实现；shift 后首日无对应历史值的行按 False 处理（NaN 不比真）。
"""
from __future__ import annotations

import json
import re
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# 字段白名单（enriched 指标 + OHLCV，与 loader.ALLOWED_SCORING_FIELDS 同源，
# 但 conditions 是独立模块，不反向依赖 loader，保持 ai/ 目录内聚）
# ---------------------------------------------------------------------------

# 字段 → 中文标签（注入 system 提示词，让 LLM 只敢用这些字段）
FIELD_LABELS: dict[str, str] = {
    # OHLCV 行情
    "open": "开盘价",
    "high": "最高价",
    "low": "最低价",
    "close": "收盘价",
    "volume": "成交量",
    "amount": "成交额",
    # 均线 / 指数均线
    "ma5": "5日均线",
    "ma10": "10日均线",
    "ma20": "20日均线",
    "ma60": "60日均线",
    "ema12": "12日指数均线",
    "ema26": "26日指数均线",
    # MACD（国内软件口径：HIST = 2×(DIF−DEA)）
    "macd_dif": "MACD DIF",
    "macd_dea": "MACD DEA",
    "macd_hist": "MACD 柱(红正绿负)",
    # 其他指标
    "rsi14": "14日RSI(0-100)",
    "boll_upper": "布林上轨",
    "boll_lower": "布林下轨",
    "momentum_5d": "5日动量(小数, 0.05=5%)",
    "momentum_20d": "20日动量(小数)",
    "vol_ratio_5d": "量比(当日量/5日均量)",
    "high_20d": "20日最高价",
    "low_20d": "20日最低价",
}

ALLOWED_FIELDS = frozenset(FIELD_LABELS)
ALLOWED_OPS = frozenset({">", ">=", "<", "<=", "==", "!="})
MAX_DAYS = 60
MAX_CONDITIONS = 8

_FIELD_PREFIX = "field:"
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


# ---------------------------------------------------------------------------
# 提示词组装
# ---------------------------------------------------------------------------


def _format_fields() -> str:
    return "\n".join(f"- {name}：{label}" for name, label in FIELD_LABELS.items())


_SYSTEM_TEMPLATE = """你是量化信号设计专家。用户会描述一个选股/交易信号思路，你要把它拆解为一组布尔条件（多条件之间是「且」关系，即同时满足），输出固定结构的 JSON，由系统编译成信号矩阵。

可用字段（白名单，只能使用以下字段，禁止自造字段）：
{fields}

运算符（op，只能六选一）：>  >=  <  <=  ==  !=

右值（right）两种写法：
- 数字：如 2、3000、0.05（动量/RSI 等小数口径字段注意单位，momentum 0.05 表示 5%）
- 另一字段：必须带 "field:" 前缀，如 "field:ma20"；裸写字段名不允许

日期偏移（leftDays / rightDays）：取 N 个交易日前的值，0 = 当日，范围 0~{max_days}。只有明确需要「N 日前」时才用非零偏移（如「今日收盘上穿 20 日线」= close>field:ma20 且 close(leftDays=1)<=field:ma20(rightDays=1)）。

输出要求：
1. 只输出一个 JSON 对象，禁止 markdown 代码块、禁止任何解释文字。
2. 结构固定为：
{{"name": "简短中文信号名称(≤12字)", "conditions": [
  {{"left": "字段", "op": "运算符", "right": 数字或"field:字段", "leftDays": 0, "rightDays": 0}}
]}}
3. conditions 至少 1 个、最多 {max_conditions} 个；用最少的条件表达清晰的思路。
4. 多条件必须能同时满足，不要输出互相矛盾的条件（如 close>10 且 close<5）。"""


def build_messages(description: str) -> list[dict]:
    """组装 LLM 消息：[system（白名单+规则+schema）, user（用户描述）]。"""
    system = _SYSTEM_TEMPLATE.format(
        fields=_format_fields(),
        max_days=MAX_DAYS,
        max_conditions=MAX_CONDITIONS,
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": description},
    ]


# ---------------------------------------------------------------------------
# 解析与校验
# ---------------------------------------------------------------------------


def parse_and_validate(text: str) -> dict[str, Any]:
    """解析 LLM 返回并校验。永不抛异常。

    返回 {"valid": bool, "error": str | None, "name": str, "conditions": list}；
    valid=False 时 name/conditions 为空占位。
    """

    def _fail(error: str) -> dict[str, Any]:
        return {"valid": False, "error": error, "name": "", "conditions": []}

    try:
        raw = _extract_json_object(text)
    except ValueError as e:
        return _fail(str(e))
    if not isinstance(raw, dict):
        return _fail("AI 返回的 JSON 不是对象")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        return _fail("缺少信号名称 name（非空字符串）")
    name = name.strip()
    if len(name) > 12:
        return _fail(f"信号名称超长（{len(name)} 字，上限 12 字）")

    conds_raw = raw.get("conditions")
    if not isinstance(conds_raw, list) or not conds_raw:
        return _fail("conditions 必须是非空数组")
    if len(conds_raw) > MAX_CONDITIONS:
        return _fail(f"条件数超限（{len(conds_raw)} 个，上限 {MAX_CONDITIONS} 个）")

    conditions: list[dict] = []
    for i, c in enumerate(conds_raw):
        cond, error = _validate_condition(c, i)
        if error is not None:
            return _fail(error)
        conditions.append(cond)

    return {"valid": True, "error": None, "name": name, "conditions": conditions}


def _validate_condition(c: Any, index: int) -> tuple[dict, str | None]:
    """校验单条条件；返回 (规范化条件, 错误描述或 None)。"""
    prefix = f"条件[{index}]"
    if not isinstance(c, dict):
        return {}, f"{prefix} 必须是 JSON 对象"

    left = c.get("left")
    if not isinstance(left, str) or left not in ALLOWED_FIELDS:
        return {}, f"{prefix} left 字段 {left!r} 不在白名单"

    op = c.get("op")
    if op not in ALLOWED_OPS:
        return {}, f"{prefix} op {op!r} 非法（仅允许 > >= < <= == !=）"

    right_raw = c.get("right")
    right: float | str
    right_field: str | None = None
    if isinstance(right_raw, bool):
        return {}, f"{prefix} right 不能是布尔值"
    if isinstance(right_raw, (int, float)):
        right = float(right_raw)
    elif isinstance(right_raw, str):
        s = right_raw.strip()
        if s.startswith(_FIELD_PREFIX):
            field = s[len(_FIELD_PREFIX):].strip()
            if field not in ALLOWED_FIELDS:
                return {}, f"{prefix} right 引用字段 {field!r} 不在白名单"
            right = s
            right_field = field
        else:
            # 容错：AI 偶尔裸写字段名，补全 field: 前缀
            if s in ALLOWED_FIELDS:
                right = f"{_FIELD_PREFIX}{s}"
                right_field = s
            else:
                try:
                    right = float(s)
                except ValueError:
                    return {}, f"{prefix} right {right_raw!r} 既不是数字也不是 field:字段"
    else:
        return {}, f"{prefix} 缺少右值 right"

    left_days, error = _validate_days(c.get("leftDays", 0), f"{prefix} leftDays")
    if error is not None:
        return {}, error
    right_days, error = _validate_days(c.get("rightDays", 0), f"{prefix} rightDays")
    if error is not None:
        return {}, error
    # 数字右值不允许偏移（对常数 shift 无意义，多为 AI 误解）
    if right_field is None and right_days != 0:
        return {}, f"{prefix} rightDays 仅在 right 为 field:字段 时可用"

    return {
        "left": left,
        "op": op,
        "right": right,
        "leftDays": left_days,
        "rightDays": right_days,
    }, None


def _validate_days(value: Any, label: str) -> tuple[int, str | None]:
    if isinstance(value, bool):
        return 0, f"{label} 必须是 0~{MAX_DAYS} 的整数"
    try:
        days = int(value)
    except (TypeError, ValueError):
        return 0, f"{label} 必须是 0~{MAX_DAYS} 的整数"
    if isinstance(value, float) and not float(value).is_integer():
        return 0, f"{label} 必须是整数（收到 {value}）"
    if not 0 <= days <= MAX_DAYS:
        return 0, f"{label} 超出范围 0~{MAX_DAYS}（收到 {days}）"
    return days, None


def _extract_json_object(text: str) -> Any:
    """多级容错提取 JSON 对象：整段 → markdown 围栏内 → 首个平衡 {} 块。"""
    source = text or ""
    candidates: list[str] = []
    stripped = source.strip()
    if stripped:
        candidates.append(stripped)
    candidates.extend(m.group(1).strip() for m in _FENCED_JSON_RE.finditer(source))
    brace = _first_brace_block(source)
    if brace and brace.strip() not in candidates:
        candidates.append(brace)

    last_error: Exception | None = None
    for candidate in candidates:
        parsed = _try_parse_json(candidate)
        if parsed is not None:
            return parsed
        try:
            json.loads(candidate)
        except json.JSONDecodeError as e:
            last_error = e
    raise ValueError(f"AI 返回的不是合法 JSON：{last_error}")


def _try_parse_json(candidate: str) -> Any | None:
    """尽力解析可能带尾随垃圾 / 尾逗号的 JSON；失败返 None。"""
    variants = [candidate.strip()]
    last = candidate.rfind("}")
    if 0 <= last < len(candidate) - 1:
        variants.append(candidate[: last + 1].strip())
    for v in variants:
        if not v:
            continue
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            pass
        # AI 常见错误：数组/对象结尾多一个逗号 `,}` / `,]`
        cleaned = re.sub(r",\s*([}\]])", r"\1", v)
        if cleaned != v:
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass
    return None


def _first_brace_block(text: str) -> str:
    """括号配对截取首个 {...} 块（AI 混入前后解释文字时的兜底）。"""
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


# ---------------------------------------------------------------------------
# 编译为信号矩阵
# ---------------------------------------------------------------------------

_OPS = {
    ">": np.greater,
    ">=": np.greater_equal,
    "<": np.less,
    "<=": np.less_equal,
    "==": np.equal,
    "!=": np.not_equal,
}


def _shift(arr: np.ndarray, days: int) -> np.ndarray:
    """沿时间轴下移 days 行（取 N 个交易日前的值），头部补 NaN。"""
    if days == 0:
        return arr
    out = np.full(arr.shape, np.nan)
    if days < arr.shape[0]:
        out[days:] = arr[:-days]
    return out


def _field_array(enriched: Any, field: str) -> np.ndarray:
    """从 enriched 矩阵取字段数组：先看指标列，再看基础行情列。"""
    if field in enriched.indicators:
        return enriched[field]
    base = enriched.base
    if hasattr(base, field):
        return getattr(base, field)
    raise KeyError(f"enriched 矩阵中不存在字段 {field!r}")


def compile_to_mask(conditions: list[dict], enriched: Any) -> np.ndarray:
    """把校验过的条件列表编译成 (dates × symbols) bool 矩阵（多条件取「且」）。

    NaN 语义：任一参与方 NaN 则该条件为 False（numpy 比较对 NaN 恒 False，
    天然满足「首日无历史值不触发」的要求）。条件应来自 parse_and_validate，
    未经校验的列表调用本函数是调用方的责任。
    """
    shape = enriched.base.shape
    if not conditions:
        return np.zeros(shape, dtype=bool)

    mask = np.ones(shape, dtype=bool)
    for c in conditions:
        left = _shift(_field_array(enriched, c["left"]), c["leftDays"])
        right_raw = c["right"]
        if isinstance(right_raw, str) and right_raw.startswith(_FIELD_PREFIX):
            right = _shift(_field_array(enriched, right_raw[len(_FIELD_PREFIX):]), c["rightDays"])
        else:
            right = float(right_raw)
        mask &= _OPS[c["op"]](left, right)
    return mask
