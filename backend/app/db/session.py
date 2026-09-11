"""数据库层."""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool
from sqlalchemy.types import TypeDecorator

from app.config import get_settings


class _UnescapedJSON(TypeDecorator):
    """JSON 列类型：序列化时保留中文，不转义为 \\uXXXX."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return json.loads(value)


class Base(DeclarativeBase):
    pass


class SessionRecord(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ReportRecord(Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    surname: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict] = mapped_column(_UnescapedJSON)
    paid: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class PricingPlanRecord(Base):
    __tablename__ = "pricing_plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    price_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    channel: Mapped[str] = mapped_column(String(32), default="all")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict] = mapped_column(_UnescapedJSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class OrderRecord(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    report_id: Mapped[str] = mapped_column(String(36), index=True)
    session_id: Mapped[str] = mapped_column(String(36))
    plan_id: Mapped[str] = mapped_column(String(36))
    sku: Mapped[str] = mapped_column(String(64))
    price_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    payment_channel: Mapped[str] = mapped_column(String(32), default="redeem")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PromoCodeRecord(Base):
    __tablename__ = "promo_codes"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    discount_type: Mapped[str] = mapped_column(String(16), default="free")
    discount_value: Mapped[int] = mapped_column(Integer, default=0)
    max_uses: Mapped[int] = mapped_column(Integer, default=100)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CitationRecord(Base):
    __tablename__ = "citations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    book: Mapped[str] = mapped_column(String(64))
    chapter: Mapped[str] = mapped_column(String(128), default="")
    original: Mapped[str] = mapped_column(Text)
    vernacular: Mapped[str] = mapped_column(Text, default="")
    chars: Mapped[list] = mapped_column(_UnescapedJSON, default=list)
    words: Mapped[list] = mapped_column(_UnescapedJSON, default=list)
    tags: Mapped[list] = mapped_column(_UnescapedJSON, default=list)
    seg_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class CharWuxingRecord(Base):
    __tablename__ = "char_wuxing"
    char: Mapped[str] = mapped_column(String(4), primary_key=True)
    element: Mapped[str] = mapped_column(String(16))
    element_cn: Mapped[str] = mapped_column(String(4))
    confidence: Mapped[str] = mapped_column(String(16), default="high")
    source: Mapped[str] = mapped_column(String(64), default="seed")


class WordWuxingRecord(Base):
    """词级别五行属性映射（基于整体意象，LLM标注）."""
    __tablename__ = "word_wuxing"
    word: Mapped[str] = mapped_column(String(16), primary_key=True)
    element: Mapped[str] = mapped_column(String(16))
    element_cn: Mapped[str] = mapped_column(String(4))
    secondary_cn: Mapped[str | None] = mapped_column(String(16), nullable=True)
    primary_weight: Mapped[float | None] = mapped_column(nullable=True)
    confidence: Mapped[str] = mapped_column(String(16), default="llm")
    source: Mapped[str] = mapped_column(String(64), default="llm_annotation")
    contexts: Mapped[list] = mapped_column(_UnescapedJSON, default=list)
    annotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suitable_for_name: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    reasoning: Mapped[str | None] = mapped_column(String(256), nullable=True)
    score: Mapped[int] = mapped_column(BigInteger, default=0)
    pick_count: Mapped[int] = mapped_column(BigInteger, default=0)


class UserNameHistory(Base):
    """用户报告中出现过的名字记录（按 session 去重）."""
    __tablename__ = "user_name_history"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    given_name: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(timezone.utc))


_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        engine_kwargs = {"echo": False, "pool_recycle": 3600}
        if settings.database_url.startswith("mysql"):
            # MySQL + asyncmy 连接池有协议兼容问题，用 NullPool 避免 Command Out of Sync
            engine_kwargs["poolclass"] = NullPool
        _engine = create_async_engine(settings.database_url, **engine_kwargs)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def init_db() -> None:
    import logging
    import os
    from sqlalchemy import text

    _log = logging.getLogger("uvicorn")
    settings = get_settings()
    is_mysql = settings.database_url.startswith("mysql")
    is_sqlite = settings.database_url.startswith("sqlite")
    db_url = settings.database_url

    if is_sqlite:
        os.makedirs("data", exist_ok=True)

    # MySQL: 先确保数据库存在
    # 注意：asyncmy 对 CREATE DATABASE IF NOT EXISTS 在库已存在时会把服务端
    # note 打到 stderr（"Can't create database ... exists"），因此先查再建。
    if is_mysql:
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(db_url)
        db_name = parsed.path.lstrip("/")
        # 去掉 query（charset 等）后连系统库，避免驱动干扰
        base_parts = (parsed.scheme, parsed.netloc, "/mysql", "", "", "")
        base_url = urlunparse(base_parts)
        try:
            tmp_engine = create_async_engine(base_url, echo=False, poolclass=NullPool)
            async with tmp_engine.connect() as tmp_conn:
                exists = await tmp_conn.scalar(
                    text("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = :n"),
                    {"n": db_name},
                )
                if not exists:
                    await tmp_conn.execute(
                        text(
                            f"CREATE DATABASE `{db_name}` "
                            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                        )
                    )
                    await tmp_conn.commit()
            await tmp_engine.dispose()
            _log.info("MySQL 数据库 %s 已就绪", db_name)
        except Exception as e:
            _log.warning("MySQL 创建数据库跳过: %s", str(e)[:100])

    # MySQL：独立临时引擎 + NullPool，避免污染主连接池
    # SQLite/PostgreSQL：必须复用 get_engine()（尤其 :memory: 不能 dispose 另开引擎）
    init_engine = None
    if is_mysql:
        init_engine = create_async_engine(db_url, echo=False, poolclass=NullPool)
        engine = init_engine
    else:
        engine = get_engine()

    try:
        async with engine.connect() as conn:
            # 自动建表
            await conn.run_sync(Base.metadata.create_all)
            await conn.commit()

            # 迁移列（幂等）
            for tbl, col, ctype, dflt in [
                ("citations", "words", "JSON", "[]"),
                ("citations", "seg_version", "INTEGER", "0"),
                ("word_wuxing", "secondary_cn", "VARCHAR(16)", "NULL"),
                ("word_wuxing", "primary_weight", "FLOAT", "NULL"),
                ("word_wuxing", "contexts", "JSON", "'[]'"),
                ("word_wuxing", "suitable_for_name", "BOOLEAN", "NULL"),
                ("word_wuxing", "reasoning", "VARCHAR(256)", "NULL"),
                ("word_wuxing", "score", "BIGINT", "0"),
                ("word_wuxing", "pick_count", "BIGINT", "0"),
            ]:
                await _migrate_add_column(conn, tbl, col, ctype, dflt)

            # 种子数据导入
            await _import_seed_data_if_empty(conn, is_mysql)
            await conn.commit()
    finally:
        if init_engine is not None:
            await init_engine.dispose()


async def _migrate_add_column(conn, table: str, column: str, col_type: str, default: str) -> None:
    """幂等添加列——兼容 SQLite / MySQL / PostgreSQL（列已存在则跳过）."""
    from sqlalchemy import text

    # MySQL 用不同的 DEFAULT 语法，统一用 try/except 兜底
    try:
        await conn.execute(
            text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT {default}")
        )
    except Exception:
        pass  # 列已存在或数据库不支持，跳过


async def _import_seed_data_if_empty(conn, is_mysql: bool = False) -> None:
    """首次启动时，如果核心表为空，自动从 data/seed_data.sql 导入种子数据.

    MySQL 使用命令行 mysql 客户端导入（避免 Python 驱动的协议兼容问题），
    SQLite/PostgreSQL 使用 SQLAlchemy 逐条执行。
    """
    import asyncio as _asyncio
    import logging
    import os
    from pathlib import Path
    from sqlalchemy import text

    _log = logging.getLogger("uvicorn")
    seed_path = Path("data/seed_data.sql")

    if not seed_path.exists():
        _log.info("种子数据文件 %s 不存在，跳过导入", seed_path)
        return

    # 测试环境用 SEED_CITATIONS 小种子，跳过巨型 MySQL dump
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CORPUS_SEED_ONLY") == "1":
        return

    result = await conn.execute(text("SELECT COUNT(*) FROM citations"))
    count = result.scalar()
    if count and count > 0:
        _log.info("数据库已有 %d 条语料，跳过种子数据导入", count)
        return

    _log.info("数据库为空，开始导入种子数据（可能需要 1-2 分钟）…")

    if is_mysql:
        # 用 mysql 命令行导入，绕过 Python 驱动协议问题
        from app.config import get_settings
        settings = get_settings()
        from urllib.parse import urlparse
        u = urlparse(settings.database_url)
        cmd = [
            "mysql",
            f"--host={u.hostname}",
            f"--port={u.port or 3306}",
            f"--user={u.username}",
            f"--password={u.password or ''}",
            f"--database={u.path.lstrip('/')}",
            "--default-character-set=utf8mb4",
            "-e", f"source {seed_path}",
        ]
        try:
            proc = await _asyncio.create_subprocess_exec(
                *cmd,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                err_msg = stderr.decode()[:200] if stderr else "unknown"
                _log.warning("MySQL 种子导入失败 (exit %d): %s", proc.returncode, err_msg)
            else:
                _log.info("MySQL 种子数据导入完成")
        except FileNotFoundError:
            _log.warning("mysql 命令行不可用，回退到 SQLAlchemy 导入")
            await _import_seed_sqlalchemy(conn, seed_path)
        except Exception as e:
            _log.warning("MySQL 种子导入异常: %s", str(e)[:100])
    else:
        await _import_seed_sqlalchemy(conn, seed_path)


async def _import_seed_sqlalchemy(conn, seed_path) -> None:
    """SQLAlchemy 逐条执行 SQL（SQLite/PostgreSQL 回退方案）."""
    import logging
    from sqlalchemy import text

    _log = logging.getLogger("uvicorn")
    sql_content = seed_path.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql_content.split(";\n") if s.strip() and not s.strip().startswith("--")]
    imported = 0
    for stmt in statements:
        try:
            await conn.execute(text(stmt))
            imported += 1
        except Exception as e:
            _log.warning("种子数据导入跳过一条: %s", str(e)[:100])
    await conn.commit()
    _log.info("种子数据导入完成：%d 条语句已执行", imported)


def new_id() -> str:
    return str(uuid.uuid4())
