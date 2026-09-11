"""神煞查表（渊海子平/三命通会）.

文昌、天乙、桃花、驿马、华盖、将星、天德/月德、空亡。
以日干/日支为体，查年月日时地支（或天干）落位。
"""

from __future__ import annotations

from app.models.schemas import BaziChart, ShenshaItem, ShenshaResult

_WENCHANG = {
    "甲": "巳", "乙": "午", "丙": "申", "丁": "酉",
    "戊": "申", "己": "酉", "庚": "亥", "辛": "子", "壬": "寅", "癸": "卯",
}

_TIANYI = {
    "甲": ("丑", "未"), "戊": ("丑", "未"), "庚": ("丑", "未"),
    "乙": ("子", "申"), "己": ("子", "申"),
    "丙": ("亥", "酉"), "丁": ("亥", "酉"),
    "壬": ("卯", "巳"), "癸": ("卯", "巳"),
    "辛": ("寅", "午"),
}

_SANHE = {
    "申子辰": ("酉", "寅", "辰", "子"),  # 桃花/驿马/华盖/将星
    "寅午戌": ("卯", "申", "戌", "午"),
    "巳酉丑": ("午", "亥", "丑", "酉"),
    "亥卯未": ("子", "巳", "未", "卯"),
}

_YUEDE = {"寅午戌": "丙", "申子辰": "壬", "巳酉丑": "庚", "亥卯未": "甲"}

_TIANDE = {
    "寅": "丁", "卯": "申", "辰": "壬", "巳": "辛", "午": "亥", "未": "甲",
    "申": "癸", "酉": "寅", "戌": "丙", "亥": "乙", "子": "巳", "丑": "庚",
}

_XUNKONG = {
    "甲子": ("戌", "亥"), "甲戌": ("申", "酉"), "甲申": ("午", "未"),
    "甲午": ("辰", "巳"), "甲辰": ("寅", "卯"), "甲寅": ("子", "丑"),
}

# 十干禄位（《渊海子平》）
_LUSHEN = {
    "甲": "寅", "乙": "卯", "丙": "巳", "丁": "午",
    "戊": "巳", "己": "午", "庚": "申", "辛": "酉", "壬": "亥", "癸": "子",
}

# 羊刃（十干阳刃，阴干无刃——《渊海子平》）
_YANGREN = {
    "甲": "卯", "丙": "午", "戊": "午", "庚": "酉", "壬": "子",
}

# 金舆（日干查地支——《三命通会》）
_JINYU = {
    "甲": "辰", "乙": "巳", "丙": "未", "丁": "申",
    "戊": "未", "己": "申", "庚": "戌", "辛": "亥", "壬": "丑", "癸": "寅",
}

_PILLAR_CN = {"year": "年", "month": "月", "day": "日", "hour": "时"}


def detect_shensha(chart: BaziChart) -> ShenshaResult:
    day_stem = chart.day_master["stem"]
    year_branch = chart.pillars["year"].branch
    day_branch = chart.pillars["day"].branch
    month_branch = chart.pillars["month"].branch
    stems = {k: chart.pillars[k].stem for k in ("year", "month", "hour")}

    items: list[ShenshaItem] = []

    def _find(zhis: tuple[str, ...], name: str, note: str) -> None:
        for key, p in chart.pillars.items():
            if p.branch in zhis:
                items.append(ShenshaItem(name=name, pillar=_PILLAR_CN[key], note=note))

    # 文昌（日干）
    if day_stem in _WENCHANG:
        _find((_WENCHANG[day_stem],), "文昌贵人", "利学业文书、才思敏捷")
    # 天乙（日干）
    if day_stem in _TIANYI:
        _find(_TIANYI[day_stem], "天乙贵人", "逢凶化吉，贵人扶持")
    # 三合系（以年支或日支同局取）
    for group, (tao, yima, huagai, jiang) in _SANHE.items():
        if year_branch in group or day_branch in group:
            _find((tao,), "桃花（咸池）", "人缘佳、情调审美敏锐")
            _find((yima,), "驿马", "主动变迁移、奔波远方")
            _find((huagai,), "华盖", "孤高才艺、宗教玄学缘")
            _find((jiang,), "将星", "掌权领众之象")
            break
    # 月德/天德（月支查天干）
    if month_branch in _YUEDE:
        if _YUEDE[month_branch] in stems.values():
            items.append(ShenshaItem(name="月德贵人", pillar="月", note="福泽深厚，解厄化煞"))
    if month_branch in _TIANDE:
        if _TIANDE[month_branch] in stems.values():
            items.append(ShenshaItem(name="天德贵人", pillar="月", note="心地仁厚，逢难有救"))
    # 空亡（日柱旬空）：按日柱干支在六十甲子中的位置确定旬空
    from app.bazi.constants import STEMS, BRANCHES
    # 生成六十甲子表并定位日柱所在的旬
    _JIAZI60 = [STEMS[i % 10] + BRANCHES[i % 12] for i in range(60)]
    day_gz = chart.pillars["day"].ganzhi
    try:
        gz_idx = _JIAZI60.index(day_gz)
        xun_keys = ("甲子", "甲戌", "甲申", "甲午", "甲辰", "甲寅")
        xun_key = xun_keys[gz_idx // 10]
    except (ValueError, IndexError):
        xun_key = None
    if xun_key and xun_key in _XUNKONG:
        _find(_XUNKONG[xun_key], "空亡", "所临之宫主虚而不实，宜填实化解")

    # 禄神（日干查地支）
    if day_stem in _LUSHEN:
        _find((_LUSHEN[day_stem],), "禄神", "福禄之根，身强得禄为福，身弱有禄支撑")

    # 羊刃（日干查地支，仅阳干）
    if day_stem in _YANGREN:
        _find((_YANGREN[day_stem],), "羊刃", "刚强锐气，身强刃为劫，身弱刃助身")

    # 金舆（日干查地支）
    if day_stem in _JINYU:
        _find((_JINYU[day_stem],), "金舆", "贵人车马，出行安稳、得人扶持")

    summary = "神煞："
    summary += "、".join(f"{i.name}@{i.pillar}" for i in items) if items else "无明显神煞（以格局喜忌为准）"
    return ShenshaResult(items=items, summary=summary)
