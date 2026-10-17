FROM python:3.12-slim

# mock seed 一次性 Job 容器：跑完 python -m app.seed_mock 即退出。
# curl 供容器内调试/健康排查用。
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Job 型入口：单事务灌入 mock 数据后进程退出（exit 0 表示成功）。
CMD ["python", "-m", "app.seed_mock"]
