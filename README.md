# 智能起名（Name）

基于生辰八字与中华经典文献的智能起名服务 — 微信小程序 + Web + FastAPI 后端。

## 本地环境安装（PostgreSQL + pgvector + Redis）

**Python 依赖已支持**：`asyncpg`、`pgvector`（见 `backend/pyproject.toml`）。

### 一键安装（推荐）

1. 打开 **Docker Desktop**
2. 执行：

```bash
./scripts/setup-local.sh
```

### 检查环境

```bash
./scripts/check-local.sh
```

### 手动启动

```bash
docker compose up -d
cd backend && cp .env.example .env   # 默认 PostgreSQL 连接串
pip install -e ".[dev]"
PYTHONPATH=. python scripts/run_corpus_pipeline.py
```

| 服务 | 地址 | 账号/密码 | 库名 |
|------|------|-----------|------|
| PostgreSQL + pgvector | `localhost:5432` | name / name | name |
| Redis | `localhost:6379` | — | db 0 |

`DATABASE_URL=postgresql+asyncpg://name:name@localhost:5432/name`

验证 pgvector：

```bash
docker compose exec postgres psql -U name -d name -c "SELECT extname FROM pg_extension WHERE extname='vector';"
```

无 Docker 时可在 `backend/.env` 改用 SQLite：`sqlite+aiosqlite:///./data/name.db`

## 快速开始

### 后端

```bash
cd backend
cp .env.example .env
pip install -e ".[dev]"
PYTHONPATH=. uvicorn app.main:app --reload --port 8000
```

### 测试

```bash
cd backend && PYTHONPATH=. pytest tests/ -v
```

### Web

```bash
cd web && npm install && npm run dev
```

访问 http://localhost:5173（API 通过 Vite 代理到 8000）

### 微信小程序

1. 微信开发者工具打开 `miniprogram/` 目录
2. 修改 `app.js` 中 `apiBase` 为可访问的后端地址
3. 开发阶段勾选「不校验合法域名」

## 目录结构

```
name/
├── backend/          # FastAPI + BaziEngine + RAG + Agents
├── web/              # Vite + React Web 端
├── miniprogram/      # 微信原生小程序
├── packages/         # 共享 api-types
├── docs/             # PRD 与架构文档
└── quming.txt        # 黄金范本
```

## 主要 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/bazi/calculate` | 八字排盘 |
| POST | `/api/v1/report/generate` | 生成报告 |
| GET | `/api/v1/report/{id}?tier=preview\|full` | 预览/完整报告 |
| GET | `/api/v1/pricing/plans` | 动态定价 |
| POST | `/api/v1/payment/redeem` | 兑换码解锁 |

**免费规则**：`pricing_plans.price_cents = 0` 时视为免费，`checkout` 自动解锁完整报告，无需兑换码。

MVP 兑换码：`DEMO-FREE`

## 调价

```bash
cd backend && PYTHONPATH=. python scripts/set_price.py report_full 1290
```

或使用管理 API：`PUT /api/v1/admin/pricing/plans/{id}` + `X-Admin-Key` 头。

## LLM 配置

默认 DeepSeek（`LLM_MOCK=true` 时使用内置 Mock）。在 `.env` 中配置：

```
LLM_PROVIDER=deepseek
LLM_API_BASE=https://api.deepseek.com/v1
LLM_API_KEY=sk-...
LLM_MOCK=false
```

## 文档

- [docs/PRD.md](docs/PRD.md)
- [docs/architecture/system-architecture.md](docs/architecture/system-architecture.md)
- [docs/testing/golden-testcase.md](docs/testing/golden-testcase.md)
