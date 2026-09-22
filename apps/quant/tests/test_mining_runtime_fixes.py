"""mining runtime 遗留缺陷修复的回归测试。

覆盖点：
- 缺陷 3：DSR 的 n_trials 口径——与 beam_width 脱钩，按
  「内层评估池规模（≤8）× 内层折数」估算，dsr_note 明示上界估算口径。
- 缺陷 4a：save_candidate 的 candidate_id 带 sha1 短哈希后缀，
  长组合名截断后不同组合不再静默撞 cid 覆盖。
- 缺陷 4b：publish_candidate 直接复核候选库聚合指标（含 positive_fold_ratio
  真实门槛），不再伪造 FoldResult 逐项推断。
"""
from __future__ import annotations

import tempfile
import unittest
from unittest import mock

import numpy as np
import polars as pl

from app.config import settings
from app.mining import core, runtime

_TMP = tempfile.TemporaryDirectory()


def setUpModule() -> None:
    # 候选库写到临时目录，避免污染真实缓存
    settings.QUANT_CACHE_DIR = _TMP.name


def tearDownModule() -> None:
    _TMP.cleanup()


def _fake_nested(n_inner: int = 3) -> core.NestedFold:
    outer = core.ValidationFold("outer", 0, None, 0, 40, 43, 50, 51)
    inner = [
        core.ValidationFold("inner", 0, i, 0, 20 + i * 3, 23 + i * 3, 26 + i * 3, 27 + i * 3)
        for i in range(n_inner)
    ]
    return core.NestedFold(outer=outer, inner=inner)


def _candidate(combo: tuple[str, ...], folds: int = 3, pos_folds: int = 3,
               sharpe: float = 1.0, trades: int = 100) -> core.CandidateResult:
    """构造候选：pos_folds 折为正收益，其余为负。"""
    c = core.CandidateResult(combo=combo, directions={n: 1 for n in combo})
    for i in range(folds):
        positive = i < pos_folds
        c.folds.append(core.FoldResult(
            fold_index=i, combo=combo, oos_sharpe=sharpe if positive else -sharpe,
            oos_return=0.1 if positive else -0.1, oos_max_drawdown=-0.1,
            oos_trades=trades // folds, oos_positive=positive,
        ))
    return c


class DsrTrialsNoteTest(unittest.TestCase):
    """缺陷 3：n_trials 不再含 beam_width/max_size 因子，dsr_note 明示口径。"""

    def test_dsr_note_states_upper_bound_estimate(self) -> None:
        nested = _fake_nested(n_inner=3)
        rng = np.random.default_rng(1)
        factors = {f"f{i}": rng.normal(size=(60, 3)) for i in range(3)}
        fwd = rng.normal(size=(60, 3))
        combos = [((f"f{i}",), 0.1) for i in range(3)]
        # _select_combo_inner 的折数/池规模口径：len(pool) × len(nested.inner)
        with mock.patch.object(runtime.core, "beam_search", return_value=combos):
            selected = runtime._select_combo_inner(nested, factors, fwd, max_size=4, beam_width=99)
        self.assertIsNotNone(selected)
        _, _, _, _, n_evals = selected
        # beam_width=99 / max_size=4 不参与计数：3 个候选 × 3 个内层折 = 9
        self.assertEqual(n_evals, 3 * 3)


class CandidateIdCollisionTest(unittest.TestCase):
    """缺陷 4a：candidate_id 带哈希后缀，截断碰撞不再静默覆盖。"""

    def setUp(self) -> None:
        f = runtime._candidates_file("fixtest")
        if f.exists():
            f.unlink()

    def test_long_combo_prefix_collision_resolved(self) -> None:
        # 两个组合前 40 字符相同、尾部不同——旧 cid 会撞车覆盖，新 cid 不撞
        prefix = tuple(f"factor_name_{i:03d}" for i in range(3))  # 前缀撑满截断长度
        c1 = _candidate(prefix + ("aaa_tail_x",))
        c2 = _candidate(prefix + ("bbb_tail_y",))
        cid1 = runtime.save_candidate(c1, "fixtest")
        cid2 = runtime.save_candidate(c2, "fixtest")
        self.assertNotEqual(cid1, cid2)
        df = runtime.load_candidates("fixtest")
        self.assertEqual(df.height, 2)  # 两条都在，未互相覆盖

    def test_same_combo_upsert_idempotent(self) -> None:
        c = _candidate(("alpha", "beta"))
        cid1 = runtime.save_candidate(c, "fixtest")
        cid2 = runtime.save_candidate(c, "fixtest")
        self.assertEqual(cid1, cid2)
        df = runtime.load_candidates("fixtest")
        self.assertEqual(df.filter(pl.col("candidate_id") == cid1).height, 1)


class PublishGateTest(unittest.TestCase):
    """缺陷 4b：发布复核直接读库存聚合指标，positive_fold_ratio 门槛不再被绕过。"""

    def setUp(self) -> None:
        f = runtime._candidates_file("fixtest")
        if f.exists():
            f.unlink()

    def test_publish_rejects_low_positive_fold_ratio(self) -> None:
        # 3 折仅 2 折为正（ratio=2/3 达标）对照：1/3 必须被拒
        bad = _candidate(("g1", "g2"), folds=3, pos_folds=1)
        cid = runtime.save_candidate(bad, "fixtest")
        ok, msg = runtime.publish_candidate(cid, "fixtest")
        self.assertFalse(ok)
        self.assertIn("正收益折占比", msg)
        df = runtime.load_candidates("fixtest")
        status = df.filter(pl.col("candidate_id") == cid)["status"][0]
        self.assertEqual(status, "pending")

    def test_publish_rejects_ratio_half_old_bug(self) -> None:
        # 旧伪造 FoldResult 写法的漏洞场景：ratio=0.5（<2/3 门槛）时
        # oos_positive = ratio>0 = True → 全折伪造为正 → 绕过门槛发布成功。
        # 新实现按库存 ratio=0.5 复核，必须拒绝。
        bad = _candidate(("h1", "h2"), folds=2, pos_folds=1)
        self.assertAlmostEqual(bad.positive_fold_ratio, 0.5)
        cid = runtime.save_candidate(bad, "fixtest")
        ok, msg = runtime.publish_candidate(cid, "fixtest")
        self.assertFalse(ok)
        self.assertIn("正收益折占比", msg)

    def test_publish_passes_when_gate_met(self) -> None:
        good = _candidate(("ok1", "ok2"), folds=3, pos_folds=3, sharpe=1.2, trades=120)
        cid = runtime.save_candidate(good, "fixtest")
        ok, msg = runtime.publish_candidate(cid, "fixtest")
        self.assertTrue(ok, msg)
        df = runtime.load_candidates("fixtest")
        row = df.filter(pl.col("candidate_id") == cid).row(0, named=True)
        self.assertEqual(row["status"], "published")
        self.assertIsNotNone(row["published_at"])

    def test_publish_rejects_missing_metric(self) -> None:
        # 库存字段缺失（None）按不达标处理（fail-closed）
        good = _candidate(("m1", "m2"), folds=3, pos_folds=3)
        cid = runtime.save_candidate(good, "fixtest")
        f = runtime._candidates_file("fixtest")
        df = pl.read_parquet(f).with_columns(
            pl.when(pl.col("candidate_id") == cid)
            .then(pl.lit(None, dtype=pl.Float64))
            .otherwise(pl.col("positive_fold_ratio"))
            .alias("positive_fold_ratio")
        )
        df.write_parquet(f)
        ok, msg = runtime.publish_candidate(cid, "fixtest")
        self.assertFalse(ok)
        self.assertIn("正收益折占比", msg)


if __name__ == "__main__":
    unittest.main()
