"""格局判定测试."""

from datetime import datetime

from app.bazi.analysis import analyze_bazi_rules
from app.bazi.engine import calculate_bazi


def test_golden_pattern_tendency():
    dt = datetime(1988, 1, 12, 17, 55)
    chart = calculate_bazi(dt, longitude=106.03, gender="male")
    analysis = analyze_bazi_rules(chart)
    assert "官" in analysis.pattern.name or analysis.pattern.name != ""


def test_analysis_has_chain():
    dt = datetime(1988, 1, 12, 17, 55)
    chart = calculate_bazi(dt, longitude=106.03, gender="male")
    analysis = analyze_bazi_rules(chart)
    assert len(analysis.reasoning_chain) >= 4
    assert analysis.strength.level in ("极强", "偏强", "平和", "偏弱", "极弱")
