"""将语料 JSON 同步到数据库 — 含质量加权检索."""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.corpus.seed_data import (
    BOOK_DYNASTY_MAP,
    BOOK_QUALITY_SCORE,
    DEFAULT_BOOK_QUALITY,
    ELEMENT_CN_TO_EN,
    GENERATES,
    HIGH_QUALITY_BOOKS,
    SEED_CHAR_WUXING,
    SEED_CITATIONS,
    SEED_WORD_WUXING,
    WUXING_CORRECTIONS,
)
from app.db.session import CharWuxingRecord, CitationRecord, WordWuxingRecord

_CORPUS_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULT_CITATIONS_PATH = _CORPUS_DIR / "corpus" / "processed" / "citations.json"
DEFAULT_WUXING_PATH = _CORPUS_DIR / "wuxing" / "processed" / "char_wuxing_v1.json"
BATCH_SIZE = 500

_wuxing_map_cache: dict[str, str] | None = None


def _dialect_name(session: AsyncSession) -> str:
    bind = session.get_bind()
    return bind.dialect.name if bind is not None else ""


async def seed_corpus_if_empty(session: AsyncSession) -> None:
    existing = await session.scalar(select(CitationRecord.id).limit(1))
    if not existing:
        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CORPUS_SEED_ONLY") == "1":
            for c in SEED_CITATIONS:
                # 去除 quality 字段（运行时通过 _citation_quality_score 计算）
                clean = {k: v for k, v in c.items() if k != "quality"}
                await session.merge(CitationRecord(**clean))
            for char, w in SEED_CHAR_WUXING.items():
                await session.merge(CharWuxingRecord(char=char, **w))
            await session.commit()
        else:
            await sync_corpus_from_file(session)
    else:
        # 已有语料：检查是否需要回填 words 字段
        await backfill_words_if_needed(session)
    # 五行数据独立检查：即使语料已存在也确保加载
    await seed_wuxing_if_empty(session)
    # 词五行种子数据
    await seed_word_wuxing_if_empty(session)


async def backfill_words_if_needed(session: AsyncSession) -> None:
    """为已有语料回填 words 字段（词典分词）.

    仅做词典分词回填（快速，不阻塞启动）。
    LLM 重分词迁移请通过 CLI 工具显式执行:
        python scripts/resegment_corpus.py
    """
    from app.corpus.segment import segment_citation

    # 检查是否已有任何语料包含 words
    try:
        sample = await session.scalar(
            select(CitationRecord.words).limit(1)
        )
        # 如果 sample 有内容，说明已经迁移过
        if sample is not None and len(sample) > 0:
            return
    except Exception:
        # words 列可能还不存在（init_db 迁移失败时），跳过回填
        return

    # 词典分词回填（快速，不调用 LLM）
    offset = 0
    batch_size = 500
    total = 0
    while True:
        stmt = select(CitationRecord).offset(offset).limit(batch_size)
        rows = (await session.execute(stmt)).scalars().all()
        if not rows:
            break
        for row in rows:
            if not row.words:
                row.words = segment_citation(row.original or "")
                total += 1
        await session.commit()
        offset += batch_size
        print(f"    分词迁移 {offset} 条...")
    if total > 0:
        print(f"    完成：回填 {total} 条语料的 words 字段")


async def backfill_llm_segmentation(
    session: AsyncSession,
    *,
    batch_size: int = 20,
    limit: int | None = None,
    concurrency: int = 10,
) -> int:
    """使用LLM对旧分词（seg_version=0）的语料重新分词.

    多协程并发调用LLM，通过信号量控制并发数。
    每 batch_size 条提交一次，支持断点续传。
    """
    import asyncio
    import time
    from app.corpus.segment import segment_citation_llm, segment_citation
    from app.llm.config import resolve_llm_config

    cfg = resolve_llm_config()
    print(f"LLM 配置: provider={cfg['provider']}, model={cfg['model']}, 并发={concurrency}")
    if cfg["mock"] or not cfg["api_key"]:
        print("LLM 不可用（mock模式或无API key），跳过")
        return 0

    stmt = select(CitationRecord).where(CitationRecord.seg_version < 1)
    if limit:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    if not rows:
        print("没有需要迁移的语料")
        return 0

    print(f"待处理: {len(rows)} 条，每 {batch_size} 条提交一次，并发={concurrency}")
    sem = asyncio.Semaphore(concurrency)
    t_start = time.time()
    total = 0
    fallback_count = 0
    processed: list[tuple[int, str, int, int, float]] = []  # (idx, id, n_chars, n_words, elapsed)

    # 共享一个 LLM 客户端，避免每个并发任务各自创建 httpx 连接池
    from app.llm.client import get_llm_client
    shared_client = get_llm_client()

    async def _process_one(idx: int, row) -> None:
        async with sem:
            t0 = time.time()
            try:
                row.words = await segment_citation_llm(row.original or "", client=shared_client)
                elapsed = time.time() - t0
            except Exception:
                row.words = segment_citation(row.original or "")
                elapsed = 0
            row.seg_version = 1
            n_words = len(row.words)
            n_chars = len(row.original or "")
            processed.append((idx, row.id, n_chars, n_words, elapsed))

    # 分批发射LLM任务
    chunk = 200
    for i in range(0, len(rows), chunk):
        chunk_rows = [(i + j, row) for j, row in enumerate(rows[i:i + chunk])]
        await asyncio.gather(*[_process_one(idx, row) for idx, row in chunk_rows])

        # LLM 任务完成后，串行写DB（SQLite不支持并发写入）
        for idx, rid, n_chars, n_words, elapsed in processed:
            total += 1
            tag = " ⚠回退" if elapsed == 0 else ""
            print(f"  [{total}/{len(rows)}] {rid} ({n_chars}字→{n_words}词) {elapsed:.1f}s{tag}")
            if elapsed == 0:
                fallback_count += 1
        processed.clear()

        await session.commit()
        avg = (time.time() - t_start) / total
        eta = avg * (len(rows) - total)
        print(f"  --- 已提交 {total}/{len(rows)} | 平均 {avg:.1f}s/条 | 预计剩余 {eta/60:.0f}min ---")

    await session.commit()
    t_total = time.time() - t_start
    print(f"完成: {total} 条 | 耗时 {t_total/60:.1f}min | 平均 {t_total/total:.1f}s/条"
          + (f" | 回退词典 {fallback_count} 条" if fallback_count else ""))

    # 显式关闭共享 LLM 客户端，避免 httpx 在 GC 时报 _transport 错误
    await shared_client.close()

    invalidate_search_index()
    return total


async def seed_wuxing_if_empty(session: AsyncSession) -> None:
    """确保五行映射表不为空，首次启动时从文件加载."""
    existing = await session.scalar(select(CharWuxingRecord.char).limit(1))
    if existing:
        # 数据已存在：仅应用增量修正（幂等 merge，不 invalidate cache 避免每次请求重载）
        has_corrections = False
        for char, w in WUXING_CORRECTIONS.items():
            row = await session.get(CharWuxingRecord, char)
            if row is None or row.source != "manual":
                has_corrections = True
                await session.merge(CharWuxingRecord(char=char, **w))
        if has_corrections:
            await session.commit()
            invalidate_wuxing_cache()
        return
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CORPUS_SEED_ONLY") == "1":
        for char, w in SEED_CHAR_WUXING.items():
            await session.merge(CharWuxingRecord(char=char, **w))
        await session.commit()
        return
    await sync_wuxing_from_file(session)


async def seed_word_wuxing_if_empty(session: AsyncSession) -> None:
    """确保词五行映射表不为空，首次启动时从种子数据加载."""
    try:
        existing = await session.scalar(select(WordWuxingRecord.word).limit(1))
    except Exception:
        return  # 表可能还不存在
    if existing:
        return
    for word, w in SEED_WORD_WUXING.items():
        await session.merge(WordWuxingRecord(
            word=word,
            element=w["element"],
            element_cn=w["element_cn"],
            secondary_cn=w.get("secondary_cn"),
            primary_weight=w.get("primary_weight"),
            confidence=w.get("confidence", "medium"),
            source=w.get("source", "meaning"),
        ))
    await session.commit()
    invalidate_word_wuxing_cache()


async def _bulk_upsert_citations(session: AsyncSession, rows: list[dict]) -> None:
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        stmt = pg_insert(CitationRecord).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=[CitationRecord.id],
            set_={
                "book": stmt.excluded.book,
                "chapter": stmt.excluded.chapter,
                "original": stmt.excluded.original,
                "vernacular": stmt.excluded.vernacular,
                "chars": stmt.excluded.chars,
                "words": stmt.excluded.words,
                "tags": stmt.excluded.tags,
            },
        )
        await session.execute(stmt)
        done = min(i + BATCH_SIZE, len(rows))
        print(f"    语料入库 {done}/{len(rows)}")
    await session.commit()


async def _bulk_upsert_wuxing(session: AsyncSession, records: list[dict]) -> None:
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        stmt = pg_insert(CharWuxingRecord).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=[CharWuxingRecord.char],
            set_={
                "element": stmt.excluded.element,
                "element_cn": stmt.excluded.element_cn,
                "confidence": stmt.excluded.confidence,
                "source": stmt.excluded.source,
            },
        )
        await session.execute(stmt)
        done = min(i + BATCH_SIZE, len(records))
        print(f"    五行入库 {done}/{len(records)}")
    await session.commit()


async def sync_corpus_from_file(
    session: AsyncSession,
    path: str | Path = DEFAULT_CITATIONS_PATH,
) -> int:
    from app.corpus.segment import segment_citation

    p = Path(path)
    if not p.exists():
        rows = list(SEED_CITATIONS)
    else:
        rows = json.loads(p.read_text(encoding="utf-8"))
        # 始终将种子语料合并入库（种子中的典籍不在 JSON 文件中）
        seed_ids = {s["id"] for s in SEED_CITATIONS}
        seed_map = {s["id"]: s for s in SEED_CITATIONS}
        for row in rows:
            if row.get("id") in seed_ids:
                seed_map.pop(row["id"], None)
        if seed_map:
            rows = list(rows) + list(seed_map.values())

    # 为每条语料计算分词（如果尚未有 words 字段）
    segmented = 0
    for row in rows:
        if not row.get("words"):
            row["words"] = segment_citation(row.get("original", ""))
            segmented += 1
    if segmented:
        print(f"    新分词 {segmented} 条语料")

    if _dialect_name(session) == "postgresql":
        await _bulk_upsert_citations(session, rows)
    else:
        # SQLite: 使用 INSERT OR REPLACE 批量写入
        from sqlalchemy import text
        conn = await session.connection()
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            params = []
            for row in batch:
                params.append({
                    "id": row["id"], "book": row["book"],
                    "chapter": row.get("chapter", ""), "original": row["original"],
                    "vernacular": row.get("vernacular", ""),
                    "chars": json.dumps(row.get("chars", []), ensure_ascii=False),
                    "words": json.dumps(row.get("words", []), ensure_ascii=False),
                    "tags": json.dumps(row.get("tags", []), ensure_ascii=False),
                })
            await conn.execute(
                text("INSERT OR REPLACE INTO citations (id, book, chapter, original, vernacular, chars, words, tags) "
                     "VALUES (:id, :book, :chapter, :original, :vernacular, :chars, :words, :tags)"),
                params,
            )
        await session.commit()
    invalidate_search_index()
    return len(rows)


async def sync_wuxing_from_file(
    session: AsyncSession,
    path: str | Path = DEFAULT_WUXING_PATH,
) -> int:
    p = Path(path)
    if not p.exists():
        records = [{"char": c, **w} for c, w in SEED_CHAR_WUXING.items()]
    else:
        records = json.loads(p.read_text(encoding="utf-8"))

    if _dialect_name(session) == "postgresql":
        await _bulk_upsert_wuxing(session, records)
    else:
        from sqlalchemy import text
        conn = await session.connection()
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i : i + BATCH_SIZE]
            params = [{"char": r["char"], "element": r["element"], "element_cn": r["element_cn"],
                       "confidence": r["confidence"], "source": r["source"]} for r in batch]
            await conn.execute(
                text("INSERT OR REPLACE INTO char_wuxing (char, element, element_cn, confidence, source) "
                     "VALUES (:char, :element, :element_cn, :confidence, :source)"),
                params,
            )
        await session.commit()
    invalidate_wuxing_cache()
    return len(records)


def invalidate_wuxing_cache() -> None:
    global _wuxing_map_cache
    _wuxing_map_cache = None


def invalidate_search_index() -> None:
    """语料更新后使倒排索引失效."""
    global _char_index, _word_index, _citation_map, _search_cache
    _char_index = None
    _word_index = None
    _citation_map = None
    _search_cache = {}
    invalidate_word_wuxing_cache()


async def load_wuxing_map(session: AsyncSession, *, use_cache: bool = True) -> dict[str, str]:
    global _wuxing_map_cache
    if use_cache and _wuxing_map_cache is not None:
        return dict(_wuxing_map_cache)
    wx_result = await session.execute(select(CharWuxingRecord))
    wx_map = {r.char: r.element_cn for r in wx_result.scalars().all()}
    for c, w in SEED_CHAR_WUXING.items():
        wx_map.setdefault(c, w["element_cn"])
    if use_cache:
        _wuxing_map_cache = dict(wx_map)
    return wx_map


async def get_char_wuxing(session: AsyncSession, char: str) -> dict | None:
    row = await session.get(CharWuxingRecord, char)
    if row:
        return {"char": row.char, "element": row.element, "element_cn": row.element_cn, "confidence": row.confidence}
    seed = SEED_CHAR_WUXING.get(char)
    return {"char": char, **seed} if seed else None


# ── 词级别五行映射 ──

_word_wuxing_cache: dict[str, str] | None = None


async def load_word_wuxing_map(session: AsyncSession, *, use_cache: bool = True) -> dict[str, str]:
    """加载词 → 主五行映射（自动排除不适合人名的词）."""
    global _word_wuxing_cache
    if use_cache and _word_wuxing_cache is not None:
        return dict(_word_wuxing_cache)
    try:
        wx_result = await session.execute(
            select(WordWuxingRecord).where(
                (WordWuxingRecord.suitable_for_name == True)
                | (WordWuxingRecord.suitable_for_name == None)
            )
        )
        wx_map = {r.word: r.element_cn for r in wx_result.scalars().all() if r.element_cn}
    except Exception:
        wx_map = {}
    if use_cache:
        _word_wuxing_cache = dict(wx_map)
    return wx_map


async def load_word_wuxing_map_full(session: AsyncSession) -> dict[str, dict]:
    """加载词 → 完整五行信息 {word: {primary, secondary, weight}}（排除不适合人名的词）."""
    try:
        wx_result = await session.execute(
            select(WordWuxingRecord).where(
                (WordWuxingRecord.suitable_for_name == True)
                | (WordWuxingRecord.suitable_for_name == None)
            )
        )
        result = {}
        for r in wx_result.scalars().all():
            if not r.element_cn:
                continue
            secondary = []
            if r.secondary_cn:
                secondary = [s.strip() for s in r.secondary_cn.split(",") if s.strip()]
            result[r.word] = {
                "primary": r.element_cn,
                "secondary": secondary,
                "weight": r.primary_weight or 1.0,
            }
        return result
    except Exception:
        return {}


def word_matches_xiyongshen(
    element_cn: str,
    secondary_cn: list[str],
    primary: list[str],
    secondary_target: list[str],
) -> tuple[bool, str]:
    """词级别五行匹配：primary命中→primary，secondary命中→secondary."""
    if element_cn in primary:
        return True, "primary"
    if element_cn in secondary_target:
        return True, "secondary"
    # 检查次要五行
    for s in secondary_cn:
        if s in primary:
            return True, "secondary"  # 降权
        if s in secondary_target:
            return True, "secondary"
    return False, "none"


async def load_combined_wuxing_map(session: AsyncSession) -> dict[str, str]:
    """返回 {单字/词 → 五行} 的统一映射，词条目覆盖同key单字."""
    char_map = await load_wuxing_map(session)
    word_map = await load_word_wuxing_map(session)
    return {**char_map, **word_map}


def get_wuxing(text: str, wx_map: dict[str, str]) -> str | None:
    """统一的五行查询：优先精确匹配词，回退逐字兜底."""
    if len(text) >= 2 and text in wx_map:
        return wx_map[text]
    if len(text) == 1:
        return wx_map.get(text)
    # 多字词不在映射中：取首字五行作为近似
    if text:
        return wx_map.get(text[0])
    return None


def invalidate_word_wuxing_cache() -> None:
    global _word_wuxing_cache
    _word_wuxing_cache = None


_ON_DEMAND_CAP = 30
_on_demand_inflight: set[str] = set()
_on_demand_tasks: set[object] = set()


async def wait_on_demand_tasks() -> None:
    """等待所有进行中的按需补标任务（测试/运维用）."""
    import asyncio

    if _on_demand_tasks:
        await asyncio.gather(*list(_on_demand_tasks), return_exceptions=True)


def schedule_word_wuxing_on_demand(
    words: list[str],
    *,
    contexts: dict[str, list[dict]] | None = None,
) -> None:
    """后台异步按需补标：不阻塞调用方，使用独立 DB session.

    同一批词若已有任务在飞则跳过，避免重复打 LLM。
    """
    import asyncio
    import logging

    from app.llm.config import resolve_llm_config

    _log = logging.getLogger("uvicorn")
    cfg = resolve_llm_config()
    if cfg["mock"] or not cfg["api_key"]:
        return

    to_run = [w for w in dict.fromkeys(words) if w not in _on_demand_inflight]
    if not to_run:
        return

    for w in to_run:
        _on_demand_inflight.add(w)
    ctx = None
    if contexts:
        wanted = set(to_run)
        ctx = {k: v for k, v in contexts.items() if k in wanted}

    async def _run() -> None:
        try:
            from app.db.session import get_session_factory

            async with get_session_factory()() as session:
                await ensure_word_wuxing_on_demand(session, to_run, contexts=ctx)
        except Exception as exc:
            _log.warning("词五行按需标注后台任务失败: %s", exc)
        finally:
            for w in to_run:
                _on_demand_inflight.discard(w)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        for w in to_run:
            _on_demand_inflight.discard(w)
        return

    task = loop.create_task(_run())
    _on_demand_tasks.add(task)
    task.add_done_callback(_on_demand_tasks.discard)


async def ensure_word_wuxing_on_demand(
    session: AsyncSession,
    words: list[str],
    *,
    contexts: dict[str, list[dict]] | None = None,
    cap: int = _ON_DEMAND_CAP,
) -> dict[str, str]:
    """按需补标缺失词的五行并落库（同步执行版）.

    只标注「≥2字实词」且「不在 word_wuxing 表」的词，每次最多 cap 个（单次LLM请求）；
    LLM 不可用时静默跳过。检索主流程请用 schedule_word_wuxing_on_demand。
    返回本次新增 {word: element_cn}。
    """
    import logging
    from datetime import datetime, timezone

    from app.corpus.segment import is_content_word
    from app.llm.config import resolve_llm_config

    from app.db.session import WordWuxingRecord

    _log = logging.getLogger("uvicorn")

    existing = await load_word_wuxing_map(session)

    # 加载已标记为「不宜人名」的词集合，避免重复送LLM
    unsuitable_result = await session.execute(
        select(WordWuxingRecord.word).where(
            WordWuxingRecord.suitable_for_name == False
        )
    )
    unsuitable_words: set[str] = {r[0] for r in unsuitable_result.all()}

    missing = [
        w for w in dict.fromkeys(words)
        if len(w) >= 2 and is_content_word(w)
        and w not in existing and w not in unsuitable_words
    ][:cap]
    if not missing:
        return {}

    cfg = resolve_llm_config()
    if cfg["mock"] or not cfg["api_key"]:
        _log.debug("词五行按需标注：LLM不可用（mock=%s, api_key=%s），跳过 %d 个缺失词",
                   cfg["mock"], bool(cfg["api_key"]), len(missing))
        return {}

    from app.agents import WordWuxingAgent

    _log.info("词五行按需标注：LLM标注 %d 个缺失词...", len(missing))
    try:
        annotations = await WordWuxingAgent().annotate_words(missing, contexts=contexts)
    except Exception as exc:
        _log.warning("词五行按需标注：LLM调用异常，跳过落库: %s", exc)
        return {}

    if not annotations:
        _log.debug("词五行按需标注：LLM返回空结果，跳过落库")
        return {}

    now = datetime.now(timezone.utc)
    ctx = contexts or {}
    el_en_map = {"木": "wood", "火": "fire", "土": "earth", "金": "metal", "水": "water"}
    added: dict[str, str] = {}
    skipped: int = 0
    unsuitable: int = 0
    for ann in annotations:
        word = ann.get("word", "")
        if not word:
            skipped += 1
            continue

        # 人名适合性检查
        suitable = ann.get("suitable_for_name")
        if suitable is False:
            await session.merge(WordWuxingRecord(
                word=word,
                element="",
                element_cn="",
                confidence="llm",
                source="llm_annotation",
                contexts=ctx.get(word, [])[:3],
                annotated_at=now,
                suitable_for_name=False,
                reasoning=ann.get("reasoning", ""),
            ))
            unsuitable += 1
            continue

        primary = ann.get("primary", "")
        if primary not in el_en_map:
            skipped += 1
            continue
        secondary = [s for s in (ann.get("secondary") or []) if s in el_en_map]
        pw = ann.get("primary_weight")
        if pw is not None:
            pw = max(0.5, min(1.0, float(pw)))
        await session.merge(WordWuxingRecord(
            word=word,
            element=el_en_map[primary],
            element_cn=primary,
            secondary_cn=",".join(secondary) if secondary else None,
            primary_weight=pw,
            confidence=ann.get("confidence", "medium"),
            source="llm_annotation",
            contexts=ctx.get(word, [])[:3],
            annotated_at=now,
            suitable_for_name=True,
            reasoning=ann.get("reasoning", ""),
        ))
        added[word] = primary
    await session.commit()
    if added:
        invalidate_word_wuxing_cache()
        _log.info("词五行按需标注：成功入库 %d 个词（跳过 %d 个无效，排除 %d 个不宜人名）",
                  len(added), skipped, unsuitable)
    elif skipped > 0 or unsuitable > 0:
        _log.warning("词五行按需标注：%d 个无效，%d 个不宜人名，无有效标注入库",
                     skipped, unsuitable)
    return added


def _generates(primary_cn: str, element_cn: str) -> bool:
    primary_en = ELEMENT_CN_TO_EN.get(primary_cn, "")
    el_en = ELEMENT_CN_TO_EN.get(element_cn, "")
    return bool(primary_en and el_en and GENERATES.get(el_en) == primary_en)


def matches_xiyongshen(
    element_cn: str | None,
    primary: list[str],
    secondary: list[str],
    avoid: list[str] | None = None,
    *,
    allow_indirect: bool = True,
) -> tuple[bool, str]:
    """返回 (是否匹配, 标注: primary/secondary/indirect/avoid/none).

    忌神优先于一切：即使生助喜用神（如 金生水 而 金 为忌神），也一律视为不匹配。
    """
    if not element_cn:
        return False, "none"
    if avoid and element_cn in avoid:
        return False, "avoid"
    if element_cn in primary:
        return True, "primary"
    if allow_indirect and any(_generates(p, element_cn) for p in primary):
        return True, "indirect"
    if element_cn in secondary:
        return True, "secondary"
    return False, "none"


def pair_passes_strategy(
    wa: str | None,
    wb: str | None,
    primary: list[str],
    secondary: list[str],
    avoid: list[str] | None = None,
    strategy: str = "strict",
) -> bool:
    """判断双字名是否通过五行策略.

    - strict: 至少一字命中喜用（含生喜用），且两字均不得为忌神（PRD 规则 3）。
    - moderate: 至少一字命中喜用，另一字允许为忌神/中性。
    - reference: 不设五行限制。
    """
    if not wa or not wb:
        return strategy == "reference"
    avoid = avoid or []
    ma, _ = matches_xiyongshen(wa, primary, secondary, avoid)
    mb, _ = matches_xiyongshen(wb, primary, secondary, avoid)
    if strategy == "strict":
        return (ma or mb) and wa not in avoid and wb not in avoid
    if strategy == "moderate":
        return ma or mb
    return True


# 口语化/戏曲舞台标记词，含大量这些词的元曲语料不适合起名
_COLLOQUIAL_MARKERS = {"了", "的", "把", "不", "我", "你", "他", "她", "们", "个", "这", "那", "么", "吗", "吧"}

# 元曲戏曲舞台指示词
_STAGE_DIRECTION_MARKERS = {"科", "云", "唱", "做", "旦", "末", "卜", "净", "丑", "外", "贴", "冲"}


def _is_name_worthy_citation(citation: CitationRecord) -> bool:
    """过滤掉不适合起名的语料：口语过多、舞台指示、字符太少的条目."""
    chars = citation.chars or []
    original = citation.original or ""
    # 字符数过少（如"孟子曰"仅3字无法提供有意义的名字来源）或过多
    if len(chars) < 5 or len(chars) > 30:
        return False
    # 元曲特殊过滤
    if citation.book == "元曲三百首":
        # 口语词占比过高
        colloquial_count = sum(1 for c in chars if c in _COLLOQUIAL_MARKERS)
        if colloquial_count >= len(chars) * 0.3:
            return False
        # 含舞台指示词
        if any(m in original for m in _STAGE_DIRECTION_MARKERS):
            return False
    return True


def _citation_quality_score(citation: CitationRecord) -> int:
    """返回语料的来源质量分（0-3）。"""
    base = BOOK_QUALITY_SCORE.get(citation.book, DEFAULT_BOOK_QUALITY)
    # 有白话译文的加分
    if citation.vernacular:
        base = min(3, base + 1)
    return base


# ── 倒排索引：词/字 → 语料ID ──
_char_index: dict[str, set[str]] | None = None  # char → citation_ids
_word_index: dict[str, set[str]] | None = None  # word → citation_ids
_citation_map: dict[str, CitationRecord] | None = None  # id → citation
_INDEX_VERSION = 2


async def _build_inverted_index(session):
    """构建词/字级别的倒排索引，加速检索.

    排除 word_wuxing 表中适合人名标记为 False 的词。
    """
    global _char_index, _word_index, _citation_map
    from app.corpus.segment import is_content_word
    import time
    t0 = time.time()

    _char_index = {}
    _word_index = {}
    _citation_map = {}

    # 加载不适合人名的词集合（已由LLM标注为 suitable_for_name=False）
    try:
        unsuitable_result = await session.execute(
            select(WordWuxingRecord.word).where(
                WordWuxingRecord.suitable_for_name == False
            )
        )
        unsuitable_words: set[str] = {r[0] for r in unsuitable_result.all()}
    except Exception:
        unsuitable_words = set()

    stmt = select(CitationRecord)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    for row in rows:
        _citation_map[row.id] = row
        chars: list[str] = getattr(row, "chars", []) or []
        words: list[str] = getattr(row, "words", []) or []

        for ch in chars:
            _char_index.setdefault(ch, set()).add(row.id)
        for w in words:
            if is_content_word(w) and w not in unsuitable_words:
                _word_index.setdefault(w, set()).add(row.id)

    word_wx_count = sum(1 for w in _word_index if len(w) >= 2)
    excluded = len(unsuitable_words)
    import time
    t_elapsed = time.time() - t0
    print(f"    倒排索引已构建：{len(_char_index)} 字符, {len(_word_index)} 词(含{word_wx_count}复合词), "
          f"{len(_citation_map)} 语料" + (f"（排除 {excluded} 个不宜人名词）" if excluded else "")
          + f" | 耗时 {t_elapsed:.2f}s")


async def _ensure_index(session):
    """确保倒排索引已构建."""
    global _char_index
    if _char_index is None:
        await _build_inverted_index(session)


# 语料检索缓存
_search_cache: dict[str, list[CitationRecord]] = {}
_CACHE_VERSION = 2


def _search_cache_key(primary: list[str], secondary: list[str], limit: int) -> str:
    p = ",".join(sorted(primary))
    s = ",".join(sorted(secondary or []))
    return f"{_CACHE_VERSION}:{p}|{s}|{limit}"


async def search_citations(
    session: AsyncSession,
    xiyongshen_primary: list[str],
    *,
    xiyongshen_secondary: list[str] | None = None,
    limit: int = 20,
    avoid_chars: list[str] | None = None,
    wx_map: dict[str, str] | None = None,
    word_wx_map: dict[str, str] | None = None,
) -> list[CitationRecord]:
    import time
    t0 = time.perf_counter()
    secondary = xiyongshen_secondary or []
    avoid = set(avoid_chars or [])

    # ── 缓存命中：同一喜用神组合复用检索结果 ──
    cache_key = _search_cache_key(xiyongshen_primary, secondary, limit)
    if cache_key in _search_cache:
        cached = _search_cache[cache_key]
        if avoid:
            cached = [c for c in cached if not any(ch in avoid for ch in (c.chars or []))]
        return cached

    if wx_map is None:
        wx_map = await load_wuxing_map(session)
    if word_wx_map is None:
        try:
            word_wx_map = await load_word_wuxing_map(session)
        except Exception:
            word_wx_map = {}

    matching_chars = {
        char
        for char, el in wx_map.items()
        if matches_xiyongshen(el, xiyongshen_primary, secondary)[0]
    }

    # ── 使用倒排索引快速定位候选语料 ──
    await _ensure_index(session)

    # ── 起名时按需补标缺失词五行：后台异步落库，不阻塞本次检索 ──
    if _word_index is not None:
        missing_words = [w for w in _word_index if w not in word_wx_map]
        if missing_words:
            contexts: dict[str, list[dict]] = {}
            for w in missing_words[:_ON_DEMAND_CAP]:
                ctxs = []
                for cid in list(_word_index.get(w, set()))[:2]:
                    row = (_citation_map or {}).get(cid)
                    if row is not None:
                        ctxs.append({
                            "book": row.book,
                            "original": (row.original or "")[:100],
                        })
                if ctxs:
                    contexts[w] = ctxs
            schedule_word_wuxing_on_demand(missing_words, contexts=contexts)

    # ── 词级别匹配：找所有五行匹配喜用神的词 ──
    matching_words = {
        word
        for word, el in word_wx_map.items()
        if matches_xiyongshen(el, xiyongshen_primary, secondary)[0]
    }

    # 通过倒排索引收集包含匹配字符/词的语料ID
    candidate_ids: set[str] = set()
    for ch in matching_chars:
        if ch in (_char_index or {}):
            candidate_ids.update(_char_index[ch])
    # 词级别：通过_word_index添加包含匹配词的语料
    for w in matching_words:
        if w in (_word_index or {}):
            candidate_ids.update(_word_index[w])

    if not candidate_ids:
        return []

    # 按书籍品质分流
    scored_high: list[tuple[float, CitationRecord]] = []
    scored_other: list[tuple[float, CitationRecord]] = []

    for cid in candidate_ids:
        row = (_citation_map or {}).get(cid)
        if row is None:
            continue
        if not _is_name_worthy_citation(row):
            continue
        chars: list = getattr(row, "chars", []) or []
        usable = [c for c in chars if c not in avoid]
        if not usable:
            continue
        hit = sum(1 for c in usable if c in matching_chars)
        # ── 词命中计数 ──
        words: list = getattr(row, "words", []) or []
        word_hit = sum(1 for w in words if w in matching_words)
        if hit <= 0 and word_hit <= 0:
            continue
        # 检索排序：仅按匹配密度，书籍质量交给 LLM 判断
        composite = hit + word_hit * 3 + random.random() * 0.5
        if row.book in HIGH_QUALITY_BOOKS:
            scored_high.append((composite, row))
        else:
            scored_other.append((composite, row))

    scored_high.sort(key=lambda x: -x[0])
    scored_other.sort(key=lambda x: -x[0])

    # 分层抽样 + book round-robin 保障典籍多样性
    high_ratio = 0.6
    high_limit = max(1, int(limit * high_ratio))

    def _round_robin(scored: list, cap: int) -> list:
        """按书籍做 round-robin 抽样，确保小众典籍也能被 LLM 看到."""
        if len(scored) <= cap:
            return [r for _, r in scored]
        by_book: dict[str, list] = {}
        for s, r in scored:
            by_book.setdefault(r.book, []).append((s, r))
        # 按 BOOK_QUALITY_SCORE 降序排列书籍
        book_order = sorted(by_book, key=lambda b: -BOOK_QUALITY_SCORE.get(b, DEFAULT_BOOK_QUALITY))
        result: list = []
        used: set[str] = set()
        while len(result) < cap:
            added = False
            for book in book_order:
                if book not in by_book:
                    continue
                items = by_book[book]
                while items and items[0][1].id in used:
                    items.pop(0)
                if items:
                    s, r = items.pop(0)
                    result.append(r)
                    used.add(r.id)
                    added = True
                    if len(result) >= cap:
                        break
                else:
                    del by_book[book]  # 该书已无剩余
            if not added:
                break  # 所有书已耗尽
        return result

    high_result = _round_robin(scored_high, high_limit)
    other_needed = limit - len(high_result)
    other_result = _round_robin(scored_other, other_needed)

    results = high_result + other_result
    if len(results) < limit:
        # 回填剩余配额
        remaining_high = [r for _, r in scored_high if r not in results]
        remaining_other = [r for _, r in scored_other if r not in results]
        extras = remaining_high + remaining_other
        results.extend(extras[: limit - len(results)])

    # ── 写入缓存 ──
    _search_cache[cache_key] = list(results)

    # ── 检索日志 ──
    import logging
    _log = logging.getLogger("uvicorn")
    t_elapsed = time.perf_counter() - t0
    _log.info(
        "⏱ 语料检索完成：%.2fs | 喜用神=%s 次喜=%s | 匹配字符%d个 词%d个 | "
        "候选语料%d条(高品质%d+其他%d) | 最终返回%d条",
        t_elapsed, xiyongshen_primary, secondary,
        len(matching_chars), len(matching_words),
        len(scored_high) + len(scored_other), len(scored_high), len(scored_other),
        len(results),
    )
    return results
