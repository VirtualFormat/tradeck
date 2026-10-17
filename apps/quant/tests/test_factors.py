"""因子体系的回归测试（阶段 J DSL 编译器 / 注册表 / 存储验收点固化）。

覆盖点（plans/TASKS-QUANT-BACKTEST.md 阶段 J review 记录）：
- J2 DSL 编译：合法公式编译可求值（形状/手算值/预热期 NaN）、编译红线错误码
  E005（负 shift 未来函数）/ E009（截面算子嵌时序窗口）/ E001（未知标识符）/
  E002（未知函数）；防未来函数铁律——篡改 T 日之后的数据，T 日前的因子值逐位不变。
- J1 注册表多用户隔离：builtin 全局共享（所有用户可见）、用户私有因子只在本人
  命名空间可见（跨用户引用 DSL 编译期 E001）。
- J3 复合因子环检测：合法嵌套（共享叶子成员 / composite 嵌 composite）通过、
  真环（composite 链回到祖先）拒绝、自引用拒绝、>8 成员拒绝。
- J3 生命周期状态机：draft→active→watch→retired 合法边通过，非法边拒绝。

测试用户命名空间（alice/bob）在 setUp/tearDown 双向清理，保证两遍跑幂等。
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta

import numpy as np

from app.factors import registry, store
from app.factors.dsl import compile_formula
from app.factors.registry import FactorSpec
from app.matrix import MarketMatrix, enrich

_D0 = date(2026, 1, 5)
_TEST_USERS = ("alice", "bob")


def _market(n: int = 40, s: int = 2) -> MarketMatrix:
    """合成市场矩阵（确定性随机游走，正价）。"""
    rng = np.random.default_rng(42)
    close = 10.0 + np.cumsum(rng.normal(0, 0.1, (n, s)), axis=0)
    close = np.abs(close)
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


def _custom_spec(fid: str, formula: str = "momentum_5d", version: int = 1) -> FactorSpec:
    compiled = compile_formula(formula)
    assert compiled.ok, formula
    return FactorSpec(
        id=fid,
        label=fid,
        group="自定义",
        formula_text=formula,
        kind="custom",
        version=version,
        dependencies=frozenset(compiled.dependencies),
        warmup_bars=compiled.warmup_bars,
    )


def _clear_test_namespaces() -> None:
    """清掉测试用户的私有命名空间（builtin 层不动）。"""
    for uid in _TEST_USERS:
        registry._USER_REGISTRIES.pop(uid, None)  # noqa: SLF001（测试内部清理）


class DslCompileTest(unittest.TestCase):
    """J2：合法公式编译 + 求值手算值。"""

    def test_legal_formula_compiles_and_evaluates(self) -> None:
        compiled = compile_formula("ts_mean(close, 3)")
        self.assertTrue(compiled.ok, [e.message for e in compiled.errors])
        self.assertEqual(compiled.dependencies, frozenset({"close"}))
        # 预热 = 窗口 n + 1（口径见 dsl.compile_formula）
        self.assertEqual(compiled.warmup_bars, 4)
        self.assertFalse(compiled.cross_sectional)
        en = enrich(_market())
        vals = compiled.evaluate(en)
        self.assertIsNotNone(vals)
        self.assertEqual(vals.shape, en.base.shape)
        # 手算值：第 5 行 = close[2:5] 的均值；预热期（前 2 行）NaN
        for j in range(en.base.shape[1]):
            self.assertAlmostEqual(
                vals[4, j], float(en.base.close[2:5, j].mean()), places=12
            )
        self.assertTrue(np.isnan(vals[:2, :]).all())

    def test_cross_sectional_flag(self) -> None:
        self.assertTrue(compile_formula("rank(close)").cross_sectional)
        self.assertFalse(compile_formula("ts_mean(close, 5)").cross_sectional)

    def test_no_lookahead_tampering_future_rows(self) -> None:
        """防未来函数铁律：篡改第 25 行起的数据，前 25 行因子值逐位不变。"""
        formula = "ts_mean(close, 5) + ts_delay(close, 2) - rank(momentum_5d)"
        compiled = compile_formula(formula)
        self.assertTrue(compiled.ok, [e.message for e in compiled.errors])
        en = enrich(_market(n=40, s=3))
        before = compiled.evaluate(en)
        # 篡改未来（第 25 行起全字段 ×100 极端值）
        tampered = MarketMatrix(
            dates=en.base.dates,
            symbols=en.base.symbols,
            **{
                f: np.where(
                    np.arange(40)[:, None] >= 25,
                    getattr(en.base, f) * 100.0,
                    getattr(en.base, f),
                )
                for f in ("open", "high", "low", "close", "volume", "amount")
            },
        )
        after = compiled.evaluate(enrich(tampered))
        # 前 25 行逐位不变（NaN 视为相等）
        np.testing.assert_allclose(before[:25], after[:25], rtol=0, atol=0, equal_nan=True)
        # 第 25 行起确实被篡改影响（证明对照有效：值不是恒等不变）
        self.assertFalse(
            np.allclose(before[25:], after[25:], rtol=0, atol=0, equal_nan=True)
        )


class DslRedLineTest(unittest.TestCase):
    """J2：编译红线错误码（E005/E009/E001/E002）。"""

    def _codes(self, formula: str, user_id: str | None = None) -> set[str]:
        compiled = compile_formula(formula, user_id=user_id)
        self.assertFalse(compiled.ok, formula)
        return {e.code for e in compiled.errors}

    def test_e005_negative_shift_is_future_leak(self) -> None:
        # ts_delay 负数 = 向前看未来数据，编译期必须拒绝
        self.assertIn("E005", self._codes("ts_delay(close, -1)"))
        self.assertIn("E005", self._codes("ts_delta(close, -3)"))

    def test_e009_cross_sectional_inside_ts_window(self) -> None:
        # 截面算子嵌时序窗口（两阶段物化红线）
        self.assertIn("E009", self._codes("ts_mean(rank(close), 5)"))
        self.assertIn("E009", self._codes("ts_max(zscore(close), 3)"))

    def test_e001_unknown_identifier(self) -> None:
        self.assertIn("E001", self._codes("close + no_such_col"))

    def test_e002_unknown_function(self) -> None:
        self.assertIn("E002", self._codes("future_peek(close, 5)"))


class RegistryIsolationTest(unittest.TestCase):
    """J1/G4：注册表多用户隔离（builtin 共享 + 用户私有）。"""

    def setUp(self) -> None:
        _clear_test_namespaces()

    def tearDown(self) -> None:
        _clear_test_namespaces()

    def test_builtin_shared_user_private_isolated(self) -> None:
        registry.register_factor(_custom_spec("uf_alice_mom"), "alice")
        # 本人可见
        self.assertIsNotNone(registry.get_user_factor("uf_alice_mom", "alice"))
        # 其他用户与匿名视图不可见（G4 隔离铁律）
        self.assertIsNone(registry.get_user_factor("uf_alice_mom", "bob"))
        self.assertIsNone(registry.get_user_factor("uf_alice_mom", None))
        alice_ids = {s.id for s in registry.list_factors(user_id="alice")}
        bob_ids = {s.id for s in registry.list_factors(user_id="bob")}
        self.assertIn("uf_alice_mom", alice_ids)
        self.assertNotIn("uf_alice_mom", bob_ids)
        # builtin base 因子全局共享：两边都可见
        self.assertIsNotNone(registry.get_user_factor("close", "bob"))
        self.assertIn("momentum_5d", bob_ids)

    def test_same_id_different_users_coexist(self) -> None:
        registry.register_factor(_custom_spec("uf_same", "momentum_5d"), "alice")
        registry.register_factor(_custom_spec("uf_same", "momentum_20d"), "bob")
        self.assertEqual(
            registry.get_user_factor("uf_same", "alice").formula_text, "momentum_5d"
        )
        self.assertEqual(
            registry.get_user_factor("uf_same", "bob").formula_text, "momentum_20d"
        )

    def test_cross_user_reference_rejected_e001(self) -> None:
        # bob 的 DSL 公式引用 alice 的私有因子 → 编译期 E001（不越界解析）
        registry.register_factor(_custom_spec("uf_alice_only"), "alice")
        compiled = compile_formula("uf_alice_only * 2", user_id="bob")
        self.assertFalse(compiled.ok)
        self.assertIn("E001", {e.code for e in compiled.errors})
        # alice 本人引用则编译通过
        self.assertTrue(compile_formula("uf_alice_only * 2", user_id="alice").ok)

    def test_builtin_unregister_rejected(self) -> None:
        with self.assertRaises(ValueError):
            registry.unregister_factor("close")


class CompositeRingTest(unittest.TestCase):
    """J3：复合因子环检测（合法嵌套通过 + 真环拒绝）。"""

    def setUp(self) -> None:
        _clear_test_namespaces()

    def tearDown(self) -> None:
        _clear_test_namespaces()

    def _register_composite(self, fid: str, members: dict[str, float]) -> FactorSpec:
        return store.register_definition(
            {"id": fid, "label": fid, "kind": "composite", "members": members},
            user_id="alice",
            bump_version=False,
        )

    def test_legal_nesting_with_shared_leaf_passes(self) -> None:
        registry.register_factor(_custom_spec("uf_leaf"), "alice")
        self._register_composite("cf_inner", {"uf_leaf": 1.0, "close": 1.0})
        # 合法嵌套：composite 引用 composite + 共享叶子成员 close（review P1-2 修复点，
        # 叶子不参与 seen 判重，不得误判成环）
        spec = self._register_composite("cf_outer", {"cf_inner": 2.0, "close": 1.0})
        self.assertEqual(spec.kind, "composite")
        self.assertEqual(len(spec.components), 2)

    def test_true_ring_rejected(self) -> None:
        # 先注册合法链 cf_a → close，再让 cf_b → cf_a，
        # 最后改 cf_a → cf_b（环：cf_a → cf_b → cf_a）
        self._register_composite("cf_a", {"close": 1.0, "ma5": 1.0})
        self._register_composite("cf_b", {"cf_a": 1.0, "close": 1.0})
        with self.assertRaisesRegex(ValueError, "循环引用"):
            store.to_spec(
                {
                    "id": "cf_a",
                    "label": "cf_a",
                    "kind": "composite",
                    "version": 2,
                    "members": {"cf_b": 1.0, "close": 1.0},
                },
                user_id="alice",
            )

    def test_self_reference_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "自身"):
            store.to_spec(
                {
                    "id": "cf_self",
                    "label": "cf_self",
                    "kind": "composite",
                    "members": {"cf_self": 1.0, "close": 1.0},
                },
                user_id="alice",
            )

    def test_member_count_bounds(self) -> None:
        # 单成员与 9 成员均拒绝（2~8 合法）
        with self.assertRaises(ValueError):
            store.to_spec(
                {"id": "cf_one", "label": "x", "kind": "composite",
                 "members": {"close": 1.0}},
                user_id="alice",
            )
        with self.assertRaises(ValueError):
            store.to_spec(
                {"id": "cf_nine", "label": "x", "kind": "composite",
                 "members": {
                     "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
                     "volume": 1.0, "amount": 1.0, "ma5": 1.0, "ma10": 1.0,
                     "ma20": 1.0,
                 }},
                user_id="alice",
            )


class LifecycleStateMachineTest(unittest.TestCase):
    """J3：draft→active→watch→retired 状态机合法/非法边。"""

    def setUp(self) -> None:
        _clear_test_namespaces()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        store.create_factor(
            "alice",
            {
                "id": "uf_sm",
                "label": "状态机",
                "kind": "custom",
                "formula": "close",
                "status": store.STATUS_DRAFT,
            },
            cache_dir=self._tmp.name,
        )

    def tearDown(self) -> None:
        _clear_test_namespaces()

    def _transition(self, status: str) -> dict:
        return store.transition("alice", "uf_sm", status, cache_dir=self._tmp.name)

    def test_legal_path_draft_active_watch_retired(self) -> None:
        self.assertEqual(self._transition(store.STATUS_ACTIVE)["status"], "active")
        self.assertEqual(self._transition(store.STATUS_WATCH)["status"], "watch")
        # watch 可回到 active（复核后恢复）
        self.assertEqual(self._transition(store.STATUS_ACTIVE)["status"], "active")
        self.assertEqual(self._transition(store.STATUS_RETIRED)["status"], "retired")
        # retired 为终态：复活 = 新建版本，不允许直接流转
        with self.assertRaises(ValueError):
            self._transition(store.STATUS_ACTIVE)

    def test_illegal_edges_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._transition(store.STATUS_WATCH)  # draft 不能直达 watch
        with self.assertRaises(ValueError):
            self._transition(store.STATUS_RETIRED)  # draft 不能直达 retired
        with self.assertRaises(ValueError):
            self._transition("nonexistent")  # 未知状态

    def test_missing_factor_rejected(self) -> None:
        with self.assertRaises(ValueError):
            store.transition("alice", "uf_ghost", "active", cache_dir=self._tmp.name)


if __name__ == "__main__":
    unittest.main()
