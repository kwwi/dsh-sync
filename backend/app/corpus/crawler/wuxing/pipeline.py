"""字义五行采集 pipeline."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from app.corpus.crawler.wuxing.fetcher import lookup_chars
from app.corpus.seed_data import SEED_CHAR_WUXING

STRONG_RADICALS = {
    "金": ["金", "钅", "釒", "刂", "刀", "戈", "斤", "矛", "矢", "辛", "酉", "鼎",
           "弓", "车", "車", "门", "門", "斗", "贝", "貝", "见", "見", "角",
           "言", "讠", "马", "馬", "鸟", "鳥", "鱼", "魚", "龙", "龍", "齿", "齒"],
    "木": ["木", "艹", "竹", "禾", "麻", "豆", "瓜", "果", "耒", "黍", "韭",
           "生", "青", "风", "風", "飞", "飛", "羽", "毛", "艸"],
    "水": ["水", "氵", "冫", "雨", "舟", "月", "米", "气", "羽", "耳", "自",
           "血", "西", "面", "黑", "鱼魚", "亥", "子", "非", "飞飛"],
    "火": ["火", "灬", "日", "光", "赤", "心", "忄", "舌", "丙", "比", "牛",
           "犬", "犭", "虫", "羊", "缶", "幺", "纟", "糸", "糹", "足", "辰",
           "黄", "无", "爻", "釆", "卤"],
    "土": ["土", "山", "石", "田", "里", "广", "厂", "阝", "阜", "瓦", "宀",
           "穴", "示", "礻", "王", "玉", "工", "己", "巾", "干", "尸", "皮",
           "皿", "目", "立", "老", "肉", "臼", "豕", "谷", "鬼", "龟", "龜"],
}
_CJK = re.compile(r"[\u4e00-\u9fff]")


def classify_by_radical(char: str) -> str | None:
    for element_cn, radicals in STRONG_RADICALS.items():
        for r in radicals:
            if r in char:
                return element_cn
    return None


def collect_chars_from_citations(citations_path: str | Path) -> list[str]:
    path = Path(citations_path)
    if not path.exists():
        return list(SEED_CHAR_WUXING.keys())
    rows = json.loads(path.read_text(encoding="utf-8"))
    chars: list[str] = []
    for row in rows:
        chars.extend(row.get("chars", []))
        chars.extend(_CJK.findall(row.get("original", "")))
    return list(dict.fromkeys(chars))


async def run_wuxing_pipeline_async(
    chars: list[str] | None = None,
    citations_path: str | Path = "data/corpus/processed/citations.json",
    output: str | Path = "data/wuxing/processed/char_wuxing_v1.json",
) -> Path:
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    target_chars = chars or collect_chars_from_citations(citations_path)
    char_set = set(target_chars)

    records: list[dict] = []
    seen: set[str] = set()
    for c, w in SEED_CHAR_WUXING.items():
        records.append({"char": c, **w})
        seen.add(c)
        char_set.discard(c)

    print(f"    查询 makemeahanzi 五行（待查 {len(char_set)} 字）...")
    looked = await lookup_chars(char_set)
    for c, row in looked.items():
        if c not in seen:
            records.append(row)
            seen.add(c)
            char_set.discard(c)

    for c in sorted(char_set):
        rad = classify_by_radical(c)
        if rad and c not in seen:
            records.append({
                "char": c,
                "element": {"木": "wood", "火": "fire", "土": "earth", "金": "metal", "水": "water"}[rad],
                "element_cn": rad,
                "confidence": "medium",
                "source": "radical",
            })
            seen.add(c)

    records.sort(key=lambda r: r["char"])
    out.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def run_wuxing_pipeline(
    chars: list[str] | None = None,
    citations_path: str | Path = "data/corpus/processed/citations.json",
    output: str | Path = "data/wuxing/processed/char_wuxing_v1.json",
) -> Path:
    return asyncio.run(run_wuxing_pipeline_async(chars, citations_path, output))


if __name__ == "__main__":
    run_wuxing_pipeline()
