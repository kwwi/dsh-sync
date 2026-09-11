"""针对评审发现的缺陷的回归测试."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.bazi.engine import calculate_bazi
from app.bazi.pattern.special import _detect_hua_ge
from app.bazi.strength import calculate_day_master_strength
from app.bazi.xiyongshen import _tongguan_secondary
from app.corpus.search import load_wuxing_map
from app.models.schemas import Relations
from app.report.narrative import build_fate_analysis


def _chart(*args, **kwargs):
    return calculate_bazi(*args, **kwargs)


# ── 缺陷1：narrative 硬编码「木能生火」──


def test_no_false_mu_sheng_huo_when_primary_water():
    """喜用水 + 次喜含木 时，报告不得再出现「木能生火」错误推论."""
    start = datetime(1990, 1, 1, 12, 0)
    checked = 0
    for i in range(0, 800):
        dt = start + timedelta(hours=12 * i)
        fate = build_fate_analysis(_chart(dt, gender="male"))
        xy = fate.xiyongshen
        if "木" in xy.secondary and "火" not in xy.primary:
            assert "木能生火" not in fate.professional, (dt, xy.primary, xy.secondary)
            checked += 1
    assert checked > 0, "扫描未覆盖到 喜水次木 样本"


def test_mu_sheng_huo_only_when_primary_fire():
    """喜火 + 次喜含木 时，才应出现「木能生火」推论."""
    start = datetime(1988, 1, 1, 12, 0)
    found = 0
    for i in range(0, 800):
        dt = start + timedelta(hours=12 * i)
        fate = build_fate_analysis(_chart(dt, gender="male"))
        xy = fate.xiyongshen
        if "木" in xy.secondary and "火" in xy.primary:
            assert "木能生火" in fate.professional
            found += 1
    assert found > 0


# ── 缺陷2：得势漏算比肩 ──


def test_year_bijian_counts_in_shi():
    """年干与日干同为比肩时，必须计入得势分."""
    start = datetime(1988, 1, 1, 12, 0)
    found = 0
    for i in range(0, 4000):
        dt = start + timedelta(hours=12 * i)
        chart = _chart(dt, gender="male")
        dm = chart.day_master["stem"]
        if chart.pillars["year"].stem == dm and chart.pillars["month"].stem != dm:
            s = calculate_day_master_strength(chart)
            assert any("比肩" in line for line in s.reasoning if "得势" in line), dt
            found += 1
            if found >= 3:
                break
    assert found >= 3


# ── 缺陷3：化格判定过松 ──


def test_hua_ge_rejects_non_adjacent_combine():
    """年干（隔柱）与日干相合不构成化格."""
    chart = _chart(datetime(1990, 1, 9, 12, 0), gender="male")
    assert chart.pillars["year"].ganzhi == "己巳"
    assert chart.pillars["day"].ganzhi == "甲戌"
    strength = calculate_day_master_strength(chart)
    assert _detect_hua_ge(chart, strength) is None


def test_hua_ge_detects_valid_adjacent_combine():
    """月干/时干相邻 + 日主无根 + 无克化神之干 时，化格仍可判定."""
    chart = _chart(datetime(1988, 1, 2, 6, 0), gender="male")
    assert chart.pillars["day"].ganzhi == "丙辰"
    assert chart.pillars["hour"].ganzhi == "辛卯"
    strength = calculate_day_master_strength(chart)
    r = _detect_hua_ge(chart, strength)
    assert r is not None
    assert r.name == "化水格"
    assert r.formed is True


# ── 缺陷4：通关五行表 ──


def test_tongguan_table_correct():
    """子午/巳亥（水火冲）→木；寅申/卯酉（金木冲）→水；辰戌/丑未（土土冲）→金."""
    cases = [
        ("子午", "木"),
        ("丑未", "金"),
        ("寅申", "水"),
        ("卯酉", "水"),
        ("辰戌", "金"),
        ("巳亥", "木"),
    ]
    for pair, expected in cases:
        chart = type("C", (), {"relations": Relations(clash=[pair])})()
        got = _tongguan_secondary(chart)
        assert expected in got, (pair, got)


# ── 缺陷5：刑冲合害与天干五合 ──


def test_relations_computed():
    chart = _chart(datetime(1988, 1, 2, 18, 0), gender="male")
    rel = chart.relations
    assert "卯酉" in rel.clash
    assert "辰酉合" in rel.combine
    assert "子卯相刑" in rel.punishment
    assert "卯辰相害" in rel.harm
    assert "丁壬合化木" in rel.stem_combine


def test_three_combine_requires_distinct_branches():
    """三合局须三个不同地支齐全；重复地支不构成三合."""
    dup = _chart(datetime(1988, 1, 3, 0, 0), gender="male")
    branches = [p.branch for p in dup.pillars.values()]
    assert branches.count("子") == 2
    assert "辰" in branches
    assert not dup.relations.three_combine, "子子辰 不应构成申子辰三合"

    missing = _chart(datetime(1988, 1, 2, 6, 0), gender="male")
    assert not missing.relations.three_combine, "仅有子辰而缺申，不应成三合"

    full = _chart(datetime(1988, 1, 15, 18, 0), gender="male")
    assert "丑巳酉三合金局" in full.relations.three_combine


def test_stem_combine_no_duplicate_reverse():
    chart = _chart(datetime(1988, 1, 2, 6, 0), gender="male")
    assert len(set(chart.relations.stem_combine)) == len(chart.relations.stem_combine)
    assert all("壬丁" not in s for s in chart.relations.stem_combine)


# ── 缺陷6：多音字姓氏 ──


def test_tone_surname_polyphone():
    from app.tone.engine import analyze_tone

    s = analyze_tone("单景风")
    assert s[0].pinyin == "shàn"
    assert s[0].tone_label == "仄"


# ── 缺陷8：微信 session_id 跨日稳定 ──


def test_wechat_session_id_stable_across_days():
    import time as _time

    from app.api.v1.wechat_auth import _generate_session_id

    with _time_mock(1_600_000_000):
        sid_a = _generate_session_id("openid-1")
    with _time_mock(1_600_000_000 + 86400 * 3):
        sid_b = _generate_session_id("openid-1")
    assert sid_a == sid_b
    assert sid_a.startswith("wx-")


def _time_mock(value):
    """替换 time.time 的上下文管理器."""

    class _Ctx:
        def __enter__(self):
            self._orig = __import__("app.api.v1.wechat_auth", fromlist=["time"]).time
            import app.api.v1.wechat_auth as mod

            self._mod = mod
            mod.time = type("T", (), {"time": staticmethod(lambda: value)})()
            return self

        def __exit__(self, *exc):
            self._mod.time = self._orig
            return False

    return _Ctx()


# ── 缺陷9：自由创作候选可溯源校验 ──


def test_free_sources_traceable():
    from app.report.candidates import _free_sources_traceable

    class C:
        chars = ["明", "月"]
        book = "唐诗三百首"

    item = {
        "char1_source": "《唐诗三百首》明月出天山",
        "char2_source": "《唐诗三百首》月是故乡明",
    }
    assert _free_sources_traceable("明月", item, [C()]) is True

    bad_book = {"char1_source": "《尚书》明明上天", "char2_source": "《唐诗三百首》月是故乡明"}
    assert _free_sources_traceable("明月", bad_book, [C()]) is False

    no_book = {"char1_source": "明月出天山", "char2_source": "月是故乡明"}
    assert _free_sources_traceable("明月", no_book, [C()]) is False


# ── 缺陷7：报告预览访问控制 ──


@pytest.mark.asyncio
async def test_report_preview_requires_ownership():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    headers_a = {"X-Session-Id": "bugfix-owner"}
    headers_b = {"X-Session-Id": "bugfix-intruder"}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        gen = await client.post(
            "/api/v1/report/generate",
            headers=headers_a,
            json={
                "surname": "侯",
                "gender": "male",
                "birth_datetime": "1988-01-12T17:55:00+08:00",
                "birth_place": {"longitude": 106.03},
                "output_count": 3,
            },
        )
        assert gen.status_code == 200
        report_id = gen.json()["report_id"]

        own = await client.get(f"/api/v1/report/{report_id}?tier=preview", headers=headers_a)
        assert own.status_code == 200

        intruder = await client.get(f"/api/v1/report/{report_id}?tier=preview", headers=headers_b)
        assert intruder.status_code == 403


# ── 缺陷A：特殊格局 vs 调候优先级矛盾 ──


def test_special_pattern_xy_overrides_tune():
    """从/化/专旺成格时，喜用神必须以格局为准，调候不得覆盖出忌神.

    甲午 庚午 甲子 己巳（午月调候主水）：甲日主火土财食旺、印比无根成从财格，
    调候 primary 为 [水]（恰是从财格忌神），故必须以格局喜用 [土,火] 为准。
    """
    from app.bazi.analysis import analyze_bazi_rules
    from app.bazi.engine import build_chart_from_pillars

    chart = build_chart_from_pillars("甲午", "庚午", "甲子", "己巳")
    a = analyze_bazi_rules(chart)
    assert a.pattern.name == "从财格"
    xy = a.xiyongshen
    assert xy.primary == ["土", "火"], xy.primary
    assert "水" not in xy.primary, "午月调候主水，但从财格不得以忌神水为喜用"
    assert not (set(xy.primary) & set(xy.avoid)), "喜用与忌神不得重合"


def test_golden_xy_unchanged():
    """GOLDEN-001 非特格，调候路径不受影响."""
    chart = _chart(datetime(1988, 1, 12, 17, 55), gender="male")
    from app.bazi.analysis import analyze_bazi_rules

    a = analyze_bazi_rules(chart)
    assert a.xiyongshen.primary == ["火"]
    assert a.xiyongshen.secondary == ["木"]


# ── 缺陷C1：从格判定（印透破从、日主有根不从；比劫虚浮不忌）──


def test_cong_ge_rejects_yin_transparent():
    """印星透干生身即破从势，不得判为从格（神峰通考：忌印绶生扶）. """
    from app.bazi.analysis import analyze_bazi_rules
    from app.bazi.engine import build_chart_from_pillars

    # 癸酉 乙丑 丙申 丙申（滴天髓州牧造）：乙木正印透干，只作伤官格（未成）不从
    chart = build_chart_from_pillars("癸酉", "乙丑", "丙申", "丙申")
    a = analyze_bazi_rules(chart)
    assert "从" not in a.pattern.name, a.pattern.name


def test_cong_ge_requires_no_day_root():
    """日主地支通根即不从，不得判为从格."""
    from app.bazi.analysis import analyze_bazi_rules

    # 辛巳 甲午 甲寅 己巳：甲日坐寅（本气根）
    chart = _chart(datetime(2001, 6, 20, 12, 0), gender="male")
    assert chart.pillars["day"].branch == "寅"
    a = analyze_bazi_rules(chart)
    assert "从" not in a.pattern.name, a.pattern.name


# ── 缺陷C2：专旺格判定（失令不专旺；财官有根破格，虚浮不忌）──


def test_zhuanwang_rejects_rooted_caiguan():
    """财官当令/有根则克泄耗身破专旺格，不得判为专旺."""
    from app.bazi.analysis import analyze_bazi_rules

    # 己巳 丁丑 辛未 己丑：辛日主丑月，丁火七杀通根巳火（火≥3处）→ 破从革格
    chart = _chart(datetime(1990, 1, 6, 2, 0), gender="male")
    a = analyze_bazi_rules(chart)
    assert a.pattern.name not in ("曲直格", "炎上格", "稼穑格", "从革格", "润下格"), a.pattern.name


def test_zhuanwang_positive_detected():
    """当令且无财官透干的专旺格仍可判定."""
    from app.bazi.analysis import analyze_bazi_rules

    # 癸未 庚申 壬申 癸卯：壬日主申月当令，无财官透干 → 润下格
    chart = _chart(datetime(2003, 8, 27, 6, 50), gender="male")
    a = analyze_bazi_rules(chart)
    assert a.pattern.name == "润下格"
    assert a.xiyongshen.primary == ["木", "水"]
    assert "土" in a.xiyongshen.avoid


# ── 缺陷C3：日时伏吟时柱十神误标「日元」──


def test_fuyin_hour_stem_not_mislabeled_rizhu():
    """日柱与时柱全同（日时伏吟）时，时干须按其真实十神（比肩）标注，不得误标日元."""
    chart = _chart(datetime(1988, 8, 15, 4, 44), gender="male")
    assert chart.pillars["day"].ganzhi == chart.pillars["hour"].ganzhi == "壬寅"
    assert chart.pillars["hour"].ten_god == "比肩"
    assert chart.pillars["day"].ten_god == "日元"


# ── 缺陷B：忌神未参与选字过滤 + strict/moderate 策略等价 ──


def test_matches_xiyongshen_rejects_avoid():
    """忌神优先：即使生助喜用神（金生水而金为忌），也视为不匹配."""
    from app.corpus.search import matches_xiyongshen

    ok, tag = matches_xiyongshen("金", ["水"], [], ["金", "土"])
    assert ok is False
    assert tag == "avoid"
    # 非忌神元素行为不变
    ok, tag = matches_xiyongshen("金", ["金"], [], [])
    assert ok is True and tag == "primary"
    ok, tag = matches_xiyongshen("金", ["水"], [], [])  # 金生水 → indirect
    assert ok is True and tag == "indirect"


def test_strict_moderate_distinction():
    """strict 拒绝含忌神字的双字名，moderate 允许另一字为忌神."""
    from app.corpus.search import pair_passes_strategy

    p, s, av = ["火"], ["木"], ["水"]  # GOLDEN-001 喜火忌水
    # 水+木：木为喜用、水为忌神
    assert pair_passes_strategy("水", "木", p, s, av, "strict") is False
    assert pair_passes_strategy("水", "木", p, s, av, "moderate") is True
    # 火+火 通过 strict
    assert pair_passes_strategy("火", "火", p, s, av, "strict") is True
    # 土+火：土非忌神（中性），可通过 strict
    assert pair_passes_strategy("土", "火", p, s, av, "strict") is True


def test_pair_both_avoid_rejected_all_strategies():
    """忌神主导（两字皆忌）在 strict 与 moderate 下均被过滤."""
    from app.corpus.search import pair_passes_strategy

    p, s, av = ["水", "木"], [], ["金", "土"]
    assert pair_passes_strategy("金", "金", p, s, av, "strict") is False
    assert pair_passes_strategy("金", "金", p, s, av, "moderate") is False
    assert pair_passes_strategy("土", "土", p, s, av, "moderate") is False


@pytest.mark.asyncio
async def test_generate_candidates_strict_excludes_avoid_elements():
    """GOLDEN-001（喜火忌水）严格模式下，生成的备选名不得含水属性字."""
    from app.db.session import get_session_factory
    from app.report.candidates import generate_candidates

    factory = get_session_factory()
    chart = _chart(datetime(1988, 1, 12, 17, 55), gender="male")
    fate = build_fate_analysis(chart)
    assert "水" in fate.xiyongshen.avoid
    async with factory() as session:
        candidates = await generate_candidates(session, "侯", fate, 3)
        assert len(candidates) >= 1
        wx_map = await load_wuxing_map(session)
        for c in candidates:
            for ch in c.given_name:
                assert wx_map.get(ch) != "水", f"严格模式不应推荐水属性字：{c.given_name}"
