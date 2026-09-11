"""China administrative region tree (province / city / district)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.models.schemas import BirthPlace, RegionItem

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "china_regions.json"


@lru_cache
def _load_tree() -> list[dict]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _to_item(node: dict) -> RegionItem:
    return RegionItem(
        code=node["code"],
        name=node["name"],
        longitude=node.get("longitude"),
        latitude=node.get("latitude"),
        has_children=bool(node.get("children")),
    )


def list_children(parent_code: str | None) -> list[RegionItem]:
    if not parent_code:
        return [_to_item(n) for n in _load_tree()]
    node = find_node(parent_code)
    if not node:
        return []
    return [_to_item(c) for c in node.get("children", [])]


def find_node(code: str) -> dict | None:
    code = str(code)

    def walk(nodes: list[dict]) -> dict | None:
        for node in nodes:
            if node["code"] == code:
                return node
            found = walk(node.get("children", []))
            if found:
                return found
        return None

    return walk(_load_tree())


MUNICIPALITIES = frozenset({"北京市", "天津市", "上海市", "重庆市"})


def resolve_birth_place(code: str) -> BirthPlace:
    node = find_node(code)
    if not node:
        raise KeyError(code)

    path: list[dict] = []

    def walk(nodes: list[dict], trail: list[dict]) -> bool:
        for item in nodes:
            current = trail + [item]
            if item["code"] == code:
                path.extend(current)
                return True
            if walk(item.get("children", []), current):
                return True
        return False

    walk(_load_tree(), [])

    province = path[0]["name"] if path else ""
    city = ""
    district = ""
    if len(path) == 1:
        city = province
    elif len(path) == 2:
        if province in MUNICIPALITIES:
            city = province
            district = path[1]["name"]
        elif path[1].get("children"):
            city = path[1]["name"]
        else:
            city = path[1]["name"]
            district = path[1]["name"]
    else:
        city = path[1]["name"]
        district = path[-1]["name"]

    lng = node.get("longitude")
    lat = node.get("latitude")
    if lng is None or lat is None:
        for item in reversed(path):
            if item.get("longitude") is not None and item.get("latitude") is not None:
                lng = item["longitude"]
                lat = item["latitude"]
                break
    if lng is None or lat is None:
        lng, lat = 120.0, 30.0

    return BirthPlace(
        province=province,
        city=city,
        district=district,
        longitude=float(lng),
        latitude=float(lat),
    )
