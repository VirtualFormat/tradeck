FROM python:3.12-slim

# 用 glibc（Debian slim）而非 alpine/musl：akshare 部分接口依赖 py_mini_racer
# （V8 JS 引擎，glibc 二进制），在 musl 上加载 libgcc_s.so.1 失败。slim 下开箱可用。
# curl 供健康检查/调试用。
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
