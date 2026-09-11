"""真太阳时 → 四柱 端到端测试.

验证完整链路：公历时刻 → beijing_to_true_solar（经度差+均时差）→ 干支四柱，
以及同一时刻不同地点/是否启用真太阳时的时柱差异。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from lunar_python import Solar

from app.bazi.analysis import analyze_bazi_rules
from app.bazi.engine import build_chart_from_pillars, calculate_bazi
from app.bazi.solar_time import beijing_to_true_solar, equation_of_time

TZ = timezone(timedelta(hours=8))


# ── 均时差数学 ──


def test_equation_of_time_known_values():
    """均时差四个典型值：1/1≈-3.6 分，2/11≈-14.6 分（全年极小），6/22≈-1.7 分（近零），11/3≈+16.4 分（全年极大）."""
    assert equation_of_time(1) == pytest.approx(-3.607, abs=0.01)
    assert equation_of_time(42) == pytest.approx(-14.574, abs=0.01)
    assert equation_of_time(173) == pytest.approx(-1.710, abs=0.01)
    assert equation_of_time(307) == pytest.approx(16.350, abs=0.01)


def test_beijing_to_true_solar_longitude_offset():
    """经度差修正：每度 4 分钟；120° 子午线无经度差，106° 差 -56 分钟."""
    dt = datetime(2024, 1, 1, 12, 0, tzinfo=TZ)
    solar_120 = beijing_to_true_solar(dt, 120.0)
    assert solar_120 == datetime(2024, 1, 1, 11, 56, 23, 587599)
    solar_106 = beijing_to_true_solar(dt, 106.0)
    assert solar_106 == datetime(2024, 1, 1, 11, 0, 23, 587599)
    assert solar_120 - solar_106 == timedelta(minutes=56)


def test_beijing_to_true_solar_strips_tzinfo():
    """带时区输入的 datetime 视为北京时间（去掉 tzinfo 再换算）."""
    dt = datetime(2024, 1, 1, 12, 0, tzinfo=TZ)
    assert beijing_to_true_solar(dt, 120.0).tzinfo is None
    assert beijing_to_true_solar(dt.replace(tzinfo=None), 120.0) == beijing_to_true_solar(dt, 120.0)


# ── 全链路：时刻 → 四柱 ──


def _manual_pillars(dt: datetime, longitude: float) -> list[str]:
    """测试内以公开步骤手动重算四柱（beijing_to_true_solar → Solar → Lunar → EightChar）."""
    ts = beijing_to_true_solar(dt, longitude)
    solar = Solar.fromYmdHms(ts.year, ts.month, ts.day, ts.hour, ts.minute, int(ts.second))
    ec = solar.getLunar().getEightChar()
    return [ec.getYear(), ec.getMonth(), ec.getDay(), ec.getTime()]


@pytest.mark.parametrize(
    "dt, longitude, expected",
    [
        (datetime(2024, 1, 1, 12, 0, tzinfo=TZ), 120.0, ["癸卯", "甲子", "甲子", "庚午"]),
        (datetime(2024, 1, 1, 12, 0, tzinfo=TZ), 106.0, ["癸卯", "甲子", "甲子", "庚午"]),
        (datetime(2024, 2, 11, 12, 0, tzinfo=TZ), 120.0, ["甲辰", "丙寅", "乙巳", "壬午"]),
        (datetime(2024, 2, 11, 12, 0, tzinfo=TZ), 106.0, ["甲辰", "丙寅", "乙巳", "辛巳"]),
        (datetime(1988, 1, 12, 17, 55, tzinfo=TZ), 120.0, ["丁卯", "癸丑", "丙寅", "丁酉"]),
        (datetime(1988, 1, 12, 17, 55, tzinfo=TZ), 106.0, ["丁卯", "癸丑", "丙寅", "丙申"]),
        (datetime(2014, 6, 22, 11, 38, tzinfo=TZ), 106.0, ["甲午", "庚午", "甲子", "己巳"]),
    ],
)
def test_calculate_bazi_matches_manual_chain(dt, longitude, expected):
    """calculate_bazi 产出的四柱与手工链路（真太阳时→Solar→Lunar→EightChar）一致."""
    chart = calculate_bazi(dt, longitude=longitude, latitude=27.0, gender="male")
    got = [p.ganzhi for p in chart.pillars.values()]
    assert got == expected, f"{dt}@{longitude}: {got}"
    assert got == _manual_pillars(dt, longitude)
    assert chart.confidence == "full"
    assert chart.beijing_time == dt.replace(tzinfo=None).isoformat()
    assert chart.true_solar_time == beijing_to_true_solar(dt, longitude).isoformat()


# ── 真太阳时的地点/开关敏感性（时柱可跨时辰） ──


def test_hour_pillar_shifts_with_longitude():
    """同一时刻，经度不同 → 真太阳时不同 → 时柱可能不同（贵阳 vs 120°子午线）."""
    dt = datetime(2014, 6, 22, 11, 38, tzinfo=TZ)
    chart_120 = calculate_bazi(dt, longitude=120.0, latitude=27.0, gender="male")
    chart_guiyang = calculate_bazi(dt, longitude=106.0, latitude=27.0, gender="male")

    for key in ("year", "month", "day"):
        assert chart_120.pillars[key].ganzhi == chart_guiyang.pillars[key].ganzhi
    assert chart_120.pillars["hour"].ganzhi == "庚午"
    assert chart_guiyang.pillars["hour"].ganzhi == "己巳"


def test_true_solar_crosses_shichen_boundary():
    """真太阳时可将时柱从午时拉回巳时（2/11 均时差极大日 + 经度差 56 分）."""
    dt = datetime(2024, 2, 11, 12, 0, tzinfo=TZ)
    chart_120 = calculate_bazi(dt, longitude=120.0, gender="male")
    chart_106 = calculate_bazi(dt, longitude=106.0, gender="male")
    assert chart_120.true_solar_time == "2024-02-11T11:45:25.530309"
    assert chart_106.true_solar_time == "2024-02-11T10:49:25.530309"
    assert chart_120.pillars["hour"].ganzhi == "壬午"
    assert chart_106.pillars["hour"].ganzhi == "辛巳"


def test_true_solar_crosses_evening_boundary():
    """17:55 北京时在 120° 为酉时，106° 真太阳时 16:50 拉回申时（GOLDEN-001 出生时刻）."""
    dt = datetime(1988, 1, 12, 17, 55, tzinfo=TZ)
    chart_120 = calculate_bazi(dt, longitude=120.0, gender="male")
    chart_106 = calculate_bazi(dt, longitude=106.0, gender="male")
    assert chart_120.pillars["hour"].ganzhi == "丁酉"
    assert chart_106.pillars["hour"].ganzhi == "丙申"


def test_use_true_solar_off_uses_beijing_hour():
    """关闭真太阳时则直接用北京时间定四柱（时柱与 120° 子午线结果一致）."""
    dt = datetime(2014, 6, 22, 11, 38, tzinfo=TZ)
    chart_off = calculate_bazi(dt, longitude=106.0, gender="male", use_true_solar=False)
    assert chart_off.pillars["hour"].ganzhi == "庚午"
    assert chart_off.true_solar_time == chart_off.beijing_time


# ── 两条入口等价性：四柱相同 ⇒ 分析相同 ──


@pytest.mark.parametrize(
    "dt, longitude, pillars",
    [
        (datetime(2014, 6, 22, 11, 38, tzinfo=TZ), 106.0, ("甲午", "庚午", "甲子", "己巳")),
        (datetime(2014, 6, 22, 11, 38, tzinfo=TZ), 120.0, ("甲午", "庚午", "甲子", "庚午")),
    ],
)
def test_pillar_and_datetime_entry_agree(dt, longitude, pillars):
    """同一张盘：calculate_bazi(时刻+地点) 与 build_chart_from_pillars(四柱) 的分析结论一致."""
    chart_dt = calculate_bazi(dt, longitude=longitude, latitude=27.0, gender="male")
    chart_gz = build_chart_from_pillars(*pillars)
    assert [p.ganzhi for p in chart_dt.pillars.values()] == list(pillars)
    a_dt = analyze_bazi_rules(chart_dt)
    a_gz = analyze_bazi_rules(chart_gz)
    assert a_dt.pattern.name == a_gz.pattern.name
    assert a_dt.xiyongshen.primary == a_gz.xiyongshen.primary
    assert a_dt.xiyongshen.avoid == a_gz.xiyongshen.avoid
