"""滴天髓层次评估测试：贵/富/才/学倾向 + 病药."""

from __future__ import annotations

from app.bazi.analysis import analyze_bazi_rules
from app.bazi.engine import build_chart_from_pillars


def test_golden_001_guangi_with_crash_disease():
    """GOLDEN-001 丁卯癸丑丙寅丙申：正官格官印相生 → 贵气；寅申冲为病."""
    chart = build_chart_from_pillars("丁卯", "癸丑", "丙寅", "丙申")
    a = analyze_bazi_rules(chart)
    assert any("贵气" in t for t in a.level.tendencies)
    assert any("寅申" in d for d in a.level.diseases)
    assert all(c not in a.xiyongshen.avoid for c in a.level.cures), "药不得与忌神冲突"


def test_cai_fu_with_strong_day_master():
    """身强财旺：庚金酉月（当令），三透乙木正财 → 富气."""
    chart = build_chart_from_pillars("乙卯", "乙酉", "庚辰", "乙酉")
    a = analyze_bazi_rules(chart)
    assert any("富" in t for t in a.level.tendencies)


def test_shishang_caiqi():
    """食伤透干泄秀 → 才气."""
    chart = build_chart_from_pillars("丁卯", "壬寅", "癸卯", "丙辰")
    a = analyze_bazi_rules(chart)
    assert any("才" in t for t in a.level.tendencies)
