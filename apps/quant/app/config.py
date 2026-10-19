"""量化引擎配置：全部从环境变量读取。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """环境变量配置（大小写不敏感，直接读进程环境，不依赖 .env 文件）。"""

    model_config = SettingsConfigDict(env_file=None)

    # data-api（backend）地址：引擎只过 data-api 取数，绝不直连 DB（三条铁律）；
    # 默认兜底仅供本地开发，生产由环境变量注入 tradb data-api 回环地址。
    BACKEND_API_URL: str = "http://localhost:8080"
    # 调 data-api 的服务方令牌（X-Service-Token），空表示不带（内网/开发环境）；
    # 须与 tradb 侧 SERVICE_TOKENS 中的某个 token 对应，compose 由 QUANT_SERVICE_TOKEN 注入。
    SERVICE_TOKEN: str = ""
    # Parquet 缓存根目录（行情/因子缓存 + enriched 矩阵 + 报告/候选库）
    QUANT_CACHE_DIR: str = "/data/cache"
    # AI 策略生成：提供商标识（如 openai/anthropic 兼容协议），留空即关闭 AI 功能
    AI_PROVIDER: str = ""
    # AI 接口地址（OpenAI 兼容 base_url）
    AI_BASE_URL: str = ""
    # AI 接口密钥，绝不入库/入日志
    AI_API_KEY: str = ""
    # AI 模型名
    AI_MODEL: str = ""
    # 采样温度：留空不传（用服务端默认）。部分模型（如 Kimi K3）服务端固定 temperature=1，
    # 显式传其他值会被 400 拒绝，故默认不传；仅确认端点支持自定义时填写（如 0.3）。
    AI_TEMPERATURE: float | None = None
    # 多用户骨架（docs/QUANT-BACKTEST.md v2 §0）：未携带 X-User-Id 时的回落用户；
    # 现阶段不鉴权，仅做存储命名空间隔离。
    QUANT_DEFAULT_USER: str = "default"
    # 入站服务令牌（JSON {"<token>": "<consumer>"}，与 api 服务 SERVICE_TOKENS 同格式，
    # 见 docs/MCP.md）：非空时除 /health 外的请求必须带有效 X-Service-Token，
    # 且必须带 X-User-Id（不再回落 QUANT_DEFAULT_USER）；空 = 不鉴权（dev / 旧部署兼容）。
    INBOUND_SERVICE_TOKENS: str = ""
    # 启动迁移：把 users/{QUANT_DEFAULT_USER}/ 下的数据目录迁给该用户（如 u1）；空 = 不迁移。
    # 背景：web 早期不透传 X-User-Id，prod 全部策略/因子/候选库都落在 default 命名空间。
    QUANT_MIGRATE_DEFAULT_TO: str = ""
    # 策略沙箱子进程降权 uid（docs/MCP.md「轻量沙箱」）：quant 以 root 运行时，
    # 执行用户策略的子进程切到该 uid/gid（默认 65534 nobody）；<=0 不降权（仅限 dev）。
    QUANT_SANDBOX_UID: int = 65534
    # 回测 worker 池大小（spawn 子进程数；默认 1 = 串行，重计算不拖垮主进程）
    QUANT_WORKER_POOL_SIZE: int = 1
    # 每用户活跃任务上限（回测 + AI 生成任务合计，pending+running；docs/MCP.md P0）：
    # 防单人（或被提示注入的 agent）占满全局 32 个任务额度；<=0 表示不限。
    QUANT_MAX_CONCURRENT_PER_USER: int = 2
    # 每日信号定时任务总开关：False 时 lifespan 不注册每日信号 job（E4/K1）。
    QUANT_SIGNAL_ENABLED: bool = True
    # 每日信号 universe：逗号分隔的规范 symbol（如 AAPL,600519.SH,00700.HK）；
    # 留空则用 jobs.DEFAULT_SIGNAL_UNIVERSE（collector tracked 100 只的内联子集）。
    QUANT_SIGNAL_UNIVERSE: str = ""


settings = Settings()
