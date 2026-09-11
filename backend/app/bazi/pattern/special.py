"""专旺格、从格、化格判定."""

from __future__ import annotations

from app.bazi.constants import CONTROLS_EN, ELEMENT_CN, GENERATES_EN, STEM_COMBINE, STEM_ELEMENT
from app.bazi.pattern.base import (
    count_element_occurrences,
    month_main_hidden_stem,
    month_main_ten_god,
)
from app.models.schemas import BaziChart, DayMasterStrength, PatternResult

_ZHUANWANG = {
    "wood": "曲直格",
    "fire": "炎上格",
    "earth": "稼穑格",
    "metal": "从革格",
    "water": "润下格",
}


def detect_special_pattern(chart: BaziChart, strength: DayMasterStrength) -> PatternResult | None:
    hua = _detect_hua_ge(chart, strength)
    if hua:
        return hua
    cong = _detect_cong_ge(chart, strength)
    if cong:
        return cong
    zhuan = _detect_zhuanwang(chart, strength)
    if zhuan:
        return zhuan
    return None


def _detect_hua_ge(chart: BaziChart, strength: DayMasterStrength) -> PatternResult | None:
    # 化气格须「日主孤弱」（《子平真诠》：化之真者，日主孤弱，化神旺相）；
    # 日主偏强/极强时不得从化（有古籍丁壬化木原例的强度判断佐证）
    if strength.score >= 50:
        return None

    day_stem = chart.day_master["stem"]
    month_branch = chart.pillars["month"].branch
    month_el = _branch_dominant_element(month_branch)

    # 化气格条件：
    #  1. 合必须与日干相邻（月干/时干；年干隔柱不合）；
    #  2. 月令支持化神；
    #  3. 日主不得有本气真根于地支（余气/库根力弱，可从化，如真诠评注丁壬化木例）；
    #  4. 无克化神之干（日干本身除外）。
    for key in ("month", "hour"):
        partner = chart.pillars[key].stem
        if partner == day_stem:
            continue
        pair = frozenset({day_stem, partner})
        if pair not in STEM_COMBINE:
            continue
        hua_el = STEM_COMBINE[pair]
        if not _supports_combine(hua_el, month_el, month_branch):
            continue
        if _stem_has_main_branch_root(day_stem, chart):
            continue
        if any(
            CONTROLS_EN.get(STEM_ELEMENT[p.stem]) == hua_el
            for k, p in chart.pillars.items()
            if k != "day"
        ):
            continue
        hua_cn = ELEMENT_CN[hua_el]
        return PatternResult(
            name=f"化{hua_cn}格",
            formed=True,
            confidence="medium",
            reasoning=[
                f"{day_stem}与{partner}合化{hua_cn}",
                f"月令支持化神，日主无本气真根，无克化神之干，从化势成",
            ],
        )
    return None


def _stem_has_main_branch_root(stem: str, chart: BaziChart) -> bool:
    """天干五行是否落于某支本气（禄旺真根）。余气/墓库根不计。"""
    el = STEM_ELEMENT[stem]
    for key in ("year", "month", "day", "hour"):
        if chart.pillars[key].hidden_stems[0].element == el:
            return True
    return False


def _branch_dominant_element(branch: str) -> str:
    from app.bazi.constants import SEASON_DOMINANT
    from app.bazi.season import is_earth_month
    if is_earth_month(branch):
        return "earth"
    return SEASON_DOMINANT.get(branch, "earth")


def _supports_combine(hua_el: str, month_el: str, month_branch: str) -> bool:
    if hua_el == month_el:
        return True
    if GENERATES_EN.get(month_el) == hua_el:
        return True
    if month_branch in ("辰", "戌", "丑", "未") and hua_el == "earth":
        return True
    return False


def _day_master_has_root(chart: BaziChart) -> bool:
    """日主在四支是否有根（地支藏干含日主五行）。"""
    day_el = chart.day_master["element"]
    for key in ("year", "month", "day", "hour"):
        for hs in chart.pillars[key].hidden_stems:
            if hs.element == day_el:
                return True
    return False


def _is_strictly_dominant(chart: BaziChart, element_en: str) -> bool:
    """该五行（含藏干）出现数严格多于其余四行。"""
    n = count_element_occurrences(chart, element_en)
    for other in ("wood", "fire", "earth", "metal", "water"):
        if other != element_en and count_element_occurrences(chart, other) >= n:
            return False
    return True


def _drain_element_counts(chart: BaziChart) -> tuple[dict[str, int], str]:
    """财/官杀/食伤三行五行计数（含藏干），并给出月令本气所属阵营. Returns (counts, month_kind)."""
    day_el = chart.day_master["element"]
    counts = {
        CONTROLS_EN[day_el]: 0,   # 财 = 我克
        _guansha(day_el): 0,      # 官杀 = 克我
        GENERATES_EN[day_el]: 0,  # 食伤 = 我生
    }
    for key in ("year", "month", "day", "hour"):
        p = chart.pillars[key]
        counts[p.stem_element] = counts.get(p.stem_element, 0) + 1
        for hs in p.hidden_stems:
            counts[hs.element] = counts.get(hs.element, 0) + 1
    month_el = month_main_hidden_stem(chart.pillars["month"].branch)[1]
    month_kind = "比劫"
    for kind, el in (("财", CONTROLS_EN[day_el]), ("官杀", _guansha(day_el)), ("食伤", GENERATES_EN[day_el])):
        if month_el == el:
            month_kind = kind
    return counts, month_kind


def _weighted_branch_root_count(chart: BaziChart, element_en: str) -> float:
    """地支藏干加权根气：本气 1.0、中气 0.5、余气 0.25（《滴天髓》通根强弱之别）."""
    total = 0.0
    weights = (1.0, 0.5, 0.25)
    for key in ("year", "month", "day", "hour"):
        for idx, hs in enumerate(chart.pillars[key].hidden_stems):
            if hs.element == element_en:
                total += weights[idx] if idx < len(weights) else 0.25
    return total


def _detect_cong_ge(chart: BaziChart, strength: DayMasterStrength) -> PatternResult | None:
    day_el = chart.day_master["element"]
    month_branch = chart.pillars["month"].branch
    month_tg = month_main_ten_god(chart)

    # 印星透干 → 生身破从势（从财/从杀/从儿俱忌）
    if any(
        chart.pillars[key].ten_god in ("正印", "偏印")
        for key in ("year", "month", "hour")
    ):
        return None

    # 印星有根（加权根气≥1.5）生扶日主 → 不从（从儿亦忌印；滴天髓顺局：从儿忌印）
    yin_el = next(e for e, gen in GENERATES_EN.items() if gen == day_el)
    if _weighted_branch_root_count(chart, yin_el) >= 1.5:
        return None

    # ── 从儿格：月令食伤当令、食伤成气构门闾，不论日主强弱、可带比劫 ──
    # 滴天髓顺局：从儿不论身强弱，只要吾儿又得儿。忌印（已排除）、次忌官杀透干。
    if month_tg in ("食神", "伤官"):
        food_el = GENERATES_EN[day_el]
        if _is_strictly_dominant(chart, food_el) and not any(
            chart.pillars[key].ten_god in ("正官", "七杀")
            for key in ("year", "month", "hour")
        ):
            return PatternResult(
                name="从儿格",
                formed=True,
                confidence="medium",
                reasoning=[
                    f"月令{month_branch}食伤当令，{ELEMENT_CN[food_el]}成气构门闾",
                    "从儿不论身强弱，比劫生助食伤不忌",
                ],
            )

    # ── 从财/从杀/从势：须日主无根、衰极 ──
    if strength.score >= 20:
        return None
    if _day_master_has_root(chart):
        return None
    # 比劫有根（加权根气≥1.5）帮身 → 不从（天干虚浮比劫不忌，渊海子平李侍郎例）
    if _weighted_branch_root_count(chart, day_el) >= 1.5:
        return None

    # 所从之神：财/官杀/食伤 五行能量最强（含藏干），平局以月令本气优先
    counts, month_kind = _drain_element_counts(chart)
    kind_el = {
        "财": CONTROLS_EN[day_el],
        "官杀": _guansha(day_el),
        "食伤": GENERATES_EN[day_el],
    }
    month_el = kind_el.get(month_kind, "")
    dominant_el = max(counts, key=lambda e: (counts[e], e == month_el))
    if counts[dominant_el] < 3:
        return None
    if dominant_el == CONTROLS_EN[day_el]:
        name, el = "从财格", dominant_el
    elif dominant_el == _guansha(day_el):
        name, el = "从杀格", dominant_el
    else:
        name, el = "从势格", day_el

    # 真从/假从区分（《滴天髓》从化论）
    # 真从：所从之神当令成气、日主无任何根气、无印比干扰
    # 假从：有微根被冲克/有时辰余气根/印比虚浮 → 仍从但层次降低
    bi_root_count = _weighted_branch_root_count(chart, day_el)
    is_true_cong = (
        bi_root_count == 0  # 无任何比劫根气
        and month_kind != "比劫"  # 月令非比劫
    )
    cong_confidence = "high" if is_true_cong else "medium"
    cong_detail = "真从" if is_true_cong else "假从（有微根或余气，层次略降）"

    return PatternResult(
        name=name,
        formed=True,
        confidence=cong_confidence,
        reasoning=[
            f"日主极弱（{strength.score}分）且地支无根，比劫虚浮不忌，印星不现",
            f"{cong_detail}，顺势而从{name[1:]}",
        ],
    )


def _ten_god_element(day_stem: str, ten_god: str) -> str:
    from app.bazi.constants import TEN_GOD_TABLE
    for stem, el in STEM_ELEMENT.items():
        if TEN_GOD_TABLE[day_stem][stem] == ten_god:
            return el
    return "earth"


_ZHUANWANG_FANGJU = {
    "wood": ("寅", "卯", "辰"),
    "fire": ("巳", "午", "未"),
    "metal": ("申", "酉", "戌"),
    "water": ("亥", "子", "丑"),
}


def _element_has_strong_support(chart: BaziChart, element_en: str) -> bool:
    """财/官杀是否当令或有根（≥3 处）——有则破专旺格."""
    month_el = month_main_hidden_stem(chart.pillars["month"].branch)[1]
    if month_el == element_en:
        return True
    return count_element_occurrences(chart, element_en) >= 3


def _detect_zhuanwang(chart: BaziChart, strength: DayMasterStrength) -> PatternResult | None:
    day_el = chart.day_master["element"]
    month_branch = chart.pillars["month"].branch
    branches = [p.branch for p in chart.pillars.values()]

    # 支全三会方局（滴天髓方局：寅卯辰等会方亦成专旺，不论月令当令与否）
    fangju = _ZHUANWANG_FANGJU.get(day_el)
    has_fangju = bool(fangju and all(b in branches for b in fangju))

    # 非会方须当令（月令旺/相）；日主极强
    from app.bazi.season import is_de_ling
    if not has_fangju:
        if not is_de_ling(day_el, month_branch):
            return None
        if strength.score < 70:
            return None

    # 财官虚浮不忌，但当令/有根则克泄耗身破格（滴天髓方局：休金难克，强众敌寡）
    for key in ("year", "month", "hour"):
        tg = chart.pillars[key].ten_god
        if tg in ("正财", "偏财", "正官", "七杀"):
            el = chart.pillars[key].stem_element
            if _element_has_strong_support(chart, el):
                return None

    count = count_element_occurrences(chart, day_el)
    if count < 4:
        return None
    name = _ZHUANWANG.get(day_el, "专旺格")
    reason = (
        f"日主五行出现{count}处，支全三会方局，财官虚浮无根，日主极强（{strength.score}分），成{name}"
        if has_fangju
        else f"日主五行出现{count}处，当令且财官虚浮无根，日主极强（{strength.score}分），成{name}"
    )
    return PatternResult(
        name=name,
        formed=True,
        confidence="high",
        reasoning=[reason],
    )


def _yinxing(dm_en: str) -> str:
    """日主之印星（生我者）."""
    for k, v in GENERATES_EN.items():
        if v == dm_en:
            return k
    return "water"


def _guansha(dm_en: str) -> str:
    """日主之官杀（克我者）."""
    for k, v in CONTROLS_EN.items():
        if v == dm_en:
            return k
    return "water"


def _element_that_controls(el_en: str) -> str:
    """克此元素者."""
    for k, v in CONTROLS_EN.items():
        if v == el_en:
            return k
    return "water"


def special_pattern_xiyongshen(pattern: PatternResult, day_el_cn: str) -> tuple[list[str], list[str], list[str]]:
    """特殊格局喜用神：根据格局类型和日主五行动态推导."""
    name = pattern.name
    rev = {v: k for k, v in ELEMENT_CN.items()}
    day_en = rev.get(day_el_cn, "earth")

    if name.startswith("化"):
        hua_cn = name[1]
        hua_en = rev[hua_cn]
        # 喜化神五行，忌克化神者（官杀）
        ke_hua = _element_that_controls(hua_en)
        return ([hua_cn], [], [ELEMENT_CN[ke_hua]])

    if "从财" in name or "从杀" in name or "从儿" in name or "从势" in name:
        # 从格：顺势而行，忌印星（生身破格）和比劫（助身破格）
        yin_en = _yinxing(day_en)  # 印星 = 生我者

        if "从财" in name:
            dominant = CONTROLS_EN[day_en]  # 财星 = 我克者
            follow = GENERATES_EN[day_en]  # 食伤 = 生财者
        elif "从杀" in name:
            dominant = _guansha(day_en)  # 官杀 = 克我者
            follow = CONTROLS_EN[day_en]  # 财星 = 生官杀者
        elif "从儿" in name:
            # 从儿不忌比劫（比劫生食伤），忌印星（克食伤破局）
            dominant = GENERATES_EN[day_en]  # 食伤 = 我生者
            follow = CONTROLS_EN[day_en]  # 财星 = 泄食伤者
            return (
                [ELEMENT_CN[dominant], ELEMENT_CN[follow]],
                [],
                [ELEMENT_CN[yin_en]],
            )
        else:  # 从势格
            dominant = CONTROLS_EN[day_en]  # 财星
            follow = GENERATES_EN[day_en]  # 食伤

        return (
            [ELEMENT_CN[dominant], ELEMENT_CN[follow]],
            [],
            [ELEMENT_CN[yin_en], day_el_cn],
        )

    if name in _ZHUANWANG.values():
        xie = ELEMENT_CN[GENERATES_EN[day_en]]  # 食伤泄秀
        bi = day_el_cn  # 比劫助旺
        ke = ELEMENT_CN[_guansha(day_en)]  # 官杀克身破格
        return ([xie, bi], [], [ke])

    return ([], [], [])
