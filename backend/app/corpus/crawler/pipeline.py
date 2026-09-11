"""语料采集 pipeline：从公网 GitHub 镜像抓取公版古籍."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from app.corpus.crawler.parsers import parse_source
from app.corpus.crawler.sources import CORPUS_SOURCES
from app.corpus.seed_data import SEED_CITATIONS

USER_AGENT = "name-corpus-bot/0.1 (+https://github.com/local/name; public-domain classics)"


async def fetch_json(url: str) -> list | dict:
    async with httpx.AsyncClient(timeout=60, headers={"User-Agent": USER_AGENT}) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def fetch_all_sources() -> list[dict]:
    all_rows: list[dict] = []
    total = len(CORPUS_SOURCES)
    for i, src in enumerate(CORPUS_SOURCES, 1):
        print(f"    抓取 [{i}/{total}] {src.book} …")
        rows = await _fetch_one(src)
        print(f"    ✓ {src.book}: {len(rows)} 条")
        all_rows.extend(rows)
    return all_rows


async def _fetch_one(src) -> list[dict]:
    data = await fetch_json(src.url)
    rows = parse_source(src.book, src.id, src.parser, data)
    for row in rows:
        row.setdefault("tags", []).append("public_domain")
    return rows


def _merge_seed(crawled: list[dict]) -> list[dict]:
    by_id = {row["id"]: row for row in crawled}
    for seed in SEED_CITATIONS:
        by_id[seed["id"]] = seed
    return list(by_id.values())


def _dedupe_by_text(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for row in rows:
        key = row["original"]
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


async def run_pipeline_async(output_dir: str | Path) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    crawled = await fetch_all_sources()
    merged = _dedupe_by_text(_merge_seed(crawled))
    merged.sort(key=lambda r: (r["book"], r["id"]))
    path = out / "citations.json"
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    meta = {
        "count": len(merged),
        "sources": [{"id": s.id, "book": s.book, "url": s.url} for s in CORPUS_SOURCES],
    }
    (out / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_pipeline(output_dir: str | Path = "data/corpus/processed") -> Path:
    return asyncio.run(run_pipeline_async(output_dir))


if __name__ == "__main__":
    path = run_pipeline("data/corpus/processed")
    data = json.loads(path.read_text(encoding="utf-8"))
    print(f"wrote {path} ({len(data)} citations)")
