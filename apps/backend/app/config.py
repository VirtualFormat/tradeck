"""配置：从环境变量读取"""
import logging
import os
from typing import Literal, cast

logger = logging.getLogger(__name__)

DataMode = Literal["live", "mock"]
_VALID_DATA_MODES = {"live", "mock"}


def _parse_user_ids(raw: str, env_name: str) -> frozenset[int] | None:
    """解析逗号分隔的 auth.users.id 名单。

    返回 None = 未配置（无任何非空项）；否则返回合法 id 集合。空项跳过，
    非法项（非正整数，如误写成 quant 口径的 u1）忽略并告警——只会收窄名单。
    配置了但全部非法时返回空集合（= 拒绝所有人，fail-closed），绝不退化成
    「未配置 = 全部放行」。
    """
    ids: set[int] = set()
    configured = False
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        configured = True
        try:
            value = int(item)
        except ValueError:
            value = 0
        if value < 1:
            logger.warning("%s 含非法用户 id %r（应为正整数），已忽略", env_name, item)
            continue
        ids.add(value)
    if not configured:
        return None
    if not ids:
        logger.error("%s 已配置但无合法用户 id，按拒绝所有用户处理", env_name)
    return frozenset(ids)


class Settings:
    DATABASE_URL: str
    OPENBB_API_URL: str
    COLLECTOR_API_URL: str
    CLICKHOUSE_URL: str
    CLICKHOUSE_DATABASE: str
    TICKFLOW_API_KEY: str
    DATA_SYNC_TOKEN: str
    SERVICE_TOKENS: str
    DATA_POOL_ROOT: str
    DATA_MODE: DataMode
    AUTH_DATABASE_URL: str
    AUTH_INVITE_CODE: str
    AUTH_SESSION_DAYS: int
    PAT_ALLOWED_USER_IDS: frozenset[int] | None

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
        # tradb data-collector 运维 API（任务状态/调度信息聚合）。
        self.COLLECTOR_API_URL = os.getenv(
            "COLLECTOR_API_URL", "http://tradb-collector:8080"
        )
        # ClickHouse 温层（分钟K 在线 1 年）。data-api 只读查询，查不到/不可达
        # 即降级空数组，无需 ENABLED 开关（与 DB 查询失败降级一致）。
        self.CLICKHOUSE_URL = os.getenv(
            "CLICKHOUSE_URL", "http://clickhouse:8123"
        ).rstrip("/")
        self.CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "tradeck")
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
        # CORS 允许的来源（逗号分隔）。data-api 是服务间 API（消费方走
        # X-Service-Token 鉴权），本不该允许浏览器任意跨域；默认空 = 不放开
        # 跨域。仅确有浏览器直连场景（如 dev 跨端口调试）时显式配置。
        self.CORS_ORIGINS = os.getenv("CORS_ORIGINS", "")
        # data-api 只读挂载自有 Parquet 池，用于分钟 K UNION 查询。
        self.DATA_POOL_ROOT = os.getenv("DATA_POOL_ROOT", "/data/market-pool")
        # ---- 用户登录（P0，/api/auth/*）----
        # auth 库连接串：tradeck 自建 api 服务专用（用户域数据不再放 tradb）。
        # 行情 data-api 进程不使用本字段（仍走 DATABASE_URL 连 tradb）。
        self.AUTH_DATABASE_URL = os.getenv(
            "AUTH_DATABASE_URL",
            "postgresql://tradeck:tradeck_dev@localhost:5432/tradeck_auth",
        )
        # 邀请码：非空时注册必须携带匹配的 invite_token；空 = 开放注册。
        self.AUTH_INVITE_CODE = os.getenv("AUTH_INVITE_CODE", "")
        # 会话有效期（天），登录时 expires_at = now() + N 天。
        raw_session_days = os.getenv("AUTH_SESSION_DAYS", "7")
        try:
            session_days = int(raw_session_days)
        except ValueError:
            raise ValueError(
                f"Invalid AUTH_SESSION_DAYS={raw_session_days!r}; expected integer >= 1"
            ) from None
        if session_days < 1:
            raise ValueError(
                f"Invalid AUTH_SESSION_DAYS={raw_session_days!r}; expected integer >= 1"
            )
        self.AUTH_SESSION_DAYS = session_days
        # ---- 个人访问令牌（PAT，/api/auth/tokens，见 docs/MCP.md）----
        # 可签发 PAT 的用户 id 名单（逗号分隔 auth.users.id）：小范围使用的门禁。
        # 空（None）= 所有登录用户可签发；非空时名单外用户签发 403、已签发令牌
        # verify 401；配置了但全部非法 = 空集合 = 拒绝所有人（fail-closed）。
        self.PAT_ALLOWED_USER_IDS = _parse_user_ids(
            os.getenv("PAT_ALLOWED_USER_IDS", ""), "PAT_ALLOWED_USER_IDS"
        )


settings = Settings()
