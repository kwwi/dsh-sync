"""以《滴天髓阐微》《渊海子平》《子平真诠评注》等典籍原例为金标准的格局测试.

古籍仅记四柱干支，故经 build_chart_from_pillars 由干支直接造盘（跳过公历换算）。
各例的四柱、格局与喜忌均以原文评语为据（见各用例 docstring 引文）。
"""

from __future__ import annotations

import pytest

from app.bazi.analysis import analyze_bazi_rules
from app.bazi.engine import build_chart_from_pillars


def _case(*gz, gender="male"):
    chart = build_chart_from_pillars(*gz, gender=gender)
    return chart, analyze_bazi_rules(chart)


def test_cong_er_ditiansui_fengjiang():
    """《滴天髓·顺局》从儿格 封疆大吏：丁卯 壬寅 癸卯 丙辰.

    癸水日主寅月伤官当令，木（食伤）成气构门闾，比劫壬水透干不忌；
    「从儿不论身强弱，只要吾儿又得儿」。喜食伤（木）生财（火），忌印（金）。
    """
    chart, a = _case("丁卯", "壬寅", "癸卯", "丙辰")
    assert a.pattern.name == "从儿格"
    assert a.xiyongshen.primary == ["木", "火"]
    assert "金" in a.xiyongshen.avoid, "从儿忌印星"
    assert "木" not in a.xiyongshen.avoid and "水" not in a.xiyongshen.avoid, "从儿不忌比劫"


def test_cong_sha_yuanhai_lishilang():
    """《渊海子平》李侍郎从杀格：乙酉 乙酉 乙酉 甲申.

    乙木日主四支纯金（官杀当令成势），天干三乙一甲比劫虚浮透干——
    神峰通考：「天干虚浮比劫，不忌」。喜官杀（金）财（土）生杀，忌印（水）比（木）。
    """
    chart, a = _case("乙酉", "乙酉", "乙酉", "甲申")
    assert a.pattern.name == "从杀格"
    assert a.xiyongshen.primary == ["金", "土"]
    assert set(a.xiyongshen.avoid) == {"水", "木"}


def test_quzhi_fangju_ditiansui():
    """《滴天髓·方局》曲直仁寿格：丁卯 甲辰 甲寅 乙亥.

    甲木日主，地支寅卯辰三会东方木方（「格名曲直仁寿者」），虽辰月土旺亦成局；
    天干丁火伤官泄秀（「独象喜行化地」）。喜食伤（火）比劫（木），忌官杀（金）。
    """
    chart, a = _case("丁卯", "甲辰", "甲寅", "乙亥")
    assert a.pattern.name == "曲直格"
    assert a.xiyongshen.primary == ["火", "木"]
    assert "金" in a.xiyongshen.avoid


def test_runxia_ditiansui():
    """《滴天髓·形象》润下格：壬子 辛亥 癸丑 壬子.

    癸水日主，地支亥子丑三会北方水，天干三透壬癸，「水气独旺即润下格」。
    喜食伤（木）比劫（水），忌官杀（土）。
    """
    chart, a = _case("壬子", "辛亥", "癸丑", "壬子")
    assert a.pattern.name == "润下格"
    assert a.xiyongshen.primary == ["木", "水"]
    assert "土" in a.xiyongshen.avoid


def test_yanshang_ditiansui():
    """《滴天髓·形象》炎上格：丙寅 甲午 丙戌 乙未.

    丙火日主午月当令，寅午戌三合火局，「火气独旺即炎上格」。
    喜食伤（土）比劫（火），忌官杀（水）。
    """
    chart, a = _case("丙寅", "甲午", "丙戌", "乙未")
    assert a.pattern.name == "炎上格"
    assert a.xiyongshen.primary == ["土", "火"]
    assert "水" in a.xiyongshen.avoid


def test_huaqi_zhenquan_dingren():
    """《子平真诠评注·论杂格》丁壬化木 一品贵格：甲戌 丁卯 壬寅 甲辰.

    壬水日主与月干丁火合化木，卯月木当令，日主无本气真根（辰中癸水余气力弱可从化）。
    喜化神（木），忌克化神者（金）。
    """
    chart, a = _case("甲戌", "丁卯", "壬寅", "甲辰")
    assert a.pattern.name == "化木格"
    assert a.xiyongshen.primary == ["木"]
    assert "金" in a.xiyongshen.avoid


def test_cong_ge_rejects_rooted_yinbi():
    """印/比劫在地支有根（≥3处）生扶日主即破从，仅天干虚浮不忌.

    - 丁卯 戊申 丙辰 辛卯：丙火申月，卯卯辰三处印根 → 不得从势（正财格身弱）
    - 丁酉 丙午 癸酉 丁巳：癸水午月，酉酉巳三处印根 → 不得从财（偏财格身弱）
    """
    for gz in (("丁卯", "戊申", "丙辰", "辛卯"), ("丁酉", "丙午", "癸酉", "丁巳")):
        chart, a = _case(*gz)
        assert "从" not in a.pattern.name, (gz, a.pattern.name)
        assert a.pattern.name not in ("曲直格", "炎上格", "稼穑格", "从革格", "润下格"), a.pattern.name


def test_classical_cases_xy_not_overlap():
    """全部典籍原例的喜用神与忌神不得重合."""
    cases = [
        ("丁卯", "壬寅", "癸卯", "丙辰"),
        ("乙酉", "乙酉", "乙酉", "甲申"),
        ("丁卯", "甲辰", "甲寅", "乙亥"),
        ("壬子", "辛亥", "癸丑", "壬子"),
        ("丙寅", "甲午", "丙戌", "乙未"),
        ("甲戌", "丁卯", "壬寅", "甲辰"),
    ]
    for gz in cases:
        _, a = _case(*gz)
        assert not (set(a.xiyongshen.primary) & set(a.xiyongshen.avoid)), gz
