"""动态语料取名测试（无策展兜底）."""

from __future__ import annotations

import time
from datetime import datetime

import pytest

from app.bazi.engine import calculate_bazi
from app.db.session import CitationRecord, get_session_factory
from app.models.schemas import FateAnalysis, NamePreferences, Xiyongshen
from app.report.candidates import generate_candidates, _build_pair_pool
from app.corpus.search import load_wuxing_map, search_citations


@pytest.mark.asyncio
async def test_no_curated_names_in_module():
    import app.report.candidates as mod
    assert not hasattr(mod, "CURATED_NAMES")


@pytest.mark.asyncio
async def test_generate_candidates_water_primary_differs_from_fire():
    factory = get_session_factory()
    async with factory() as session:
        fate_water = FateAnalysis(
            vernacular="喜水",
            xiyongshen=Xiyongshen(primary=["水"], secondary=["金"]),
        )
        fate_fire = FateAnalysis(
            vernacular="喜火",
            xiyongshen=Xiyongshen(primary=["火"], secondary=["木"]),
        )
        water_names = await generate_candidates(
            session, "李", fate_water, 3, preferences=NamePreferences(wuxing_strategy="moderate"),
        )
        fire_names = await generate_candidates(
            session, "李", fate_fire, 3, preferences=NamePreferences(wuxing_strategy="moderate"),
        )
        assert len(water_names) >= 1
        assert len(fire_names) >= 1
        water_givens = {c.given_name for c in water_names}
        fire_givens = {c.given_name for c in fire_names}
        assert water_givens != fire_givens or len(water_givens) == 1
        for c in water_names + fire_names:
            assert 1 <= len(c.given_name) <= 2
            assert c.citation_id
            assert c.citation_explanation
            assert c.meaning_score >= 5


@pytest.mark.asyncio
async def test_generate_candidates_golden_bazi_mock_llm():
    factory = get_session_factory()
    dt = datetime.fromisoformat("1988-01-12T17:55:00")
    chart = calculate_bazi(dt, longitude=106.03, gender="male")
    from app.report.narrative import build_fate_analysis
    fate = build_fate_analysis(chart)
    async with factory() as session:
        candidates = await generate_candidates(session, "侯", fate, 3)
        assert len(candidates) >= 1
        names = [c.given_name for c in candidates]
        assert len(set(names)) == len(names)
        for c in candidates:
            assert c.citation_id
            row = await session.get(CitationRecord, c.citation_id)
            assert row is not None
            assert all(ch in row.chars for ch in c.given_name)
            assert 1 <= len(c.given_name) <= 2
            assert c.meaning_score >= 5


@pytest.mark.asyncio
async def test_build_pair_pool_adjacent_first():
    factory = get_session_factory()
    fate = FateAnalysis(
        vernacular="喜火",
        xiyongshen=Xiyongshen(primary=["火"], secondary=["木"]),
    )
    async with factory() as session:
        wx_map = await load_wuxing_map(session)
        citations = await search_citations(
            session, ["火"], xiyongshen_secondary=["木"], limit=10, wx_map=wx_map,
        )
        pool = _build_pair_pool(citations, wx_map, fate, "moderate", [])
        assert len(pool) >= 1
        assert all(1 <= len(p.chars) <= 2 for p in pool)
        assert all(p.meaning_score >= 5 for p in pool)


@pytest.mark.asyncio
async def test_build_pair_pool_bounded_on_long_citation():
    """长诗词分句组合应有上限，避免整篇 O(n²) 排列."""
    fate = FateAnalysis(
        vernacular="喜水",
        xiyongshen=Xiyongshen(primary=["水"], secondary=["金"]),
    )
    wx_map = {"水": "水", "金": "金", "云": "水", "行": "金"}
    long_chars = [chr(0x4E00 + i) for i in range(40)]
    long_chars[0], long_chars[1] = "云", "行"
    citation = CitationRecord(
        id="bench-long",
        book="测试",
        chapter="长句",
        original="。".join("".join(long_chars) for _ in range(3)),
        vernacular="",
        chars=long_chars,
        tags=[],
    )
    t0 = time.perf_counter()
    pool = _build_pair_pool([citation], wx_map, fate, "moderate", [], limit=40)
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5, f"pair pool took {elapsed:.2f}s on synthetic long citation"
    assert len(pool) >= 1


@pytest.mark.asyncio
async def test_generate_candidates_full_corpus_under_time_budget():
    """全量语料（~9k）下 generate_candidates 应在秒级完成（LLM mock）."""
    from pathlib import Path

    from app.corpus.search import invalidate_wuxing_cache, sync_corpus_from_file, sync_wuxing_from_file

    citations_path = Path("data/corpus/processed/citations.json")
    if not citations_path.exists():
        pytest.skip("full corpus not built")

    factory = get_session_factory()
    fate = FateAnalysis(
        vernacular="喜水",
        xiyongshen=Xiyongshen(primary=["水"], secondary=["金"]),
    )
    async with factory() as session:
        invalidate_wuxing_cache()
        await sync_corpus_from_file(session, citations_path)
        wuxing_path = Path("data/wuxing/processed/char_wuxing_v1.json")
        if wuxing_path.exists():
            await sync_wuxing_from_file(session, wuxing_path)
        t0 = time.perf_counter()
        candidates = await generate_candidates(
            session, "李", fate, 10, preferences=NamePreferences(wuxing_strategy="moderate"),
        )
        elapsed = time.perf_counter() - t0
    assert len(candidates) >= 1, f"expected at least 1 candidate, got {len(candidates)}"
    assert elapsed < 8.0, f"generate_candidates took {elapsed:.2f}s (budget 8s)"
    scores = [c.meaning_score for c in candidates]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_build_name_pool_includes_single_char():
    fate = FateAnalysis(
        vernacular="喜火",
        xiyongshen=Xiyongshen(primary=["火"], secondary=["木"]),
    )
    wx_map = {"明": "火", "月": "木", "悠": "火"}
    citation = CitationRecord(
        id="single-char",
        book="测试",
        chapter="",
        original="明月悠兮",
        vernacular="明月悠远",
        chars=["明", "月", "悠"],
        tags=[],
    )
    pool = _build_pair_pool([citation], wx_map, fate, "moderate", [])
    singles = [p for p in pool if len(p.chars) == 1]
    assert singles, "应包含单字候选"
    assert all(p.meaning_score >= 5 for p in singles)
