"""配置：从环境变量读取"""
import os
from typing import Literal, cast


DataMode = Literal["live", "mock"]
_VALID_DATA_MODES = {"live", "mock"}


class Settings:
    DATABASE_URL: str
    OPENBB_API_URL: str
    COLLECTOR_API_URL: str
    TICKFLOW_API_KEY: str
    DATA_SYNC_TOKEN: str
    SERVICE_TOKENS: str
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
        # data-collector 运维 API（任务状态/调度信息）。海外分流属写路径，
        # 已收敛在 collector，data-api 不再持有 OPENBB_OVERSEAS_* 配置。
        self.COLLECTOR_API_URL = os.getenv(
            "COLLECTOR_API_URL", "http://collector:8080"
        )
        # TickFlow 日K 源。为空则用免费档 TickFlow.free()（日K 足够，盘中不实时）。
        self.TICKFLOW_API_KEY = os.getenv("TICKFLOW_API_KEY", "")
        # 数据中心手动同步令牌。仅 Next.js 服务端代理持有，避免公网直接触发重任务。
        # mock 模式强制禁用，避免通过 API 启动任何真实数据任务。
        self.DATA_SYNC_TOKEN = (
            os.getenv("DATA_SYNC_TOKEN", "") if self.DATA_MODE == "live" else ""
        )
        # 消费方鉴权令牌表（JSON：{"<token>": "<consumer_name>"}）。data-api 作为
        # 唯一数据出口后用于区分消费方（限流/审计/未来收紧）。空 = 未启用，
        # 全部放行（内网默认）；配置后量化批量接口强制有效 X-Service-Token。
        self.SERVICE_TOKENS = os.getenv("SERVICE_TOKENS", "")


settings = Settings()
