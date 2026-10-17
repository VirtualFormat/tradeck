"""任务化 AI 生成端点（POST /api/ai/generate + task 轮询/取消）的单元测试。

覆盖点：
- POST 登记即返 task_id（202 语义），未配置 AI 返回 200 降级（不建任务）。
- 后台协程终态写回注册表：done 带 result（{valid, code, meta, error} 原结构）。
- generator 业务失败（valid=False）收敛为 done + result，不转 failed（与旧同步版口径一致）。
- 取消幂等：运行中 cancel 转 cancelled（协作式丢弃结果）；终态 cancel 返回现状。
- 路由注册齐全。

说明：直接调端点函数 + 手动驱动后台协程（TestClient 对本仓库 starlette 版本
有挂起问题，见 test_result_wiring）；LLM 调用经 mock 屏蔽（不触网）。
"""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest import mock


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class AIGenerateTaskApiTest(unittest.TestCase):
    """任务化生成的登记/终态/取消语义。"""

    def setUp(self) -> None:
        # 每个用例独立注册表（模块单例跨用例会串状态）
        import app.tasks

        app.tasks._registry = None
        from app.tasks import get_registry

        self.registry = get_registry()

    def tearDown(self) -> None:
        import app.tasks

        app.tasks._registry = None

    def _post_generate(self, description: str = "双均线金叉买入死叉卖出"):
        from app.api import AIGenerateRequest, api_ai_generate

        return _run(api_ai_generate(AIGenerateRequest(description=description)))

    def test_route_registered(self) -> None:
        from app.api import app

        paths = {r.path for r in app.routes}
        for p in (
            "/api/ai/generate",
            "/api/ai/task/{task_id}",
            "/api/ai/task/{task_id}/cancel",
        ):
            self.assertIn(p, paths)

    def test_register_returns_task_id_when_enabled(self) -> None:
        from app.api import AIGenerateRequest, api_ai_generate

        with mock.patch("app.ai.generator.AIStrategyGenerator") as gen_cls:
            gen_cls.return_value.enabled = True
            # 屏蔽后台协程真实执行（单测不调 LLM；协程体由专门用例覆盖）
            with mock.patch("app.api.asyncio.create_task") as create_task:
                resp = _run(api_ai_generate(AIGenerateRequest(description="测试策略描述")))
        self.assertIn("task_id", resp)
        create_task.assert_called_once()
        # 关掉协程对象防 RuntimeWarning（未 await）
        create_task.call_args[0][0].close()

    def test_not_configured_returns_200_without_task(self) -> None:
        with mock.patch("app.ai.generator.AIStrategyGenerator") as gen_cls:
            gen_cls.return_value.enabled = False
            resp = self._post_generate()
        # JSONResponse：200 + 降级错误体；不产生任务
        self.assertEqual(resp.status_code, 200)
        body = json.loads(bytes(resp.body))
        self.assertFalse(body["valid"])
        self.assertIn("AI_API_KEY", body["error"])
        self.assertEqual(self.registry.list(), [])

    def test_background_task_done_with_result(self) -> None:
        from app.api import _run_ai_generate_task

        expected = {"valid": True, "code": "META = {}", "meta": {"id": "ai_x"}, "error": None}
        with mock.patch("app.ai.generator.AIStrategyGenerator") as gen_cls:
            gen_cls.return_value.generate = mock.AsyncMock(return_value=expected)
            task = self.registry.create()
            _run(_run_ai_generate_task(task.task_id, "测试"))
        snap = self.registry.poll(task.task_id)
        self.assertEqual(snap["status"], "done")
        self.assertEqual(snap["result"], expected)

    def test_business_failure_is_done_not_failed(self) -> None:
        """generator valid=False（LLM 网络失败/校验不过）是业务终态：done + result，不转 failed。"""
        from app.api import _run_ai_generate_task

        failed_result = {
            "valid": False,
            "code": "",
            "meta": {},
            "error": "LLM 调用失败（连接或响应异常）",
        }
        with mock.patch("app.ai.generator.AIStrategyGenerator") as gen_cls:
            gen_cls.return_value.generate = mock.AsyncMock(return_value=failed_result)
            task = self.registry.create()
            _run(_run_ai_generate_task(task.task_id, "测试"))
        snap = self.registry.poll(task.task_id)
        self.assertEqual(snap["status"], "done")
        self.assertFalse(snap["result"]["valid"])
        self.assertIn("LLM", snap["result"]["error"])

    def test_generator_exception_marks_failed(self) -> None:
        from app.api import _run_ai_generate_task

        with mock.patch("app.ai.generator.AIStrategyGenerator") as gen_cls:
            gen_cls.return_value.generate = mock.AsyncMock(side_effect=RuntimeError("boom"))
            task = self.registry.create()
            _run(_run_ai_generate_task(task.task_id, "测试"))
        snap = self.registry.poll(task.task_id)
        self.assertEqual(snap["status"], "failed")
        self.assertIn("boom", snap["error"])

    def test_cancel_during_generate_discards_result(self) -> None:
        """运行中取消：LLM 调用结束后丢弃结果转 cancelled（协作式，不打断 HTTP）。"""
        from app.api import _run_ai_generate_task

        task = self.registry.create()

        async def slow_generate(_desc, base_code=None):
            # 模拟 LLM 调用期间用户点了取消
            self.registry.cancel(task.task_id)
            return {"valid": True, "code": "x", "meta": {}, "error": None}

        with mock.patch("app.ai.generator.AIStrategyGenerator") as gen_cls:
            gen_cls.return_value.generate = slow_generate
            _run(_run_ai_generate_task(task.task_id, "测试"))
        snap = self.registry.poll(task.task_id)
        self.assertEqual(snap["status"], "cancelled")
        self.assertNotIn("result", snap)

    def test_poll_unknown_task_404(self) -> None:
        from fastapi import HTTPException

        from app.api import api_ai_task_poll

        with self.assertRaises(HTTPException) as ctx:
            api_ai_task_poll("nonexistent")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_cancel_unknown_task_404(self) -> None:
        from fastapi import HTTPException

        from app.api import api_ai_task_cancel

        with self.assertRaises(HTTPException) as ctx:
            api_ai_task_cancel("nonexistent")
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
