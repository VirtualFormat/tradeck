"""配置：从环境变量读取"""
import os


class Settings:
    DATABASE_URL: str
    OPENBB_API_URL: str
    OPENBB_OVERSEAS_API_URL: str
    OPENBB_OVERSEAS_TOKEN: str
    TICKFLOW_API_KEY: str
    DEV_SEED: bool

    def __init__(self) -> None:
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
        # dev 环境启动时自动灌入假数据（仅 devcontainer 置 1；prod 不置，默认关）。
        self.DEV_SEED = os.getenv("DEV_SEED", "") == "1"


settings = Settings()
