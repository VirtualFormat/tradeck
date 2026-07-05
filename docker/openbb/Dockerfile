# OpenBB Platform — 数据层后端
# 作为 docker service 供 tradeck 项目（及其他项目）复用
# PyPI 安装，稳定且快速；源码 clone 仅用于写 akshare-provider 时参考

FROM python:3.12-slim

# 系统依赖（pandas/numpy/lxml 编译需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 安装 OpenBB（含 Platform API + 30+ 官方 Provider）
# 预装免费 Provider：yfinance/sec/fred/federal_reserve/bls/cftc/congress_gov/ecb/eia 等
# 付费 Provider（fmp/intrinio/tiingo 等）装了但不配 key 不启用
RUN pip install --no-cache-dir openbb

# 安装 openbb-akshare-provider（本地包，A 股深度数据）
COPY packages/openbb-akshare-provider /opt/openbb-akshare-provider
RUN pip install --no-cache-dir /opt/openbb-akshare-provider

# 重建 OpenBB 静态资产（注册新 Provider）
RUN openbb-build

# 配置目录
WORKDIR /data
ENV OPENBB_PLATFORM_CONFIG=/root/.openbb_platform
RUN mkdir -p /root/.openbb_platform

# 默认端口 6900（OpenBB Platform API 标准）
EXPOSE 6900

# 健康检查（OpenBB 无 /health 端点，用 /openapi.json 替代）
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -sf http://localhost:6900/openapi.json > /dev/null || exit 1

# 启动 OpenBB Platform API（FastAPI via uvicorn）
CMD ["openbb-api", "--host", "0.0.0.0", "--port", "6900"]
