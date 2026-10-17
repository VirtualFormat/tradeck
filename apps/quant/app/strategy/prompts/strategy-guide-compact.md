# 策略开发精简指南（AI 运行时注入版）

> 本文件是 AI 运行时注入 system 提示词的精简指南，人类开发者请看完整版 `strategy-guide.md`。
> 协议以 `app/strategy/base.py`（StrategySignals）与 `app/strategy/loader.py`（META 校验）为准。

## 1. 铁律（违反即被安全闸拒绝，无例外）

1. **单文件自足**：一个策略 = 一个 Python 文件，禁止跨策略文件 import；小工具函数（如昨日值 prev）在文件内部各写一份。
2. **import 白名单**：只允许 `import polars / numpy / datetime / __future__`，以及 `from app.strategy.base import StrategySignals`、`from app.matrix import EnrichedMatrix`。其余一切 import（os/sys/math/pandas 等）一律拒。
3. **只读输入**：禁止网络 / DB / 文件读写，禁止修改任何现有文件。
4. **禁危险调用**：`eval / exec / compile / open / input / __import__ / globals / locals / vars / dir / getattr / setattr / delattr / breakpoint / exit / quit / help` 一律禁止调用。
5. **禁下划线前缀访问**：任何以 `_` 或 `__` 开头的属性读取和字符串常量下标（如 `obj.__class__`、`obj["__class__"]`）一律拒；自己的辅助函数用非下划线名（如 prev）。
6. **纯向量化**：指标层已是 (dates × symbols) 矩阵，整列 numpy 运算，禁止逐股 Python 循环。

## 2. META（顶层字面量 dict，ast.literal_eval 解析）

- 必须是**顶层字面量 dict**，不得含函数调用或变量引用；多余键放行。
- 必填 `id`（英文，全局唯一，建议与文件名同名，AI 生成用 `ai_` 前缀）与 `name`（中文显示名），均为非空字符串。
- 可选：`description` / `tags`（list[str]）/ `params` / `scoring` / `order_by`（通常 "score"）/ `limit` / `stop_loss`（负数，如 -0.06）/ `max_hold_days`（int）。
- `scoring` 若写必须是 dict，且字段**全部在白名单内**（见第 4 节），白名单外任何一个字段都会导致加载失败。

## 3. compute 函数与返回约定

```python
from app.matrix import EnrichedMatrix
from app.strategy.base import StrategySignals

def compute(enriched: EnrichedMatrix, params: dict) -> StrategySignals:
    ...
```

- `enriched` 只读：`enriched.base` 为 OHLCV 矩阵（`.open/.high/.low/.close/.volume/.amount`，均为 (dates × symbols)），另有 `enriched.base.dates / .symbols / .shape`；指标用 `enriched["ma5"]` 方式访问。
- `params`：META.params 默认值已被调用方合并（用户覆盖优先），用 `params.get("xxx", 默认值)` 读取并对 None 兜底。
- 返回 `StrategySignals(entry, exit, score)`，三者形状必须等于 `enriched.base.shape`（不一致会被拒绝）：
  - `entry`：bool 矩阵，True = 当日收盘产生买入信号（撮合层次日成交，策略不用管）。
  - `exit`：bool 矩阵，True = 当日收盘产生卖出信号。
  - `score`：float 矩阵，当日评分，通常只在 entry 日有值、其余 NaN（`np.where(entry, score, np.nan)`）；score 越大排名越前，「越小越好」的字段在公式里取负。

## 4. 可用字段（共 23 个，即 scoring 白名单全集）

OHLCV（`enriched.base`，6 个）：`open / high / low / close`（原始价，未复权）、`volume`（成交量）、`amount`（成交额）。

预计算指标（`enriched["…"]`，17 个，同形状 (dates × symbols)，预热期与停牌期为 NaN）：

| 指标 | 口径 |
|---|---|
| `ma5` / `ma10` / `ma20` / `ma60` | 简单均线；窗口内任一 NaN 则该期 NaN |
| `ema12` / `ema26` | 指数均线，alpha=2/(n+1)，同 pandas ewm(span=n) |
| `macd_dif` | EMA12 − EMA26 |
| `macd_dea` | DIF 的 9 周期 EMA |
| `macd_hist` | **2 × (DIF − DEA)，国内口径**（非国际 1 倍，阈值判断注意） |
| `rsi14` | Wilder RSI，[0,100]；有涨无跌=100，横盘=50 |
| `boll_upper` / `boll_lower` | MA20 ± 2 × 20 日标准差（ddof=0） |
| `momentum_5d` / `momentum_20d` | **小数口径** close/close[N 天前] − 1（0.05 = 5%） |
| `vol_ratio_5d` | **量比**：当日 volume / 5 日均量（1=平量，2=倍量） |
| `high_20d` / `low_20d` | 20 日窗口收盘最高 / 最低（含当日） |

无换手率字段（数据层无流通股本），不要编造。

## 5. NaN 与穿越写法（最易踩的坑）

- **不要 fillna(0)**：NaN 是停牌/预热期的真实语义，比较运算遇 NaN 自然得 False，填 0 会在预热期误触发信号。
- **上穿/下穿必须是双边条件**：只写 ma5 > ma20 会在趋势持续期每天触发；正确写法是叠加昨日值比较（prev helper 沿时间轴下移一行、首行 NaN）：

```python
def prev(arr: np.ndarray) -> np.ndarray:
    out = np.full(arr.shape, np.nan)
    if arr.shape[0] > 1:
        out[1:] = arr[:-1]
    return out
```

- 上穿：`(a > b) & (prev(a) <= prev(b))`；下穿：`(a < b) & (prev(a) >= prev(b))`。

## 6. params 写法

`META["params"]` 为 `list[dict]`，每项：`id`（必填，compute 里用 `params.get(id, default)` 读）、`label`（中文显示名）、`type`（`float` / `int` / `bool` / `select`，缺省 float）、`default`（必填）；float/int 可加 `min` / `max` / `step`，select 另带 `options: [{"label": ..., "value": ...}]`。只参数化用户会调的阈值，公式常数不必参数化；bool 参数用「是否启用某过滤」语义，默认 True。

## 7. 三市场差异（策略不用管）

CN 的 T+1、±10%/±20% 涨跌停、整手 100 股全部由撮合层处理，策略对 CN/US/HK 同一份代码通吃——**不要**在策略里写市场判断、涨跌停判断或手数取整。

## 8. 最小完整示例（能直接过安全闸）

```python
"""MA5 上穿 MA20 金叉入场，下穿离场。"""
from __future__ import annotations

import numpy as np

from app.matrix import EnrichedMatrix
from app.strategy.base import StrategySignals

META = {
    "id": "ai_ma_cross_demo",
    "name": "MA 金叉示例",
    "description": "MA5 上穿 MA20 入场，下穿离场，按动量与量比评分。",
    "params": [
        {"id": "vol_ratio_min", "label": "最低量比（0 关闭）", "type": "float",
         "default": 1.2, "min": 0.0, "max": 5.0, "step": 0.1},
    ],
    "scoring": {"momentum_20d": 0.6, "vol_ratio_5d": 0.4},
    "order_by": "score",
    "limit": 100,
    "stop_loss": -0.06,
    "max_hold_days": 15,
}


def prev(arr: np.ndarray) -> np.ndarray:
    out = np.full(arr.shape, np.nan)
    if arr.shape[0] > 1:
        out[1:] = arr[:-1]
    return out


def compute(enriched: EnrichedMatrix, params: dict) -> StrategySignals:
    ma5 = enriched["ma5"]
    ma20 = enriched["ma20"]
    entry = (ma5 > ma20) & (prev(ma5) <= prev(ma20))
    dead = (ma5 < ma20) & (prev(ma5) >= prev(ma20))
    vol_min = params.get("vol_ratio_min", 1.2)
    if vol_min:
        entry &= enriched["vol_ratio_5d"] >= float(vol_min)
    score = 0.6 * enriched["momentum_20d"] + 0.4 * enriched["vol_ratio_5d"]
    return StrategySignals(entry=entry, exit=dead, score=np.where(entry, score, np.nan))
```
