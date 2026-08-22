"""配置：从环境变量读取（mock seed 独立容器用）"""
import os
from typing import Literal, cast


DataMode = Literal["live", "mock"]
_VALID_DATA_MODES = {"live", "mock"}


class Settings:
    DATABASE_URL: str
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


settings = Settings()
