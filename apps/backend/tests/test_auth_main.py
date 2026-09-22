"""auth_main 入口结构测试：只验证可导入 + 路由表，不触发 lifespan（无需真 DB）。"""
import importlib
import unittest

try:
    import fastapi  # noqa: F401
except ImportError:
    fastapi = None


def _route_paths(app) -> set[str]:
    # fastapi>=0.141 的 include_router 生成 _IncludedRouter 代理（无 .path，
    # 真实路由在 .original_router.routes 内），需递归展开。
    paths: set[str] = set()
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        path = getattr(route, "path", None)
        if path is not None:
            paths.add(path)
        inner = getattr(route, "original_router", None)
        if inner is not None:
            stack.extend(getattr(inner, "routes", []))
    return paths


@unittest.skipIf(fastapi is None, "fastapi 未安装（沙箱缺依赖）")
class TestAuthMain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module("app.auth_main")

    def test_importable(self):
        self.assertIsNotNone(self.module.app)
        self.assertEqual(self.module.app.title, "tradeck auth-api")

    def test_has_auth_routes_and_health(self):
        paths = _route_paths(self.module.app)
        self.assertIn("/api/auth/register", paths)
        self.assertIn("/api/auth/login", paths)
        self.assertIn("/api/auth/session", paths)
        self.assertIn("/api/auth/logout", paths)
        self.assertIn("/health", paths)

    def test_no_market_routes(self):
        paths = _route_paths(self.module.app)
        for p in ("/api/quotes", "/api/historical", "/api/indices", "/api/news"):
            self.assertNotIn(p, paths)
        # 兜底：除 auth/health/OpenAPI 内置端点外不应有其它 /api/* 路由
        api_paths = {p for p in paths if p.startswith("/api/")}
        self.assertTrue(all(p.startswith("/api/auth/") for p in api_paths))


if __name__ == "__main__":
    unittest.main()
