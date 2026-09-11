"""将各数据源 JSON 解析为统一 citation 记录."""

from __future__ import annotations

import re
from typing import Any

_CJK = re.compile(r"[\u4e00-\u9fff]")
_SKIP = re.compile(r"[「」『』《》〈〉【】（）()“”\"'·…—\s]")


def extract_chars(text: str) -> list[str]:
    chars = _CJK.findall(_SKIP.sub("", text))
    return list(dict.fromkeys(chars))


def _citation(
    *,
    source_id: str,
    book: str,
    chapter: str,
    original: str,
    seq: int,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    text = original.strip()
    if len(text) < 4:
        return {}
    chars = extract_chars(text)
    if len(chars) < 2:
        return {}
    return {
        "id": f"{source_id}-{seq:05d}",
        "book": book,
        "chapter": chapter,
        "original": text,
        "vernacular": "",
        "chars": chars,
        "tags": tags or ["公版"],
    }


def parse_shijing(book: str, source_id: str, data: list[dict]) -> list[dict]:
    out: list[dict] = []
    seq = 1
    for item in data:
        chapter = " · ".join(x for x in [item.get("chapter", ""), item.get("section", ""), item.get("title", "")] if x)
        for line in item.get("content", []):
            row = _citation(source_id=source_id, book=book, chapter=chapter, original=line, seq=seq)
            if row:
                out.append(row)
                seq += 1
    return out


def parse_chuci(book: str, source_id: str, data: list[dict]) -> list[dict]:
    out: list[dict] = []
    seq = 1
    for item in data:
        chapter = " · ".join(x for x in [item.get("section", ""), item.get("title", "")] if x)
        for line in item.get("content", []):
            row = _citation(source_id=source_id, book=book, chapter=chapter, original=line, seq=seq, tags=["公版", "楚辞"])
            if row:
                out.append(row)
                seq += 1
    return out


def parse_paragraphs_chapters(book: str, source_id: str, data: list[dict]) -> list[dict]:
    out: list[dict] = []
    seq = 1
    for item in data:
        chapter = item.get("chapter", book)
        for para in item.get("paragraphs", []):
            row = _citation(source_id=source_id, book=book, chapter=chapter, original=para, seq=seq)
            if row:
                out.append(row)
                seq += 1
    return out


def parse_paragraphs_single(book: str, source_id: str, data: dict) -> list[dict]:
    chapter = data.get("chapter", book)
    out: list[dict] = []
    seq = 1
    for para in data.get("paragraphs", []):
        row = _citation(source_id=source_id, book=book, chapter=chapter, original=para, seq=seq)
        if row:
            out.append(row)
            seq += 1
    return out


def parse_poetry_lines(book: str, source_id: str, data: list[dict]) -> list[dict]:
    """唐诗/宋词等：author + title/rhythmic + paragraphs 逐句入库."""
    out: list[dict] = []
    seq = 1
    for item in data:
        parts = [item.get("author", ""), item.get("rhythmic", ""), item.get("title", "")]
        chapter = " · ".join(x for x in parts if x)
        tags = ["公版", *item.get("tags", [])]
        for line in item.get("paragraphs", []):
            row = _citation(source_id=source_id, book=book, chapter=chapter, original=line, seq=seq, tags=tags)
            if row:
                out.append(row)
                seq += 1
    return out


def parse_daodejing(book: str, source_id: str, data: list[dict]) -> list[dict]:
    out: list[dict] = []
    seq = 1
    for item in data:
        chapter = item.get("chapter") or item.get("title") or f"第{item.get('id', seq)}章"
        original = item.get("original", "")
        row = _citation(source_id=source_id, book=book, chapter=str(chapter), original=original, seq=seq, tags=["公版", "道家"])
        if row:
            out.append(row)
            seq += 1
    return out


def parse_content_lines(book: str, source_id: str, data: dict) -> list[dict]:
    """蒙学等：content 字段为长文本，按换行/标点拆分."""
    out: list[dict] = []
    seq = 1
    chapter = data.get("chapter", data.get("title", book))
    content = data.get("content", "")
    # 按换行拆分
    lines = [l.strip() for l in content.replace("\r", "\n").split("\n") if l.strip()]
    for line in lines:
        # 跳过过短或纯标点行
        if len(line) < 4:
            continue
        row = _citation(source_id=source_id, book=book, chapter=chapter, original=line, seq=seq, tags=["公版", "蒙学"])
        if row:
            out.append(row)
            seq += 1
    return out


def parse_paragraphs_dict(book: str, source_id: str, data: dict) -> list[dict]:
    """dict 格式含 paragraphs 数组（百家姓、千字文、三字经等）."""
    out: list[dict] = []
    seq = 1
    chapter = data.get("chapter", data.get("title", book))
    for para in data.get("paragraphs", []):
        row = _citation(source_id=source_id, book=book, chapter=chapter, original=para, seq=seq, tags=["公版", "蒙学"])
        if row:
            out.append(row)
            seq += 1
    return out


def parse_nalan_poetry(book: str, source_id: str, data: list[dict]) -> list[dict]:
    """纳兰性德：para 字段替代 paragraphs."""
    out: list[dict] = []
    seq = 1
    for item in data:
        parts = [item.get("author", ""), item.get("rhythmic", ""), item.get("title", "")]
        chapter = " · ".join(x for x in parts if x)
        tags = ["公版", *item.get("tags", [])]
        paras = item.get("para", item.get("paragraphs", []))
        for line in paras:
            row = _citation(source_id=source_id, book=book, chapter=chapter, original=line, seq=seq, tags=tags)
            if row:
                out.append(row)
                seq += 1
    return out


def parse_content_list(book: str, source_id: str, data: list[dict]) -> list[dict]:
    """list 格式含 content 字段（幽梦影等）."""
    out: list[dict] = []
    seq = 1
    for item in data:
        content = item.get("content", "")
        if len(content) < 4:
            continue
        chapter = data[0].get("title", book) if isinstance(data, list) and data else book
        row = _citation(source_id=source_id, book=book, chapter=chapter, original=content, seq=seq, tags=["公版"])
        if row:
            out.append(row)
            seq += 1
    return out


PARSERS = {
    "shijing": parse_shijing,
    "chuci": parse_chuci,
    "paragraphs_chapters": parse_paragraphs_chapters,
    "paragraphs_single": parse_paragraphs_single,
    "poetry_lines": parse_poetry_lines,
    "daodejing": parse_daodejing,
    "content_lines": parse_content_lines,
    "paragraphs_dict": parse_paragraphs_dict,
    "nalan_poetry": parse_nalan_poetry,
    "content_list": parse_content_list,
}


def parse_source(book: str, source_id: str, parser: str, data: Any) -> list[dict]:
    fn = PARSERS[parser]
    return fn(book, source_id, data)
