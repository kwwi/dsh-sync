"""文本工具：繁简转换等."""

from functools import lru_cache

from zhconv import convert


@lru_cache(maxsize=4096)
def to_simplified(text: str) -> str:
    """将繁体中文转为简体中文，已为简体则原样返回."""
    if not text:
        return text
    return convert(text, "zh-cn")
