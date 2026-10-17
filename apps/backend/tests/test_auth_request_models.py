"""auth 请求模型校验测试：宽松邮箱形态 + 密码最小长度。

内部部署允许无点号域名（如 best@thu），底线是「恰好一个 @、两端非空、
无空白」；密码 P0 内测期放宽到 6 位。沙箱缺 fastapi/pydantic 时整体 skip。
"""
from __future__ import annotations

import importlib
import unittest

try:
    import fastapi  # noqa: F401
    import pydantic  # noqa: F401
except ImportError:  # 沙箱可能未装，跳过相关用例
    fastapi = None
    pydantic = None


@unittest.skipIf(fastapi is None or pydantic is None, "fastapi/pydantic 未安装（沙箱缺依赖）")
class TestAuthRequestModels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module("app.api.auth")

    def _assert_email_rejected(self, model, email: str):
        with self.assertRaises(Exception):
            model(email=email, password="whatever1")

    def test_internal_email_accepted(self):
        # 无点号域名的内部账号必须可注册/可登录
        reg = self.module.RegisterRequest(email="best@thu", password="thu26p1")
        self.assertEqual(reg.email, "best@thu")
        login = self.module.LoginRequest(email="best@thu", password="thu26p1")
        self.assertEqual(login.email, "best@thu")

    def test_short_password_accepted(self):
        # P0 内测期 6 位密码可注册，6 位以下仍拒绝
        reg = self.module.RegisterRequest(email="a@b", password="123456")
        self.assertEqual(reg.password, "123456")
        with self.assertRaises(Exception):
            self.module.RegisterRequest(email="a@b", password="12345")

    def test_malformed_emails_rejected(self):
        for model in (self.module.RegisterRequest, self.module.LoginRequest):
            for bad in ("no-at-sign", "a@", "@b", "a@@b", "a @b", "a@ b", ""):
                self._assert_email_rejected(model, bad)


if __name__ == "__main__":
    unittest.main()
