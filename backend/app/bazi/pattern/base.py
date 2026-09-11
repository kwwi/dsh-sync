"""格局判定公共工具."""

from __future__ import annotations

from app.bazi.constants import HIDDEN_STEMS, STEM_ELEMENT, TEN_GOD_TABLE
from app.models.schemas import BaziChart, Pillar


def month_main_hidden_stem(month_branch: str) -> tuple[str, str]:
    """月令本气藏干."""
    first = HIDDEN_STEMS[month_branch][0]
    return first[0], first[1]


def month_main_ten_god(chart: BaziChart) -> str:
    day_stem = chart.day_master["stem"]
    hs, _ = month_main_hidden_stem(chart.pillars["month"].branch)
    return TEN_GOD_TABLE[day_stem][hs]


def exposed_stems(chart: BaziChart) -> list[tuple[str, str, Pillar]]:
    """(柱位, 天干, pillar) 除日干外."""
    out = []
    for key in ("year", "month", "hour"):
        p = chart.pillars[key]
        out.append((key, p.stem, p))
    return out


def stem_has_branch_root(stem: str, chart: BaziChart) -> bool:
    el = STEM_ELEMENT[stem]
    for key in ("year", "month", "day", "hour"):
        for hs in chart.pillars[key].hidden_stems:
            if hs.element == el:
                return True
    return False


def count_element_occurrences(chart: BaziChart, element_en: str) -> int:
    n = 0
    for key in ("year", "month", "day", "hour"):
        p = chart.pillars[key]
        if p.stem_element == element_en:
            n += 1
        for hs in p.hidden_stems:
            if hs.element == element_en:
                n += 1
    return n


def count_branch_element_occurrences(chart: BaziChart, element_en: str) -> int:
    """地支藏干中某五行的出现次数（不数天干）——用于判断某行是否「有根」."""
    n = 0
    for key in ("year", "month", "day", "hour"):
        for hs in chart.pillars[key].hidden_stems:
            if hs.element == element_en:
                n += 1
    return n
