"""策略沙箱（docs/MCP.md「轻量沙箱」）端到端单测。

覆盖点：
- 主进程注册表（sandbox=True）对 custom/ai 只静态解析：模块顶层代码不执行，
  compute 为占位，误调抛 SandboxViolation（registry.run 不吞成空信号）。
- needs_sandbox：builtin 否、custom/ai 是、composite 含用户子策略是。
- 沙箱子进程：密钥环境变量不可见、无法写缓存目录；用户策略在子进程真实执行。
- 保存试加载：compute 抛错/形状不符/顶层副作用都在子进程暴露为 422 并回滚；
  错误回显截断。
- validate 接口：不落盘；errors 接口只给文件名。
- 回测 / 选股：用户策略经沙箱子进程跑出与进程内一致的结果。

以非 root 运行（CI/本机）时降权分支不触发（uid 不变），其余属性照常验证；
root 下的降权在 prod 镜像验收（见 plans/TASKS-MCP.md）。
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import polars as pl

_GOOD = '''"""沙箱测试策略：收盘上穿 5 日均线入场。"""
import numpy as np

from app.strategy.base import StrategySignals

META = {"id": "custom_sbx", "name": "沙箱测试", "scoring": {"close": 1.0}}


def compute(enriched, params):
    close = enriched.base.close
    ma5 = enriched["ma5"]
    prev = np.full(close.shape, np.nan)
    prev[1:] = close[:-1] - ma5[:-1]
    entry = (close > ma5) & (prev <= 0)
    exit_ = close < ma5
    return StrategySignals(entry=entry, exit=exit_, score=np.where(entry, close, np.nan))
'''

# 顶层副作用：主进程若执行模块代码会创建该文件
_SIDE_EFFECT = _GOOD.replace(
    "META = {", "np.save(\"__MARKER__\", np.zeros(1))\nMETA = {"
).replace("custom_sbx", "custom_side")

_RAISES = _GOOD.replace("    close = enriched.base.close", "    raise ValueError(\"x\" * 5000)").replace(
    "custom_sbx", "custom_raise"
)

_BAD_SHAPE = _GOOD.replace(
    "    return StrategySignals(entry=entry, exit=exit_, score=np.where(entry, close, np.nan))",
    "    return StrategySignals(entry=entry[:1], exit=exit_[:1], score=close[:1])",
).replace("custom_sbx", "custom_shape")

# 截面 top-k / 长回看窗口：旧 80×3 合成矩阵会误报，放大后应通过（review 回归）
_TOPK = _GOOD.replace(
    "    entry = (close > ma5) & (prev <= 0)",
    "    top = np.argpartition(-np.nan_to_num(close), 10, axis=1)[:, :10]\n"
    "    entry = np.zeros(close.shape, dtype=bool)\n"
    "    np.put_along_axis(entry, top, True, axis=1)\n"
    "    entry &= prev <= 0",
).replace("custom_sbx", "custom_topk")

# 执行期修改 META：静态解析与执行结果不一致，validator 应拒
_META_MUTATED = _GOOD.replace(
    'META = {"id": "custom_sbx", "name": "沙箱测试", "scoring": {"close": 1.0}}',
    'META = {"id": "custom_mut", "name": "沙箱测试", "scoring": {"close": 1.0}}\n'
    'META["params"] = [{"id": "n", "default": 5}]',
)

# 探针：经 ctypes 读子进程 uid 与环境（validator 静态检查放行 np.ctypeslib）
_PROBE = '''import numpy as np

from app.strategy.base import StrategySignals

META = {"id": "custom_probe", "name": "探针", "scoring": {"close": 1.0}}


def compute(enriched, params):
    libc = np.ctypeslib.ctypes.CDLL(None)
    libc.getenv.restype = np.ctypeslib.ctypes.c_char_p
    leaked = libc.getenv(b"AI_API_KEY")
    if leaked:
        raise ValueError("LEAK:" + leaked.decode())
    try:
        np.save(params.get("target") or "__TARGET__", np.zeros(1))
        raise ValueError("WROTE_FILE")
    except OSError:
        pass
    shape = enriched.base.shape
    return StrategySignals(
        entry=np.zeros(shape, dtype=bool), exit=np.zeros(shape, dtype=bool),
        score=np.full(shape, np.nan),
    )
'''

SYM = "AAPL"
_N = 60


def _dates(n: int) -> list[date]:
    out, d = [], date(2025, 1, 2)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _seed(cache: str) -> None:
    from app.data import store

    closes = [10 + (i % 7) * 0.5 + i * 0.05 for i in range(_N)]
    store.save(SYM, pl.DataFrame({
        "symbol": [SYM] * _N,
        "date": _dates(_N),
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": [1_000_000.0] * _N,
        "amount": [c * 1e6 for c in closes],
    }))


class _SandboxCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.chmod(self._tmp.name, 0o755)
        self._patches = [
            mock.patch("app.config.settings.QUANT_CACHE_DIR", self._tmp.name),
            mock.patch.dict(os.environ, {"AI_API_KEY": "sk-secret-should-not-leak"}),
        ]
        for p in self._patches:
            p.start()
        self.user = "u9"

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def _write(self, code: str, sid: str, sub: str = "custom") -> Path:
        from app.runner import user_strategy_dirs

        d = user_strategy_dirs(self.user)[sub]
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{sid}.py"
        path.write_text(code, encoding="utf-8")
        return path


class StaticRegistryTest(_SandboxCase):
    def test_main_process_does_not_execute_user_module(self) -> None:
        from app.api import _registry

        marker = Path(self._tmp.name) / "marker.npy"
        self._write(_SIDE_EFFECT.replace("__MARKER__", str(marker)), "custom_side")
        reg = _registry(self.user)
        sdef = reg.get("custom_side")
        self.assertEqual(sdef.source, "custom")
        self.assertFalse(marker.exists(), "主进程执行了用户策略模块顶层代码")

    def test_placeholder_compute_raises_violation_not_swallowed(self) -> None:
        from app.api import _registry
        from app.matrix import enrich
        from app.sandbox import SandboxViolation
        from app.strategy.loader import _trial_matrix

        self._write(_GOOD, "custom_sbx")
        reg = _registry(self.user)
        enriched = _trial_matrix()
        with self.assertRaises(SandboxViolation):
            reg.run("custom_sbx", enriched)
        self.assertTrue(reg.needs_sandbox("custom_sbx"))
        self.assertFalse(reg.needs_sandbox("ma_golden_cross"))
        _ = enrich  # 仅确认导入路径存在

    def test_composite_with_user_child_needs_sandbox(self) -> None:
        from app.api import _registry

        self._write(_GOOD, "custom_sbx")
        self._write(
            'META = {"id": "custom_combo", "name": "组合", "kind": "composite", '
            '"children": [{"strategy_id": "custom_sbx"}, {"strategy_id": "ma_golden_cross"}]}\n',
            "custom_combo",
        )
        reg = _registry(self.user)
        self.assertTrue(reg.needs_sandbox("custom_combo"))

    def test_errors_endpoint_returns_file_names_only(self) -> None:
        from app.api import api_strategy_errors

        self._write("META = {\"id\": \"custom_bad\"}\ndef compute(e, p):\n    pass\n", "custom_bad")
        errs = api_strategy_errors(user_id=self.user)
        self.assertEqual([e["file"] for e in errs], ["custom_bad.py"])
        self.assertNotIn(self._tmp.name, str(errs))


class SandboxExecutionTest(_SandboxCase):
    def test_probe_hides_secrets_and_blocks_file_writes(self) -> None:
        from app.worker import trial_load_sandboxed

        target = Path(self._tmp.name) / "escape.npy"
        path = self._write(_PROBE.replace("__TARGET__", str(target)), "custom_probe")
        out = trial_load_sandboxed(path, "custom", self.user)
        self.assertEqual(out["strategy_id"], "custom_probe")
        # RLIMIT_FSIZE=0 拦住写入内容；空文件能否创建取决于目录权限——prod 子进程是
        # nobody，对 root 所有的缓存目录无写权限，本机同用户运行时可能留下 0 字节文件
        self.assertTrue(not target.exists() or target.stat().st_size == 0)

    def test_selftest_probe(self) -> None:
        from app.sandbox import run_sandboxed

        out = run_sandboxed("selftest", {"mode": "probe"})
        self.assertNotIn("AI_API_KEY", out["env_keys"])
        self.assertFalse(out["can_write_cache"])
        self.assertEqual(out["today"], date.today())  # 日期标记经 JSON 协议还原

    def test_save_rejects_and_rolls_back(self) -> None:
        from fastapi import HTTPException

        from app.api import StrategySaveRequest, api_strategy_save
        from app.runner import user_strategy_dirs

        for code, sid, needle in (
            (_BAD_SHAPE, "custom_shape", "形状"),
            (_META_MUTATED, "custom_mut", "META"),
        ):
            with self.subTest(sid=sid):
                with self.assertRaises(HTTPException) as ctx:
                    api_strategy_save(StrategySaveRequest(code=code), user_id=self.user)
                self.assertEqual(ctx.exception.status_code, 422)
                self.assertIn(needle, ctx.exception.detail)
                self.assertLessEqual(len(ctx.exception.detail), 2200)  # 截断
                self.assertFalse((user_strategy_dirs(self.user)["custom"] / f"{sid}.py").exists())

    def test_save_good_strategy(self) -> None:
        from app.api import StrategySaveRequest, api_strategy_save

        out = api_strategy_save(StrategySaveRequest(code=_GOOD), user_id=self.user)
        self.assertEqual(out["strategy_id"], "custom_sbx")

    def test_save_accepts_runtime_raising_and_topk(self) -> None:
        """运行期异常 / 截面 top-k 这类在小矩阵上会出错的合法策略不再被拒存。"""
        from app.api import StrategySaveRequest, api_strategy_save

        for code, sid in ((_RAISES, "custom_raise"), (_TOPK, "custom_topk")):
            with self.subTest(sid=sid):
                out = api_strategy_save(StrategySaveRequest(code=code), user_id=self.user)
                self.assertEqual(out["strategy_id"], sid)

    def test_ai_save_failure_restores_previous_version(self) -> None:
        """/api/ai/save 覆盖同 id 失败时还原旧版本（review F3）。"""
        from fastapi import HTTPException

        from app.api import AISaveRequest, api_ai_save
        from app.runner import user_strategy_dirs

        v1 = _GOOD.replace("custom_sbx", "ai_keep")
        v2 = _BAD_SHAPE.replace("custom_shape", "ai_keep")
        api_ai_save(AISaveRequest(code=v1), user_id=self.user)
        with self.assertRaises(HTTPException) as ctx:
            api_ai_save(AISaveRequest(code=v2), user_id=self.user)
        self.assertEqual(ctx.exception.status_code, 422)
        path = user_strategy_dirs(self.user)["ai"] / "ai_keep.py"
        self.assertEqual(path.read_text(encoding="utf-8"), v1)

    def test_builtin_id_collision_rejected(self) -> None:
        """custom 策略与内置同名会被静默屏蔽，保存必须拒绝（review F6）。"""
        from fastapi import HTTPException

        from app.api import StrategySaveRequest, api_strategy_save

        code = _GOOD.replace("custom_sbx", "boll_breakout")
        with self.assertRaises(HTTPException) as ctx:
            api_strategy_save(StrategySaveRequest(code=code), user_id=self.user)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_validate_composite_matches_save(self) -> None:
        """validate 对 composite 子策略引用的结论与 save 一致（review F7）。"""
        from app.api import StrategyValidateRequest, api_strategy_validate

        combo = (
            'META = {"id": "custom_combo", "name": "组合", "kind": "composite", '
            '"children": [{"strategy_id": "custom_missing"}, {"strategy_id": "ma_golden_cross"}]}\n'
        )
        bad = api_strategy_validate(StrategyValidateRequest(code=combo), user_id=self.user)
        self.assertFalse(bad["valid"])
        self.assertIn("custom_missing", bad["error"])
        ok = combo.replace("custom_missing", "macd_golden")
        self.assertTrue(
            api_strategy_validate(StrategyValidateRequest(code=ok), user_id=self.user)["valid"]
        )

    def test_validate_does_not_persist(self) -> None:
        from app.api import StrategyValidateRequest, api_strategy_validate
        from app.runner import user_strategy_dirs

        ok = api_strategy_validate(StrategyValidateRequest(code=_GOOD), user_id=self.user)
        self.assertTrue(ok["valid"], ok)
        self.assertEqual(ok["warnings"], [])
        # compute 在合成矩阵上抛普通异常：与运行时 registry.run 同口径降级，只告警不拒
        warn = api_strategy_validate(StrategyValidateRequest(code=_RAISES), user_id=self.user)
        self.assertTrue(warn["valid"], warn)
        self.assertIn("ValueError", warn["warnings"][0])
        self.assertLessEqual(len(warn["warnings"][0]), 2200)  # 截断
        bad = api_strategy_validate(StrategyValidateRequest(code=_BAD_SHAPE), user_id=self.user)
        self.assertFalse(bad["valid"])
        self.assertIn("形状", bad["error"])
        static = api_strategy_validate(
            StrategyValidateRequest(code="import os\n" + _GOOD), user_id=self.user,
        )
        self.assertFalse(static["valid"])
        self.assertIn("import os", static["error"])
        self.assertFalse(user_strategy_dirs(self.user)["custom"].exists())

    def test_backtest_and_screen_match_inprocess(self) -> None:
        from app.runner import run_backtest, user_strategy_dirs
        from app.screener import screen
        from app.strategy import StrategyRegistry
        from app.worker import run_backtest_in_worker, run_screen_in_worker

        _seed(self._tmp.name)
        self._write(_GOOD, "custom_sbx")
        start, end = _dates(_N)[0], _dates(_N)[-1]
        trusted = StrategyRegistry(user_strategy_dirs(self.user), user_id=self.user)

        expect_bt = run_backtest([SYM], "custom_sbx", start, end, registry=trusted)
        got_bt = asyncio.run(run_backtest_in_worker([SYM], "custom_sbx", start, end, user_id=self.user))
        self.assertGreater(expect_bt["stats"]["trades"], 0)
        self.assertEqual(got_bt["stats"]["trades"], expect_bt["stats"]["trades"])
        self.assertAlmostEqual(got_bt["stats"]["total_return"], expect_bt["stats"]["total_return"])

        expect_sc = screen("custom_sbx", [SYM], end_date=end, registry=trusted)
        got_sc = asyncio.run(run_screen_in_worker("custom_sbx", [SYM], end, None, self.user))
        self.assertEqual(got_sc["total"], expect_sc.total)
        self.assertEqual(got_sc["as_of"], expect_sc.as_of)


if __name__ == "__main__":
    unittest.main()
