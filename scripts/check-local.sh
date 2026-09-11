#!/usr/bin/env bash
# 检查本地依赖是否就绪
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ok=0
fail=0

check() {
  if eval "$2" >/dev/null 2>&1; then
    echo "[OK] $1"
    ok=$((ok+1))
  else
    echo "[--] $1"
    fail=$((fail+1))
  fi
}

check "Python 3.10+" "python3 -c 'import sys; assert sys.version_info>=(3,10)'"
check "pip 包 fastapi" "python3 -c 'import fastapi'"
check "pip 包 asyncpg" "python3 -c 'import asyncpg'"
check "pip 包 pgvector" "python3 -c 'import pgvector'"
check "Docker 已安装" "command -v docker"
check "Docker 守护进程运行中" "docker info"
check "PostgreSQL 容器运行中" "docker compose exec -T postgres pg_isready -U name -d name"
check "pgvector 扩展已启用" "docker compose exec -T postgres psql -U name -d name -tAc \"SELECT 1 FROM pg_extension WHERE extname='vector'\" | grep -q 1"
check "Redis 容器运行中" "docker compose exec -T redis redis-cli ping | grep -q PONG"

echo ""
echo "通过 $ok 项，未通过 $fail 项"
if [[ $fail -gt 0 ]]; then
  echo "运行 ./scripts/setup-local.sh 安装并启动（需先打开 Docker Desktop）"
  exit 1
fi
