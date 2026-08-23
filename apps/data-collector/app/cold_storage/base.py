"""ColdStorage 抽象基类：冷层文件接口（Parquet 读写 + 幂等 + 列分区）。

路径语义统一：key 是逻辑路径（如 minute_bars/year=2026/market=CN/part-000.parquet），
local 后端拼到本地根目录、s3 后端拼到 bucket。业务只传 key。

方法均为同步（Parquet 写是 CPU/IO 操作）；调用方 job 用 asyncio.to_thread 包裹，
不阻塞 collector 的事件循环。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ColdStorage(ABC):
    """冷层文件存储接口。"""

    @abstractmethod
    def write_parquet(
        self,
        key: str,
        rows: list[dict[str, Any]],
        *,
        sort_by: list[str],
    ) -> str:
        """把行写成 Parquet（snappy 压缩，按 sort_by 排序）。

        分钟K 必须传 sort_by=["symbol", "ts"]——文件内按 symbol 排序后，
        DuckDB 可凭 row group 统计跳过非目标 symbol（回测点查性能关键，
        见 docs/DATA-STORAGE-TIERED.md）。

        返回实际写入的完整路径/URI。覆盖同 key（幂等：重跑覆盖同分区文件）。
        失败抛带 key + backend 上下文的异常（由调用方 job catch 记日志降级）。
        """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """幂等判断：key 是否已存在。"""

    @abstractmethod
    def read_parquet(self, key: str) -> list[dict[str, Any]]:
        """读回（测试/校验用）。失败抛带上下文异常。"""

    @abstractmethod
    def list_keys(self, prefix: str) -> list[str]:
        """列某分区前缀下的所有 key。"""
