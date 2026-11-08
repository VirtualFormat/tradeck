#!/usr/bin/env python3
"""完整读取镜像站的 amd64 manifest、config 与 layer，预热 pull-through 缓存。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request


ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class CacheRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        # 跳到上游 CDN 会绕过缓存节点，不能作为预热成功。
        old = urllib.parse.urlsplit(request.full_url)
        new = urllib.parse.urlsplit(new_url)
        if (new.scheme, new.netloc) != (old.scheme, old.netloc):
            raise ValueError("镜像站将请求重定向到其他站点，无法确认 blob 已缓存")
        return super().redirect_request(request, response, code, message, headers, new_url)


def fetch(opener, url, digest, deadline, *, manifest=False, expected_size=None):
    if not DIGEST.fullmatch(digest):
        raise ValueError("非法镜像 digest")
    for attempt in range(1, 4):
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("预热超过总时限")
            request = urllib.request.Request(url, headers={"Accept": ACCEPT, "User-Agent": "tradeck-image-prewarmer/1.0"})
            checksum = hashlib.sha256()
            chunks = []
            size = 0
            with opener.open(request, timeout=min(30, remaining)) as response:
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("预热超过总时限")
                    chunk = response.read1(1024 * 1024)
                    if not chunk:
                        break
                    checksum.update(chunk)
                    size += len(chunk)
                    if manifest:
                        if size > 8 * 1024 * 1024:
                            raise ValueError("manifest 大小超过限制")
                        chunks.append(chunk)
            if "sha256:" + checksum.hexdigest() != digest:
                raise ValueError("下载内容的 SHA256 与 digest 不一致")
            if expected_size is not None and size != expected_size:
                raise ValueError("下载内容大小与 manifest 不一致")
            print(f"已缓存 {digest}，完整读取 {size} 字节", flush=True)
            return json.loads(b"".join(chunks)) if manifest else None
        except (OSError, ValueError, urllib.error.HTTPError) as error:
            if isinstance(error, urllib.error.HTTPError) and error.code in {401, 403, 404}:
                raise
            if attempt == 3 or time.monotonic() >= deadline:
                raise
            delay = min(attempt * 2, max(0, deadline - time.monotonic()))
            print(f"第 {attempt}/3 次请求失败，{delay:.0f}s 后重试，原因 {error}", flush=True)
            time.sleep(delay)


def warm_image(reference, registry, timeout):
    if not re.fullmatch(r"[a-z0-9.-]+(?::[0-9]+)?", registry):
        raise ValueError("非法镜像站域名")
    repository, digest = reference.split("@", 1)
    if not re.fullmatch(r"[a-z0-9._-]+(?:/[a-z0-9._-]+)+", repository):
        raise ValueError("镜像参数应为 owner/image@sha256:...")
    base = f"https://{registry}/v2/{repository}"
    opener = urllib.request.build_opener(CacheRedirects())
    deadline = time.monotonic() + timeout
    manifest = fetch(opener, f"{base}/manifests/{digest}", digest, deadline, manifest=True)
    if "manifests" in manifest:
        candidates = [
            item for item in manifest["manifests"]
            if item.get("platform", {}).get("os") == "linux"
            and item.get("platform", {}).get("architecture") == "amd64"
        ]
        if len(candidates) != 1:
            raise ValueError("manifest list 必须含有唯一 linux/amd64 镜像")
        item = candidates[0]
        manifest = fetch(
            opener, f"{base}/manifests/{item['digest']}", item["digest"], deadline,
            manifest=True, expected_size=item["size"],
        )
    # 必须 GET 并读完 config 与每一层。HEAD 或只读 manifest 无法预热 blob。
    config = manifest["config"]
    platform = fetch(
        opener, f"{base}/blobs/{config['digest']}", config["digest"], deadline,
        manifest=True, expected_size=config["size"],
    )
    if platform.get("os") != "linux" or platform.get("architecture") != "amd64":
        raise ValueError("镜像平台必须为 linux/amd64")
    for item in manifest["layers"]:
        fetch(opener, f"{base}/blobs/{item['digest']}", item["digest"], deadline,
              expected_size=item["size"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", help="owner/image@sha256:不可变 digest")
    parser.add_argument("--registry", default="ghcr.zqg.cc.cd")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 1800:
        parser.error("timeout 必须在 1 到 1800 秒之间")
    try:
        warm_image(args.reference, args.registry, args.timeout)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"预热失败，原因 {error}\n")


if __name__ == "__main__":
    main()
