"""滴天髓格局层次评估：贵/富/才/学倾向 + 病药（刑冲破局与通关解法）."""

from __future__ import annotations

from app.bazi.constants import CONTROLS_EN, GENERATES_EN
from app.bazi.pattern.base import count_element_occurrences
from app.bazi.season import is_de_ling
from app.models.schemas import BaziChart, DayMasterStrength, LevelResult, PatternResult

_CRASH_CURE = {
    ("寅", "申"): ("水", "寅申相冲，财印交战，心绪多动、事业多变"),
    ("卯", "酉"): ("水", "卯酉相冲，木金交战，易生是非变动"),
    ("子", "午"): ("木", "子午相冲，水火交战，性情急躁、劳心耗神"),
    ("巳", "亥"): ("木", "巳亥相冲，财官交战，行踪不定、奔波劳碌"),
    ("辰", "戌"): ("金", "辰戌相冲，土库相激，家宅事业多变动"),
    ("丑", "未"): ("金", "丑未相冲，土库相激，多劳碌奔波"),
}

_HARM_NOTE = "地支相害，人际暗耗、贵人缘略减"
_PUNISH_NOTE = "地支刑冲并见，多是非刑伤，宜以和为贵"


def _guansha_en(dm_en: str) -> str:
    for other, controlled in CONTROLS_EN.items():
        if controlled == dm_en:
            return other
    return "water"


def _yin_en(dm_en: str) -> str:
    for k, v in GENERATES_EN.items():
        if v == dm_en:
            return k
    return "water"


def assess_level(
    chart: BaziChart,
    strength: DayMasterStrength,
    pattern: PatternResult,
    avoid: list[str] | None = None,
) -> LevelResult:
    """按滴天髓判层次：官星有理会为贵、财气通门户为富、食伤泄秀为才、印绶得用为学.

    avoid: 忌神五行（药与忌神冲突时弃药，避免「以忌为药」）.
    """
    avoid = avoid or []
    dm_en = chart.day_master["element"]
    guansha_el = _guansha_en(dm_en)
    yin_el = _yin_en(dm_en)
    cai_el = CONTROLS_EN[dm_en]
    shi_el = GENERATES_EN[dm_en]

    exposed_tgs = [chart.pillars[key].ten_god for key in ("year", "month", "hour")]
    branch = chart.pillars["month"].branch
    strong = strength.level in ("偏强", "极强")

    guansha_n = count_element_occurrences(chart, guansha_el)
    yin_n = count_element_occurrences(chart, yin_el)
    cai_n = count_element_occurrences(chart, cai_el)

    tendencies: list[str] = []
    if pattern.name.startswith("从"):
        special_tg = {
            "从儿格": "才气（从儿泄秀，技艺才华）",
            "从财格": "富气（从财，财气通门户）",
            "从杀格": "贵气（从杀，杀势凌厉）",
            "从势格": "顺势之气（从势而行，顺势而为）",
        }.get(pattern.name, "")
        if special_tg:
            tendencies.append(special_tg)
    elif pattern.name.startswith("化"):
        tendencies.append("化气（合化得真，一气专成）")
    elif pattern.name in ("曲直格", "炎上格", "稼穑格", "从革格", "润下格"):
        tendencies.append("纯气（专旺一行，气势专一）")

    if not tendencies:
        if any(tg in ("正官", "七杀") for tg in exposed_tgs) and guansha_n >= 3 and yin_n >= 2:
            tendencies.append("贵气（官印相生，宜体制名望之路）")
        elif any(tg in ("正官", "七杀") for tg in exposed_tgs) and guansha_n >= 3:
            tendencies.append("贵气（官星透干得势）")
        if cai_n >= 3 and (is_de_ling(cai_el, branch) or strong):
            tendencies.append("富气（财气通门户，宜财路经营）")
        if any(tg in ("食神", "伤官") for tg in exposed_tgs):
            tendencies.append("才气（食伤泄秀，技艺才华）")
        if any(tg in ("正印", "偏印") for tg in exposed_tgs) or yin_n >= 3:
            tendencies.append("学养（印绶得用，文墨学问）")

    diseases: list[str] = []
    cures: list[str] = []
    for clash in chart.relations.clash:
        pair = tuple(sorted((clash[0], clash[1])))
        if pair in _CRASH_CURE:
            cure, note = _CRASH_CURE[pair]
            diseases.append(note)
            if cure not in cures and cure not in avoid:
                cures.append(cure)
    if chart.relations.harm and not diseases:
        diseases.append(_HARM_NOTE)
    if chart.relations.punishment and len(chart.relations.clash) >= 2:
        diseases.append(_PUNISH_NOTE)

    if not tendencies:
        tendencies.append("中平之造（以稳求成）")

    parts = []
    parts.append("命局气象：")
    parts.append("、".join(tendencies))
    if diseases:
        parts.append(f"病：{'；'.join(diseases)}")
    if cures:
        parts.append(f"药：宜以{'、'.join(cures)}五行调停解冲")
    verdict = "".join(parts)

    return LevelResult(
        tendencies=tendencies,
        diseases=diseases,
        cures=cures,
        verdict=verdict,
    )
