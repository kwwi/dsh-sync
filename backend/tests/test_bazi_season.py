"""四季旺衰测试."""

import json
from datetime import datetime
from pathlib import Path

from app.bazi.engine import calculate_bazi
from app.bazi.season import is_earth_month, season_strength_for_month

GOLDEN = json.loads(
    (Path(__file__).parent.parent.parent / "docs/testing/golden-001-input.json").read_text(encoding="utf-8")
)


def _golden_chart():
    inp = GOLDEN["input"]
    dt = datetime.fromisoformat(inp["birth_datetime"]["gregorian"].replace("+08:00", ""))
    return calculate_bazi(dt, longitude=inp["birth_place"]["longitude"], gender=inp["gender"])


def test_earth_month_chou():
    ss = season_strength_for_month("丑")
    assert ss.earth == "旺"
    assert ss.metal == "相"
    assert ss.fire == "休"
    assert ss.wood == "囚"
    assert ss.water == "死"


def test_spring_wood_dominant():
    ss = season_strength_for_month("寅")
    assert ss.wood == "旺"
    assert ss.fire == "相"


def test_summer_fire_dominant():
    ss = season_strength_for_month("午")
    assert ss.fire == "旺"
    assert ss.earth == "相"


def test_golden_season_strength():
    chart = _golden_chart()
    exp = GOLDEN["expected"]["season_strength"]
    ss = chart.season_strength
    assert ss.wood == exp["wood"]
    assert ss.fire == exp["fire"]
    assert ss.earth == exp["earth"]
    assert ss.metal == exp["metal"]
    assert ss.water == exp["water"]


def test_all_months_have_five_statuses():
    branches = list("子丑寅卯辰巳午未申酉戌亥")
    for br in branches:
        ss = season_strength_for_month(br)
        vals = {ss.wood, ss.fire, ss.earth, ss.metal, ss.water}
        assert vals == {"旺", "相", "休", "囚", "死"}, br
