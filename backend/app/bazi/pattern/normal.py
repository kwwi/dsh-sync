"""八正格判定."""

from __future__ import annotations

from app.bazi.constants import CONTROLS_EN, ELEMENT_CN, GENERATES_EN
from app.bazi.pattern.base import month_main_ten_god
from app.models.schemas import BaziChart, DayMasterStrength, PatternResult

_PATTERN_MAP = {
    "正官": "正官格",
    "七杀": "七杀格",
    "正财": "正财格",
    "偏财": "偏财格",
    "正印": "正印格",
    "偏印": "偏印格",
    "食神": "食神格",
    "伤官": "伤官格",
}


def detect_normal_pattern(chart: BaziChart, strength: DayMasterStrength) -> PatternResult:
    """八正格判定（《子平真诠》取格法）.

    取格：月令藏干按本气→中气→余气序，最先透出于年/月/时干者取为格局；
          皆不透则取月令本气。
    成败：用神有破为败——官格忌伤官破官、官杀混杂；杀格忌混官；
          食神格忌枭神夺食；伤官格忌伤官见官；印格忌财星坏印。
    """
    month_pillar = chart.pillars["month"]
    month_hidden_tgs = [hs.ten_god for hs in month_pillar.hidden_stems]
    exposed_tgs = [chart.pillars[key].ten_god for key in ("year", "month", "hour")]

    chosen = next((tg for tg in month_hidden_tgs if tg in exposed_tgs), month_hidden_tgs[0])
    pattern_name = _PATTERN_MAP.get(chosen, "无格")
    if pattern_name == "无格":
        return PatternResult(
            name="无格", formed=False, confidence="low",
            reasoning=[f"月令{month_pillar.branch}本气非八正格"],
        )

    broke: list[str] = []
    if chosen == "正官":
        if "伤官" in exposed_tgs:
            broke.append("伤官透干破官")
        if "七杀" in exposed_tgs:
            broke.append("官杀混杂")
    elif chosen == "七杀" and "正官" in exposed_tgs:
        broke.append("官杀混杂")
    elif chosen == "食神" and "偏印" in exposed_tgs:
        broke.append("枭神夺食")
    elif chosen == "伤官" and ("正官" in exposed_tgs or "七杀" in exposed_tgs):
        broke.append("伤官见官")
    elif chosen in ("正印", "偏印") and "正财" in exposed_tgs:
        broke.append("财星坏印")

    formed = not broke
    if formed:
        # 相神检查：辅助用神透干则格局更深（《子平真诠》）
        xiangshen: list[str] = []
        if chosen == "正官":
            if "正财" in exposed_tgs or "偏财" in exposed_tgs:
                xiangshen.append("财生官")
            if "正印" in exposed_tgs or "偏印" in exposed_tgs:
                xiangshen.append("官印相生")
        elif chosen == "七杀":
            if "食神" in exposed_tgs or "伤官" in exposed_tgs:
                xiangshen.append("食伤制杀")
            if "正印" in exposed_tgs or "偏印" in exposed_tgs:
                xiangshen.append("印化杀")
        elif chosen in ("正财", "偏财"):
            if "食神" in exposed_tgs or "伤官" in exposed_tgs:
                xiangshen.append("食伤生财")
            if "正官" in exposed_tgs or "七杀" in exposed_tgs:
                xiangshen.append("官护财")
        elif chosen in ("正印", "偏印"):
            if "正官" in exposed_tgs or "七杀" in exposed_tgs:
                xiangshen.append("官杀生印")
            if "比肩" in exposed_tgs or "劫财" in exposed_tgs:
                xiangshen.append("比劫泄印")
        elif chosen in ("食神", "伤官"):
            if "正财" in exposed_tgs or "偏财" in exposed_tgs:
                xiangshen.append("食伤生财")
            if chosen == "伤官" and ("正印" in exposed_tgs or "偏印" in exposed_tgs):
                xiangshen.append("伤官佩印")

        confidence = "high" if xiangshen else "medium"
        reasoning = [
            f"月令{month_pillar.branch}藏{'/'.join(month_hidden_tgs)}，透{chosen}取为{pattern_name}",
            "无破格之病（成格）" + (f"，相神{'/'.join(xiangshen)}" if xiangshen else ""),
        ]
    else:
        confidence = "low"
        pattern_name = f"{pattern_name}（未成）"
        reasoning = [
            f"月令{month_pillar.branch}取{_PATTERN_MAP[chosen]}",
            "；".join(broke),
        ]

    return PatternResult(
        name=pattern_name,
        formed=formed,
        confidence=confidence,
        reasoning=reasoning,
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


def pattern_xiyongshen(
    pattern_name: str,
    strength: DayMasterStrength,
    dm_en: str,
) -> tuple[list[str], list[str], list[str]]:
    """格局用神：根据日主五行和格局类型动态推导喜用神.

    Args:
        pattern_name: 格局名称
        strength: 日主强弱
        dm_en: 日主五行（英文键：wood/fire/earth/metal/water）

    Returns:
        (primary, secondary, avoid) 喜用神五行中文列表
    """
    base = pattern_name.replace("（未成）", "")
    weak = strength.level in ("偏弱", "极弱", "平和")
    strong = strength.level in ("偏强", "极强")

    bi = dm_en  # 比劫 = 同我
    yin = _yinxing(dm_en)  # 印星 = 生我
    shi = GENERATES_EN[dm_en]  # 食伤 = 我生
    cai = CONTROLS_EN[dm_en]  # 财星 = 我克
    sha = _guansha(dm_en)  # 官杀 = 克我

    bi_cn = ELEMENT_CN[bi]
    yin_cn = ELEMENT_CN[yin]
    shi_cn = ELEMENT_CN[shi]
    cai_cn = ELEMENT_CN[cai]
    sha_cn = ELEMENT_CN[sha]

    if "正官" in base:
        # 正官格（真诠）：忌伤官破官、忌财坏印
        if weak:
            return ([yin_cn, bi_cn], [], [shi_cn, cai_cn])
        else:
            return ([cai_cn], [], [shi_cn])
    if "七杀" in base:
        # 七杀格：身弱用印化杀+比劫助身（食伤制杀次之）；身强用财滋杀+食伤制杀
        if weak:
            return ([yin_cn, bi_cn], [shi_cn], [cai_cn])
        else:
            return ([cai_cn, shi_cn], [], [yin_cn, bi_cn])
    if "财" in base:
        # 财格：身弱用比劫制财+印星生身；身强用食伤生财+官杀护财
        if weak:
            return ([bi_cn, yin_cn], [], [shi_cn, sha_cn])
        else:
            return ([shi_cn, sha_cn], [], [bi_cn, yin_cn])
    if "印" in base:
        # 印格：身弱用比劫+官杀生印；身强用财破印+食伤泄身
        if weak:
            return ([bi_cn, sha_cn], [], [cai_cn])
        else:
            return ([cai_cn, shi_cn], [], [yin_cn, bi_cn])
    if "食" in base or "伤" in base:
        # 食伤格：身弱用印制食伤+比劫助身；身强用财泄食伤+比劫生食伤
        if weak:
            return ([yin_cn, bi_cn], [], [cai_cn])
        else:
            return ([cai_cn, shi_cn], [], [yin_cn])
    return ([], [], [])
