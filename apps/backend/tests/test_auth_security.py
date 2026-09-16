"""auth_security 单测：密码哈希/校验，纯标准库 + 可选 argon2-cffi，不依赖数据库。

覆盖：
- pbkdf2 往返（hash_password 产出可 verify，同密码不同盐）
- 迭代数越界（被污染的高迭代哈希）立即拒绝，不阻塞进程
- argon2 哈希的校验（argon2-cffi 现造；未装则 skip）
- 错误密码拒绝（两种格式）
- 未知格式 / 损坏格式拒绝（不抛异常）
"""
from __future__ import annotations

import time
import unittest

from app.auth_security import PBKDF2_ITERATIONS, hash_password, verify_password

try:
    from argon2 import PasswordHasher

    _HAS_ARGON2 = True
except ImportError:  # 沙箱可能未装 argon2-cffi，跳过相关用例
    _HAS_ARGON2 = False


class TestPbkdf2(unittest.TestCase):
    def test_roundtrip(self):
        stored = hash_password("S3cret!密码")
        self.assertTrue(verify_password(stored, "S3cret!密码"))

    def test_format(self):
        stored = hash_password("password123")
        parts = stored.split("$")
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[0], "pbkdf2_sha256")
        self.assertEqual(int(parts[1]), PBKDF2_ITERATIONS)
        self.assertEqual(len(parts[2]), 32)  # 16 字节盐 hex
        self.assertEqual(len(parts[3]), 64)  # sha256 hex

    def test_random_salt(self):
        # 同密码两次哈希结果应不同（随机盐）
        self.assertNotEqual(
            hash_password("password123"), hash_password("password123")
        )

    def test_wrong_password_rejected(self):
        stored = hash_password("password123")
        self.assertFalse(verify_password(stored, "password124"))

    def test_corrupted_hash_rejected(self):
        self.assertFalse(verify_password("pbkdf2_sha256$abc$zz$yy", "password123"))
        self.assertFalse(verify_password("pbkdf2_sha256$260000$00$00", "password123"))

    def test_excessive_iterations_rejected_fast(self):
        # 被污染的 20 亿迭代哈希：应立即拒绝（<1s），而不是阻塞事件循环
        stored = "pbkdf2_sha256$2000000000$00$00"
        start = time.monotonic()
        self.assertFalse(verify_password(stored, "password123"))
        self.assertLess(time.monotonic() - start, 1.0)

    def test_zero_iterations_rejected(self):
        # 迭代数下界：0 同样非法，立即拒绝
        self.assertFalse(verify_password("pbkdf2_sha256$0$00$00", "password123"))

@unittest.skipUnless(_HAS_ARGON2, "argon2-cffi 未安装，跳过 argon2 用例")
class TestArgon2(unittest.TestCase):
    def test_verify_argon2id_hash(self):
        # 模拟 web 侧 @node-rs/argon2 产生的 argon2id PHC 串
        stored = PasswordHasher().hash("password123")
        self.assertTrue(stored.startswith("$argon2id$"))
        self.assertTrue(verify_password(stored, "password123"))

    def test_wrong_password_rejected(self):
        stored = PasswordHasher().hash("password123")
        self.assertFalse(verify_password(stored, "password124"))


class TestUnknownFormat(unittest.TestCase):
    def test_unknown_prefix_rejected(self):
        self.assertFalse(verify_password("bcrypt$2b$10$xxxx", "password123"))
        self.assertFalse(verify_password("plain-text-password", "password123"))

    def test_empty_inputs_rejected(self):
        self.assertFalse(verify_password("", "password123"))
        self.assertFalse(verify_password(hash_password("password123"), ""))


if __name__ == "__main__":
    unittest.main()
