"""穷通宝鉴调候查表."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.bazi.constants import ELEMENT_CN, STEM_ELEMENT
from app.models.schemas import BaziChart, TuneResult

_DATA_PATH = Path(__file__).resolve().parent / "data" / "qiongtong_baojian.json"

_ELEMENT_TO_STEMS = {
    "木": ["甲", "乙"],
    "火": ["丙", "丁"],
    "土": ["戊", "己"],
    "金": ["庚", "辛"],
    "水": ["壬", "癸"],
}


@lru_cache(maxsize=1)
def load_qiongtong_table() -> dict:
    return json.loads(_DATA_PATH.read_text(encoding="utf-8"))


def lookup_tune(day_stem: str, month_branch: str) -> dict:
    table = load_qiongtong_table()
    return table.get(day_stem, {}).get(month_branch, {
        "primary": [], "secondary": [], "avoid": [], "stems_needed": [], "classical_note": "",
    })


def _chart_stems_present(chart: BaziChart) -> set[str]:
    present: set[str] = set()
    for key in ("year", "month", "day", "hour"):
        present.add(chart.pillars[key].stem)
        for hs in chart.pillars[key].hidden_stems:
            present.add(hs.stem)
    return present


def analyze_tune(chart: BaziChart) -> TuneResult:
    day_stem = chart.day_master["stem"]
    month_branch = chart.pillars["month"].branch
    entry = lookup_tune(day_stem, month_branch)
    present_stems = _chart_stems_present(chart)

    needed: list[str] = entry.get("stems_needed", [])
    for el in entry.get("primary", []):
        needed.extend(_ELEMENT_TO_STEMS.get(el, []))
    needed = list(dict.fromkeys(needed))

    found = [s for s in needed if s in present_stems]
    missing = [s for s in needed if s not in present_stems]

    if found and not missing:
        summary = f"命局已具备调候用神（{''.join(found)}），{entry.get('classical_note', '')}"
    elif found:
        summary = f"调候神部分具备（{'、'.join(found)}），尚缺{'、'.join(missing)}。{entry.get('classical_note', '')}"
    else:
        summary = f"调候神欠缺，宜补{'、'.join(entry.get('primary', []))}。{entry.get('classical_note', '')}"

    return TuneResult(
        primary=entry.get("primary", []),
        secondary=entry.get("secondary", []),
        avoid=entry.get("avoid", []),
        stems_needed=needed,
        present=found,
        missing=missing,
        classical_note=entry.get("classical_note", ""),
        summary=summary,
    )


def needs_tune_priority(chart: BaziChart) -> bool:
    """调候优先判定.

    穷通宝鉴认为全年都需要调候，但优先级不同：
    - 冬夏极端月份（子丑亥/午巳未）：寒暖为本，调候始终优先
    - 春秋平月（寅卯辰/申酉戌）：调候神全部缺失时才优先
    """
    tune = analyze_tune(chart)
    month = chart.pillars["month"].branch

    # 冬夏寒暖极端月份：调候为急，即使部分具备也优先
    if month in ("子", "丑", "亥", "午", "巳", "未"):
        return True

    # 春秋平月：调候神全部缺失时才优先
    return bool(tune.missing and not tune.present)
