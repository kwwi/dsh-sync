"""四季旺相休囚死与月令季节判定."""

from __future__ import annotations

from app.bazi.constants import (
    CONTROLS_EN,
    EARTH_MONTH_STRENGTH,
    ELEMENT_CN,
    GENERATES_EN,
    SEASON_DOMINANT,
    WINTER_STRENGTH,
)
from app.models.schemas import SeasonStrength

STATUS_ORDER = ("旺", "相", "休", "囚", "死")
# 得令权重：压缩两极（旺/死），避免月令一项主导总分、半数命例落入「极弱」
STATUS_SCORE = {"旺": 40, "相": 25, "休": 8, "囚": -8, "死": -12}


def is_earth_month(month_branch: str) -> bool:
    return month_branch in ("辰", "戌", "丑", "未")


def season_strength_for_month(month_branch: str) -> SeasonStrength:
    """按月令计算五行旺相休囚死."""
    if is_earth_month(month_branch):
        data = EARTH_MONTH_STRENGTH
    elif month_branch in ("亥", "子"):
        data = WINTER_STRENGTH
    elif month_branch in ("寅", "卯"):
        data = _derive_from_dominant("wood")
    elif month_branch in ("巳", "午"):
        data = _derive_from_dominant("fire")
    elif month_branch in ("申", "酉"):
        data = _derive_from_dominant("metal")
    else:
        data = _derive_from_dominant(SEASON_DOMINANT.get(month_branch, "earth"))
    return SeasonStrength(**data)


def _derive_from_dominant(dominant: str) -> dict[str, str]:
    """当令者旺，我生者相，生我者休，克我者囚，我克者死."""
    result: dict[str, str] = {}
    for element in ("wood", "fire", "earth", "metal", "water"):
        if element == dominant:
            result[element] = "旺"
        elif GENERATES_EN[dominant] == element:
            result[element] = "相"
        elif GENERATES_EN[element] == dominant:
            result[element] = "休"
        elif CONTROLS_EN[element] == dominant:
            result[element] = "囚"
        elif CONTROLS_EN[dominant] == element:
            result[element] = "死"
        else:
            result[element] = "休"
    return result


def element_status_in_month(element_en: str, month_branch: str) -> str:
    ss = season_strength_for_month(month_branch)
    return getattr(ss, element_en)


def element_status_cn(element_cn: str, month_branch: str) -> str:
    rev = {v: k for k, v in ELEMENT_CN.items()}
    en = rev.get(element_cn, "earth")
    return element_status_in_month(en, month_branch)


def is_de_ling(day_element_en: str, month_branch: str) -> bool:
    status = element_status_in_month(day_element_en, month_branch)
    return status in ("旺", "相")


def de_ling_score(day_element_en: str, month_branch: str) -> int:
    status = element_status_in_month(day_element_en, month_branch)
    return STATUS_SCORE.get(status, 0)


def season_label(month_branch: str) -> str:
    if is_earth_month(month_branch):
        return "四季末（土旺）"
    dominant = SEASON_DOMINANT.get(month_branch, "earth")
    labels = {"wood": "春季", "fire": "夏季", "metal": "秋季", "water": "冬季"}
    return labels.get(dominant, "四季末（土旺）")
