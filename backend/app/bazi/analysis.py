"""命理规则分析总入口."""

from __future__ import annotations

from app.bazi.season import season_strength_for_month, season_label
from app.bazi.strength import calculate_day_master_strength
from app.bazi.tune import analyze_tune
from app.bazi.xiyongshen import detect_pattern, synthesize_xiyongshen
from app.bazi.level import assess_level
from app.bazi.shensha import detect_shensha
from app.models.schemas import BaziAnalysis, BaziChart


def analyze_bazi_rules(chart: BaziChart) -> BaziAnalysis:
    month_branch = chart.pillars["month"].branch
    season_ss = season_strength_for_month(month_branch)
    strength = calculate_day_master_strength(chart)
    tune = analyze_tune(chart)
    pattern = detect_pattern(chart, strength)
    xy, xy_chain = synthesize_xiyongshen(chart, strength, tune, pattern)
    level = assess_level(chart, strength, pattern, avoid=xy.avoid)
    shensha = detect_shensha(chart)

    chain = [
        f"月令{chart.pillars['month'].ganzhi}（{season_label(month_branch)}）",
        f"日主{chart.day_master['element_cn']}{strength.level}（{strength.score}分）",
        tune.summary,
        f"格局：{pattern.name}" + ("（成格）" if pattern.formed else "（未成）"),
        *xy_chain,
        f"喜用神：{'/'.join(xy.primary)}" + (f"，次喜{'/'.join(xy.secondary)}" if xy.secondary else ""),
    ]

    return BaziAnalysis(
        season_strength=season_ss,
        strength=strength,
        tune=tune,
        pattern=pattern,
        xiyongshen=xy,
        level=level,
        shensha=shensha,
        reasoning_chain=chain,
    )
