"""公版语料网络数据源（GitHub 镜像）."""

from __future__ import annotations

from dataclasses import dataclass

GITHUB_RAW = "https://raw.githubusercontent.com/chinese-poetry/chinese-poetry/master"


@dataclass(frozen=True)
class CorpusSource:
    id: str
    book: str
    parser: str
    url: str
    copyright: str = "public_domain"


CORPUS_SOURCES: list[CorpusSource] = [
    CorpusSource("shijing", "诗经", "shijing", f"{GITHUB_RAW}/诗经/shijing.json"),
    CorpusSource("chuci", "楚辞", "chuci", f"{GITHUB_RAW}/楚辞/chuci.json"),
    CorpusSource("lunyu", "论语", "paragraphs_chapters", f"{GITHUB_RAW}/论语/lunyu.json"),
    CorpusSource("mengzi", "孟子", "paragraphs_chapters", f"{GITHUB_RAW}/四书五经/mengzi.json"),
    CorpusSource("zhongyong", "中庸", "paragraphs_single", f"{GITHUB_RAW}/四书五经/zhongyong.json"),
    CorpusSource("daxue", "大学", "paragraphs_single", f"{GITHUB_RAW}/四书五经/daxue.json"),
    CorpusSource(
        "daodejing",
        "道德经",
        "daodejing",
        "https://raw.githubusercontent.com/zhaoolee/daodejing/main/src/data/chapters.json",
    ),
    CorpusSource("tangshi300", "唐诗三百首", "poetry_lines", f"{GITHUB_RAW}/全唐诗/唐诗三百首.json"),
    CorpusSource("songci300", "宋词三百首", "poetry_lines", f"{GITHUB_RAW}/宋词/宋词三百首.json"),
    CorpusSource("yuanqu", "元曲三百首", "poetry_lines", f"{GITHUB_RAW}/元曲/yuanqu.json"),
]
