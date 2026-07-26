"""配置：从环境变量读取"""
import os


class Settings:
    DATABASE_URL: str
    OPENBB_API_URL: str
    OPENBB_OVERSEAS_API_URL: str
    OPENBB_OVERSEAS_TOKEN: str

    def __init__(self) -> None:
        self.DATABASE_URL = os.getenv(
            "DATABASE_URL",
            "postgresql://tradeck:tradeck_dev@postgres:5432/tradeck",
        )
        self.OPENBB_API_URL = os.getenv("OPENBB_API_URL", "http://openbb:6900")
        # 海外节点（韩国瘦 OpenBB）。为空则海外源回落到国内 OPENBB_API_URL，行为不变。
        self.OPENBB_OVERSEAS_API_URL = os.getenv("OPENBB_OVERSEAS_API_URL", "")
        self.OPENBB_OVERSEAS_TOKEN = os.getenv("OPENBB_OVERSEAS_TOKEN", "")


settings = Settings()
