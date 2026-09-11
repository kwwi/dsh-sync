"""八字排盘引擎."""

from __future__ import annotations

from datetime import datetime

from lunar_python import Solar

from app.bazi.constants import (
    BRANCHES,
    CLASH_PAIRS,
    CONTROLS_EN,
    ELEMENT_CN,
    GENERATES_EN,
    GROWTH_STAGE,
    HIDDEN_STEMS,
    NAYIN,
    SEASON_DOMINANT,
    SELF_PUNISHMENT_BRANCHES,
    SIX_HARMONY_PAIRS,
    SIX_HARMS_PAIRS,
    SIX_PUNISHMENT_PAIRS,
    SIX_PUNISHMENT_TRIPLES,
    STEM_COMBINE,
    STEM_ELEMENT,
    STEMS,
    TEN_GOD_TABLE,
    THREE_HARMONY_GROUPS,
    ZODIAC,
)
from app.bazi.season import season_strength_for_month
from app.bazi.strength import calculate_day_master_strength
from app.bazi.solar_time import beijing_to_true_solar
from app.models.schemas import (
    BaziChart,
    ElementCounts,
    HiddenStemItem,
    Pillar,
    Relations,
    SeasonStrength,
)


def _stem_index(stem: str) -> int:
    return STEMS.index(stem)


def _branch_index(branch: str) -> int:
    return BRANCHES.index(branch)


def _growth_stage(day_stem: str, branch: str) -> str:
    return GROWTH_STAGE[day_stem][_branch_index(branch)]


def _ten_god(day_stem: str, stem: str) -> str:
    return TEN_GOD_TABLE[day_stem][stem]


def _count_elements(pillars: list[Pillar]) -> ElementCounts:
    counts = {"wood": 0, "fire": 0, "earth": 0, "metal": 0, "water": 0}
    for p in pillars:
        counts[STEM_ELEMENT[p.stem]] += 1
        for hs in p.hidden_stems:
            counts[hs.element] += 1
    return ElementCounts(**counts)


def _detect_clashes(branches: list[str]) -> list[str]:
    clashes = []
    for i in range(len(branches)):
        for j in range(i + 1, len(branches)):
            pair = (branches[i], branches[j])
            rev = (branches[j], branches[i])
            if pair in CLASH_PAIRS or rev in CLASH_PAIRS:
                clashes.append(f"{branches[i]}{branches[j]}")
    return clashes


def _combine_forms(hua_el: str, month_branch: str, stems: list[str], pair: frozenset) -> bool:
    """天干五合是否成化：化神得月令支持（当令或月令所生），且无克化神之干透干（合之两干自身除外）.

    与 pattern/special.py 化气格判定的月令支持条件保持一致；化气格另需日干相邻、
    日主无本气真根，属格局层判定，此处仅作关系层「合/合化」标注。
    """
    month_el = "earth" if month_branch in ("辰", "戌", "丑", "未") else SEASON_DOMINANT.get(month_branch, "earth")
    supported = hua_el == month_el or GENERATES_EN.get(month_el) == hua_el
    if not supported:
        return False
    for s in stems:
        if s in pair:
            continue
        if CONTROLS_EN.get(STEM_ELEMENT[s]) == hua_el:
            return False
    return True


def _detect_relations(stems: list[str], branches: list[str]) -> Relations:
    clash = _detect_clashes(branches)

    combine: list[str] = []
    for a, b in SIX_HARMONY_PAIRS:
        if a in branches and b in branches:
            combine.append(f"{a}{b}合")

    three_combine: list[str] = []
    for group, el_cn in THREE_HARMONY_GROUPS.items():
        present = sorted((b for b in set(branches) if b in group), key=BRANCHES.index)
        if len(present) == 3:
            three_combine.append("".join(present) + f"三合{el_cn}局")

    harm: list[str] = []
    for a, b in SIX_HARMS_PAIRS:
        if a in branches and b in branches:
            harm.append(f"{a}{b}相害")

    punishment: list[str] = []
    # 三刑（寅巳申/丑戌未）：三字俱全称三刑，二字相见即论相刑（《渊海子平·论刑》）
    for triple in SIX_PUNISHMENT_TRIPLES:
        present = [b for b in triple if b in branches]
        if len(present) == 3:
            punishment.append(f"{triple}三刑")
        elif len(present) == 2:
            punishment.append(f"{present[0]}{present[1]}相刑")
    if SIX_PUNISHMENT_PAIRS and "子" in branches and "卯" in branches:
        punishment.append("子卯相刑")
    for b in SELF_PUNISHMENT_BRANCHES:
        if branches.count(b) >= 2:
            punishment.append(f"{b}{b}自刑")

    stem_combine: list[str] = []
    month_branch = branches[1]
    for i in range(len(stems)):
        for j in range(i + 1, len(stems)):
            pair = frozenset({stems[i], stems[j]})
            if pair in STEM_COMBINE:
                ordered = "".join(sorted((stems[i], stems[j]), key=_stem_index))
                label = f"{ordered}合"
                # 合而不化是常态：仅当化神得月令支持且无克化神之干透干时才论「合化」
                if _combine_forms(STEM_COMBINE[pair], month_branch, stems, pair):
                    label += f"化{ELEMENT_CN[STEM_COMBINE[pair]]}"
                stem_combine.append(label)
    stem_combine = list(dict.fromkeys(stem_combine))

    return Relations(
        clash=clash,
        combine=combine,
        harm=harm,
        punishment=punishment,
        three_combine=three_combine,
        stem_combine=stem_combine,
    )


def build_chart_from_pillars(
    year_gz: str,
    month_gz: str,
    day_gz: str,
    hour_gz: str,
    gender: str = "male",
) -> BaziChart:
    """由给定的四柱干支直接构造命盘（用于古籍原例，跳过公历换算）."""
    if len(year_gz) != 2 or len(month_gz) != 2 or len(day_gz) != 2 or len(hour_gz) != 2:
        raise ValueError(f"干支必须为两位字符: {year_gz} {month_gz} {day_gz} {hour_gz}")
    if year_gz[0] not in STEMS or year_gz[1] not in BRANCHES:
        raise ValueError(f"非法年柱干支: {year_gz}")
    if month_gz[0] not in STEMS or month_gz[1] not in BRANCHES:
        raise ValueError(f"非法月柱干支: {month_gz}")
    if day_gz[0] not in STEMS or day_gz[1] not in BRANCHES:
        raise ValueError(f"非法日柱干支: {day_gz}")
    if hour_gz[0] not in STEMS or hour_gz[1] not in BRANCHES:
        raise ValueError(f"非法时柱干支: {hour_gz}")

    def make_pillar(gz: str, day_stem: str, is_day: bool = False) -> Pillar:
        stem, branch = gz[0], gz[1]
        hidden = [
            HiddenStemItem(stem=s, element=e, ten_god=_ten_god(day_stem, s))
            for s, e in HIDDEN_STEMS[branch]
        ]
        tg = "日元" if is_day else _ten_god(day_stem, stem)
        return Pillar(
            stem=stem,
            branch=branch,
            ganzhi=gz,
            stem_element=STEM_ELEMENT[stem],
            ten_god=tg,
            hidden_stems=hidden,
            growth_stage=_growth_stage(day_stem, branch),
        )

    day_stem = day_gz[0]
    pillars = [
        make_pillar(year_gz, day_stem),
        make_pillar(month_gz, day_stem),
        make_pillar(day_gz, day_stem, is_day=True),
        make_pillar(hour_gz, day_stem),
    ]

    branches = [p.branch for p in pillars]
    element_counts = _count_elements(pillars)
    month_branch = month_gz[1]
    season_ss = season_strength_for_month(month_branch)

    chart = BaziChart(
        beijing_time="",
        true_solar_time="",
        lunar_year=year_gz,
        lunar_month="",
        lunar_day="",
        lunar_hour=hour_gz[1] + "时",
        pillars={
            "year": pillars[0],
            "month": pillars[1],
            "day": pillars[2],
            "hour": pillars[3],
        },
        zodiac=ZODIAC[_branch_index(year_gz[1])],
        element_counts=element_counts,
        season_strength=season_ss,
        relations=_detect_relations([p.stem for p in pillars], branches),
        day_master={
            "stem": day_stem,
            "element": STEM_ELEMENT[day_stem],
            "element_cn": ELEMENT_CN[STEM_ELEMENT[day_stem]],
            "strength": "平和",
            "growth_on_day": pillars[2].growth_stage,
        },
        gender=gender,
        confidence="classic",
    )
    dm_strength = calculate_day_master_strength(chart)
    chart.day_master["strength"] = dm_strength.level
    chart.day_master["strength_score"] = dm_strength.score
    return chart


def calculate_bazi(
    birth_datetime: datetime,
    longitude: float = 120.0,
    latitude: float = 30.0,
    gender: str = "male",
    use_true_solar: bool = True,
) -> BaziChart:
    beijing = birth_datetime.replace(tzinfo=None) if birth_datetime.tzinfo else birth_datetime
    true_solar = beijing_to_true_solar(beijing, longitude) if use_true_solar else beijing

    solar = Solar.fromYmdHms(
        true_solar.year, true_solar.month, true_solar.day,
        true_solar.hour, true_solar.minute, true_solar.second,
    )
    lunar = solar.getLunar()
    ec = lunar.getEightChar()

    year_gz = ec.getYear()
    month_gz = ec.getMonth()
    day_gz = ec.getDay()
    hour_gz = ec.getTime()

    def make_pillar(gz: str, day_stem: str, is_day: bool = False) -> Pillar:
        stem, branch = gz[0], gz[1]
        hidden = [
            HiddenStemItem(stem=s, element=e, ten_god=_ten_god(day_stem, s))
            for s, e in HIDDEN_STEMS[branch]
        ]
        tg = "日元" if is_day else _ten_god(day_stem, stem)
        return Pillar(
            stem=stem,
            branch=branch,
            ganzhi=gz,
            stem_element=STEM_ELEMENT[stem],
            ten_god=tg,
            hidden_stems=hidden,
            growth_stage=_growth_stage(day_stem, branch),
        )

    day_stem = day_gz[0]
    pillars = [
        make_pillar(year_gz, day_stem),
        make_pillar(month_gz, day_stem),
        make_pillar(day_gz, day_stem, is_day=True),
        make_pillar(hour_gz, day_stem),
    ]

    branches = [p.branch for p in pillars]
    element_counts = _count_elements(pillars)
    month_branch = month_gz[1]
    season_ss = season_strength_for_month(month_branch)

    chart = BaziChart(
        beijing_time=beijing.isoformat(),
        true_solar_time=true_solar.isoformat(),
        lunar_year=lunar.getYearInGanZhi(),
        lunar_month=lunar.getMonthInChinese(),
        lunar_day=lunar.getDayInChinese(),
        lunar_hour=lunar.getTimeZhi() + "时",
        pillars={
            "year": pillars[0],
            "month": pillars[1],
            "day": pillars[2],
            "hour": pillars[3],
        },
        zodiac=ZODIAC[_branch_index(year_gz[1])],
        element_counts=element_counts,
        season_strength=season_ss,
        relations=_detect_relations([p.stem for p in pillars], branches),
        day_master={
            "stem": day_stem,
            "element": STEM_ELEMENT[day_stem],
            "element_cn": ELEMENT_CN[STEM_ELEMENT[day_stem]],
            "strength": "平和",
            "growth_on_day": pillars[2].growth_stage,
        },
        gender=gender,
        confidence="full",
    )
    dm_strength = calculate_day_master_strength(chart)
    chart.day_master["strength"] = dm_strength.level
    chart.day_master["strength_score"] = dm_strength.score
    return chart


def get_nayin(ganzhi: str) -> tuple[str, str]:
    """返回干支的纳音五行（名称, 五行英文键）——《三命通会》."""
    return NAYIN.get(ganzhi, ("未知", "earth"))


def chart_nayin_summary(chart: BaziChart) -> str:
    """四柱纳音摘要."""
    parts = []
    for key, label in [("year", "年"), ("month", "月"), ("day", "日"), ("hour", "时")]:
        gz = chart.pillars[key].ganzhi
        name, el_en = get_nayin(gz)
        parts.append(f"{label}柱{name}")
    return "，".join(parts)
