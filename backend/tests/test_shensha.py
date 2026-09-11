"""神煞查表测试."""

from __future__ import annotations

from app.bazi.analysis import analyze_bazi_rules
from app.bazi.engine import build_chart_from_pillars


def test_golden_001_wenchang():
    """丙火日主坐申时 → 文昌贵人在时柱（丙→申）."""
    chart = build_chart_from_pillars("丁卯", "癸丑", "丙寅", "丙申")
    a = analyze_bazi_rules(chart)
    names = [i.name for i in a.shensha.items]
    assert "文昌贵人" in names
    wc = next(i for i in a.shensha.items if i.name == "文昌贵人")
    assert wc.pillar == "时"


def test_tianyi_gui_ren():
    """甲日主 → 天乙贵人在丑/未：甲戌年时见丑 → 天乙."""
    chart = build_chart_from_pillars("甲辰", "丁丑", "甲午", "乙丑")
    a = analyze_bazi_rules(chart)
    assert any(i.name == "天乙贵人" for i in a.shensha.items)


def test_ma_yi_and_kong_wang():
    """申子辰局年支 → 驿马在寅（时柱丙寅）；甲子日旬空戌亥（月支戌）."""
    chart = build_chart_from_pillars("壬申", "庚戌", "甲子", "丙寅")
    a = analyze_bazi_rules(chart)
    names = [i.name for i in a.shensha.items]
    assert "驿马" in names
    my = next(i for i in a.shensha.items if i.name == "驿马")
    assert my.pillar == "时"
    assert "空亡" in names
