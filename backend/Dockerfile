# ── 微信云托管 Dockerfile ──
# MySQL 8.0 + 种子数据自动导入
# 环境变量在云托管控制台配置，不要写入镜像

FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖层（利用 Docker 缓存）
COPY pyproject.toml .
RUN pip install --no-cache-dir \
    fastapi>=0.115.0 \
    uvicorn[standard]>=0.32.0 \
    pydantic>=2.9.0 \
    pydantic-settings>=2.6.0 \
    lunar-python>=1.4.0 \
    pypinyin>=0.53.0 \
    sqlalchemy>=2.0.36 \
    asyncmy>=0.2.9 \
    aiosqlite>=0.20.0 \
    httpx>=0.28.0 \
    openai>=1.55.0 \
    python-multipart>=0.0.12 \
    aiofiles>=24.1.0 \
    pyyaml>=6.0.2 \
    zhconv>=1.4.3 \
    fpdf2>=2.8.0 \
    cryptography>=43.0.0

# 应用代码
COPY app/ ./app/
COPY scripts/ ./scripts/

# 种子数据（首次启动自动导入 MySQL）
COPY data/seed_data.sql ./data/

# 微信云托管端口
EXPOSE 80

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]
