#!/usr/bin/env python3
"""语料采集 → 五行库 → 入库（从公网 GitHub 镜像抓取公版古籍）."""

import asyncio
import time

from app.corpus.crawler.pipeline import run_pipeline_async
from app.corpus.crawler.wuxing.pipeline import run_wuxing_pipeline_async
from app.corpus.search import sync_corpus_from_file, sync_wuxing_from_file
from app.db.session import get_session_factory, init_db
from app.services.pricing import seed_pricing_if_empty

CITATIONS_PATH = "data/corpus/processed/citations.json"
WUXING_PATH = "data/wuxing/processed/char_wuxing_v1.json"


async def main() -> None:
    t0 = time.perf_counter()

    print("==> 1/4 从公网抓取公版语料")
    await run_pipeline_async("data/corpus/processed")
    print(f"    完成，耗时 {time.perf_counter() - t0:.1f}s")

    t1 = time.perf_counter()
    print("==> 2/4 生成五行字库（本地缓存索引 + 种子覆盖）")
    await run_wuxing_pipeline_async(citations_path=CITATIONS_PATH, output=WUXING_PATH)
    print(f"    完成，耗时 {time.perf_counter() - t1:.1f}s")

    print("==> 3/4 初始化数据库")
    await init_db()

    t2 = time.perf_counter()
    print("==> 4/4 批量同步语料与五行到 PostgreSQL")
    factory = get_session_factory()
    async with factory() as session:
        n_cit = await sync_corpus_from_file(session, CITATIONS_PATH)
        n_wx = await sync_wuxing_from_file(session, WUXING_PATH)
        await seed_pricing_if_empty(session)
    print(f"    入库完成，耗时 {time.perf_counter() - t2:.1f}s")
    print(f"pipeline done: {n_cit} citations, {n_wx} char_wuxing rows（总耗时 {time.perf_counter() - t0:.1f}s）")


if __name__ == "__main__":
    asyncio.run(main())
