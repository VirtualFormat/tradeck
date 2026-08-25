"""量化引擎配置：全部从环境变量读取。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """环境变量配置（大小写不敏感，直接读进程环境，不依赖 .env 文件）。"""

    model_config = SettingsConfigDict(env_file=None)

    # data-api（backend）地址：引擎只过 data-api 取数，绝不直连 DB（三条铁律）
    BACKEND_API_URL: str = "http://localhost:8080"
    # 调 data-api 的服务方令牌（X-Service-Token），空表示不带（内网/开发环境）
    SERVICE_TOKEN: str = ""
    # TickFlow API Key：拉除权因子用；为空则用免费档 TickFlow.free()
    TICKFLOW_API_KEY: str = ""
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


settings = Settings()
