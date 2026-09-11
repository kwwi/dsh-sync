"""LLM重分词CLI —— 将语料库从词典分词升级到LLM分词.

用法:
    python scripts/resegment_corpus.py                     # 增量迁移
    python scripts/resegment_corpus.py --limit 100         # 限制数量（测试用）
    python scripts/resegment_corpus.py --concurrency 20    # 20并发（默认10）
    python scripts/resegment_corpus.py --force             # 强制全部重分词
    python scripts/resegment_corpus.py --annotate --export # 重分词+重标注+导出
"""

import argparse
import asyncio
import sys
from pathlib import Path


async def run(
    *,
    force: bool = False,
    limit: int | None = None,
    concurrency: int = 10,
    annotate: bool = False,
    export: bool = False,
) -> int:
    from app.corpus.search import backfill_llm_segmentation, invalidate_search_index
    from app.db.session import get_session_factory, init_db

    await init_db()
    factory = get_session_factory()
    async with factory() as session:
        if force:
            # 将所有语料的 seg_version 重置为 0
            from sqlalchemy import update
            from app.db.session import CitationRecord
            stmt = update(CitationRecord).values(seg_version=0)
            await session.execute(stmt)
            await session.commit()
            print("已重置所有语料的分词版本为 0")

        # 获取待处理数量
        from sqlalchemy import select, func
        from app.db.session import CitationRecord
        pending = await session.scalar(
            select(func.count()).select_from(CitationRecord).where(CitationRecord.seg_version < 1)
        )
        print(f"待重分词语料: {pending} 条")
        if limit:
            print(f"限制数量: {limit} 条")

        count = await backfill_llm_segmentation(session, limit=limit, concurrency=concurrency)
        print(f"\n完成：已迁移 {count} 条语料到 LLM 分词")

        if annotate:
            print("\n重新标注词五行...")
            from app.agents import WordWuxingAgent
            # 清空旧的LLM标注
            from app.db.session import WordWuxingRecord
            from sqlalchemy import delete
            await session.execute(
                delete(WordWuxingRecord).where(WordWuxingRecord.source == "llm_annotation")
            )
            await session.commit()

            agent = WordWuxingAgent()
            annotated = await agent.annotate_all_corpus_words(session)
            print(f"词五行标注完成：新增 {annotated} 条")

            from app.corpus.search import invalidate_word_wuxing_cache
            invalidate_word_wuxing_cache()

        invalidate_search_index()
        print("倒排索引已失效，下次检索时将重建。")

        if export:
            await _export_word_wuxing(session)

    return 0


async def _export_word_wuxing(session) -> None:
    from app.db.session import WordWuxingRecord
    from sqlalchemy import select
    import json

    result = await session.execute(select(WordWuxingRecord))
    records = []
    for r in result.scalars().all():
        records.append({
            "word": r.word,
            "element": r.element,
            "element_cn": r.element_cn,
            "confidence": r.confidence,
            "source": r.source,
        })

    out_path = Path(__file__).resolve().parents[1] / "data" / "wuxing" / "processed" / "word_wuxing_v1.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已导出 {len(records)} 条到 {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM重分词工具")
    parser.add_argument("--force", action="store_true", help="强制重分词所有语料")
    parser.add_argument("--limit", type=int, default=None, help="限制处理数量")
    parser.add_argument("--concurrency", type=int, default=10, help="并发数（默认10）")
    parser.add_argument("--annotate", action="store_true", help="重分词后重新标注词五行")
    parser.add_argument("--export", action="store_true", help="标注后导出 word_wuxing_v1.json")
    args = parser.parse_args()

    code = asyncio.run(run(
        force=args.force,
        limit=args.limit,
        concurrency=args.concurrency,
        annotate=args.annotate,
        export=args.export,
    ))
    sys.exit(code)
