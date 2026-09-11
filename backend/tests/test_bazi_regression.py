"""命理推理缺陷修复的回归测试.

覆盖（评审结论对应的修复）：
1. 大运顺逆方向：立春~春节窗口期必须以八字年柱（立春为岁首）定阴阳
2. 起运岁数：节气时刻保留时分秒，生于「节」当日时刻前不得误计
3. 纳音表：壬辰/癸巳为「长流水」
4. 三刑：二字相见即论相刑（恃势/无恩之刑），三字全称三刑
5. 天干五合：合而不化为常态，仅化神得月令支持且无破时论「合化」
6. 调候表：全表 primary/secondary/avoid 两两不得重叠
7. 化气格：日主偏强/极强时不得从化（《子平真诠》日主孤弱）
8. 调候与正格喜忌硬冲突时以格局为先
9. 大运/流年喜忌判定含地支本气
"""

from __future__ import annotations

from datetime import datetime

from app.bazi.analysis import analyze_bazi_rules
from app.bazi.dayun import _compute_dayun
from app.bazi.engine import build_chart_from_pillars, calculate_bazi, get_nayin
from app.bazi.tune import load_qiongtong_table


# ── 1. 大运顺逆方向：立春~春节窗口 ──


def test_dayun_direction_lichun_spring_festival_window():
    """2024-02-05（立春 2/4 后、春节 2/10 前）：八字年柱甲辰（阳年）.

    阳年男 → 顺排；阳年女 → 逆排。（旧实现取农历年干癸 → 方向颠倒）
    """
    birth = datetime(2024, 2, 5, 10, 0)
    chart = calculate_bazi(birth, gender="male")
    assert chart.pillars["year"].ganzhi == "甲辰"
    assert _compute_dayun(birth, "male").direction == "顺排"
    assert _compute_dayun(birth, "female").direction == "逆排"


def test_dayun_direction_before_lichun():
    """2024-01-15（立春前）：八字年柱癸卯（阴年） → 男逆排、女顺排."""
    birth = datetime(2024, 1, 15, 10, 0)
    chart = calculate_bazi(birth, gender="male")
    assert chart.pillars["year"].ganzhi == "癸卯"
    assert _compute_dayun(birth, "male").direction == "逆排"
    assert _compute_dayun(birth, "female").direction == "顺排"


def test_compute_dayun_uses_chart_year_stem():
    """compute_dayun 以命盘年柱定方向，与 _compute_dayun 直调口径一致."""
    chart = calculate_bazi(datetime(2024, 2, 5, 10, 0), gender="male")
    from app.bazi.dayun import compute_dayun

    r = compute_dayun(chart)
    assert r.direction == "顺排"


# ── 2. 起运岁数：节时刻精度 ──


def test_dayun_start_age_on_jie_day_before_jie_time():
    """2024-02-04 10:00（立春日，立春时刻 16:27 前，年柱癸卯 → 男逆排）.

    应数至上一节小寒（1/6）→ 约 29 天 → 约 9.7 岁起运。
    旧实现把立春按 0 点计入 → 0.14 岁（误差近 10 年）。
    """
    birth = datetime(2024, 2, 4, 10, 0)
    r = _compute_dayun(birth, "male")
    assert r.direction == "逆排"
    assert 8.5 <= r.start_age <= 11.0, r.start_age


def test_dayun_start_age_precise_after_jie_time():
    """2024-02-04 18:00（立春时刻后，年柱甲辰 → 男顺排）数至惊蛰 3/5 → 约 9.9 岁."""
    birth = datetime(2024, 2, 4, 18, 0)
    r = _compute_dayun(birth, "male")
    assert r.direction == "顺排"
    assert 9.0 <= r.start_age <= 11.0, r.start_age


# ── 3. 纳音表 ──


def test_nayin_changliushui():
    """壬辰/癸巳 纳音为「长流水」（原误作「流年水」）."""
    assert get_nayin("壬辰") == ("长流水", "water")
    assert get_nayin("癸巳") == ("长流水", "water")


def test_nayin_other_entries_unchanged():
    assert get_nayin("甲子") == ("海中金", "metal")
    assert get_nayin("丙寅") == ("炉中火", "fire")
    assert get_nayin("壬戌") == ("大海水", "water")


# ── 4. 三刑：二字相见即刑 ──


def test_punishment_two_of_three():
    """寅巳相见（无申）→ 恃势之刑；丑戌相见（无未）→ 无恩之刑."""
    c = build_chart_from_pillars("丙寅", "癸巳", "甲子", "乙巳")
    assert "寅巳相刑" in c.relations.punishment

    c2 = build_chart_from_pillars("辛丑", "己丑", "庚戌", "丁丑")
    assert "丑戌相刑" in c2.relations.punishment


def test_punishment_full_triple():
    """寅巳申三字俱全 → 寅巳申三刑."""
    c = build_chart_from_pillars("丙寅", "丙申", "甲子", "乙巳")
    assert "寅巳申三刑" in c.relations.punishment


# ── 5. 天干五合：合而不化 ──


def test_stem_combine_no_hua_when_month_unsupported():
    """卯月（木旺、土死）：甲己合不得论化 → 仅报「甲己合」."""
    c = build_chart_from_pillars("甲寅", "己卯", "甲辰", "乙亥")
    assert c.relations.stem_combine == ["甲己合"]


def test_stem_combine_hua_when_supported():
    """子月（水生木）：丁壬合化木（无金克化神） → 报「丁壬合化木」."""
    c = build_chart_from_pillars("丁卯", "壬子", "丙辰", "丁酉")
    assert "丁壬合化木" in c.relations.stem_combine


def test_stem_combine_no_hua_with_killer_stem():
    """子月丁壬合但庚金透干克化神（木）→ 不得论化."""
    c = build_chart_from_pillars("庚寅", "壬子", "丙辰", "丁酉")
    assert "丁壬合" in c.relations.stem_combine
    assert all("化" not in s for s in c.relations.stem_combine)


# ── 6. 调候表全表一致性 ──


def test_qiongtong_no_overlap_all_fields():
    """全表 primary/secondary/avoid 两两不得重叠."""
    table = load_qiongtong_table()
    for stem, months in table.items():
        for month, entry in months.items():
            p, s, a = set(entry["primary"]), set(entry["secondary"]), set(entry["avoid"])
            assert not (p & s), f"{stem}{month}: primary∩secondary={p & s}"
            assert not (s & a), f"{stem}{month}: secondary∩avoid={s & a}"
            assert not (p & a), f"{stem}{month}: primary∩avoid={p & a}"
            assert a, f"{stem}{month}: 忌神缺失"


def test_jia_chou_tune_warm_fire():
    """甲木丑月（腊月天寒）：调候用丙丁火暖局（与子月「寒木向阳」同表一致）."""
    from app.bazi.tune import lookup_tune

    e = lookup_tune("甲", "丑")
    assert "火" in e["primary"]
    assert "金" in e["avoid"]


# ── 7. 化气格：日主强旺不从化 ──


def test_hua_ge_rejects_strong_day_master():
    """丁火日主三寅（身极强）不得从化木格（《子平真诠》：化之真者，日主孤弱）."""
    chart = build_chart_from_pillars("壬寅", "甲寅", "丁卯", "壬寅")
    a = analyze_bazi_rules(chart)
    assert a.strength.level in ("偏强", "极强")
    assert not a.pattern.name.startswith("化"), a.pattern.name


def test_hua_ge_keeps_weak_day_master():
    """真诠丁壬化木原例（壬水日主卯月衰极）仍判化木格."""
    chart = build_chart_from_pillars("甲戌", "丁卯", "壬寅", "甲辰")
    a = analyze_bazi_rules(chart)
    assert a.pattern.name == "化木格"


# ── 8. 调候与正格喜忌硬冲突 → 以格局为先 ──


def test_tune_pattern_conflict_falls_back_to_pattern():
    """甲木丑月（调候主火）正财格身弱：身弱财格忌火（食伤泄身）.

    调候用神=格局忌神 → 以格局为先（喜木水印比），不得推荐忌神火。
    """
    chart = build_chart_from_pillars("甲寅", "己丑", "甲辰", "乙亥")
    a = analyze_bazi_rules(chart)
    assert a.pattern.name == "正财格"
    xy = a.xiyongshen
    assert "火" not in xy.primary, (xy.primary, xy.avoid)
    assert any("以格局为先" in s for s in a.reasoning_chain)


def test_tune_keeps_priority_when_no_conflict():
    """金样例（丑月调候主火、正官格身弱喜印比木火）无冲突 → 仍走调候路径."""
    chart = calculate_bazi(datetime(1988, 1, 12, 17, 55), longitude=106.03, gender="male")
    a = analyze_bazi_rules(chart)
    assert a.xiyongshen.primary == ["火"]
    assert a.xiyongshen.secondary == ["木"]


# ── 9. 大运/流年喜忌含地支本气 ──


def test_dayun_note_uses_branch_element():
    """流年判定同时参考地支本气：金样例 丙午（干支皆火=喜用）→ 助用."""
    from app.bazi.dayun import compute_dayun, dayun_xiyong_note
    from app.report.narrative import build_fate_analysis

    chart = calculate_bazi(datetime(1988, 1, 12, 17, 55), longitude=106.03, gender="male")
    a = analyze_bazi_rules(chart)
    r = build_fate_analysis(chart, a)
    assert "地支本气" in r.professional
    dayun = compute_dayun(chart)
    note = dayun_xiyong_note(chart, a, dayun)
    assert "（助用" in note or "（平" in note


# ── 10. 五行表述不再「缺啥补啥」 ──


def test_wuxing_headline_not_que_shi():
    """报告五行分析头版为「俱全/不全+仅供参考」，不输出「五行缺X」式断言."""
    from app.report.narrative import format_wuxing_analysis

    chart = build_chart_from_pillars("丁卯", "癸丑", "丙寅", "丙申")
    text = format_wuxing_analysis(chart)
    assert "个数仅供参考" in text
    assert not text.startswith("五行缺"), text
