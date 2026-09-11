"""专旺、从格、化格测试."""

from datetime import datetime

from app.bazi.analysis import analyze_bazi_rules
from app.bazi.engine import calculate_bazi
from app.bazi.pattern.special import detect_special_pattern
from app.bazi.strength import calculate_day_master_strength


def test_special_detector_runs_on_golden():
    dt = datetime(1988, 1, 12, 17, 55)
    chart = calculate_bazi(dt, longitude=106.03, gender="male")
    strength = calculate_day_master_strength(chart)
    result = detect_special_pattern(chart, strength)
    assert result is None or isinstance(result.name, str)


def test_fate_agent_sync_rules():
    from app.agents import FateAnalysisAgent

    dt = datetime(1988, 1, 12, 17, 55)
    chart = calculate_bazi(dt, longitude=106.03, gender="male")
    fate = FateAnalysisAgent().analyze_sync_rules(chart)
    assert "火" in fate.xiyongshen.primary
    assert fate.professional
    assert "日元" in fate.professional or "偏弱" in fate.professional or "平和" in fate.professional


def test_analysis_includes_tune_and_pattern():
    dt = datetime(1988, 1, 12, 17, 55)
    chart = calculate_bazi(dt, longitude=106.03, gender="male")
    a = analyze_bazi_rules(chart)
    assert a.tune.primary
    assert a.pattern.name
    assert a.strength.level in ("平和", "偏弱")
