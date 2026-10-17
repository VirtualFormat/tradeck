"""密码哈希与校验（用户登录 P0）。

支持两种哈希格式（register 产生 pbkdf2，web 侧 @node-rs/argon2 预哈希产生 argon2）：
- ``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>``
  本进程自实现：hashlib.pbkdf2_hmac（sha256，260000 次，16 字节随机盐）。
  无第三方依赖，供 /api/auth/register 直接落库。
- ``argon2`` 开头（argon2-cffi 标准 PHC 字符串，如 ``$argon2id$...``）
  web BFF 侧用 @node-rs/argon2 预哈希后传来的格式，经 argon2-cffi 校验。

verify_password 按前缀自动分发；未知格式一律拒绝（返回 False），绝不抛异常。
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

logger = logging.getLogger(__name__)

# pbkdf2 参数（OWASP 对 sha256 的推荐量级；迭代数写进哈希串，日后可调）
PBKDF2_ITERATIONS = 260_000
PBKDF2_SALT_BYTES = 16
# 迭代数上限：超出范围视为被污染的哈希，直接拒绝
PBKDF2_MAX_ITERATIONS = 1_000_000
_PBKDF2_PREFIX = "pbkdf2_sha256"
_ARGON2_PREFIX = "$argon2"


def hash_password(password: str) -> str:
    """生成 pbkdf2_sha256 格式哈希（register 落库用）。"""
    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"{_PBKDF2_PREFIX}${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_pbkdf2(stored: str, password: str) -> bool:
    try:
        _prefix, iterations_s, salt_hex, hash_hex = stored.split("$", 3)
        iterations = int(iterations_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, TypeError):
        logger.warning("pbkdf2 哈希格式损坏，按校验失败处理")
        return False
    # 边界校验：防止库中被污染的高迭代哈希阻塞单进程事件循环（单进程 DoS）
    if not (1 <= iterations <= PBKDF2_MAX_ITERATIONS):
        logger.warning("pbkdf2 迭代数越界（%d），按校验失败处理", iterations)
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _verify_argon2(stored: str, password: str) -> bool:
    try:
        from argon2 import PasswordHasher
        from argon2.exceptions import Argon2Error, VerificationError
    except ImportError:
        logger.error("argon2-cffi 未安装，无法校验 argon2 哈希（按失败处理）")
        return False
    try:
        # argon2-cffi：verify 内部用恒定时间比较；参数不匹配的异常一并按失败处理
        return PasswordHasher().verify(stored, password)
    except (Argon2Error, VerificationError):
        return False


def verify_password(stored_hash: str, password: str) -> bool:
    """校验密码。按哈希前缀分发 argon2 / pbkdf2；未知格式返回 False。"""
    if not stored_hash or not password:
        return False
    if stored_hash.startswith(_ARGON2_PREFIX):
        return _verify_argon2(stored_hash, password)
    if stored_hash.startswith(f"{_PBKDF2_PREFIX}$"):
        return _verify_pbkdf2(stored_hash, password)
    logger.warning("未知密码哈希格式（前缀不符），按校验失败处理")
    return False
