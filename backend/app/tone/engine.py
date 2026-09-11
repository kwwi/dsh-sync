"""音韵引擎."""

from pypinyin import Style, pinyin

from app.models.schemas import ToneSyllable

TONE_TO_LABEL = {1: "平", 2: "平", 3: "仄", 4: "仄", 5: "平"}

# 常见多音姓氏：首字为姓时按姓氏读音标注
SURNAME_POLYPHONES: dict[str, tuple[str, int]] = {
    "单": ("shàn", 4),
    "解": ("xiè", 4),
    "查": ("zhā", 1),
    "仇": ("qiú", 2),
    "区": ("ōu", 1),
    "曾": ("zēng", 1),
    "任": ("rén", 2),
    "冼": ("xiǎn", 3),
    "尉": ("yù", 4),
    "翟": ("zhái", 2),
    "纪": ("jǐ", 3),
    "乐": ("yuè", 4),
    "种": ("chóng", 2),
    "秘": ("bì", 4),
    "薄": ("bó", 2),
    "哈": ("hǎ", 3),
    "燕": ("yān", 1),
    "华": ("huà", 4),
    "员": ("yùn", 4),
    "盖": ("gě", 3),
    "宁": ("nìng", 4),
    "牟": ("móu", 2),
    "那": ("nā", 1),
    "繁": ("pó", 2),
    "缪": ("miào", 4),
    "折": ("shé", 2),
    "朴": ("piáo", 2),
    "柏": ("bǎi", 3),
    "召": ("shào", 4),
    "逄": ("páng", 2),
    "郇": ("xún", 2),
}


def analyze_tone(full_name: str) -> list[ToneSyllable]:
    result = []
    for idx, char in enumerate(full_name):
        if not ("\u4e00" <= char <= "\u9fff"):
            continue
        override = SURNAME_POLYPHONES.get(char) if idx == 0 else None
        if override:
            marked, tone_num = override
            result.append(ToneSyllable(char=char, pinyin=marked, tone_label=TONE_TO_LABEL.get(tone_num, "平")))
            continue
        py_list = pinyin(char, style=Style.TONE3, heteronym=False)
        py = py_list[0][0] if py_list else char
        tone_num = int(py[-1]) if py and py[-1].isdigit() else 5
        tone_label = TONE_TO_LABEL.get(tone_num, "平")
        py_tone = pinyin(char, style=Style.TONE, heteronym=False)[0][0]
        result.append(ToneSyllable(char=char, pinyin=py_tone, tone_label=tone_label))
    return result


def tone_pattern(syllables: list[ToneSyllable]) -> str:
    return "".join(s.tone_label for s in syllables)


def syllable_base(pinyin_str: str) -> str:
    """去掉拼音声调符号，提取基础音节（如 \"lǐ\" → \"li\"）。

    使用 unicodedata 分解组合字符后过滤声调标记。
    """
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", pinyin_str)
    return "".join(c for c in nfkd if not unicodedata.combining(c))
