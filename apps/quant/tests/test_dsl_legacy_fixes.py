"""DSL 编译器遗留缺陷修复的回归测试。

覆盖点：
- 缺陷 1：and/or 编译闭包对左右子树各求值一次（与 _cmp 闭包同写法），
  语义保持「任一侧 NaN → NaN，否则按非零真值化」。
- 缺陷 2：power 非整数指数的底数编译期校验（E010）——
  静态可证非负（abs/sqrt/max/clamp 下界 ≥ 0/量价列）才放行，
  无法判定的底数编译期拒绝；整数指数不受限（负底数合法）；求值期 errstate 兜底不变。
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta

import numpy as np

from app.factors.dsl import compile_formula
from app.matrix import MarketMatrix, enrich

_D0 = date(2026, 1, 5)


def _market(n: int = 30, s: int = 2) -> MarketMatrix:
    """合成市场矩阵（确定性随机游走，正价）。"""
    rng = np.random.default_rng(7)
    close = np.abs(10.0 + np.cumsum(rng.normal(0, 0.1, (n, s)), axis=0))
    return MarketMatrix(
        dates=[_D0 + timedelta(days=i) for i in range(n)],
        symbols=[f"SYM{k}" for k in range(s)],
        open=close - 0.05,
        high=close + 0.1,
        low=close - 0.1,
        close=close,
        volume=np.full((n, s), 1e6),
        amount=close * 1e6,
    )


class AndOrSingleEvalTest(unittest.TestCase):
    """缺陷 1：and/or 闭包每个子树只求值一次（旧写法 NaN 判空 + 真值化各调一次）。"""

    def test_and_evaluates_children_once(self) -> None:
        compiled = compile_formula("ts_sum(volume, 5) > 0 and volume > 0")
        self.assertTrue(compiled.ok, compiled.errors)
        en = enrich(_market())
        calls = {"n": 0}

        def counting_get_col(name: str):
            calls["n"] += 1  # volume 引用 2 处（ts_sum 内 1 + and 右子树 1）
            return np.asarray(getattr(en.base, name), dtype=np.float64)

        out = compiled.evaluate(en, counting_get_col)
        self.assertIsNotNone(out)
        # 若 and 闭包对右子树重复求值（NaN 判空 + 真值化各一次），此处会是 3
        self.assertEqual(calls["n"], 2)
        self.assertTrue(np.all(np.isnan(out[:4])))  # ts_sum 窗口预热 4 期 NaN
        self.assertTrue(np.all(out[4:] == 1.0))  # volume 恒正 → and 恒真

    def test_or_evaluates_children_once(self) -> None:
        compiled = compile_formula("ts_sum(volume, 5) > 0 or close > 0")
        self.assertTrue(compiled.ok, compiled.errors)
        en = enrich(_market())
        calls = {"n": 0}

        def counting_get_col(name: str):
            calls["n"] += 1
            return np.asarray(getattr(en.base, name), dtype=np.float64)

        out = compiled.evaluate(en, counting_get_col)
        self.assertIsNotNone(out)
        # volume 1 处 + close 1 处；or 闭包重复求值右子树时会是 3
        self.assertEqual(calls["n"], 2)
        self.assertTrue(np.all(np.isnan(out[:4])))
        self.assertTrue(np.all(out[4:] == 1.0))

    def test_and_or_nan_propagation(self) -> None:
        # 语义不变：预热期 ts_* 产 NaN → and/or 结果 NaN
        compiled = compile_formula("ts_sum(volume, 5) > 0 and close > 0")
        self.assertTrue(compiled.ok, compiled.errors)
        out = compiled.evaluate(enrich(_market()))
        self.assertIsNotNone(out)
        self.assertTrue(np.all(np.isnan(out[:4])))  # 窗口预热 4 期 NaN
        self.assertTrue(np.all(out[4:] == 1.0))


class PowerBaseValidationTest(unittest.TestCase):
    """缺陷 2：power 非整数指数底数静态非负校验（E010）。"""

    def _errors(self, formula: str):
        compiled = compile_formula(formula)
        return compiled, [e.code for e in compiled.errors]

    def test_reject_unknown_base_with_fractional_exponent(self) -> None:
        # macd_dif 可正可负且无法静态判定 → 编译期拒绝（旧行为静默产 NaN）
        compiled, codes = self._errors("power(macd_dif, 0.5)")
        self.assertFalse(compiled.ok)
        self.assertIn("E010", codes)

    def test_reject_user_factor_like_base(self) -> None:
        # momentum_5d 同理（非白名单列）
        compiled, codes = self._errors("power(momentum_5d, 1.5)")
        self.assertFalse(compiled.ok)
        self.assertIn("E010", codes)

    def test_allow_abs_base(self) -> None:
        compiled, _ = self._errors("power(abs(macd_dif), 0.5)")
        self.assertTrue(compiled.ok, compiled.errors)

    def test_allow_volume_and_amount(self) -> None:
        for formula in ("power(volume, 0.5)", "power(amount, 1.5)", "power(close, 0.3)"):
            compiled, _ = self._errors(formula)
            self.assertTrue(compiled.ok, formula)

    def test_allow_sqrt_and_max_and_clamp(self) -> None:
        for formula in (
            "power(sqrt(macd_dif), 0.5)",   # sqrt 非法输入产 NaN，不产负数
            "power(max(macd_dif, volume), 0.5)",  # max 任一参数非负即非负
            "power(clamp(macd_dif, 0, 10), 0.5)",  # clamp 下界 ≥ 0
        ):
            compiled, _ = self._errors(formula)
            self.assertTrue(compiled.ok, formula)

    def test_reject_min_with_maybe_negative_arg(self) -> None:
        # min 取小者：只要有一个参数不可证非负就不能放行
        compiled, codes = self._errors("power(min(volume, macd_dif), 0.5)")
        self.assertFalse(compiled.ok)
        self.assertIn("E010", codes)

    def test_reject_clamp_negative_lo(self) -> None:
        compiled, codes = self._errors("power(clamp(volume, -1, 10), 0.5)")
        self.assertFalse(compiled.ok)
        self.assertIn("E010", codes)

    def test_integer_exponent_unrestricted(self) -> None:
        # 整数指数负底数合法（如 (-2)^3），不受新校验限制
        compiled, _ = self._errors("power(macd_dif, 2)")
        self.assertTrue(compiled.ok, compiled.errors)
        compiled, _ = self._errors("power(macd_dif, -1)")
        self.assertTrue(compiled.ok, compiled.errors)

    def test_abs_max_still_enforced(self) -> None:
        # 原有 |c| ≤ POWER_ABS_MAX 红线保持
        compiled, codes = self._errors("power(volume, 5)")
        self.assertFalse(compiled.ok)
        self.assertIn("E010", codes)

    def test_evaluation_fallback_still_silent(self) -> None:
        # 求值期 errstate 兜底不变：整数指数负底数正常求值（不产 NaN）
        compiled = compile_formula("power(macd_dif, 3)")
        self.assertTrue(compiled.ok, compiled.errors)
        out = compiled.evaluate(enrich(_market()))
        self.assertIsNotNone(out)
        # macd_dif 预热期外应全为有限值（奇次幂负底数 → 负值，非 NaN）
        tail = out[-5:]
        self.assertTrue(np.all(np.isfinite(tail)))


if __name__ == "__main__":
    unittest.main()
