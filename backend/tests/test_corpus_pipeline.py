"""语料 pipeline 测试（使用本地 fixture，不依赖网络）."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.corpus.crawler.parsers import parse_paragraphs_chapters, parse_poetry_lines, parse_shijing
from app.corpus.crawler.pipeline import _dedupe_by_text, _merge_seed
from app.corpus.seed_data import SEED_CITATIONS


FIXTURE = Path(__file__).parent / "fixtures" / "lunyu_sample.json"


@pytest.mark.asyncio
async def test_sync_corpus_from_file():
    from app.corpus.search import sync_corpus_from_file
    from app.db.session import CitationRecord, get_session_factory

    sample = [
        {
            "id": "test-001",
            "book": "测试",
            "chapter": "一章",
            "original": "明德至善，格物致知。",
            "vernacular": "",
            "chars": ["明", "德", "至", "善"],
            "tags": ["test"],
        }
    ]
    path = Path("data/corpus/processed/_test_citations.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sample, ensure_ascii=False), encoding="utf-8")
    factory = get_session_factory()
    async with factory() as session:
        n = await sync_corpus_from_file(session, path)
        assert n >= 1  # 包含种子语料合并
        row = await session.get(CitationRecord, "test-001")
        assert row is not None
        assert row.book == "测试"


def test_parse_shijing_minimal():
    data = [{"title": "关雎", "chapter": "国风", "section": "周南", "content": ["关关雎鸠，在河之洲。窈窕淑女，君子好逑。"]}]
    rows = parse_shijing("诗经", "shijing", data)
    assert len(rows) == 1
    assert "君子" in rows[0]["original"] or "君子好逑" in rows[0]["original"]


def test_parse_poetry_lines_minimal():
    data = [
        {
            "author": "李白",
            "title": "静夜思",
            "paragraphs": ["床前明月光，疑是地上霜。"],
            "tags": ["唐诗三百首"],
        }
    ]
    rows = parse_poetry_lines("唐诗三百首", "tangshi300", data)
    assert len(rows) == 1
    assert rows[0]["book"] == "唐诗三百首"
    assert "李白" in rows[0]["chapter"]
    assert "唐诗三百首" in rows[0]["tags"]


def test_parse_lunyu_minimal():
    data = [{"chapter": "学而篇", "paragraphs": ["子曰：学而时习之，不亦说乎？"]}]
    rows = parse_paragraphs_chapters("论语", "lunyu", data)
    assert len(rows) == 1
    assert rows[0]["book"] == "论语"


def test_merge_and_dedupe():
    crawled = [{"id": "a-1", "book": "A", "chapter": "c", "original": "重复句。", "vernacular": "", "chars": ["重", "复"], "tags": []}]
    merged = _dedupe_by_text(_merge_seed(crawled + crawled))
    assert len(merged) >= len(SEED_CITATIONS)
