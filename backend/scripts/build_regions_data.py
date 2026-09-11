#!/usr/bin/env python3
"""Download and normalize China administrative regions with coordinates."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

SOURCE_URL = (
    "https://raw.githubusercontent.com/simonkuang/cn-pcas-geo/main/"
    "xzqh_with_amap_coordinates.json"
)
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "china_regions.json"


def norm(node: dict) -> dict:
    center = node.get("center") or {}
    item = {
        "code": str(node["code"]),
        "name": node["name"],
        "longitude": center.get("longitude"),
        "latitude": center.get("latitude"),
    }
    children = node.get("children") or []
    if children:
        item["children"] = [norm(c) for c in children]
    return item


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(SOURCE_URL, timeout=60) as resp:
        data = json.load(resp)
    normalized = [norm(p) for p in data]
    OUT.write_text(json.dumps(normalized, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, {len(normalized)} provinces)")


if __name__ == "__main__":
    main()
