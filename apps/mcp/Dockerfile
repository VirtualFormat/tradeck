FROM python:3.12-slim

# 与 api / quant 同基础镜像（glibc slim）。curl 供 compose 健康检查 / 调试用。
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 非 root 运行：mcp 是公网入口（经 nginx 反代），不需要任何特权，也不写本地文件
RUN useradd --system --no-create-home --uid 10001 mcp
USER mcp

EXPOSE 8084

# 单进程纪律：PAT 校验缓存（撤销 30 秒生效）与配额计数（每令牌 60 次/分钟、每用户 30 次回测/小时）
# 都在进程内存，多 worker 会让配额按 worker 数放大、撤销生效时间不可控，必须 --workers 1。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8084", "--workers", "1"]
