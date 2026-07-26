FROM python:3.12-alpine

# 无额外系统依赖：asyncpg/pandas 等均用官方 musllinux wheel，免装编译工具链

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
