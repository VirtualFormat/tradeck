FROM python:3.12-slim

# 与 data-collector 一致用 glibc（Debian slim）：TickFlow SDK 及其传递依赖
# 在 musl 上有二进制兼容风险，slim 下开箱可用。curl 供健康检查/调试用。
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8083

# 单进程纪律：策略注册表/缓存为进程内存，多 worker 会重复加载。
# CLI 用 docker compose run --rm quant python -m app.cli ... 覆盖本 CMD。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8083", "--workers", "1"]
