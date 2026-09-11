"""大运排法测试（命理探原体系）."""

from __future__ import annotations

from datetime import datetime

from app.bazi.dayun import _compute_dayun
from app.bazi.engine import calculate_bazi
from app.bazi.analysis import analyze_bazi_rules


def test_golden_001_reverse_direction():
    """丁卯阴年男命 → 逆排；约2.25岁起运；第一步壬子（月柱癸丑逆推）. """
    birth = datetime(1988, 1, 12, 17, 55)
    r = _compute_dayun(birth, "male", now=datetime(2026, 3, 1))
    assert r.direction == "逆排"
    assert 2.0 <= r.start_age <= 2.5
    assert r.steps[0].ganzhi == "壬子"
    assert r.steps[1].ganzhi == "辛亥"
    assert r.current.ganzhi == "己酉"
    assert r.current_year_ganzhi == "丙午"


def test_yang_year_male_forward():
    """甲子阳年男命 → 顺排."""
    birth = datetime(1984, 6, 15, 10, 0)
    r = _compute_dayun(birth, "male", now=datetime(2026, 3, 1))
    assert r.direction == "顺排"


def test_yin_year_male_reverse():
    """乙丑阴年男命 → 逆排."""
    birth = datetime(1985, 6, 15, 10, 0)
    r = _compute_dayun(birth, "male", now=datetime(2026, 3, 1))
    assert r.direction == "逆排"


def test_chart_without_beijing_time_returns_none():
    """build_chart_from_pillars 无公历时刻 → compute_dayun 返回 None（报告自动跳过）."""
    from app.bazi.engine import build_chart_from_pillars
    from app.bazi.dayun import compute_dayun
    chart = build_chart_from_pillars("丁卯", "癸丑", "丙寅", "丙申")
    assert compute_dayun(chart) is None


def test_dayun_report_note():
    """报告含大运节：丙午流年（火，含地支本气）为助用."""
    chart = calculate_bazi(datetime(1988, 1, 12, 17, 55), longitude=106.03, gender="male")
    a = analyze_bazi_rules(chart)
    from app.report.narrative import build_fate_analysis
    r = build_fate_analysis(chart, a)
    assert "大运" in r.professional
    assert "丙午（助用" in r.professional
    assert "地支本气" in r.professional
