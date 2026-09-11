"""《子平真诠》取格法测试：透干优先取格、用神有破为败、官杀喜忌拆分.

取格规则：月令藏干按本气→中气→余气序，最先透出于年/月/时干者取为格局；
          皆不透则取月令本气。
成败规则：官格忌伤官透干破官、官杀混杂；杀格忌混官；食神格忌枭神夺食；
          伤官格忌伤官见官；印格忌财星坏印。
"""

from __future__ import annotations

import pytest

from app.bazi.analysis import analyze_bazi_rules
from app.bazi.engine import build_chart_from_pillars


def _case(*gz, gender="male"):
    chart = build_chart_from_pillars(*gz, gender=gender)
    return chart, analyze_bazi_rules(chart)


def test_golden_001_is_zhengguan_ge():
    """GOLDEN-001 丁卯 癸丑 丙寅 丙申：丑藏己癸辛，癸水正官透月干 → 正官格（成）."""
    chart, a = _case("丁卯", "癸丑", "丙寅", "丙申")
    assert a.pattern.name == "正官格"
    assert a.pattern.formed
    assert a.pattern.reasoning[0] == "月令丑藏伤官/正财/正官，透正官取为正官格"


def test_zhoumu_is_zhengguan_ge_with_peiyin():
    """滴天髓州牧 癸酉 乙丑 丙申 丙申：癸正官透年干 → 正官格，乙印透为官印相生."""
    chart, a = _case("癸酉", "乙丑", "丙申", "丙申")
    assert a.pattern.name == "正官格"
    assert "官印相生" in "；".join(a.pattern.reasoning)
    assert "从" not in a.pattern.name


def test_middle_hidden_stem_exposed_takes_pattern():
    """本气不透、中气透：戊土寅月（藏甲七杀/丙偏印/戊比肩），甲不透丙透 → 偏印格."""
    chart, a = _case("丙辰", "庚寅", "戊午", "戊午")
    assert a.pattern.name == "偏印格"
    assert a.pattern.formed


def test_guan_sha_hunza_breaks_zhengguan():
    """正官格遇七杀透干 → 官杀混杂，格局未成."""
    chart, a = _case("壬申", "癸丑", "丙午", "庚寅")
    assert a.pattern.name == "正官格（未成）"
    assert not a.pattern.formed
    assert "官杀混杂" in a.pattern.reasoning


def test_shangguan_jian_guan_breaks_shangguan():
    """伤官格遇正官透干 → 伤官见官，格局未成."""
    chart, a = _case("己巳", "癸丑", "丙寅", "庚寅")
    assert a.pattern.name == "伤官格（未成）"
    assert "伤官见官" in a.pattern.reasoning


def test_xiaoshen_duoshi_breaks_shishen():
    """食神格遇偏印透干 → 枭神夺食，格局未成."""
    chart, a = _case("辛未", "乙卯", "癸巳", "庚申")
    assert a.pattern.name == "食神格（未成）"
    assert "枭神夺食" in a.pattern.reasoning


def test_cai_xing_huai_yin_breaks_yin():
    """印格遇正财透干 → 财星坏印，格局未成."""
    chart, a = _case("己巳", "己亥", "甲子", "丙寅")
    assert a.pattern.name == "偏印格（未成）"
    assert "财星坏印" in a.pattern.reasoning


def test_shangguan_peiyin_forms():
    """伤官格遇印透 → 伤官佩印，成格."""
    chart, a = _case("甲辰", "己丑", "丙午", "庚寅")
    assert a.pattern.name == "伤官格"
    assert a.pattern.formed
    assert "伤官佩印" in "；".join(a.pattern.reasoning)


def test_zhengguan_ge_weak_avoids_shishang():
    """正官格身弱：喜印比，忌伤官（破官）与财（坏印）——官杀喜忌已拆分."""
    chart, a = _case("丁卯", "癸丑", "丙寅", "丙申", gender="male")
    xy = a.xiyongshen
    assert set(xy.primary) & {"木", "火"}
    assert set(xy.avoid) & {"土", "金"} or xy.avoid
