"""配置：从环境变量读取"""
import os
from typing import Literal, cast


DataMode = Literal["live", "mock"]
_VALID_DATA_MODES = {"live", "mock"}


class Settings:
    DATABASE_URL: str
    OPENBB_API_URL: str
    OPENBB_OVERSEAS_API_URL: str
    OPENBB_OVERSEAS_TOKEN: str
    TICKFLOW_API_KEY: str
    DATA_SYNC_TOKEN: str
    COLD_STORAGE_BACKEND: str
    COLD_STORAGE_LOCAL_ROOT: str
    COLD_S3_BUCKET: str
    COLD_S3_ENDPOINT: str
    COLD_S3_ACCESS_KEY: str
    COLD_S3_SECRET_KEY: str
    COLD_S3_REGION: str
    DATA_MODE: DataMode

    def __init__(self) -> None:
        data_mode = os.getenv("DATA_MODE", "live").strip()
        if data_mode not in _VALID_DATA_MODES:
            allowed = ", ".join(sorted(_VALID_DATA_MODES))
            raise ValueError(
                f"Invalid DATA_MODE={data_mode!r}; expected one of: {allowed}"
            )
        self.DATA_MODE = cast(DataMode, data_mode)

        self.DATABASE_URL = os.getenv(
            "DATABASE_URL",
            "postgresql://tradeck:tradeck_dev@postgres:5432/tradeck",
        )
        self.OPENBB_API_URL = os.getenv("OPENBB_API_URL", "http://openbb:6900")
        # 海外节点（韩国瘦 OpenBB）。为空则海外源回落到国内 OPENBB_API_URL，行为不变。
        self.OPENBB_OVERSEAS_API_URL = os.getenv("OPENBB_OVERSEAS_API_URL", "")
        self.OPENBB_OVERSEAS_TOKEN = os.getenv("OPENBB_OVERSEAS_TOKEN", "")
        # TickFlow 日K 源。为空则用免费档 TickFlow.free()（日K 足够，盘中不实时）。
        self.TICKFLOW_API_KEY = os.getenv("TICKFLOW_API_KEY", "")
        # 数据中心手动同步令牌。仅 Next.js 服务端代理持有，避免公网直接触发重任务。
        # mock 模式强制禁用，避免通过 API 启动任何真实数据任务。
        self.DATA_SYNC_TOKEN = (
            os.getenv("DATA_SYNC_TOKEN", "") if self.DATA_MODE == "live" else ""
        )
        # ── 冷层存储（分钟K/tick Parquet，app/cold_storage/）──
        # 后端：local（本地文件，日常开发/单测默认）/ s3（S3 兼容，生产指 COS、
        # 验收指本地 MinIO）。
        self.COLD_STORAGE_BACKEND = os.getenv("COLD_STORAGE_BACKEND", "local").strip()
        # local 后端根目录。
        self.COLD_STORAGE_LOCAL_ROOT = os.getenv("COLD_STORAGE_LOCAL_ROOT", "./data-lake")
        # s3 后端：bucket + endpoint（COS 指 COS endpoint，MinIO 指 minio:9000，
        # 真 AWS S3 留空）+ 密钥。s3 后端缺 bucket/key 时 get_cold_storage 抛错。
        self.COLD_S3_BUCKET = os.getenv("COLD_S3_BUCKET", "")
        self.COLD_S3_ENDPOINT = os.getenv("COLD_S3_ENDPOINT", "")
        self.COLD_S3_ACCESS_KEY = os.getenv("COLD_S3_ACCESS_KEY", "")
        self.COLD_S3_SECRET_KEY = os.getenv("COLD_S3_SECRET_KEY", "")
        self.COLD_S3_REGION = os.getenv("COLD_S3_REGION", "")


settings = Settings()
