import json
from datetime import datetime
from pathlib import Path

import pytest

from app.bazi.engine import calculate_bazi


GOLDEN = json.loads(
    (Path(__file__).parent.parent.parent / "docs/testing/golden-001-input.json").read_text(encoding="utf-8")
)


def test_golden_001_pillars():
    inp = GOLDEN["input"]
    dt = datetime.fromisoformat(inp["birth_datetime"]["gregorian"].replace("+08:00", ""))
    chart = calculate_bazi(
        dt,
        longitude=inp["birth_place"]["longitude"],
        gender=inp["gender"],
    )
    exp = GOLDEN["expected"]["pillars"]
    pillars = chart.pillars
    assert pillars["year"].ganzhi == exp["year"]
    assert pillars["month"].ganzhi == exp["month"]
    assert pillars["day"].ganzhi == exp["day"]
    assert pillars["hour"].ganzhi == exp["hour"]


def test_golden_001_element_counts():
    inp = GOLDEN["input"]
    dt = datetime.fromisoformat(inp["birth_datetime"]["gregorian"].replace("+08:00", ""))
    chart = calculate_bazi(dt, longitude=inp["birth_place"]["longitude"], gender=inp["gender"])
    ec = chart.element_counts
    exp = GOLDEN["expected"]["element_counts"]
    assert ec.wood == exp["wood"]
    assert ec.fire == exp["fire"]
    assert ec.earth == exp["earth"]
    assert ec.metal == exp["metal"]
    assert ec.water == exp["water"]


def test_golden_001_clash():
    inp = GOLDEN["input"]
    dt = datetime.fromisoformat(inp["birth_datetime"]["gregorian"].replace("+08:00", ""))
    chart = calculate_bazi(dt, longitude=inp["birth_place"]["longitude"], gender=inp["gender"])
    assert "寅申" in chart.relations.clash


def test_wuxing_golden_chars():
    from app.corpus.seed_data import SEED_CHAR_WUXING
    assert SEED_CHAR_WUXING["明"]["element_cn"] == "火"
    assert SEED_CHAR_WUXING["悠"]["element_cn"] == "火"
    assert SEED_CHAR_WUXING["庭"]["element_cn"] == "土"
    assert SEED_CHAR_WUXING["奕"]["element_cn"] == "火"
