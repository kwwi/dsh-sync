from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.admin_pricing import router as admin_router
from app.api.v1.regions import router as regions_router
from app.api.v1.routes import router
from app.api.v1.security import router as security_router
from app.api.v1.wechat_auth import router as wechat_auth_router
from app.api.v1.wechat_pay import router as wechat_pay_router
from app.config import get_settings
from app.corpus.search import seed_corpus_if_empty
from app.db.session import init_db, get_session_factory
from app.api.v1.routes import _cleanup_expired_reports

logger = logging.getLogger("uvicorn")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with get_session_factory()() as session:
        await seed_corpus_if_empty(session)
        # 启动时清理过期报告（保留3天）
        deleted = await _cleanup_expired_reports(session)
        if deleted:
            logger.info(f"Cleaned up {deleted} expired reports")
    # 必须在 lifespan session 关闭后再调度：后台任务使用独立 session，
    # 避免与 asyncmy 关闭连接时发生 IllegalStateChangeError
    _schedule_llm_segmentation()
    yield


def _schedule_llm_segmentation() -> None:
    """LLM可用时，后台异步将词典分词语料迁移为LLM分词（seg_version<1）.

    词五行标注不再于启动时全量执行，改为起名检索时按需补标并落库。
    """
    from app.llm.config import resolve_llm_config

    cfg = resolve_llm_config()
    if cfg["mock"] or not cfg["api_key"]:
        return

    async def _run():
        try:
            from app.corpus.search import backfill_llm_segmentation
            from sqlalchemy import select, func
            from app.db.session import CitationRecord

            async with get_session_factory()() as session:
                pending = await session.scalar(
                    select(func.count()).select_from(CitationRecord).where(
                        CitationRecord.seg_version < 1
                    )
                )
                if pending and pending > 0:
                    logger.info(f"检测到 {pending} 条语料待LLM分词迁移，后台处理中...")
                    migrated = await backfill_llm_segmentation(session)
                    if migrated > 0:
                        logger.info(f"LLM分词迁移完成：{migrated} 条")
        except Exception as e:
            logger.warning(f"LLM分词迁移失败（不影响正常使用）: {e}")

    asyncio.create_task(_run())


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="智能起名 API", version="0.1.0", lifespan=lifespan)
    origins = settings.cors_origin_list
    if origins == ["*"]:
        # CORS 通配符模式：不允许 credentials，适用于开放 API / 小程序等场景
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(router)
    app.include_router(regions_router)
    app.include_router(admin_router)
    app.include_router(security_router)
    app.include_router(wechat_auth_router)
    app.include_router(wechat_pay_router)
    return app


app = create_app()
