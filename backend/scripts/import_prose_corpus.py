"""从 NiuTrans/Classical-Modern 导入散文语料.

用法:
    python scripts/import_prose_corpus.py                        # 导入所有散文
    python scripts/import_prose_corpus.py --dry-run              # 仅预览，不入库
    python scripts/import_prose_corpus.py --book 世说新语         # 仅导入指定书
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

_CJK = re.compile(r"[一-鿿]")

# NiuTrans 数据集路径
_NIUTRANS_DIR = Path("/tmp/Classical-Modern/双语数据")

# 要导入的散文/笔记类书籍（已有白话译文）
_PROSE_BOOKS: dict[str, dict] = {
    "世说新语": {"quality": 3, "dynasty": "魏晋", "desc": "魏晋名士言行轶事，文辞隽永"},
    "梦溪笔谈": {"quality": 3, "dynasty": "宋", "desc": "沈括笔记，包罗万象"},
    "容斋随笔": {"quality": 3, "dynasty": "宋", "desc": "洪迈笔记，考证精审"},
    "智囊(选录)": {"quality": 2, "dynasty": "明", "desc": "冯梦龙辑，智慧故事"},
    "贞观政要": {"quality": 2, "dynasty": "唐", "desc": "唐太宗治国言论集"},
    "国语": {"quality": 2, "dynasty": "先秦", "desc": "春秋时期各国言论"},
    "战国策": {"quality": 2, "dynasty": "先秦", "desc": "战国纵横家言论"},
    "颜氏家训": {"quality": 2, "dynasty": "北齐", "desc": "颜之推家训，立身治家"},
    "冰鉴": {"quality": 2, "dynasty": "清", "desc": "曾国藩相人术"},
    "了凡四训": {"quality": 2, "dynasty": "明", "desc": "袁了凡家训，劝善立命"},
    "呻吟语": {"quality": 2, "dynasty": "明", "desc": "吕坤语录，处世哲学"},
    "陶庵梦忆": {"quality": 2, "dynasty": "明", "desc": "张岱笔记，晚明风物"},
    "浮生六记": {"quality": 2, "dynasty": "清", "desc": "沈复自传体散文"},
    "闲情偶寄": {"quality": 2, "dynasty": "清", "desc": "李渔生活美学笔记"},
}

# 旧书中已有的（跳过，避免重复）
_SKIP_BOOKS = {"菜根谭", "围炉夜话", "幽梦影", "小窗幽记", "增广贤文",
               "弟子规", "千字文", "三字经", "幼学琼林", "声律启蒙",
               "朱子家训", "千家诗", "论语", "孟子", "大学", "中庸",
               "道德经", "庄子", "荀子", "尚书", "礼记", "周易",
               "孙子兵法", "文心雕龙", "列子", "淮南子", "成语",
               "诗经", "楚辞", "唐诗三百首", "宋词三百首", "古诗十九首",
               "曹操诗集", "纳兰性德词集", "花间集", "南唐二主词",
               "元曲三百首", "古文观止"}

# 不适合起名的章节关键词（医药、技术、制度等）
_SKIP_CHAPTER_KEYWORDS = {
    "药议", "补笔谈", "乐律", "象数", "历法",
    "官政", "器用", "技艺", "杂志",
    "金石", "算术", "律历", "职官", "食货",
}


def _extract_cjk(text: str) -> str:
    return "".join(_CJK.findall(text))


async def run(
    *,
    dry_run: bool = False,
    book_filter: str | None = None,
) -> int:
    from app.db.session import get_session_factory, init_db, CitationRecord, new_id

    await init_db()
    factory = get_session_factory()

    books = _PROSE_BOOKS
    if book_filter:
        if book_filter in books:
            books = {book_filter: books[book_filter]}
        else:
            print(f"未知书籍: {book_filter}")
            print(f"可选: {list(books.keys())}")
            return 1

    total_imported = 0
    total_skipped = 0

    async with factory() as session:
        for book_name, meta in books.items():
            book_dir = _NIUTRANS_DIR / book_name
            if not book_dir.is_dir():
                print(f"跳过（目录不存在）: {book_name}")
                continue

            if book_name in _SKIP_BOOKS:
                print(f"跳过（已存在）: {book_name}")
                continue

            # 收集所有章节的句对
            chapters: dict[str, list[tuple[str, str]]] = {}
            for chapter_dir in sorted(book_dir.iterdir()):
                if not chapter_dir.is_dir():
                    continue
                src_file = chapter_dir / "source.txt"
                tgt_file = chapter_dir / "target.txt"
                if not src_file.exists() or not tgt_file.exists():
                    continue

                src_lines = src_file.read_text(encoding="utf-8").strip().split("\n")
                tgt_lines = tgt_file.read_text(encoding="utf-8").strip().split("\n")

                chapter_name = chapter_dir.name

                # 跳过不适合起名的章节（医药、乐律、官制等）
                if any(kw in chapter_name for kw in _SKIP_CHAPTER_KEYWORDS):
                    continue

                pairs = []
                for s, t in zip(src_lines, tgt_lines):
                    s = s.strip()
                    t = t.strip()
                    if not s or not t:
                        continue
                    pairs.append((s, t))

                if pairs:
                    chapters[chapter_name] = pairs

            if not chapters:
                print(f"跳过（无有效句对）: {book_name}")
                continue

            new_citations = []
            for ch_name, pairs in chapters.items():
                for src, tgt in pairs:
                    cjk = _extract_cjk(src)
                    n_chars = len(cjk)
                    # 过滤：太短或太长的句子不适合起名
                    if n_chars < 5 or n_chars > 30:
                        total_skipped += 1
                        continue

                    # 过滤口语/对话标记过多的句子
                    if _has_too_much_dialogue(src):
                        total_skipped += 1
                        continue

                    cid = f"{book_name}-{ch_name}-{len(new_citations):04d}"
                    cid = re.sub(r"[^\w\-]", "_", cid)

                    new_citations.append({
                        "id": cid,
                        "book": book_name,
                        "chapter": f"{meta['dynasty']} · {ch_name}",
                        "original": src,
                        "vernacular": tgt,
                        "chars": list(dict.fromkeys(cjk)),
                        "tags": [meta["dynasty"], "散文"],
                    })

            if dry_run:
                print(f"\n{book_name}（{meta['desc']}）:")
                print(f"  章节: {len(chapters)} 个")
                print(f"  有效句对: {len(new_citations)} 条")
                print(f"  过滤掉: {total_skipped} 条（过短/过长/口语多）")
                for c in new_citations[:5]:
                    print(f"  [{c['chapter']}] {c['original'][:60]}")
                    print(f"    白话: {c['vernacular'][:60]}")
                continue

            # 入库
            from sqlalchemy import text
            from app.corpus.segment import segment_citation

            conn = await session.connection()
            imported = 0
            for c in new_citations:
                c["words"] = segment_citation(c["original"])
                params = {
                    "id": c["id"], "book": c["book"],
                    "chapter": c["chapter"], "original": c["original"],
                    "vernacular": c["vernacular"],
                    "chars": __import__("json").dumps(c["chars"], ensure_ascii=False),
                    "words": __import__("json").dumps(c["words"], ensure_ascii=False),
                    "tags": __import__("json").dumps(c["tags"], ensure_ascii=False),
                }
                await conn.execute(
                    text("INSERT OR IGNORE INTO citations (id, book, chapter, original, vernacular, chars, words, tags) "
                         "VALUES (:id, :book, :chapter, :original, :vernacular, :chars, :words, :tags)"),
                    params,
                )
                imported += 1

            await session.commit()
            total_imported += imported
            print(f"{book_name}: 入库 {imported} 条（{len(chapters)} 章）")

    if dry_run:
        print(f"\n预览完成：共 {total_imported + total_skipped} 条候选，其中 {total_skipped} 条被过滤")
    else:
        print(f"\n导入完成：{total_imported} 条语料入库")

    if total_imported > 0:
        from app.corpus.search import invalidate_search_index
        invalidate_search_index()
        print("倒排索引已失效，下次检索时自动重建。")

    return 0


def _has_too_much_dialogue(text: str) -> bool:
    """检测是否对话/口语标记过多."""
    markers = {"曰", "云", "谓", "问", "对曰", "曰：", "云：",
               "了", "的", "吧", "吗", "呢", "啊", "呀"}
    count = sum(1 for m in markers if m in text)
    cjk = _extract_cjk(text)
    return len(cjk) > 0 and count >= len(cjk) * 0.15


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从 NiuTrans/Classical-Modern 导入散文语料")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不入库")
    parser.add_argument("--book", type=str, default=None, help="仅导入指定书籍")
    args = parser.parse_args()

    code = asyncio.run(run(
        dry_run=args.dry_run,
        book_filter=args.book,
    ))
    sys.exit(code)
