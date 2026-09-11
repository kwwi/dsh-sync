#!/usr/bin/env python3
"""批量处理本地 chinese-poetry 语料库，合并到 citations.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.corpus.crawler.parsers import parse_poetry_lines, parse_nalan_poetry, parse_paragraphs_chapters

LOCAL_BASE = Path("/Users/houyuan/Downloads/chinese-poetry-master")
CITATIONS_PATH = Path("data/corpus/processed/citations.json")

EXISTING_IDS = {
    "shijing", "chuci", "lunyu", "mengzi", "zhongyong", "daxue",
    "daodejing", "tangshi300", "songci300", "yuanqu",
}

_CJK_chars = __import__('re').compile(r"[一-鿿]")


def extract_chars(text: str) -> list[str]:
    return list(dict.fromkeys(_CJK_chars.findall(text)))


def make_citation(source_id: str, book: str, chapter: str, original: str, seq: int) -> dict | None:
    text = original.strip()
    if len(text) < 4:
        return None
    chars = extract_chars(text)
    if len(chars) < 2:
        return None
    return {
        "id": f"{source_id}-{seq:05d}",
        "book": book,
        "chapter": chapter,
        "original": text,
        "vernacular": "",
        "chars": chars,
        "tags": ["公版"],
    }


def flatten_paragraphs(data: list[dict], book: str, source_id: str,
                       chapter_prefix: str = "") -> list[dict]:
    """递归展开嵌套的 paragraphs/content 结构."""
    out = []
    seq = 1

    def walk(items: list, prefix: str):
        nonlocal seq
        if isinstance(items, str):
            items = [items]
        if not isinstance(items, list):
            return
        for item in items:
            if isinstance(item, str):
                cit = make_citation(source_id, book, prefix, item, seq)
                if cit:
                    out.append(cit)
                    seq += 1
            elif isinstance(item, dict):
                ch = item.get("chapter", item.get("title", item.get("type", "")))
                new_prefix = f"{prefix} · {ch}" if prefix and ch else (ch or prefix)
                # Check for paragraphs
                paras = item.get("paragraphs", [])
                if paras:
                    for p in paras:
                        if isinstance(p, str):
                            cit = make_citation(source_id, book, new_prefix, p, seq)
                            if cit:
                                out.append(cit)
                                seq += 1
                        elif isinstance(p, dict):
                            walk([p], new_prefix)
                # Check for nested content
                nested = item.get("content", [])
                if nested:
                    walk(nested, new_prefix)
                # Check for direct text
                direct = item.get("original", item.get("text", ""))
                if direct and not paras and not nested:
                    cit = make_citation(source_id, book, new_prefix, direct, seq)
                    if cit:
                        out.append(cit)
                        seq += 1

    walk(data, chapter_prefix)
    return out


def process_file(path: Path, book: str, source_id: str,
                 parser_type: str = "auto") -> list[dict]:
    """Process a single JSON file."""
    if not path.exists():
        print(f"  ⚠ not found: {path}")
        return []

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if parser_type == "poetry_lines":
        return parse_poetry_lines(book, source_id, data)
    elif parser_type == "nalan_poetry":
        return parse_nalan_poetry(book, source_id, data)
    elif parser_type == "paragraphs_chapters":
        return parse_paragraphs_chapters(book, source_id, data)
    elif parser_type == "auto":
        # Auto-detect: handle dict or list
        if isinstance(data, dict):
            # Try paragraphs first, then content
            content = data.get("content", data.get("paragraphs", []))
            return flatten_paragraphs(
                content if isinstance(content, list) else [{"paragraphs": [content]}],
                book, source_id, data.get("title", data.get("chapter", book))
            )
        elif isinstance(data, list):
            return flatten_paragraphs(data, book, source_id, book)
    else:
        raise ValueError(f"Unknown parser: {parser_type}")

    return []


# ── 源配置 ──
NEW_SOURCES = [
    # 诗词类（明确 parser）
    ("caocao", "曹操诗集", "poetry_lines", LOCAL_BASE / "曹操诗集/caocao.json"),
    ("nalan", "纳兰性德词集", "nalan_poetry", LOCAL_BASE / "纳兰性德/纳兰性德诗集.json"),
    ("nantang", "南唐二主词", "poetry_lines", LOCAL_BASE / "五代诗词/nantang/poetrys.json"),
    # 花间集：多个卷文件
    ("huajianji", "花间集", "poetry_lines", None),  # special handling below
    # 幽梦影
    ("youmengying", "幽梦影", "auto", LOCAL_BASE / "幽梦影/youmengying.json"),
    # 蒙学 — auto-detect
    ("dizigui", "弟子规", "auto", LOCAL_BASE / "蒙学/dizigui.json"),
    ("qianjiashi", "千家诗", "auto", LOCAL_BASE / "蒙学/qianjiashi.json"),
    ("qianziwen", "千字文", "auto", LOCAL_BASE / "蒙学/qianziwen.json"),
    ("sanzijing", "三字经", "auto", LOCAL_BASE / "蒙学/sanzijing-new.json"),
    ("shenglvqimeng", "声律启蒙", "auto", LOCAL_BASE / "蒙学/shenglvqimeng.json"),
    ("youxueqionglin", "幼学琼林", "auto", LOCAL_BASE / "蒙学/youxueqionglin.json"),
    ("zengguangxianwen", "增广贤文", "auto", LOCAL_BASE / "蒙学/zengguangxianwen.json"),
    ("zhuzijiaxun", "朱子家训", "auto", LOCAL_BASE / "蒙学/zhuzijiaxun.json"),
    ("guwenguanzhi", "古文观止", "auto", LOCAL_BASE / "蒙学/guwenguanzhi.json"),
]


def main():
    CITATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Load existing
    if CITATIONS_PATH.exists():
        existing = json.loads(CITATIONS_PATH.read_text(encoding="utf-8"))
        existing_ids = {c["id"] for c in existing}
        print(f"现有语料: {len(existing)} 条")
    else:
        existing = []
        existing_ids = set()
        print("无现有语料")

    total_new = 0

    for src_id, book, parser_type, path in NEW_SOURCES:
        if src_id in EXISTING_IDS:
            print(f"  ⊘ {book}: 已有，跳过")
            continue

        # Special: 花间集 multi-file
        if src_id == "huajianji":
            hj_dir = LOCAL_BASE / "五代诗词/huajianji"
            all_rows = []
            for f in sorted(hj_dir.glob("*.json")):
                rows = process_file(f, book, src_id, parser_type)
                all_rows.extend(rows)
            rows = all_rows
        else:
            rows = process_file(path, book, src_id, parser_type)

        if not rows:
            print(f"  ✗ {book}: 无数据")
            continue

        new_rows = [r for r in rows if r["id"] not in existing_ids]
        if not new_rows:
            print(f"  ⊘ {book}: {len(rows)} 条全重复")
            continue

        existing.extend(new_rows)
        existing_ids.update(r["id"] for r in new_rows)
        print(f"  ✓ {book}: +{len(new_rows)} 条 (共 {len(rows)} 条)")
        total_new += len(new_rows)

    # Save
    CITATIONS_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    books = len({c["book"] for c in existing})
    print(f"\n✅ 总计: {len(existing)} 条, {books} 部典籍 (新增 {total_new} 条)")
    print(f"保存至: {CITATIONS_PATH}")


if __name__ == "__main__":
    main()
