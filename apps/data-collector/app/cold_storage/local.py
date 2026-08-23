"""本地文件系统后端：日常开发/单测用，零依赖离线可用。

key 拼到根目录（默认 ./data-lake）下，自动建目录。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.cold_storage.base import ColdStorage


class LocalColdStorage(ColdStorage):
    def __init__(self, root: str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # 防路径逃逸：用 relative_to 判定 p 是否在 root 内（startswith 前缀匹配
        # 会被 /app/data-lake-evil 这类同前缀目录绕过）
        p = (self._root / key).resolve()
        try:
            p.relative_to(self._root.resolve())
        except ValueError:
            raise ValueError(f"非法 key（路径逃逸）: {key!r}")
        return p

    def write_parquet(
        self,
        key: str,
        rows: list[dict[str, Any]],
        *,
        sort_by: list[str],
    ) -> str:
        import pyarrow as pa
        import pyarrow.parquet as pq

        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            table = pa.Table.from_pylist(rows)
            if sort_by:
                # pyarrow sort_by 需 [(列名, 方向), ...] 形式，统一升序
                table = table.sort_by([(c, "ascending") for c in sort_by])
            pq.write_table(table, path, compression="snappy")
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"local 后端写 Parquet 失败 key={key!r}: {e}") from e
        return str(path)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def read_parquet(self, key: str) -> list[dict[str, Any]]:
        import pyarrow.parquet as pq

        path = self._path(key)
        try:
            return pq.read_table(path).to_pylist()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"local 后端读 Parquet 失败 key={key!r}: {e}") from e

    def list_keys(self, prefix: str) -> list[str]:
        base = self._path(prefix)
        if not base.exists():
            return []
        root_len = len(str(self._root.resolve()))
        return [
            str(p)[root_len:].lstrip("/")
            for p in sorted(base.rglob("*.parquet"))
            if p.is_file()
        ]
