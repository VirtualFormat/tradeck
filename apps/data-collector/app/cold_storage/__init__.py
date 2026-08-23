"""冷层存储 provider（ColdStorage）：分钟K/tick 的 Parquet 落地。

双后端按环境变量切换（COLD_STORAGE_BACKEND）：
- local：本地文件系统（默认，日常开发/单测，零依赖离线可用）
- s3：S3 兼容对象存储（boto3；生产指向腾讯云 COS，验收指向本地 MinIO）

业务代码（分钟K 采集 job）只面向 ColdStorage 接口，不关心后端。
测试策略：日常用 local 验逻辑，上线真 COS 前用 MinIO 验 S3 协议路径。

设计见 docs/DATA-STORAGE-TIERED.md（冷层分区布局 + 文件内排序决策）。
"""
from app.cold_storage.base import ColdStorage

__all__ = ["ColdStorage", "get_cold_storage", "reset_cold_storage"]

_instance: ColdStorage | None = None


def get_cold_storage() -> ColdStorage:
    """按 config.COLD_STORAGE_BACKEND 返回对应后端单例。"""
    global _instance
    if _instance is not None:
        return _instance

    from app.config import settings

    backend = settings.COLD_STORAGE_BACKEND
    if backend == "local":
        from app.cold_storage.local import LocalColdStorage

        _instance = LocalColdStorage(settings.COLD_STORAGE_LOCAL_ROOT)
    elif backend == "s3":
        from app.cold_storage.s3 import S3ColdStorage

        _instance = S3ColdStorage(
            bucket=settings.COLD_S3_BUCKET,
            endpoint_url=settings.COLD_S3_ENDPOINT or None,
            access_key=settings.COLD_S3_ACCESS_KEY,
            secret_key=settings.COLD_S3_SECRET_KEY,
            region=settings.COLD_S3_REGION or None,
        )
    else:
        raise ValueError(
            f"非法 COLD_STORAGE_BACKEND={backend!r}；期望 local / s3"
        )
    return _instance


def reset_cold_storage() -> None:
    """清缓存单例（测试切换后端用）。"""
    global _instance
    _instance = None
