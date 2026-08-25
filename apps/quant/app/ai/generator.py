"""AI 策略生成器 —— 读策略指南 → 调 LLM → validator 安全校验 → 不合格重试 repair 一轮。

职责边界：只负责「生成 + 校验」，不负责落盘/加载（那是 strategy/loader 的事，
且只有校验通过的代码才允许写入 strategy/ai/ 目录）。

未配置降级：AI_API_KEY 为空时 enabled=False，generate 直接返回未配置错误，
绝不发网络请求；import 本模块本身也不触网、不读配置以外的状态。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

from app.ai.validator import validate_strategy_code
from app.config import settings

logger = logging.getLogger(__name__)

# 策略开发精简指南（C4 任务创建；不存在时用内置兜底说明，不崩）
GUIDE_PATH = (
    Path(__file__).resolve().parent.parent / "strategy" / "prompts" / "strategy-guide-compact.md"
)

_FALLBACK_GUIDE = """## 策略文件结构（兜底说明，完整指南缺失时使用）

```python
from app.strategy.base import StrategySignals
import numpy as np

META = {
    "id": "ai_xxx",            # 唯一 id，ai_ 前缀
    "name": "策略中文名",
    "scoring": {"close": 1.0},  # 评分字段必须来自白名单，权重总和 1.0
    "params": [],               # 可选：可调参数列表
}

def compute(enriched, params):
    # enriched["close"] / enriched["ma20"] 等为 (dates × symbols) 的 numpy 数组，NaN 为缺失
    # 返回 StrategySignals(entry=bool矩阵, exit=bool矩阵, score=float矩阵)
    ...
```

scoring 可用字段：open high low close volume amount ma5 ma10 ma20 ma60
ema12 ema26 macd_dif macd_dea macd_hist rsi14 boll_upper boll_lower
momentum_5d momentum_20d vol_ratio_5d high_20d low_20d。
"""

# 铁律提示词：内置在 generator，不依赖外部文件的核心安全约束
_SYSTEM_PREFIX = """你是量化策略设计专家。根据用户描述，参考下方《策略开发指南》生成一个完整的策略 Python 文件。

安全铁律（不可违反，违反将被安全闸拒绝）：
1. 只生成这一个 .py 文件：不拆分模块、不创建多文件、不跨文件引用，不改任何现有文件
2. import 只允许 polars（as pl）/ numpy（as np）/ datetime，以及 from app.strategy.base / from app.matrix 导入协议所需名；禁止 import os/sys/subprocess/pathlib/requests/httpx 等一切其他模块
3. 禁止网络/文件/系统访问：不得调用 open/eval/exec/compile/__import__/getattr/globals/locals 等，不得访问任何 __ 开头的 dunder 属性
4. META 必须是顶层字面量 dict，含 id（ai_ 前缀）与 name；scoring 字段只能用白名单内的真实指标字段，权重总和 1.0
5. 必须定义 compute(enriched, params) 并返回 StrategySignals(entry, exit, score)；entry/exit 为与矩阵同形状的 bool 矩阵，score 为同形状 float 矩阵
6. 全部计算用 numpy/polars 向量化完成，禁止逐股逐日 Python 循环；NaN（停牌/预热期）参与比较自然为 False，不要填 0
7. 直接输出 Python 代码，不要输出解释文字

--- 策略开发指南 ---

"""

_LLM_TIMEOUT_S = 120.0
_FENCED_CODE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


class AIStrategyGenerator:
    """AI 策略生成器（AI_API_KEY 为空时整体关闭）。"""

    def __init__(self) -> None:
        self._enabled = bool(settings.AI_API_KEY.strip())
        self._base_url = settings.AI_BASE_URL.rstrip("/")
        self._model = settings.AI_MODEL
        self._guide_cache: str | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _read_guide(self) -> str:
        """读策略指南（带缓存）；文件不存在用内置兜底说明，不崩。"""
        if self._guide_cache is None:
            try:
                if GUIDE_PATH.exists():
                    self._guide_cache = GUIDE_PATH.read_text(encoding="utf-8")
                else:
                    logger.warning("策略指南不存在 %s，使用内置兜底说明", GUIDE_PATH)
                    self._guide_cache = _FALLBACK_GUIDE
            except OSError as e:
                logger.warning("策略指南读取失败 %s：%s，使用内置兜底说明", GUIDE_PATH, e)
                self._guide_cache = _FALLBACK_GUIDE
        return self._guide_cache

    async def generate(self, description: str) -> dict:
        """生成策略代码并过安全闸；不合法时把错误反馈给 LLM 重试 repair 一轮。

        返回 {"valid": bool, "code": str, "meta": dict, "error": str | None}。
        永不抛异常：网络失败 / 校验失败都收敛为 valid=False + error。
        """
        if not self._enabled:
            return {
                "valid": False,
                "code": "",
                "meta": {},
                "error": "AI 未配置（缺少 AI_API_KEY 环境变量）",
            }
        if not isinstance(description, str) or not description.strip():
            return {"valid": False, "code": "", "meta": {}, "error": "策略描述为空"}

        messages = [
            {"role": "system", "content": _SYSTEM_PREFIX + self._read_guide()},
            {"role": "user", "content": description.strip()},
        ]
        code = await self._call_llm(messages)
        if code is None:
            return {"valid": False, "code": "", "meta": {}, "error": "LLM 调用失败（连接或响应异常）"}

        result = validate_strategy_code(code)
        if result["valid"]:
            return {"valid": True, "code": code, "meta": result["meta"], "error": None}

        # repair 一轮：把 validator 的错误反馈给 LLM 重生成
        logger.info("AI 策略首次生成未过安全闸（%s），发起 repair 重试", result["error"])
        repair_messages = messages + [
            {"role": "assistant", "content": code},
            {
                "role": "user",
                "content": (
                    f"上次生成的代码未通过安全校验，错误：{result['error']}\n"
                    "请输出修复后的完整策略 Python 文件，保持原策略意图，"
                    "严格遵守安全铁律。只输出完整 Python 代码。"
                ),
            },
        ]
        repaired = await self._call_llm(repair_messages)
        if repaired is None:
            return {
                "valid": False,
                "code": code,
                "meta": result.get("meta", {}),
                "error": f"{result['error']}（repair 重试时 LLM 调用失败）",
            }
        final = validate_strategy_code(repaired)
        if final["valid"]:
            return {"valid": True, "code": repaired, "meta": final["meta"], "error": None}
        return {
            "valid": False,
            "code": repaired,
            "meta": final.get("meta", {}),
            "error": f"repair 后仍未通过安全校验：{final['error']}",
        }

    async def _call_llm(self, messages: list[dict]) -> str | None:
        """调 OpenAI 兼容 chat completions；失败返回 None（优雅降级，不抛）。"""
        if not self._base_url:
            logger.error("AI_BASE_URL 未配置，无法调用 LLM")
            return None
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.3,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {settings.AI_API_KEY}"}
        try:
            async with httpx.AsyncClient(timeout=_LLM_TIMEOUT_S) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.warning("LLM 调用失败：%s", e)
            return None

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            logger.warning("LLM 响应结构异常：%s", e)
            return None
        if not isinstance(content, str) or not content.strip():
            logger.warning("LLM 返回空内容")
            return None
        return _extract_code(content)


def _extract_code(text: str) -> str:
    """容错剥 markdown 代码块：有围栏取首个 python 块，否则取全文。"""
    blocks = _FENCED_CODE_RE.findall(text)
    if blocks:
        return blocks[0].strip()
    return text.strip()
