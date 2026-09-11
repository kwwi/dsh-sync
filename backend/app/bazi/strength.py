"""日主强弱：得令、得地、得势量化."""

from __future__ import annotations

from app.bazi.constants import (
    GENERATES_EN,
    HIDDEN_STEMS,
    HIDDEN_WEIGHTS,
    STEM_ELEMENT,
    STRONG_STAGES,
    TEN_GOD_TABLE,
    TEN_GOD_XIESHI,
    TEN_GOD_YINBI,
    WEAK_STAGES,
)
from app.bazi.season import de_ling_score, is_de_ling
from app.models.schemas import BaziChart, DayMasterStrength, Pillar


def _pillar_list(chart: BaziChart) -> list[tuple[str, Pillar]]:
    return [("year", chart.pillars["year"]), ("month", chart.pillars["month"]),
            ("day", chart.pillars["day"]), ("hour", chart.pillars["hour"])]


def _stem_has_root(stem: str, pillars: list[tuple[str, Pillar]]) -> bool:
    """天干在地支有无根气（同五行藏干，不含印星）——《子平真诠》通根论."""
    stem_el = STEM_ELEMENT[stem]
    for _, p in pillars:
        for hs in p.hidden_stems:
            if hs.element == stem_el:
                return True
    return False


def calculate_day_master_strength(chart: BaziChart) -> DayMasterStrength:
    day_stem = chart.day_master["stem"]
    day_el = chart.day_master["element"]
    month_branch = chart.pillars["month"].branch
    pillars = _pillar_list(chart)
    reasoning: list[str] = []

    # --- 得令 ---
    ling_score = de_ling_score(day_el, month_branch)
    de_ling = is_de_ling(day_el, month_branch)
    status_cn = chart.day_master["element_cn"]
    from app.bazi.season import element_status_in_month
    st = element_status_in_month(day_el, month_branch)
    reasoning.append(f"得令：日主{status_cn}生于{month_branch}月，月令状态「{st}」，得令分{ling_score}")

    # --- 得地 ---
    # 月支通根（禄刃/印库）是得地之重（《子平真诠》通根论），四支全计；
    # 得令与得地维度不同（月令状态 vs 通根），权重已分别压缩避免月令独大
    di_score = 0
    for key, p in pillars:
        hidden = HIDDEN_STEMS.get(p.branch, [])
        for idx, (hs, el) in enumerate(hidden):
            weight = HIDDEN_WEIGHTS[idx] if idx < len(HIDDEN_WEIGHTS) else 4
            if el == day_el:
                di_score += weight
                reasoning.append(f"得地：{key}支{p.branch}藏{hs}同日主五行，+{weight}")
            elif GENERATES_EN.get(el) == day_el:
                di_score += max(weight // 2, 4)
                reasoning.append(f"得地：{key}支{p.branch}藏{hs}印星生身，+{max(weight // 2, 4)}")

    day_stage = chart.pillars["day"].growth_stage
    if day_stage in STRONG_STAGES:
        di_score += 5
        reasoning.append(f"得地：日坐{day_stage}，+5")
    elif day_stage in WEAK_STAGES:
        di_score -= 5
        reasoning.append(f"得地：日坐{day_stage}，-5")

    # --- 得势 ---
    shi_score = 0
    stem_positions = [("year", 3), ("month", 2), ("hour", 1)]
    for key, dist in stem_positions:
        p = chart.pillars[key]
        tg = TEN_GOD_TABLE[day_stem][p.stem]
        if tg not in TEN_GOD_YINBI:
            continue
        base = {1: 10, 2: 7, 3: 5}[dist]
        if not _stem_has_root(p.stem, pillars):
            base = base // 2
        shi_score += base
        reasoning.append(f"得势：{key}干{p.stem}（{tg}）距日干{dist}柱，+{base}")

    # --- 克泄耗修正 ---
    drain = 0
    for key, p in pillars:
        if p.stem == day_stem and key == "day":
            continue
        tg = TEN_GOD_TABLE[day_stem][p.stem]
        if tg in TEN_GOD_XIESHI:
            penalty = 6 if key in ("month", "hour") else 4
            if _stem_has_root(p.stem, pillars):
                penalty += 2
            drain += penalty
            reasoning.append(f"克泄耗：{key}干{p.stem}（{tg}），-{penalty}")

    total = ling_score + di_score + shi_score - drain
    level = _score_to_level(total)
    reasoning.insert(0, f"日主强弱总分{total}（得令{ling_score}+得地{di_score}+得势{shi_score}-克泄耗{drain}）→{level}")

    return DayMasterStrength(
        score=total,
        level=level,
        de_ling=de_ling,
        de_di=di_score,
        de_shi=shi_score,
        reasoning=reasoning,
    )


def _score_to_level(score: int) -> str:
    """强弱档位（阈值与月令状态的中位数对齐：旺≈偏强、相≈平和、休≈偏弱、囚≈偏弱、死≈极弱）."""
    if score >= 65:
        return "极强"
    if score >= 48:
        return "偏强"
    if score >= 32:
        return "平和"
    if score >= 0:
        return "偏弱"
    return "极弱"
