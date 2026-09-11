"""穷通宝鉴调候测试."""

import json
from datetime import datetime
from pathlib import Path

from app.bazi.engine import calculate_bazi
from app.bazi.tune import analyze_tune, load_qiongtong_table, lookup_tune

GOLDEN = json.loads(
    (Path(__file__).parent.parent.parent / "docs/testing/golden-001-input.json").read_text(encoding="utf-8")
)
STEMS = list("甲乙丙丁戊己庚辛壬癸")
BRANCHES = list("子丑寅卯辰巳午未申酉戌亥")


def test_qiongtong_120_entries():
    table = load_qiongtong_table()
    assert len(table) == 10
    for stem in STEMS:
        assert len(table[stem]) == 12
        for br in BRANCHES:
            entry = table[stem][br]
            assert "primary" in entry
            assert "classical_note" in entry
            assert entry.get("avoid"), f"{stem}{br} 调候忌神缺失"
            assert not (set(entry.get("primary", [])) & set(entry.get("avoid", []))), (
                f"{stem}{br} 喜忌重叠"
            )


def test_bing_zi_tune():
    entry = lookup_tune("丙", "子")
    assert "火" in entry["primary"]


def test_golden_winter_bing_tune():
    inp = GOLDEN["input"]
    dt = datetime.fromisoformat(inp["birth_datetime"]["gregorian"].replace("+08:00", ""))
    chart = calculate_bazi(dt, longitude=inp["birth_place"]["longitude"], gender=inp["gender"])
    tune = analyze_tune(chart)
    assert "火" in tune.primary
    assert "木" in tune.secondary
