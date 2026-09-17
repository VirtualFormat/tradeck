"""AI 策略保存端点（POST /api/ai/save）的单元测试。

覆盖点：
- 合法代码落盘到用户命名空间 strategies/ai/{id}.py，落盘后注册表可见（热生效）。
- 幂等：同 id 重复保存覆盖更新。
- 安全闸：未过 validator 的代码 422 拒绝，不落盘。
- 防路径穿越：id 形态白名单（ai_ 前缀 + 限定字符），畸形 id 422。
- 落盘后加载失败回滚删文件（不留半截策略）。

说明：与 test_result_wiring 同款——TestClient 对本仓库 starlette 版本有挂起问题，
故直接调用端点函数；QUANT_CACHE_DIR 经 mock.patch 指向临时目录隔离。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

_VALID_CODE = (
    '"""测试策略。"""\n'
    "\n"
    "import numpy as np\n"
    "\n"
    "from app.strategy.base import StrategySignals\n"
    "\n"
    "META = {\n"
    '    "id": "ai_test_save",\n'
    '    "name": "测试保存策略",\n'
    '    "scoring": {"close": 1.0},\n'
    "}\n"
    "\n"
    "\n"
    "def compute(enriched, params):\n"
    "    shape = enriched.base.shape\n"
    "    entry = np.zeros(shape, dtype=bool)\n"
    "    exit_ = np.zeros(shape, dtype=bool)\n"
    "    score = np.zeros(shape, dtype=float)\n"
    "    return StrategySignals(entry=entry, exit=exit_, score=score)\n"
)


class AISaveApiTest(unittest.TestCase):
    """保存端点行为（直接调端点函数，HTTP 转换由 FastAPI 保证）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        # 缓存目录指向临时目录：用户命名空间（含 strategies/ai/）落在其中
        self._patch = mock.patch(
            "app.config.settings.QUANT_CACHE_DIR", self._tmp.name
        )
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def _save(self, code: str):
        from app.api import AISaveRequest, api_ai_save

        return api_ai_save(AISaveRequest(code=code), user_id="tester")

    def _ai_dir(self) -> Path:
        return Path(self._tmp.name) / "users" / "tester" / "strategies" / "ai"

    def test_save_valid_code_persists_and_loads(self) -> None:
        resp = self._save(_VALID_CODE)
        self.assertTrue(resp["saved"])
        self.assertEqual(resp["strategy_id"], "ai_test_save")
        self.assertEqual(resp["name"], "测试保存策略")
        # 文件落盘
        path = self._ai_dir() / "ai_test_save.py"
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(encoding="utf-8"), _VALID_CODE)
        # 注册表热生效（每次请求重建，无需重启）
        from app.api import _registry

        s = _registry("tester").get("ai_test_save")
        self.assertEqual(s.source, "ai")

    def test_save_idempotent_overwrite(self) -> None:
        self._save(_VALID_CODE)
        updated = _VALID_CODE.replace("测试保存策略", "测试保存策略v2")
        resp = self._save(updated)
        self.assertTrue(resp["saved"])
        self.assertEqual(resp["name"], "测试保存策略v2")
        files = list(self._ai_dir().glob("*.py"))
        self.assertEqual(len(files), 1)  # 同 id 覆盖，不产生第二份文件

    def test_save_rejects_unsafe_code(self) -> None:
        from fastapi import HTTPException

        evil = _VALID_CODE.replace(
            "import numpy as np", "import os\nimport numpy as np"
        )
        with self.assertRaises(HTTPException) as ctx:
            self._save(evil)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("白名单", ctx.exception.detail)
        self.assertFalse(self._ai_dir().exists())  # 未落盘

    def test_save_rejects_non_ai_prefix_id(self) -> None:
        from fastapi import HTTPException

        bad = _VALID_CODE.replace("ai_test_save", "evil_strategy")
        with self.assertRaises(HTTPException) as ctx:
            self._save(bad)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertFalse(self._ai_dir().exists())

    def test_save_rollback_when_load_fails(self) -> None:
        """validator 通过但执行期加载失败（compute 非函数）→ 删文件回滚。"""
        from fastapi import HTTPException

        # validator 只查 compute 存在（含 async），不查是否可调用；
        # 把 compute 改成常量，loader 的 _wrap_compute 会拒 → 触发回滚分支
        code = _VALID_CODE.replace(
            "def compute(enriched, params):",
            "async def compute(enriched, params):",
        )
        # async def 过 validator 的「存在性」检查；再在模块尾部覆盖为常量
        code += "\ncompute = 42\n"
        with self.assertRaises(HTTPException) as ctx:
            self._save(code)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("已回滚", ctx.exception.detail)
        self.assertFalse((self._ai_dir() / "ai_test_save.py").exists())

    def test_route_registered(self) -> None:
        from app.api import app

        paths = {r.path for r in app.routes}
        self.assertIn("/api/ai/save", paths)


if __name__ == "__main__":
    unittest.main()
