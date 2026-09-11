"""测试五行 fetcher 本地索引（不访问网络）."""

from __future__ import annotations

import json

import pytest

from app.corpus.crawler.wuxing import fetcher


@pytest.mark.asyncio
async def test_lookup_chars_uses_local_index(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    dict_path = cache / "makemeahanzi_dictionary.txt"
    index_path = cache / "char_radical_index.json"

    dict_path.write_text(
        "\n".join([
            json.dumps({"character": "明", "radical": "日"}, ensure_ascii=False),
            json.dumps({"character": "水", "radical": "水"}, ensure_ascii=False),
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(fetcher, "CACHE_DIR", cache)
    monkeypatch.setattr(fetcher, "DICT_CACHE", dict_path)
    monkeypatch.setattr(fetcher, "INDEX_CACHE", index_path)

    result = await fetcher.lookup_chars({"明", "水", "未知"})
    assert result["明"]["element_cn"] == "火"
    assert result["水"]["element_cn"] == "水"
    assert "未知" not in result
    assert index_path.exists()
