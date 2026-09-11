"""生成对齐 quming.txt 风格的专业报告叙事."""

from __future__ import annotations

from datetime import datetime

from app.bazi.analysis import analyze_bazi_rules
from app.bazi.constants import ELEMENT_CN, GENERATES_EN
from app.bazi.season import season_label
from app.models.schemas import BaziAnalysis, BaziChart, BirthPlace, FateAnalysis, Xiyongshen

PILLAR_LABELS = ("年柱", "月柱", "日柱", "时柱")
PILLAR_KEYS = ("year", "month", "day", "hour")
GENDER_LABEL = {"male": "男", "female": "女"}
CONSTRUCT_LABEL = {"male": "乾造", "female": "坤造"}


def _stem_display(stem: str, element: str) -> str:
    return f"{stem}（{ELEMENT_CN[element]}）"


def build_birth_summary(chart: BaziChart, birth_place: BirthPlace) -> dict[str, str]:
    place = " ".join(x for x in [birth_place.province, birth_place.city, birth_place.district] if x)
    beijing = datetime.fromisoformat(chart.beijing_time)
    true_solar = datetime.fromisoformat(chart.true_solar_time)
    weekday = "一二三四五六日"[true_solar.weekday()]
    pillars = chart.pillars
    ganzhi = " ".join(pillars[k].ganzhi for k in PILLAR_KEYS)
    return {
        "性别": GENDER_LABEL.get(chart.gender, chart.gender),
        "出生地点": place or "未填写",
        "出生公历_北京": beijing.strftime("%Y年%m月%d日%H时%M分") + "(北京时间)",
        "出生公历_真太阳": true_solar.strftime("%Y年%m月%d日%H时%M分") + f"(真太阳时间)，星期{weekday}",
        "出生农历": f"{chart.lunar_year}年 {chart.lunar_month} {chart.lunar_day} {chart.lunar_hour}",
        "生辰八字": ganzhi,
        "生肖": chart.zodiac,
    }


def format_bazi_chart(chart: BaziChart) -> str:
    pillars = [chart.pillars[k] for k in PILLAR_KEYS]
    lines = [
        "【八字命盘】",
        CONSTRUCT_LABEL.get(chart.gender, "乾造"),
        "　　".join(PILLAR_LABELS),
        "　　".join(p.ten_god for p in pillars),
        "　　".join(_stem_display(p.stem, p.stem_element) for p in pillars),
        "　　".join(p.branch for p in pillars),
        "藏干",
    ]
    hidden_rows = []
    hidden_wx = []
    hidden_tg = []
    for p in pillars:
        stems = " ".join(h.stem for h in p.hidden_stems) or "—"
        wx = " ".join(ELEMENT_CN[h.element] for h in p.hidden_stems) or "—"
        tg = " ".join(h.ten_god for h in p.hidden_stems) or "—"
        hidden_rows.append(stems)
        hidden_wx.append(wx)
        hidden_tg.append(tg)
    lines.append("　　".join(hidden_rows))
    lines.append("　　".join(hidden_wx))
    lines.append("　　".join(hidden_tg))
    lines.append("地势")
    lines.append("　　".join(p.growth_stage for p in pillars))
    return "\n".join(lines)


def format_wuxing_analysis(chart: BaziChart, analysis: BaziAnalysis | None = None) -> str:
    if analysis is None:
        analysis = analyze_bazi_rules(chart)
    ec = chart.element_counts
    counts = f"{ec.fire}火  {ec.earth}土  {ec.metal}金  {ec.water}水  {ec.wood}木"
    missing = [ELEMENT_CN[k] for k, v in ec.model_dump().items() if v == 0]
    # 五行个数仅作参考，喜忌以旺衰格局为准（避免「缺啥补啥」误导）
    if missing:
        head = f"四柱五行不全（缺{'、'.join(missing)}）。个数仅供参考，旺衰喜忌以月令格局为准："
    else:
        head = "四柱五行俱全。个数仅供参考，旺衰喜忌以月令格局为准："
    ss = analysis.season_strength
    dm_cn = chart.day_master["element_cn"]
    month_branch = chart.pillars["month"].branch
    season_line = (
        f"季节的影响加成：{dm_cn}生于{season_label(month_branch)}，"
        f"土{ss.earth}、金{ss.metal}、火{ss.fire}、木{ss.wood}、水{ss.water}。"
    )
    stem_combine = "、".join(chart.relations.stem_combine) if chart.relations.stem_combine else "无"
    branch_notes = []
    if chart.relations.combine:
        branch_notes.append("、".join(chart.relations.combine))
    if chart.relations.three_combine:
        branch_notes.append("、".join(chart.relations.three_combine))
    if chart.relations.clash:
        branch_notes.append("、".join(chart.relations.clash) + "相冲")
    if chart.relations.harm:
        branch_notes.append("、".join(chart.relations.harm))
    if chart.relations.punishment:
        branch_notes.append("、".join(chart.relations.punishment))
    branch_text = "、".join(branch_notes) if branch_notes else "无明显冲合刑害"
    day = chart.pillars["day"]
    month = chart.pillars["month"]
    hour = chart.pillars["hour"]
    year = chart.pillars["year"]
    hidden_day = "、".join(f"{h.stem}{h.ten_god}" for h in day.hidden_stems)
    strength = analysis.strength
    lines = [
        "【五行分析】",
        head + "分列如下：",
        f"五行个数  {counts}。",
        "注意：分析五行不是简单看个数多少来确定哪个属性强旺的。还必须综合考虑四柱所处的地势衰旺；"
        "五行的旺、相、休、囚、死；以及天干地支之间的合化，和刑、冲、破、害的相互转化关系。",
        "对于这个命局：",
        f"此命局天干{stem_combine}。地支{branch_text}。",
        season_line,
        (
            f"日元{strength.level}（旺衰分{strength.score}）。"
            f"日柱天干本元是{dm_cn}（民间所谓「{dm_cn}命」），"
            f"{day.ganzhi}坐[{day.growth_stage}]位，座下{hidden_day}。"
        ),
        (
            f"年柱{year.stem}{year.ten_god}，坐[{year.growth_stage}]位；"
            f"月柱{month.stem}{month.ten_god}，坐[{month.growth_stage}]位；"
            f"时柱{hour.stem}{hour.ten_god}，坐[{hour.growth_stage}]位。"
        ),
    ]
    return "\n".join(lines)


def infer_xiyongshen(chart: BaziChart, analysis: BaziAnalysis | None = None) -> Xiyongshen:
    from app.bazi.xiyongshen import infer_xiyongshen as _infer
    return _infer(chart, analysis)


def build_fate_analysis(chart: BaziChart, analysis: BaziAnalysis | None = None) -> FateAnalysis:
    if analysis is None:
        analysis = analyze_bazi_rules(chart)
    xy = analysis.xiyongshen
    dm = chart.day_master["element_cn"]
    month_branch = chart.pillars["month"].branch
    strength = analysis.strength
    pattern = analysis.pattern
    tune = analysis.tune

    clash_note = ""
    if chart.relations.clash:
        clash_note = f"命局地支见{'、'.join(chart.relations.clash)}相冲，取名字时宜求平衡调和，不宜再加重冲激之象。"

    # 次喜元素中能生助主喜用者，动态生成生克推论（如 木能生火）
    rev = {v: k for k, v in ELEMENT_CN.items()}
    sheng_notes = []
    for sec in xy.secondary:
        for prim in xy.primary:
            if GENERATES_EN.get(rev[sec]) == rev[prim]:
                sheng_notes.append(f"{sec}能生{prim}")
    sheng_text = ""
    if sheng_notes:
        sheng_text = f"另外，{'、'.join(sheng_notes)}，用这些属性的字也可起到间接优化命局的作用。"
    sec_text = f"次喜{'、'.join(xy.secondary)}。" if xy.secondary else ""

    tune_text = tune.summary
    pattern_text = ""
    if pattern.formed:
        pattern_text = f"格局判定：{pattern.name}。" + "；".join(pattern.reasoning)
    elif pattern.name != "无格":
        pattern_text = f"格局倾向：{pattern.name}。"

    strength_text = f"日主{dm}{strength.level}（得分{strength.score}），{'得令' if strength.de_ling else '失令'}。"

    level_text = ""
    if analysis.level:
        level_text = analysis.level.verdict

    shensha_text = ""
    if analysis.shensha and analysis.shensha.items:
        shensha_text = analysis.shensha.summary
        wen = [i for i in analysis.shensha.items if i.name == "文昌贵人"]
        if wen:
            shensha_text += "。带文昌贵人，取名宜用文雅向学之字，益学业文途"

    dayun_text = ""
    if chart.beijing_time:
        from app.bazi.dayun import compute_dayun, dayun_xiyong_note
        dayun = compute_dayun(chart)
        if dayun:
            dayun_text = dayun_xiyong_note(chart, analysis, dayun)

    professional_parts = [
        format_wuxing_analysis(chart, analysis),
        strength_text,
        tune_text,
        pattern_text,
        level_text,
        shensha_text,
        dayun_text,
        clash_note,
        (
            f"综合来看，本命局喜用{'、'.join(xy.primary)}，优先考虑{xy.primary[0]}属性的名字；"
            f"{sheng_text}{sec_text}"
        ),
    ]
    vernacular = (
        f"四柱五行{'俱全' if all(getattr(chart.element_counts, k) > 0 for k in ('wood','fire','earth','metal','water')) else '不全'}，"
        f"喜忌以旺衰格局为准。"
        f"日主{strength.level}。"
        + (f"命局气象：{'、'.join(analysis.level.tendencies)}。" if analysis.level and analysis.level.tendencies else "")
        + (f"注意：{'；'.join(analysis.level.diseases)}。" if analysis.level and analysis.level.diseases else "")
        + f"建议优先考虑含{xy.primary[0]}属性的名字"
        + (f"，其次考虑含{'、'.join(xy.secondary)}属性的名字" if xy.secondary else "")
        + "，也可以结合家庭偏好与音韵美感综合选定。"
    )
    chain = list(analysis.reasoning_chain)
    return FateAnalysis(
        professional="\n".join(p for p in professional_parts if p),
        vernacular=vernacular,
        xiyongshen=xy,
        reasoning_chain=chain,
    )


def build_naming_advice(fate: FateAnalysis) -> str:
    xy = fate.xiyongshen
    return (
        "【取名建议】\n"
        "上面是专业术语和分析过程，下面写出通俗易懂的结论：\n"
        f"{fate.vernacular}\n"
        f"严格喜用神模式下，名字用字宜优先{xy.primary[0]}，其次{'/'.join(xy.secondary) or '视具体用字而定'}；"
        "每个备选名均标注典籍出处、白话释义与五行属性，供您斟酌选用。"
    )
