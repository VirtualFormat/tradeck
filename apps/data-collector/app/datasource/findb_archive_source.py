"""findb COS 分发包只读客户端。

prod 通过 CVM 绑定的 CAM 角色获取临时凭证，以 COS XML API 下载 full 档
MANIFEST 和模块文件。仅用于人工触发的全量初始化，不参与日常调度。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


def _credentials() -> tuple[str, str, str]:
    """从腾讯云 CVM 元数据服务读取角色临时凭证。"""
    role = urllib.parse.quote(settings.FINDB_COS_ROLE, safe="")
    url = (
        "http://metadata.tencentyun.com/latest/meta-data/cam/"
        f"security-credentials/{role}"
    )
    with urllib.request.urlopen(url, timeout=5) as response:
        payload = json.loads(response.read())
    return payload["TmpSecretId"], payload["TmpSecretKey"], payload["Token"]


def _authorization(
    secret_id: str,
    secret_key: str,
    method: str,
    uri: str,
    headers: dict[str, str],
) -> str:
    now = int(time.time())
    key_time = f"{now - 60};{now + 3600}"
    sign_key = hmac.new(
        secret_key.encode(), key_time.encode(), hashlib.sha1
    ).hexdigest()

    def encode(items: dict[str, str]) -> str:
        return "&".join(
            f"{urllib.parse.quote(key.lower(), safe='')}="
            f"{urllib.parse.quote(str(value), safe='')}"
            for key, value in sorted(items.items())
        )

    lowered = {key.lower(): value for key, value in headers.items()}
    http_string = f"{method.lower()}\n{uri}\n\n{encode(lowered)}\n"
    string_to_sign = (
        f"sha1\n{key_time}\n{hashlib.sha1(http_string.encode()).hexdigest()}\n"
    )
    signature = hmac.new(
        sign_key.encode(), string_to_sign.encode(), hashlib.sha1
    ).hexdigest()
    return (
        f"q-sign-algorithm=sha1&q-ak={secret_id}&q-sign-time={key_time}"
        f"&q-key-time={key_time}&q-header-list={';'.join(sorted(lowered))}"
        f"&q-url-param-list=&q-signature={signature}"
    )


def _request(key: str) -> Any:
    secret_id, secret_key, token = _credentials()
    bucket = settings.FINDB_ARCHIVE_BUCKET
    region = settings.FINDB_ARCHIVE_REGION
    host = f"{bucket}.cos.{region}.myqcloud.com"
    uri = "/" + urllib.parse.quote(key, safe="/_.-")
    headers = {"Host": host}
    request = urllib.request.Request(f"https://{host}{uri}", method="GET")
    request.add_header(
        "Authorization",
        _authorization(secret_id, secret_key, "GET", uri, headers),
    )
    request.add_header("x-cos-security-token", token)
    return urllib.request.urlopen(request, timeout=60)


def read_json(key: str) -> dict[str, Any]:
    """读取一个 JSON 对象。"""
    with _request(key) as response:
        return json.loads(response.read())


def download(key: str, target: Path, expected_sha256: str) -> int:
    """流式下载并校验 SHA256，成功后原子替换 target。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    digest = hashlib.sha256()
    size = 0
    try:
        with _request(key) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(4 * 1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        actual = digest.hexdigest()
        if actual != expected_sha256:
            raise ValueError(
                f"COS 对象校验失败 key={key}: expected={expected_sha256}, actual={actual}"
            )
        os.replace(temporary, target)
        return size
    finally:
        temporary.unlink(missing_ok=True)


def full_manifest() -> dict[str, Any]:
    prefix = settings.FINDB_ARCHIVE_PREFIX
    return read_json(f"{prefix}/MANIFEST.json")
