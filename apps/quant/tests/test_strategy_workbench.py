"""AI 策略工作台新增端点的单元测试。

覆盖点：
- GET /api/strategies/{id}/code：读取已有策略源码（custom/ai/builtin），404。
- POST /api/ai/tweak：登记调整任务（mock 掉 LLM），未配置 AI 时 200 降级。
- POST /api/strategies/save：统一保存入口——
  ai_ 前缀进 ai/、非 ai_ 进 custom/、overwrite 覆盖/重命名（含回滚）、builtin 只读 409。

说明：与 test_ai_save 同款——TestClient 对本仓库 starlette 版本有挂起问题，
故直接调用端点函数；QUANT_CACHE_DIR 经 mock.patch 指向临时目录隔离。
"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_AI_CODE = (
    '"""测试 AI 策略。"""\n'
    "\n"
    "import numpy as np\n"
    "\n"
    "from app.strategy.base import StrategySignals\n"
    "\n"
    "META = {\n"
    '    "id": "ai_workbench_test",\n'
    '    "name": "工作台测试策略",\n'
    '    "scoring": {"close": 1.0},\n'
    "}\n"
    "\n"
    "\n"
    "def compute(enriched, params):\n"
    "    shape = enriched.base.shape\n"
    "    return StrategySignals(\n"
    "        entry=np.zeros(shape, dtype=bool),\n"
    "        exit=np.zeros(shape, dtype=bool),\n"
    "        score=np.zeros(shape, dtype=float),\n"
    "    )\n"
)

_CUSTOM_CODE = _AI_CODE.replace("ai_workbench_test", "custom_workbench_test").replace(
    "工作台测试策略", "工作台自定义策略"
)


class _CacheDirTestCase(unittest.TestCase):
    """把 QUANT_CACHE_DIR 指向临时目录的基类（用户命名空间隔离）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = mock.patch(
            "app.config.settings.QUANT_CACHE_DIR", self._tmp.name
        )
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def _dirs(self, user: str = "tester") -> dict[str, Path]:
        base = Path(self._tmp.name) / "users" / user / "strategies"
        return {"custom": base / "custom", "ai": base / "ai"}


class StrategyCodeReadTest(_CacheDirTestCase):
    """源码读取端点。"""

    def test_read_saved_strategy_code(self) -> None:
        from app.api import StrategySaveRequest, api_strategy_save, get_strategy_code

        api_strategy_save(StrategySaveRequest(code=_AI_CODE), user_id="tester")
        resp = get_strategy_code("ai_workbench_test", user_id="tester")
        self.assertEqual(resp["id"], "ai_workbench_test")
        self.assertEqual(resp["source"], "ai")
        self.assertEqual(resp["code"], _AI_CODE)

    def test_read_missing_strategy_404(self) -> None:
        from fastapi import HTTPException

        from app.api import get_strategy_code

        with self.assertRaises(HTTPException) as ctx:
            get_strategy_code("nonexistent_strategy", user_id="tester")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_read_builtin_strategy(self) -> None:
        """builtin 策略源码可读（展示/另存底稿），不写。"""
        from app.api import _registry, get_strategy_code

        reg = _registry("tester")
        builtins = [s for s in reg.all() if s.source == "builtin"]
        if not builtins:
            self.skipTest("无内置策略（包目录为空）")
        sid = builtins[0].strategy_id
        resp = get_strategy_code(sid, user_id="tester")
        self.assertEqual(resp["source"], "builtin")
        self.assertIn("META", resp["code"])


class StrategySaveUnifiedTest(_CacheDirTestCase):
    """统一保存端点（POST /api/strategies/save）。"""

    def _save(self, code: str, overwrite_id: str | None = None):
        from app.api import StrategySaveRequest, api_strategy_save

        return api_strategy_save(
            StrategySaveRequest(code=code, overwrite_id=overwrite_id),
            user_id="tester",
        )

    def test_ai_prefix_goes_to_ai_dir(self) -> None:
        resp = self._save(_AI_CODE)
        self.assertTrue(resp["saved"])
        self.assertEqual(resp["strategy_id"], "ai_workbench_test")
        self.assertTrue((self._dirs()["ai"] / "ai_workbench_test.py").exists())

    def test_non_ai_prefix_goes_to_custom_dir(self) -> None:
        resp = self._save(_CUSTOM_CODE)
        self.assertTrue(resp["saved"])
        self.assertEqual(resp["strategy_id"], "custom_workbench_test")
        self.assertTrue(
            (self._dirs()["custom"] / "custom_workbench_test.py").exists()
        )
        self.assertFalse(
            (self._dirs()["ai"] / "custom_workbench_test.py").exists()
        )

    def test_overwrite_same_id_updates_in_place(self) -> None:
        self._save(_AI_CODE)
        updated = _AI_CODE.replace("工作台测试策略", "工作台测试策略v2")
        resp = self._save(updated, overwrite_id="ai_workbench_test")
        self.assertTrue(resp["saved"])
        files = list(self._dirs()["ai"].glob("*.py"))
        self.assertEqual(len(files), 1)
        self.assertIn("v2", files[0].read_text(encoding="utf-8"))

    def test_overwrite_rename_moves_file(self) -> None:
        """overwrite_id 与 META.id 不同 → 重命名（旧文件删除，新文件落盘）。"""
        self._save(_AI_CODE)
        renamed = _AI_CODE.replace("ai_workbench_test", "ai_workbench_renamed")
        resp = self._save(renamed, overwrite_id="ai_workbench_test")
        self.assertTrue(resp["saved"])
        self.assertEqual(resp["strategy_id"], "ai_workbench_renamed")
        self.assertFalse((self._dirs()["ai"] / "ai_workbench_test.py").exists())
        self.assertTrue((self._dirs()["ai"] / "ai_workbench_renamed.py").exists())
        # 注册表里旧 id 不可见、新 id 可见
        from app.api import _registry

        reg = _registry("tester")
        with self.assertRaises(KeyError):
            reg.get("ai_workbench_test")
        self.assertEqual(reg.get("ai_workbench_renamed").source, "ai")

    def test_overwrite_builtin_rejected(self) -> None:
        from fastapi import HTTPException

        from app.api import _registry

        reg = _registry("tester")
        builtins = [s for s in reg.all() if s.source == "builtin"]
        if not builtins:
            self.skipTest("无内置策略（包目录为空）")
        builtin_id = builtins[0].strategy_id
        code = _AI_CODE.replace("ai_workbench_test", builtin_id)
        with self.assertRaises(HTTPException) as ctx:
            self._save(code, overwrite_id=builtin_id)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("只读", ctx.exception.detail)

    def test_overwrite_missing_strategy_404(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self._save(_AI_CODE, overwrite_id="nonexistent_strategy")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_rename_rollback_restores_old_file(self) -> None:
        """重命名后新代码加载失败 → 旧文件还原、新文件删除。"""
        from fastapi import HTTPException

        self._save(_AI_CODE)
        # compute 被覆盖为常量 → validator 过（存在性）但 loader 拒 → 触发回滚
        broken = _AI_CODE.replace("ai_workbench_test", "ai_workbench_broken")
        broken += "\ncompute = 42\n"
        with self.assertRaises(HTTPException) as ctx:
            self._save(broken, overwrite_id="ai_workbench_test")
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("已回滚", ctx.exception.detail)
        # 旧文件还原，新文件与 .bak 都不留
        self.assertTrue((self._dirs()["ai"] / "ai_workbench_test.py").exists())
        self.assertFalse((self._dirs()["ai"] / "ai_workbench_broken.py").exists())
        self.assertEqual(list(self._dirs()["ai"].glob("*.bak")), [])
        # 注册表里旧策略仍可加载
        from app.api import _registry

        self.assertEqual(
            _registry("tester").get("ai_workbench_test").source, "ai"
        )

    def test_overwrite_same_id_rollback_keeps_old_file(self) -> None:
        """同 id 覆盖保存但新代码加载失败 → 旧文件还原（不丢已保存策略）。"""
        from fastapi import HTTPException

        self._save(_AI_CODE)
        broken = _AI_CODE + "\ncompute = 42\n"  # validator 过、loader 拒 → 回滚
        with self.assertRaises(HTTPException) as ctx:
            self._save(broken, overwrite_id="ai_workbench_test")
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("已回滚", ctx.exception.detail)
        # 旧文件内容完整还原，无残留 .bak
        path = self._dirs()["ai"] / "ai_workbench_test.py"
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(encoding="utf-8"), _AI_CODE)
        self.assertEqual(list(self._dirs()["ai"].glob("*.bak")), [])
        from app.api import _registry

        self.assertEqual(
            _registry("tester").get("ai_workbench_test").source, "ai"
        )

    def test_cross_dir_same_id_conflict_rejected(self) -> None:
        """同名 id 文件已存在于另一目录 → 409 拒绝双写（防注册表 id 冲突）。"""
        from fastapi import HTTPException

        self._save(_AI_CODE)  # ai_workbench_test 落 ai/
        # 目录由 id 前缀决定，正常流程不会出现同 id 跨目录；直接放文件模拟
        # 残留/手工挪文件造成的脏状态，验证静态冲突检查兜底
        dirs = self._dirs()
        dirs["custom"].mkdir(parents=True, exist_ok=True)
        (dirs["custom"] / "ai_workbench_test.py").write_text(_AI_CODE, encoding="utf-8")
        with self.assertRaises(HTTPException) as ctx:
            self._save(_AI_CODE)  # 目标 ai/ai_workbench_test.py，custom/ 有同名
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("已存在", ctx.exception.detail)

    def test_rejects_unsafe_code(self) -> None:
        from fastapi import HTTPException

        evil = _AI_CODE.replace("import numpy as np", "import os\nimport numpy as np")
        with self.assertRaises(HTTPException) as ctx:
            self._save(evil)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertFalse(self._dirs()["ai"].exists())

    def test_route_registered(self) -> None:
        from app.api import app

        paths = {r.path for r in app.routes}
        self.assertIn("/api/strategies/save", paths)
        self.assertIn("/api/strategies/{strategy_id}/code", paths)
        self.assertIn("/api/ai/tweak", paths)


class AITweakTaskTest(_CacheDirTestCase):
    """AI 调整端点（任务登记 + 后台协程，LLM 调用 mock 掉）。"""

    def test_tweak_task_done_via_mock_generator(self) -> None:
        from app import api as api_mod
        from app.ai.generator import AIStrategyGenerator

        tweaked = _AI_CODE.replace("工作台测试策略", "调整后策略")

        async def _fake_generate(self, description, base_code=None):
            _fake_generate.calls.append(
                {"description": description, "base_code": base_code}
            )
            return {
                "valid": True,
                "code": tweaked,
                "meta": {"id": "ai_workbench_test", "name": "调整后策略"},
                "error": None,
            }

        _fake_generate.calls = []

        async def _run() -> None:
            with (
                mock.patch.object(AIStrategyGenerator, "enabled", True),
                mock.patch.object(
                    AIStrategyGenerator, "generate", _fake_generate
                ),
            ):
                resp = await api_mod.api_ai_tweak(
                    api_mod.AITweakRequest(
                        code=_AI_CODE, description="把止损收紧到 5%"
                    )
                )
                task_id = resp["task_id"]
                state = None
                for _ in range(200):
                    state = api_mod.api_ai_task_poll(task_id)
                    if state["status"] in ("done", "failed", "cancelled"):
                        break
                    await asyncio.sleep(0.05)
                self.assertIsNotNone(state)
                self.assertEqual(state["status"], "done")
                self.assertTrue(state["result"]["valid"])
                self.assertEqual(state["result"]["code"], tweaked)
                # base_code 被透传给 generator（prompt 组装在 generator 内）
                self.assertEqual(
                    _fake_generate.calls[0]["base_code"], _AI_CODE
                )

        asyncio.run(_run())

    def test_tweak_not_configured_degrades(self) -> None:
        from app import api as api_mod
        from app.ai.generator import AIStrategyGenerator

        async def _run() -> None:
            with mock.patch.object(AIStrategyGenerator, "enabled", False):
                return await api_mod.api_ai_tweak(
                    api_mod.AITweakRequest(
                        code=_AI_CODE, description="把止损收紧到 5%"
                    )
                )

        resp = asyncio.run(_run())
        # 未配置 AI 时返回 200 JSONResponse（不建任务），前端按降级路径展示
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
