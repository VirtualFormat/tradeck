# OpenBB Platform — 数据层后端
# 作为 docker service 供 tradeck 项目（及其他项目）复用
# PyPI 安装，稳定且快速。
# 注：A 股报价与深度数据已由 backend 经 call_akshare 直调 akshare，不再依赖自写 provider。

FROM python:3.12-alpine

# 系统依赖（curl 用于健康检查；alpine/musl 下 pandas/numpy/lxml 等均用官方 musllinux wheel，免装编译工具链）
RUN apk add --no-cache curl ca-certificates

# 安装 OpenBB（含 Platform API + 30+ 官方 Provider）
# 预装免费 Provider：yfinance/sec/fred/federal_reserve/bls/cftc/congress_gov/ecb/eia 等
# 付费 Provider（fmp/intrinio/tiingo 等）装了但不配 key 不启用
RUN pip install --no-cache-dir openbb && \
    pip uninstall -y openbb-cftc 2>/dev/null || true

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
# openbb-api 不支持 --workers 参数，用 uvicorn 直接启动支持多 worker
CMD ["uvicorn", "openbb_platform_api.main:app", "--host", "0.0.0.0", "--port", "6900", "--workers", "4"]
