"""配置：从环境变量读取"""
import os


class Settings:
    DATABASE_URL: str
    OPENBB_API_URL: str

    def __init__(self) -> None:
        self.DATABASE_URL = os.getenv(
            "DATABASE_URL",
            "postgresql://tradeck:tradeck_dev@postgres:5432/tradeck",
        )
        self.OPENBB_API_URL = os.getenv("OPENBB_API_URL", "http://openbb:6900")


settings = Settings()
