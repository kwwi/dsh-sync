"""报告叙事与黄金用例测试."""

from datetime import datetime
from pathlib import Path
import json

import pytest

from app.bazi.engine import calculate_bazi
from app.report.narrative import build_fate_analysis, format_bazi_chart, infer_xiyongshen

GOLDEN = json.loads(
    (Path(__file__).parent.parent.parent / "docs/testing/golden-001-input.json").read_text(encoding="utf-8")
)


def _golden_chart():
    inp = GOLDEN["input"]
    dt = datetime.fromisoformat(inp["birth_datetime"]["gregorian"].replace("+08:00", ""))
    return calculate_bazi(dt, longitude=inp["birth_place"]["longitude"], gender=inp["gender"])


def test_narrative_contains_bazi_sections():
    chart = _golden_chart()
    text = format_bazi_chart(chart)
    assert "【八字命盘】" in text
    assert "藏干" in text
    assert "地势" in text
    assert "丁卯" in text or "丁（火）" in text


def test_narrative_xiyongshen_golden():
    chart = _golden_chart()
    fate = build_fate_analysis(chart)
    assert "火" in fate.xiyongshen.primary
    assert "木" in fate.xiyongshen.secondary
    # 五行个数仅作参考，不作「缺啥补啥」式断言
    assert "俱全" in fate.vernacular
    assert "寅申" in fate.professional or "寅申" in chart.relations.clash[0]


def test_infer_xiyongshen_winter_fire():
    chart = _golden_chart()
    xy = infer_xiyongshen(chart)
    assert xy.primary == ["火"]
