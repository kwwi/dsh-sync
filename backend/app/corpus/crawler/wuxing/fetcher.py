"""从 makemeahanzi 字典按部首推断五行（本地缓存 + 索引）."""

from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

import httpx

MAKEMEAHANZI_URL = "https://raw.githubusercontent.com/skishore/makemeahanzi/master/dictionary.txt"
USER_AGENT = "name-corpus-bot/0.1"
CACHE_DIR = Path("data/wuxing/cache")
DICT_CACHE = CACHE_DIR / "makemeahanzi_dictionary.txt"
INDEX_CACHE = CACHE_DIR / "char_radical_index.json"

RADICAL_WUXING: dict[str, str] = {
    # === 金 (metal) — 金属、兵器、工具 ===
    "金": "金", "钅": "金", "釒": "金", "刀": "金", "刂": "金", "戈": "金", "斤": "金",
    "矛": "金", "矢": "金", "辛": "金", "酉": "金", "鼎": "金", "鬥": "金",
    "弓": "金", "殳": "金", "戚": "金", "钅金": "金", "车": "金", "車": "金",
    "门": "金", "門": "金", "斗": "金", "黹": "金", "韦": "金", "韋": "金",
    "网": "金", "罒": "金", "片": "金", "齿": "金", "齒": "金", "骨": "金",
    "言": "金", "讠": "金", "贝": "金", "貝": "金", "见": "金", "見": "金",
    "角": "金", "身": "金", "革": "金", "音": "金", "页": "金", "頁": "金",
    "食": "金", "飠": "金", "饣": "金", "首": "金", "香": "金", "马": "金", "馬": "金",
    "鱼": "金", "魚": "金", "鸟": "金", "鳥": "金", "鹿": "金", "鼠": "金",
    "鼻": "金", "齐": "金", "齊": "金", "齿齒": "金", "龙": "金", "龍": "金",
    "钅钅": "金", "钅": "金",

    # === 木 (wood) — 草木、植物、生长 ===
    "木": "木", "艹": "木", "竹": "木", "禾": "木", "麻": "木", "豆": "木",
    "瓜": "木", "果": "木", "耒": "木", "黍": "木", "韭": "木", "黍黍": "木",
    "生": "木", "青": "木", "東": "木", "朩": "木",
    # 风 → 木 (巽为风，属木)
    "风": "木", "風": "木",

    # === 水 (water) — 水、液体、寒冷 ===
    "水": "水", "氵": "水", "冫": "水", "雨": "水", "舟": "水", "月": "水",
    "鱼魚": "水", "亥": "水", "子": "水", "气": "水", "米": "水",
    "冖": "水", "羽": "水", "耳": "水", "而": "水", "自": "水",
    "艮": "水", "行": "水", "血": "水", "西": "水", "襾": "水",
    "隶": "水", "非": "水", "革革": "水", "面": "水", "韋韋": "水",
    "飛": "水", "髟": "水", "鬲": "水", "鬲鬲": "水", "高": "水", "魚魚": "水",
    "黑": "水", "黽": "水", "鼓": "水", "鼠鼠": "水", "鼻鼻": "水",
    "齊齊": "水", "齿齒齒": "水",

    # === 火 (fire) — 火、热、光、心 ===
    "火": "火", "灬": "火", "日": "火", "光": "火", "赤": "火", "心": "火",
    "忄": "火", "舌": "火", "丙": "火", "无": "火", "艮艮": "火",
    "比": "火", "毛": "火", "氏": "火", "爻": "火", "牙": "火",
    "牛": "火", "犬": "火", "犭": "火", "虫": "火", "虍": "火",
    "缶": "火", "羊": "火", "耒耒": "火", "而而": "火", "臼": "火",
    "至": "火", "舌舌": "火", "舛": "火", "艮艮艮": "火", "色": "火",
    "虫虫": "火", "衣": "火", "糸": "火", "幺": "火", "纟": "火", "糹": "火",
    "行行": "火", "見見": "火", "角角": "火", "豸": "火", "豸豸": "火",
    "赤赤": "火", "走走": "火", "足": "火", "足足": "火", "身身": "火",
    "辛辛": "火", "辰": "火", "酉酉": "火", "釆": "火", "里里": "火",
    "鳥鳥": "火", "卤": "火", "麻麻": "火", "黄": "火", "黍黍黍": "火", "黑黑": "火",

    # === 土 (earth) — 土、石、山、建筑 ===
    "土": "土", "山": "土", "石": "土", "田": "土", "里": "土", "广": "土",
    "厂": "土", "阝": "土", "阜": "土", "瓦": "土", "宀": "土", "穴": "土",
    "示": "土", "王": "土", "玉": "土", "礻": "土", "禸": "土",
    "屮": "土", "屮屮": "土", "尸": "土", "屮屮屮": "土", "山山": "土",
    "工": "土", "己": "土", "巾": "土", "干": "土", "幺幺": "土",
    "廴": "土", "廾": "土", "弋": "土", "户户": "土", "手扌": "土",
    "攵": "土", "攴": "土", "文": "土", "方": "土", "日曰": "土",
    "欠": "土", "止": "土", "歹": "土", "殳殳": "土", "毋": "土",
    "甘": "土", "用": "土", "疒": "土", "癶": "土", "白": "土",
    "皮": "土", "皿": "土", "目": "土", "石石": "土", "示示": "土",
    "禾禾": "土", "穴穴": "土", "立": "土", "米米": "土", "缶缶": "土",
    "老": "土", "而而而": "土", "耳耳": "土", "聿": "土", "肉": "土",
    "自自": "土", "臼臼": "土", "虍虍": "土", "虍虍虍": "土",
    "言言": "土", "豕": "土", "豕豕": "土", "走走走": "土",
    "谷": "土", "谷谷": "土", "豆豆": "土", "豸豸豸": "土",
    "鬼": "土", "鬼鬼": "土", "魚魚魚": "土", "麻麻麻": "土",
    "黄黄": "土", "黑黑黑": "土", "黹黹": "土", "黽黽": "土",
    "鼓鼓": "土", "齊齊齊": "土", "龍龍": "土", "龟": "土", "龜": "土",
    "龠": "土",
}
ELEMENT_EN = {"木": "wood", "火": "fire", "土": "earth", "金": "metal", "水": "water"}


def wuxing_from_radical(radical: str) -> str | None:
    """根据部首确定五行，先精确匹配再模糊匹配."""
    if not radical:
        return None
    if radical in RADICAL_WUXING:
        return RADICAL_WUXING[radical]
    # 模糊匹配：清理后尝试
    clean = radical.strip().replace(" ", "")
    if clean in RADICAL_WUXING:
        return RADICAL_WUXING[clean]
    # 取第一个字符尝试（复合部首取主部首）
    if len(clean) > 1:
        for ch in clean:
            if ch in RADICAL_WUXING:
                return RADICAL_WUXING[ch]
    return None


async def _download_dictionary() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print("    下载 makemeahanzi 字典（首次约 2.5MB，之后使用本地缓存）...")
    async with httpx.AsyncClient(timeout=120, headers={"User-Agent": USER_AGENT}) as client:
        async with client.stream("GET", MAKEMEAHANZI_URL) as resp:
            resp.raise_for_status()
            with DICT_CACHE.open("wb") as f:
                async for chunk in resp.aiter_bytes():
                    f.write(chunk)
    print(f"    字典已缓存: {DICT_CACHE}")


def _build_index_from_cache() -> dict[str, str]:
    index: dict[str, str] = {}
    total = 0
    with DICT_CACHE.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            ch = row.get("character")
            if ch:
                index[ch] = row.get("radical") or ""
            total += 1
            if total % 2000 == 0:
                print(f"    构建索引… {total} 行")
    INDEX_CACHE.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"    索引已缓存: {INDEX_CACHE}（{len(index)} 字）")
    return index


async def ensure_radical_index(force_rebuild: bool = False) -> dict[str, str]:
    if INDEX_CACHE.exists() and not force_rebuild:
        return json.loads(INDEX_CACHE.read_text(encoding="utf-8"))
    if not DICT_CACHE.exists():
        await _download_dictionary()
    return _build_index_from_cache()


async def lookup_chars(chars: set[str]) -> dict[str, dict]:
    if not chars:
        return {}
    index = await ensure_radical_index()
    found: dict[str, dict] = {}
    total = len(chars)
    for i, ch in enumerate(sorted(chars), 1):
        radical = index.get(ch, "")
        element_cn = wuxing_from_radical(radical) if radical else None
        if element_cn:
            found[ch] = {
                "char": ch,
                "element": ELEMENT_EN[element_cn],
                "element_cn": element_cn,
                "confidence": "medium",
                "source": "makemeahanzi_radical",
            }
        if i % 1000 == 0 or i == total:
            print(f"    五行匹配进度 {i}/{total}（已命中 {len(found)}）")
    return found
