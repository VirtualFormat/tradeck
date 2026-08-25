FROM python:3.12-slim

# 与 data-collector 一致用 glibc（Debian slim）：TickFlow SDK 及其传递依赖
# 在 musl 上有二进制兼容风险，slim 下开箱可用。curl 供健康检查/调试用。
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 阶段 A1 占位入口：HTTP 服务（uvicorn app.api）在后续阶段接入，先以 CLI 自检作为 CMD。
CMD ["python", "-m", "app.cli", "--help"]
