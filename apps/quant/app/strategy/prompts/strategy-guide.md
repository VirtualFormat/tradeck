# 策略开发指南（tradeck 量化引擎）

本文档是策略开发的完整参考，人类开发者与 AI 生成策略共用。策略协议以
`app/strategy/base.py`（StrategySignals）与 `app/strategy/loader.py`（META 校验）为准，
本文与代码冲突时以代码为准。

## 1. 策略模型：信号矩阵产出

一个策略 = **一个独立 Python 文件**，内含顶层 `META` 字面量 dict + 一个 `compute()` 函数。
与旧的「选股表达式 / 回测类」双后端不同，tradeck 统一为**信号矩阵产出**：

- 选股：取最后一个交易日的 entry 信号 + score 排序。
- 回测：全历史 entry/exit 信号矩阵直接进撮合引擎（engine/matcher）。

一套代码同时喂两条链路，无双后端历史包袱。

### 三层目录（权限分明）

| 目录 | 来源 | 说明 |
|---|---|---|
| `app/strategy/builtin/` | 内置策略 | 随镜像维护，仅项目维护者可改；**AI 生成策略永不入此目录** |
| `data/strategies/custom/` | 用户手写 | 建议文件名/ID 用 `custom_` 前缀 |
| `data/strategies/ai/` | AI 生成 | 文件名/ID 用 `ai_` 前缀，须先经安全校验才可入此目录 |

加载容错：单文件坏不波及其他策略，错误记入 `StrategyRegistry.load_errors()`。

### 铁律（安全闸强制）

- 策略**只读**注入的 `EnrichedMatrix`，禁止网络 / DB / 文件写。
- 策略文件必须**单文件自足**：禁止跨策略文件 import，共享小工具（如昨日值 shift）在每个文件内部各写一份。
- 纯 numpy 向量化，禁止逐股 Python 循环（指标层已是 (dates × symbols) 矩阵，整列运算即可）。

## 2. META 全字段说明

`META` 必须是**顶层字面量 dict**（loader 只接受字面量）。必填键仅 `id` / `name`，
其余键可省略；多余键放行（向前兼容）。

```python
META = {
    "id": "ma_golden_cross",        # 必填，str：英文 ID，全局唯一，建议与文件名同名
    "name": "MA 金叉",               # 必填，str：中文显示名
    "description": "策略逻辑一句话说明",  # 可选，str
    "tags": ["均线", "金叉"],          # 可选，list[str]：分类标签

    # 可调参数（见第 5 节）；没有可调参数可整键省略
    "params": [],

    # 评分权重（选股排序用）：字段必须在白名单内（见第 6 节），权重总和约定为 1.0
    "scoring": {"momentum_20d": 0.5, "vol_ratio_5d": 0.3, "rsi14": 0.2},

    "order_by": "score",            # 可选：选股排序字段，通常 "score"
    "limit": 100,                   # 可选：选股最多返回条数

    # 回测风控（撮合层读取；不适用可省略）
    "stop_loss": -0.06,             # 可选，负数：止损线，如 -0.06 表示亏 6% 离场
    "max_hold_days": 15,            # 可选，int：最长持有交易日数，到期强制离场
}
```

校验规则（loader）：

- `id` / `name` 缺失或非空字符串 → 加载失败。
- `scoring` 若含白名单外字段 → 加载失败（防 AI 编造评分列）。
- `params` 格式容错：dict / list[str] / list[dict] 混写都接受，整体坏则降级为空参数表，不崩加载。

## 3. compute 函数与 StrategySignals 返回约定

```python
from app.matrix import EnrichedMatrix
from app.strategy.base import StrategySignals

def compute(enriched: EnrichedMatrix, params: dict) -> StrategySignals:
    ...
```

- `enriched`：市场矩阵 + 预计算指标（见第 4 节），只读。
- `params`：META.params 的默认值已被调用方合并（用户覆盖优先），用
  `params.get("xxx", 默认值)` 读取并对 None 做兜底。
- 返回 `StrategySignals`，三个字段均为 **(dates × symbols)** 矩阵，与输入同形状：
  - `entry: np.ndarray`（bool）：True = 当日收盘产生买入信号。
  - `exit: np.ndarray`（bool）：True = 当日收盘产生卖出信号。
  - `score: np.ndarray`（float）：当日评分，通常**只在 entry 日有值，其余 NaN**。

关键约定：

- **信号是「当日收盘产生」**，撮合层在次日（或按撮合规则）成交，策略不用管。
- **NaN 传播**：指标预热期 / 停牌期为 NaN，比较运算遇 NaN 自然得 False（numpy 行为），
  **不要 fillna(0)**——那会把缺失当数值参与判断。
- 上穿 / 下穿用昨日值矩阵：沿时间轴下移一行、首行 NaN（见示例中的 `_prev`）。
- 权重方向：score 越大排名越前。若某字段「越小越好」（如超卖策略的 RSI），
  在 score 公式里取负（见 oversold_reversal）。

## 4. 可用数据与指标

### OHLCV（`enriched.base`，MarketMatrix）

| 字段 | 说明 |
|---|---|
| `open` / `high` / `low` / `close` | 原始价（未复权；复权由 engine 层处理） |
| `volume` | 成交量 |
| `amount` | 成交额 |

另有 `enriched.base.dates`（交易日轴，升序）、`enriched.base.symbols`（标的轴，升序）、
`enriched.base.shape`（(交易日数, 标的数)）。

### 预计算指标（`enriched.indicators` dict，用 `enriched["ma5"]` 访问）

全部基于 close / volume 原始价口径，同形状 (dates × symbols)，预热期与停牌期为 NaN。

| 指标 | 口径说明 |
|---|---|
| `ma5` / `ma10` / `ma20` / `ma60` | 简单均线；窗口内任一 NaN 则该期 NaN |
| `ema12` / `ema26` | 指数均线，alpha = 2/(n+1)，与 pandas ewm(span=n) 一致 |
| `macd_dif` | EMA12 − EMA26 |
| `macd_dea` | DIF 的 9 周期 EMA |
| `macd_hist` | **2 × (DIF − DEA)，国内软件口径**（非国际惯例的 1 倍） |
| `rsi14` | Wilder 平滑 RSI，取值 [0, 100]；有涨无跌 = 100，横盘 = 50 |
| `boll_upper` / `boll_lower` | MA20 ± 2 倍 20 日标准差（ddof=0 有偏口径，同国内行情软件） |
| `momentum_5d` / `momentum_20d` | **小数口径** close/close[N 天前] − 1，如 0.05 表示 5% |
| `vol_ratio_5d` | **量比**：当日 volume / 5 日均量（1 = 平量，2 = 倍量） |
| `high_20d` / `low_20d` | 20 日窗口收盘最高 / 最低（含当日） |

注意：换手率（turnover）需要流通股本，数据层暂无该字段，指标层不提供。

## 5. params 写法

`META["params"]` 为 `list[dict]`，每项字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 参数键名，compute 里用 `params.get(id, default)` 读取 |
| `label` | 建议 | 中文显示名（缺省回退为 id） |
| `type` | 建议 | `float` / `int` / `bool` / `select`（缺省 float） |
| `default` | 是 | 默认值；用户未覆盖时注入 compute |
| `min` / `max` / `step` | 否 | float/int 的取值范围与步进（前端滑杆用） |

`select` 类型另带 `options: [{"label": "显示名", "value": ...}]`。

只把用户可能调节的阈值参数化，公式常数（如 MA 窗口 5/20）不必参数化。
`bool` 参数约定用「是否启用某过滤」的语义，默认 True。

## 6. scoring 白名单

`META["scoring"]` 的字段必须在 `loader.ALLOWED_SCORING_FIELDS` 内（防 AI 编造评分列）：

```text
open, high, low, close, volume, amount,
ma5, ma10, ma20, ma60, ema12, ema26,
macd_dif, macd_dea, macd_hist, rsi14,
boll_upper, boll_lower, momentum_5d, momentum_20d,
vol_ratio_5d, high_20d, low_20d
```

## 7. 完整示例：ma_golden_cross（annotated）

```python
"""MA 金叉 — MA5 上穿 MA20，可选要求站上 MA60 与量能配合。"""
from __future__ import annotations

import numpy as np

from app.matrix import EnrichedMatrix
from app.strategy.base import StrategySignals

# META 必须是顶层字面量 dict；id/name 必填，scoring 字段必须在白名单内
META = {
    "id": "ma_golden_cross",            # 全局唯一，建议与文件名同名
    "name": "MA 金叉",
    "description": "MA5 上穿 MA20 当日入场，可选要求收盘站上 MA60 且量比放大；下穿离场。",
    "tags": ["均线", "金叉", "趋势"],
    "params": [
        # bool 参数：是否启用某过滤，默认 True
        {"id": "require_above_ma60", "label": "要求收盘站上 MA60", "type": "bool", "default": True},
        # float 参数：带 min/max/step，前端渲染为滑杆；0 约定为「关闭」
        {"id": "vol_ratio_min", "label": "最低量比（0 关闭）", "type": "float",
         "default": 1.2, "min": 0.0, "max": 5.0, "step": 0.1},
    ],
    # 评分权重：字段在白名单内，总和约定 1.0
    "scoring": {"momentum_20d": 0.5, "vol_ratio_5d": 0.3, "rsi14": 0.2},
    "order_by": "score",
    "limit": 100,
    "stop_loss": -0.06,                 # 亏 6% 止损
    "max_hold_days": 15,                # 最长持有 15 个交易日
}


def _prev(arr: np.ndarray) -> np.ndarray:
    """昨日值矩阵（沿时间轴下移一行，第一行 NaN；NaN 参与比较自然得 False）。

    单文件自足铁律：共享小工具不跨文件 import，每个策略文件内部各写一份。
    """
    out = np.full(arr.shape, np.nan)
    if arr.shape[0] > 1:
        out[1:] = arr[:-1]
    return out


def compute(enriched: EnrichedMatrix, params: dict) -> StrategySignals:
    """策略唯一入口，纯函数，只读 enriched。"""
    ma5 = enriched["ma5"]
    ma20 = enriched["ma20"]
    # 金叉：今日 MA5 > MA20 且昨日 MA5 <= MA20；死叉反之。
    # 预热期 ma5/ma20 为 NaN，比较自然得 False，无需特判。
    golden = (ma5 > ma20) & (_prev(ma5) <= _prev(ma20))
    dead = (ma5 < ma20) & (_prev(ma5) >= _prev(ma20))

    entry = golden.copy()
    # bool 参数：是否要求收盘站上 MA60（趋势过滤）
    if params.get("require_above_ma60", True):
        entry &= enriched.base.close > enriched["ma60"]
    # 参数兜底：None / 0 表示关闭量比过滤
    vol_min = params.get("vol_ratio_min", 1.2)
    if vol_min:
        entry &= enriched["vol_ratio_5d"] >= float(vol_min)

    # 评分：scoring 字段的指标值加权合成；仅 entry 日有值，其余 NaN。
    # 注意各指标量纲不同，权重已隐含归一意图；选股排序只比较相对大小。
    score = (
        0.5 * enriched["momentum_20d"]
        + 0.3 * enriched["vol_ratio_5d"]
        + 0.2 * enriched["rsi14"]
    )
    return StrategySignals(
        entry=entry,
        exit=dead,
        score=np.where(entry, score, np.nan),
    )
```

## 8. 三市场差异说明

策略对 CN / US / HK 三市场**同一份代码通吃**，市场差异全部由撮合层处理，策略不用管：

| 差异 | CN（A 股） | US / HK |
|---|---|---|
| 交收制度 | T+1（当日买入次日可卖） | 无限制 |
| 涨跌停 | ±10% / ±20%（涨停无法买入、跌停无法卖出，撮合层拒单） | 无限制 |
| 交易单位 | 整手 100 股 | 1 股 |

策略只负责产生「收盘信号矩阵」，成交价格、可否成交、持仓约束由 engine/matcher
按市场规则模拟。因此策略代码里**不要**写市场判断、涨跌停判断或手数取整。

## 9. 常见坑

1. **不要 fillna(0)**：NaN 是停牌/预热期的真实语义，填 0 会让金叉/阈值判断在预热期误触发。
2. **上穿必须是双边条件**：只写 `ma5 > ma20` 会在趋势持续期每天都触发；必须叠加
   `_prev(ma5) <= _prev(ma20)` 才是「当日发生穿越」。
3. **跌破同理用下穿口径**：`close < ma20` 持续成立时，离场信号每天都为 True 虽不影响撮合
   （已离场后无持仓可卖），但会污染信号统计；建议 `_prev(close) >= _prev(ma20) & (close < ma20)`。
4. **shape 必须一致**：返回的 entry/exit/score 形状必须与 `enriched.base.shape` 一致，
   不一致会被 loader 拒绝（ValueError）。
5. **compute 抛异常不会崩调用方**：registry.run 会降级为空信号并记日志，但静默降级会掩盖 bug，
   开发期请直接调用 `compute_fn` 或用合成矩阵自测。
6. **macd_hist 是 2 倍口径**：与国际版 MACD 柱状值差一倍，做阈值判断时注意。
