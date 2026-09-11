"""起名时按需补标词五行（LLM标注+落库）测试."""

from __future__ import annotations

import pytest

from app.corpus.search import (
    ensure_word_wuxing_on_demand,
    invalidate_word_wuxing_cache,
    search_citations,
)
from app.db.session import WordWuxingRecord, get_session_factory


@pytest.fixture()
def fake_llm(monkeypatch):
    """伪造可用的 LLM 配置与标注响应."""
    from app.llm import config as llm_config

    monkeypatch.setattr(
        llm_config,
        "resolve_llm_config",
        lambda: {
            "mock": False,
            "api_key": "test-key",
            "provider": "mock",
            "api_base": "https://example.com/v1",
            "model": "gpt-test",
            "model_compose": "gpt-test",
            "model_fate": "gpt-test",
            "model_qa": "gpt-test",
            "model_curator": "gpt-test",
            "model_wuxing": "gpt-test",
            "timeout": 30,
            "max_retries": 1,
            "temperature": 0.1,
        },
    )
    calls = []

    async def fake_annotate(self, words, contexts=None):
        calls.append(list(words))
        return [
            {
                "word": w,
                "primary": "水",
                "primary_weight": 0.8,
                "confidence": "high",
                "reasoning": "test",
            }
            for w in words[:3]
        ]

    from app.agents import WordWuxingAgent

    monkeypatch.setattr(WordWuxingAgent, "annotate_words", fake_annotate)
    return calls


async def test_ensure_annotates_and_persists(fake_llm):
    async with get_session_factory()() as session:
        added = await ensure_word_wuxing_on_demand(session, ["云帆", "明月"])
        assert added == {"云帆": "水", "明月": "水"}
        for w in ("云帆", "明月"):
            row = await session.get(WordWuxingRecord, w)
            assert row is not None
            assert row.element_cn == "水"
            assert row.source == "llm_annotation"
        # 已标注的词不再重复请求
        added2 = await ensure_word_wuxing_on_demand(session, ["云帆", "明月", "沧海"])
        assert "云帆" not in added2 and "明月" not in added2
        assert len(fake_llm) == 1


async def test_ensure_skips_when_llm_unavailable():
    # conftest 默认 LLM_MOCK=true → resolve_llm_config mock=True
    async with get_session_factory()() as session:
        added = await ensure_word_wuxing_on_demand(session, ["云帆", "明月"])
        assert added == {}
        row = await session.get(WordWuxingRecord, "云帆")
        assert row is None


async def test_search_citations_triggers_on_demand_annotation(fake_llm):
    from app.corpus.search import wait_on_demand_tasks

    async with get_session_factory()() as session:
        # 测试种子语料无 words 字段，先词典分词回填（生产由文件同步完成）
        from app.corpus.search import backfill_words_if_needed
        await backfill_words_if_needed(session)

        await search_citations(session, ["水"], limit=5)
        # 补标已改为后台异步，需等任务结束后再断言落库
        await wait_on_demand_tasks()

        from sqlalchemy import select
        result = await session.execute(
            select(WordWuxingRecord).where(WordWuxingRecord.source == "llm_annotation")
        )
        annotated = result.scalars().all()
        assert annotated, "起名检索应触发缺失词五行补标"
        assert fake_llm, "应发起至少一次LLM标注请求"

        # 二次检索同一喜用组合：不再重复标注（命中缓存/已落库/inflight 去重）
        before = len(fake_llm)
        invalidate_word_wuxing_cache()
        await search_citations(session, ["水"], limit=5)
        await wait_on_demand_tasks()
        assert len(fake_llm) == before
