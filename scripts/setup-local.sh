#!/usr/bin/env bash
# 本地环境一键安装：Python 依赖 + Docker(PostgreSQL/pgvector + Redis)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> 1/4 检查 Docker"
if ! command -v docker >/dev/null 2>&1; then
  echo "未安装 Docker，请先安装 Docker Desktop: https://www.docker.com/products/docker-desktop/"
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker 未运行，请先启动 Docker Desktop，然后重新执行本脚本。"
  exit 1
fi

echo "==> 2/4 启动 PostgreSQL(pgvector) + Redis"
docker compose up -d
echo "等待数据库就绪..."
for i in {1..30}; do
  if docker compose exec -T postgres pg_isready -U name -d name >/dev/null 2>&1; then
    echo "PostgreSQL 已就绪"
    break
  fi
  sleep 1
  if [[ $i -eq 30 ]]; then
    echo "PostgreSQL 启动超时"
    exit 1
  fi
done

echo "==> 3/4 安装 Python 依赖"
cd backend
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "已创建 backend/.env（使用 PostgreSQL）"
fi
pip install -e ".[dev]" -q

echo "==> 4/4 初始化数据库表与种子数据"
PYTHONPATH=. python scripts/run_corpus_pipeline.py

echo ""
echo "完成。验证 pgvector："
docker compose exec -T postgres psql -U name -d name -c "SELECT extname, extversion FROM pg_extension WHERE extname='vector';"

echo ""
echo "启动后端: cd backend && PYTHONPATH=. uvicorn app.main:app --reload --port 8000"
echo "启动 Web:   cd web && npm install && npm run dev"
