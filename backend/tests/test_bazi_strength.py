"""日主强弱测试."""

import json
from datetime import datetime
from pathlib import Path

from app.bazi.engine import calculate_bazi
from app.bazi.strength import calculate_day_master_strength

GOLDEN = json.loads(
    (Path(__file__).parent.parent.parent / "docs/testing/golden-001-input.json").read_text(encoding="utf-8")
)


def _golden_chart():
    inp = GOLDEN["input"]
    dt = datetime.fromisoformat(inp["birth_datetime"]["gregorian"].replace("+08:00", ""))
    return calculate_bazi(dt, longitude=inp["birth_place"]["longitude"], gender=inp["gender"])


def test_golden_strength_level():
    chart = _golden_chart()
    assert chart.day_master["strength"] in ("平和", "偏弱")
    score = chart.day_master.get("strength_score", 0)
    assert 20 <= score < 70


def test_golden_not_extremely_strong():
    chart = _golden_chart()
    assert chart.day_master["strength"] not in ("极强", "偏强")


def test_strength_has_reasoning():
    chart = _golden_chart()
    s = calculate_day_master_strength(chart)
    assert s.score == chart.day_master["strength_score"]
    assert len(s.reasoning) >= 3
