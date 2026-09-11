"""大运排法（命理探原体系）：阴阳年×男女定顺逆、节气定起运、月柱顺逆推运.

规则：
- 顺逆：阳年（甲丙戊庚壬）男、阴年女 顺排；阴年男、阳年女 逆排。
- 起运：顺排数至下一「节」，逆排数至上一「节」；3天=1岁，1天=4个月。
- 大运：月柱干支顺/逆各推六步，每步十年。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from lunar_python import Solar

from app.bazi.constants import BRANCHES, STEMS
from app.models.schemas import BaziChart, DayunResult, DayunStep

_JIE_NAMES = ("立春", "惊蛰", "清明", "立夏", "芒种", "小暑", "立秋", "白露", "寒露", "立冬", "大雪", "小寒")
_YANG_YEAR = set("甲丙戊庚壬")


def _dayun_direction(year_stem: str, gender: str) -> str:
    """阳年男/阴年女顺排，否则逆排."""
    forward = (year_stem in _YANG_YEAR) == (gender == "male")
    return "顺排" if forward else "逆排"


def _jie_dates(birth: datetime) -> dict[str, datetime]:
    """出生农历年所含十二「节」的精确时刻（保留时分秒，起运折算以时辰为精度）."""
    solar = Solar.fromYmdHms(birth.year, birth.month, birth.day, birth.hour, birth.minute, birth.second)
    out = {}
    for name, s in solar.getLunar().getJieQiTable().items():
        if name in _JIE_NAMES:
            out[name] = datetime(s.getYear(), s.getMonth(), s.getDay(), s.getHour(), s.getMinute(), s.getSecond())
    return out


def _compute_dayun(birth: datetime, gender: str, now: datetime | None = None, year_stem: str | None = None) -> DayunResult:
    now = now or datetime.now()
    if year_stem is None:
        # 大运阴阳以八字年柱（立春为岁首换年）定：getYearGan 取农历年干，立春~春节窗口期内与年柱不一致
        year_stem = (
            Solar.fromYmdHms(birth.year, birth.month, birth.day, birth.hour, birth.minute, birth.second)
            .getLunar().getEightChar().getYear()[0]
        )
    direction = _dayun_direction(year_stem, gender)
    forward = direction == "顺排"

    jies = _jie_dates(birth)
    birth_dt = birth.replace(tzinfo=None)
    if forward:
        candidates = [dt for dt in jies.values() if dt >= birth_dt]
        jie = min(candidates) if candidates else None
    else:
        candidates = [dt for dt in jies.values() if dt <= birth_dt]
        jie = max(candidates) if candidates else None
    if jie is None:
        jie = min(jies.values())

    gap_days = abs((jie - birth_dt).total_seconds()) / 86400.0
    start_age = round(gap_days / 3.0, 2)  # 3 天 = 1 岁

    month_gz = Solar.fromYmdHms(birth.year, birth.month, birth.day, 0, 0, 0).getLunar().getEightChar().getMonth()
    si, bi = STEMS.index(month_gz[0]), BRANCHES.index(month_gz[1])
    step = 1 if forward else -1

    steps: list[DayunStep] = []
    for i in range(8):
        si = (si + step) % 10
        bi = (bi + step) % 12
        gz = STEMS[si] + BRANCHES[bi]
        steps.append(
            DayunStep(
                index=i + 1,
                ganzhi=gz,
                start_age=round(start_age + i * 10, 1),
                end_age=round(start_age + (i + 1) * 10, 1),
            )
        )

    age = (now - birth_dt).days / 365.25
    if age < start_age:
        current = None  # 尚未起运
    else:
        current = next((s for s in steps if s.start_age <= age < s.end_age), steps[-1])

    curr_year_gz = Solar.fromYmdHms(now.year, now.month, now.day, 0, 0, 0).getLunar().getYearInGanZhi()
    return DayunResult(
        direction=direction,
        start_age=start_age,
        steps=steps,
        current=current,
        current_year_ganzhi=curr_year_gz,
    )


def compute_dayun(chart: BaziChart) -> DayunResult | None:
    """由命盘计算大运（需公历时刻；build_chart_from_pillars 无公历则返回 None）.

    顺逆方向以命盘年柱干支（立春为岁首）定阴阳，与排盘口径完全一致。
    """
    if not chart.beijing_time:
        return None
    birth = datetime.fromisoformat(chart.beijing_time)
    return _compute_dayun(birth, chart.gender, year_stem=chart.pillars["year"].stem)


def dayun_xiyong_note(chart: BaziChart, analysis, result: DayunResult) -> str:
    """当前大运/流年与喜用神的关系提示（天干、地支分别判定，取地支本气）."""
    if result is None:
        return ""
    xy = analysis.xiyongshen
    from app.bazi.constants import ELEMENT_CN, HIDDEN_STEMS, STEM_ELEMENT

    def rel(gz: str) -> str:
        """整体判定：干支有一为喜用且无一是忌 → 助用；两皆忌 → 耗忌；其余 → 平."""
        stem_el = ELEMENT_CN[STEM_ELEMENT[gz[0]]]
        branch_el = ELEMENT_CN[HIDDEN_STEMS[gz[1]][0][1]]  # 地支本气
        liked = [e for e in (stem_el, branch_el) if e in xy.primary or e in xy.secondary]
        disliked = [e for e in (stem_el, branch_el) if e in xy.avoid]
        if liked and not disliked:
            return "助用"
        if disliked and not liked:
            return "耗忌"
        return "平"

    if result.current is None:
        return (
            f"大运{result.direction}，{result.start_age}岁起运（尚未入运）；"
            f"流年{result.current_year_ganzhi}。改名择时宜选大运流年助用之期。"
        )
    dg, yg = result.current.ganzhi, result.current_year_ganzhi
    return (
        f"当前大运{result.current.ganzhi}（{rel(dg)}，含地支本气），"
        f"流年{result.current_year_ganzhi}（{rel(yg)}，含地支本气）；"
        f"大运{result.direction}，{result.start_age}岁起运。"
        f"改名择时宜选大运流年助用之期。"
    )
