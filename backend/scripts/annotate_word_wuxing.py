"""词五行LLM标注 CLI.

用法:
    python scripts/annotate_word_wuxing.py              # 增量补标（仅标注未覆盖的词）
    python scripts/annotate_word_wuxing.py --force       # 强制重新标注所有词（覆盖已有）
    python scripts/annotate_word_wuxing.py --limit 30    # 限制标注数量（用于测试）
    python scripts/annotate_word_wuxing.py --dry-run     # 仅显示待标注的词，不执行LLM调用
    python scripts/annotate_word_wuxing.py --export      # 标注完成后导出到 JSON 文件
    python scripts/annotate_word_wuxing.py -c 5          # 5 个批次并发调用 LLM
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.db.session import get_session_factory, init_db


async def run(
    *,
    force: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
    export: bool = False,
    concurrency: int = 3,
) -> int:
    from app.corpus.search import load_word_wuxing_map
    from app.corpus.segment import is_content_word
    from sqlalchemy import select
    from app.db.session import CitationRecord

    await init_db()
    factory = get_session_factory()
    async with factory() as session:
        # 收集所有多字实词
        existing = await load_word_wuxing_map(session)

        # 加载已标记为「不宜人名」的词集合，避免重复送LLM判断
        from app.db.session import WordWuxingRecord
        unsuitable_result = await session.execute(
            select(WordWuxingRecord.word).where(
                WordWuxingRecord.suitable_for_name == False
            )
        )
        unsuitable_words: set[str] = {r[0] for r in unsuitable_result.all()}

        stmt = select(CitationRecord.words)
        result = await session.execute(stmt)
        all_words: set[str] = set()
        for (words,) in result:
            if words:
                for w in words:
                    if is_content_word(w) and len(w) == 2:
                        all_words.add(w)

        if force:
            pending = sorted(w for w in all_words if w not in unsuitable_words)
        else:
            pending = sorted(w for w in all_words if w not in existing and w not in unsuitable_words)

        print(f"语料库实词（多字）: {len(all_words)} 个")
        print(f"已标注（适合人名）: {len(existing)} 个")
        print(f"已标记（不宜人名）: {len(unsuitable_words)} 个")
        print(f"待标注: {len(pending)} 个")

        if limit and limit < len(pending):
            pending = pending[:limit]
            print(f"限制数量: {limit} 个")

        if dry_run:
            print("\n待标注词列表:")
            for i, w in enumerate(pending, 1):
                print(f"  {i:3d}. {w}")
            return 0

        if not pending:
            print("没有需要标注的词。")
            return 0

        from app.agents import WordWuxingAgent
        from app.llm.config import resolve_llm_config

        cfg = resolve_llm_config()
        if cfg["mock"] or not cfg["api_key"]:
            print("错误：LLM 不可用（mock 模式或无 API key），无法标注。")
            print("请设置 LLM_MOCK=false 并配置 LLM_API_KEY。")
            return 1

        agent = WordWuxingAgent()
        batch_size = 20  # 每批词数（prompt含人名适合性判断+五行标注）

        # 收集上下文
        from app.db.session import CitationRecord
        from app.corpus.segment import is_content_word
        cit_result = await session.execute(select(CitationRecord))
        word_contexts: dict[str, list[dict]] = {}
        for row in cit_result.scalars().all():
            for w in (row.words or []):
                if w in pending and len(word_contexts.get(w, [])) < 3:
                    word_contexts.setdefault(w, []).append({
                        "book": row.book,
                        "original": (row.original or "")[:50],
                    })

        # ── 构建批次列表 ──
        batches: list[tuple[int, list[str], dict[str, list[dict]]]] = []
        for i in range(0, len(pending), batch_size):
            batch = pending[i : i + batch_size]
            batch_no = i // batch_size + 1
            batch_contexts = {w: word_contexts.get(w, []) for w in batch}
            batches.append((batch_no, batch, batch_contexts))

        total_batches = len(batches)
        print(f"\n共 {total_batches} 个批次，并发数 {concurrency}，开始并行标注...\n")

        # ── 并发控制 ──
        semaphore = asyncio.Semaphore(concurrency)
        from app.db.session import WordWuxingRecord

        el_en_map = {"木": "wood", "火": "fire", "土": "earth", "金": "metal", "水": "water"}

        async def _process_batch(
            batch_no: int, batch: list[str], batch_contexts: dict
        ) -> tuple[int, int]:
            """处理一个批次，使用独立的 DB session，返回 (annotated, unsuitable)."""
            async with semaphore:
                print(f"[批次 {batch_no}/{total_batches}] 开始标注 {len(batch)} 个词...")

                # 每个并发任务用自己的 session
                batch_factory = get_session_factory()
                async with batch_factory() as batch_session:
                    annotations = None
                    for attempt in (1, 2):
                        try:
                            annotations = await agent.annotate_words(batch, contexts=batch_contexts)
                            if annotations:
                                break
                            if attempt == 1:
                                print(f"  [批次{batch_no}] 第{attempt}次返回空结果，重试...")
                        except Exception as exc:
                            if attempt == 1:
                                print(f"  [批次{batch_no}] 第{attempt}次异常: {exc}，重试...")
                            else:
                                print(f"  [批次{batch_no}] 第{attempt}次仍失败: {exc}")

                    if not annotations:
                        print(f"  [批次{batch_no}] LLM 返回空结果，跳过")
                        return 0, 0

                    count = 0
                    unsuitable_count = 0
                    for ann in annotations:
                        word = ann.get("word", "")
                        if not word:
                            continue

                        suitable = ann.get("suitable_for_name")
                        if suitable is False:
                            await batch_session.merge(WordWuxingRecord(
                                word=word,
                                element="", element_cn="",
                                confidence="llm", source="llm_annotation",
                                contexts=batch_contexts.get(word, [])[:3],
                                suitable_for_name=False,
                                annotated_at=datetime.now(timezone.utc),
                                reasoning=ann.get("reasoning", ""),
                            ))
                            print(f"  {word} → [不宜人名] {ann.get('reasoning','')}")
                            unsuitable_count += 1
                            continue

                        primary = ann.get("primary", "") or ann.get("element_cn", "")
                        if primary not in el_en_map:
                            continue
                        secondary = ann.get("secondary") or []
                        secondary = [s for s in secondary if s in el_en_map]
                        pw = ann.get("primary_weight")
                        if pw is not None:
                            pw = max(0.5, min(1.0, float(pw)))
                        await batch_session.merge(WordWuxingRecord(
                            word=word,
                            element=el_en_map[primary],
                            element_cn=primary,
                            secondary_cn=",".join(secondary) if secondary else None,
                            primary_weight=pw,
                            confidence=ann.get("confidence", "medium"),
                            source="llm_annotation",
                            contexts=batch_contexts.get(word, [])[:3],
                            suitable_for_name=True,
                            annotated_at=datetime.now(timezone.utc),
                            reasoning=ann.get("reasoning", ""),
                        ))
                        tag = f" +{','.join(secondary)}" if secondary else ""
                        print(f"  {word} → {primary}{tag} (w={pw}) {ann.get('reasoning','')}")
                        count += 1

                    await batch_session.commit()
                    if unsuitable_count:
                        print(f"  [批次{batch_no}] 标记 {unsuitable_count} 个不宜人名的词")
                    print(f"[批次 {batch_no}/{total_batches}] 完成，标注 {count} 个词")
                    return count, unsuitable_count

        # ── 并发执行所有批次 ──
        tasks = [
            _process_batch(batch_no, batch, ctx)
            for batch_no, batch, ctx in batches
        ]
        results = await asyncio.gather(*tasks)

        total = sum(r[0] for r in results)

        # 所有批次完成后统一失效缓存
        from app.corpus.search import invalidate_word_wuxing_cache
        invalidate_word_wuxing_cache()

        # 显式关闭 LLM 客户端连接池，避免 httpx 在 GC 时报 _transport 错误
        await agent.client.close()

        print(f"\n完成：新增 {total} 条词五行标注")

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
        if r.suitable_for_name is False:
            continue  # 不适合人名的词不导出
        records.append({
            "word": r.word,
            "element": r.element,
            "element_cn": r.element_cn,
            "confidence": r.confidence,
            "source": r.source,
            "suitable_for_name": r.suitable_for_name,
        })

    out_path = Path(__file__).resolve().parents[1] / "data" / "wuxing" / "processed" / "word_wuxing_v1.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已导出 {len(records)} 条到 {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="词五行LLM标注工具")
    parser.add_argument("--force", action="store_true", help="强制重新标注所有词（覆盖已有）")
    parser.add_argument("--limit", type=int, default=None, help="限制标注数量")
    parser.add_argument("--dry-run", action="store_true", help="仅显示待标注词列表，不执行LLM调用")
    parser.add_argument("--export", action="store_true", help="标注完成后导出到 JSON 文件")
    parser.add_argument("-c", "--concurrency", type=int, default=3, help="并发 LLM 调用数（默认 3）")
    args = parser.parse_args()

    code = asyncio.run(run(
        force=args.force,
        limit=args.limit,
        dry_run=args.dry_run,
        export=args.export,
        concurrency=args.concurrency,
    ))
    sys.exit(code)
