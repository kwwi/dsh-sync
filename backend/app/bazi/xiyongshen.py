"""喜用神合成：调候 > 格局 > 扶抑 > 通关."""

from __future__ import annotations

from app.bazi.constants import CONTROLS_EN, ELEMENT_CN, GENERATES_EN
from app.bazi.pattern.normal import detect_normal_pattern, pattern_xiyongshen
from app.bazi.pattern.special import detect_special_pattern, special_pattern_xiyongshen
from app.bazi.tune import analyze_tune, needs_tune_priority
from app.models.schemas import BaziAnalysis, BaziChart, DayMasterStrength, PatternResult, Xiyongshen


def detect_pattern(chart: BaziChart, strength: DayMasterStrength) -> PatternResult:
    special = detect_special_pattern(chart, strength)
    if special and special.formed:
        return special
    normal = detect_normal_pattern(chart, strength)
    if normal.formed:
        return normal
    if special:
        return special
    return normal


def _fuyi_xiyongshen(chart: BaziChart, strength: DayMasterStrength) -> Xiyongshen:
    dm_cn = chart.day_master["element_cn"]
    rev = {v: k for k, v in ELEMENT_CN.items()}
    dm_en = rev[dm_cn]

    if strength.level == "平和":
        # 中和命局不宜强行扶抑，以顺势调候为主
        # 喜用取食伤泄秀 + 财星流通，忌过强克泄
        shi = ELEMENT_CN[GENERATES_EN[dm_en]]
        cai = ELEMENT_CN[CONTROLS_EN[dm_en]]
        yin = ELEMENT_CN.get(_support_element(dm_en), "木")
        return Xiyongshen(primary=[shi], secondary=[cai], avoid=[yin])

    if strength.level in ("偏强", "极强"):
        primary = [ELEMENT_CN[e] for e in _drain_elements(dm_en)]
        secondary = []
        avoid = [dm_cn, ELEMENT_CN.get(_support_element(dm_en), "木")]
    else:
        primary = [dm_cn, ELEMENT_CN.get(_support_element(dm_en), "木")]
        sec_el = ELEMENT_CN.get(_support_element(dm_en), "木")
        secondary = [sec_el] if sec_el != dm_cn else []
        avoid = [ELEMENT_CN[e] for e in _drain_elements(dm_en)]

    primary = list(dict.fromkeys(primary))
    secondary = [s for s in secondary if s not in primary]
    avoid = [a for a in avoid if a not in primary and a not in secondary]
    return Xiyongshen(primary=primary[:2], secondary=secondary[:2], avoid=avoid[:2])


def _support_element(el_en: str) -> str:
    for k, v in {"wood": "water", "fire": "wood", "earth": "fire", "metal": "earth", "water": "metal"}.items():
        if k == el_en:
            return v
    return "water"


def _drain_elements(el_en: str) -> list[str]:
    """日主泄耗元素：食伤(我生)、财星(我克)、官杀(克我)。"""
    from app.bazi.constants import GENERATES_EN, CONTROLS_EN
    out = [GENERATES_EN[el_en], CONTROLS_EN[el_en]]
    # 官杀：遍历克我者
    for other, controlled in CONTROLS_EN.items():
        if controlled == el_en:
            out.append(other)
    return out


def _tongguan_secondary(chart: BaziChart) -> list[str]:
    """地支冲战取通关五行.

    通关原则：以能同时「泄一神而生一神」的中间五行调停相冲。
    金木相冲（寅申、卯酉）→ 水；水火相冲（子午、巳亥）→ 木；土土相冲（辰戌、丑未）→ 金。
    """
    clashes = chart.relations.clash
    secondary: list[str] = []
    for clash in clashes:
        if "寅" in clash and "申" in clash:
            secondary.append("水")
        elif "子" in clash and "午" in clash:
            secondary.append("木")
        elif "卯" in clash and "酉" in clash:
            secondary.append("水")
        elif "辰" in clash and "戌" in clash:
            secondary.append("金")
        elif "丑" in clash and "未" in clash:
            secondary.append("金")
        elif "巳" in clash and "亥" in clash:
            secondary.append("木")
    return list(dict.fromkeys(secondary))


def _add_tongguan(xy: Xiyongshen, tg: list[str], chain: list[str]) -> None:
    """添加通关五行到喜用神，排除与主喜用或忌神冲突的元素."""
    conflict = set(xy.primary) | set(xy.avoid)
    valid = [t for t in tg if t not in conflict]
    if valid:
        xy.secondary = list(dict.fromkeys([*xy.secondary, *valid]))[:3]
        chain.append(f"通关：{'/'.join(valid)}")
    rejected = [t for t in tg if t in conflict]
    if rejected:
        chain.append(f"通关{'/'.join(rejected)}与喜忌冲突，已排除")


_SPECIAL_PATTERN_NAMES = ("化", "从", "曲直格", "炎上格", "稼穑格", "从革格", "润下格")


def _is_special_pattern(name: str) -> bool:
    return name.startswith("化") or "从" in name or name in _SPECIAL_PATTERN_NAMES


def synthesize_xiyongshen(
    chart: BaziChart,
    strength: DayMasterStrength,
    tune,
    pattern: PatternResult,
) -> tuple[Xiyongshen, list[str]]:
    chain: list[str] = []
    dm_cn = chart.day_master["element_cn"]

    # 特殊格局（从/化/专旺）优先于调候：从势论命，不按月令寒暖套调候
    if pattern.formed and _is_special_pattern(pattern.name):
        p, s, a = special_pattern_xiyongshen(pattern, dm_cn)
        if p:
            xy = Xiyongshen(primary=p[:2], secondary=s[:2], avoid=a[:2])
            chain.append(f"特殊格局{pattern.name}")
            tg = _tongguan_secondary(chart)
            if tg:
                _add_tongguan(xy, tg, chain)
            return xy, chain

    if needs_tune_priority(chart) and tune.primary:
        # 清理调候表中 secondary 与 avoid 的矛盾（如丙生寅月 secondary=水 avoid=水）
        sec_clean = [s for s in tune.secondary if s not in (tune.avoid or [])]
        avoid_clean = [a for a in (tune.avoid or []) if a not in tune.primary]
        xy = Xiyongshen(
            primary=tune.primary[:2],
            secondary=sec_clean[:2],
            avoid=avoid_clean[:2],
        )
        chain.append(f"调候优先：{'/'.join(tune.primary)}")
        # 调候与正格喜忌交叉校验：调候用神=格局忌神 或 格局用神=调候忌神 属硬冲突，
        # 以格局为先（《子平真诠》格局用神为本），避免把格局忌神当作喜用推荐
        if pattern.formed and not _is_special_pattern(pattern.name):
            p, s, a = pattern_xiyongshen(pattern.name, strength, chart.day_master["element"])
            if p:
                conflict = (set(xy.primary) & set(a)) or (set(p) & set(xy.avoid))
                if conflict:
                    xy = Xiyongshen(primary=p[:2], secondary=s[:2], avoid=a[:2])
                    chain.append(f"调候与{pattern.name}喜忌冲突，以格局为先")
        tg = _tongguan_secondary(chart)
        if tg:
            _add_tongguan(xy, tg, chain)
        return xy, chain

    if pattern.formed and not _is_special_pattern(pattern.name):
        p, s, a = pattern_xiyongshen(pattern.name, strength, chart.day_master["element"])
        chain.append(f"格局{pattern.name}")
        if p:
            xy = Xiyongshen(primary=p[:2], secondary=s[:2], avoid=a[:2])
            tg = _tongguan_secondary(chart)
            if tg:
                _add_tongguan(xy, tg, chain)
            return xy, chain

    xy = _fuyi_xiyongshen(chart, strength)
    chain.append(f"扶抑法：日主{strength.level}")
    tg = _tongguan_secondary(chart)
    if tg:
        _add_tongguan(xy, tg, chain)
    return xy, chain


def infer_xiyongshen(chart: BaziChart, analysis: BaziAnalysis | None = None) -> Xiyongshen:
    if analysis:
        return analysis.xiyongshen
    from app.bazi.analysis import analyze_bazi_rules
    return analyze_bazi_rules(chart).xiyongshen
