"""繁体转简体（报告输出用）."""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def _converter():
    try:
        from zhconv import convert

        return convert
    except ImportError:
        return None


def to_simplified(text: str) -> str:
    """将文本转为简体；无 zhconv 时原样返回."""
    if not text:
        return text
    convert = _converter()
    if convert is None:
        return text
    return convert(text, "zh-cn")
