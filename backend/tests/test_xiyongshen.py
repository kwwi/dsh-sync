"""喜用神合成测试."""

import json
from datetime import datetime
from pathlib import Path

from app.bazi.analysis import analyze_bazi_rules
from app.bazi.engine import calculate_bazi

GOLDEN = json.loads(
    (Path(__file__).parent.parent.parent / "docs/testing/golden-001-input.json").read_text(encoding="utf-8")
)


def test_golden_xiyongshen():
    inp = GOLDEN["input"]
    dt = datetime.fromisoformat(inp["birth_datetime"]["gregorian"].replace("+08:00", ""))
    chart = calculate_bazi(dt, longitude=inp["birth_place"]["longitude"], gender=inp["gender"])
    xy = analyze_bazi_rules(chart).xiyongshen
    assert "火" in xy.primary
    assert "木" in xy.secondary
