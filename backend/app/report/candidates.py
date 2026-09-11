"""备选名生成：语料检索 + LLM 组名 + 寓意评分."""

from __future__ import annotations

import asyncio
import itertools
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import NameComposeAgent, NameFreeComposeAgent
from app.corpus.search import (
    load_wuxing_map,
    matches_xiyongshen,
    pair_passes_strategy,
    search_citations,
)
from app.corpus.seed_data import BOOK_QUALITY_SCORE, DEFAULT_BOOK_QUALITY
from app.llm.config import resolve_llm_config
from app.models.schemas import FateAnalysis, NameCandidate, NamePreferences, ToneSyllable
from app.tone.engine import analyze_tone, syllable_base, tone_pattern

_CJK = re.compile(r"[\u4e00-\u9fff]")
WuxingStrategy = Literal["strict", "moderate", "reference"]
# 非相邻字对仅在同一分句内组合，避免长诗词整篇 O(n²) 排列
_MAX_SEGMENT_PERM_CHARS = 14
# 寓意评分低于此阈值的候选名直接丢弃
MIN_MEANING_SCORE = 5
# LLM生成候选名的最低分数阈值（应高于规则生成）
MIN_MEANING_SCORE_LLM = 6


# ── 候选池规模：大幅扩量，让 LLM 从更多素材中精选 ──
def _citation_limit(output_count: int) -> int:
    """语料检索上限。output_count=10 → 1000 条."""
    return max(600, output_count * 100)


def _pool_limit(output_count: int) -> int:
    """候选名池上限。output_count=10 → 350 个."""
    return max(250, output_count * 35)


def _hint_limit(output_count: int) -> int:
    """给 LLM 的 name_hints 上限。output_count=10 → 200 条."""
    return max(120, output_count * 20)


# ── 近二十年高频起名字/用字（数据来源：公安部户政管理研究中心历年姓名报告）──
# 热门双字名：命中后大幅降分
_COMMON_GIVEN_NAMES: set[str] = {
    "子涵", "梓涵", "子轩", "梓轩", "浩然", "浩宇", "雨桐", "雨彤",
    "一诺", "欣怡", "宇轩", "沐宸", "沐萱", "若曦", "思涵",
    "睿泽", "铭泽", "奕辰", "子墨", "子琪", "子睿", "宇辰",
    "铭宇", "浩轩", "梓豪", "梓萱", "梓琪", "梓瑶", "梓琳",
    "宇浩", "宇琪", "宇涵", "宇洋", "浩铭", "浩霖", "浩宸",
    "浩然", "沐阳", "沐恩", "沐辰", "沐瑶", "沐晗", "沐霖",
    "若溪", "若瑶", "若琳", "若涵", "思源", "思远", "思琪",
    "子豪", "子杰", "子航", "子恒", "子恒", "子洋", "子铭",
    "天佑", "天宇", "天浩", "天铭", "星辰", "星宇", "星辰",
}
# 起名过度使用字（单个字命中扣分）
_OVERUSED_CHARS: set[str] = {
    "涵", "梓", "轩", "萱", "睿", "昊", "彤", "怡", "欣",
    "浩", "宇", "铭", "泽", "辰", "沐", "瑶", "诺", "曦",
    "若", "琪", "琳", "宸", "霖", "洋", "航", "杰", "博",
}
# 常见网感名/网红风名字（完全匹配禁止）
_TRENDY_NAME_BLACKLIST: set[str] = {
    "玖玥", "琉萤", "琉璃", "星璃", "月璃", "沫漓", "浅汐",
    "墨染", "倾尘", "落尘", "顾北", "顾南", "南笙", "北笙",
    "清欢", "微凉", "凉笙", "暖阳", "初雪", "初夏", "浅唱",
}


@dataclass
class ScoredName:
    chars: tuple[str, ...]
    citation: Any
    meaning_score: int
    adjacent: bool = False
    is_word: bool = False

    @property
    def given(self) -> str:
        return "".join(self.chars)


# ── 单字音韵缓存：避免 analyze_tone 对同一字符重复调用 ──
_char_tone_cache: dict[str, tuple[ToneSyllable, str]] = {}


def _cached_tone(char: str) -> tuple[ToneSyllable, str]:
    """返回 (ToneSyllable, syllable_base)，首次调用时缓存."""
    if char not in _char_tone_cache:
        syls = analyze_tone(char)
        if syls:
            s = syls[0]
            base = syllable_base(s.pinyin)
        else:
            s = ToneSyllable(char=char, pinyin=char, tone_label="平")
            base = char
        _char_tone_cache[char] = (s, base)
    return _char_tone_cache[char]


def _pinyin_collides(surname: str, given: str) -> bool:
    """检测姓末字与名中字是否同音（如 李+鲤 → 同音碰撞）."""
    if not surname or not given:
        return False
    surname_last = surname[-1]
    surname_base = _cached_tone(surname_last)[1]
    for ch in given:
        given_base = _cached_tone(ch)[1]
        if given_base == surname_base:
            return True
    return False


# ── 五行预计算通过集：一次计算，后续所有过滤变 O(1) set lookup ──
class _WuxingPassSets:
    """五行硬过滤预计算集合.

    在请求开始时根据喜用神和策略一次生成，后续 _char_passes / _pair_passes 仅做 set lookup。
    """

    __slots__ = (
        "primary_chars", "secondary_chars", "indirect_chars", "avoid_chars",
        "strategy", "primary", "secondary",
    )

    def __init__(
        self,
        wx_map: dict[str, str],
        primary: list[str],
        secondary: list[str],
        avoid: list[str] | None,
        strategy: WuxingStrategy = "strict",
    ):
        from app.corpus.search import matches_xiyongshen as _mxs

        self.primary = primary
        self.secondary = secondary
        self.strategy = strategy
        self.primary_chars: set[str] = set()
        self.secondary_chars: set[str] = set()
        self.indirect_chars: set[str] = set()
        self.avoid_chars: set[str] = set(avoid or [])

        for char, element_cn in wx_map.items():
            if not element_cn:
                continue
            ok, tag = _mxs(element_cn, primary, secondary, avoid)
            if not ok:
                continue
            if tag == "primary":
                self.primary_chars.add(char)
            elif tag == "secondary":
                self.secondary_chars.add(char)
            elif tag == "indirect":
                self.indirect_chars.add(char)

    def char_passes(self, char: str) -> bool:
        if not self.primary and not self.secondary:
            return True  # reference 模式：无喜用神时全部通过
        if self.strategy == "reference":
            return char not in self.avoid_chars
        char_set = self.primary_chars | self.secondary_chars
        if self.strategy == "moderate":
            char_set |= self.indirect_chars
        return char in char_set and char not in self.avoid_chars

    def pair_passes(self, a: str, b: str) -> bool:
        if not self.primary and not self.secondary:
            return True
        if self.strategy == "reference":
            return a not in self.avoid_chars and b not in self.avoid_chars
        if a in self.avoid_chars or b in self.avoid_chars:
            return False
        if self.strategy == "moderate":
            allowed = self.primary_chars | self.secondary_chars | self.indirect_chars
            return (a in allowed) and (b in allowed)
        # strict: 至少一字命中 primary/secondary（含 indirect），且两字都不在 avoid
        allowed = self.primary_chars | self.secondary_chars
        allow_indirect = bool(self.indirect_chars)
        if allow_indirect:
            allowed |= self.indirect_chars
        if a not in allowed or b not in allowed:
            return False
        # strict: 至少一字命中 primary（含 indirect generates primary）
        a_primary = a in (self.primary_chars | self.indirect_chars)
        b_primary = b in (self.primary_chars | self.indirect_chars)
        if not a_primary and not b_primary:
            return self.secondary_chars and (a in self.secondary_chars or b in self.secondary_chars)
        return True


@dataclass
class NamePrecomputed:
    """预计算的命名数据，可在 FateAnalysisAgent 并行期间完成."""
    wx_map: dict[str, str]
    citations: list
    ranked: list[ScoredName]


def _tone_comment(syllables: list[ToneSyllable], surname: str) -> str:
    given_syl = syllables[len(surname):]
    gp = tone_pattern(given_syl) if given_syl else tone_pattern(syllables)
    py = " ".join(s.pinyin for s in given_syl)
    # 根据平仄模式给出差异化评价
    if gp == "平仄" or gp == "仄平":
        quality = "平仄相间，朗朗上口"
    elif gp == "平" or gp == "仄":
        quality = "单字名，音韵" + ("平和温润" if gp == "平" else "铿锵有力")
    elif gp in ("平平平", "仄仄仄"):
        quality = "三字同调，韵律稍显单调"
    elif "平仄" in gp and "仄平" in gp:
        quality = "平仄交替，抑扬顿挫"
    elif "平仄平" == gp or "仄平仄" == gp:
        quality = "平仄错落，节奏优美"
    elif gp in ("平平仄", "仄仄平"):
        quality = "尾字收束有力，朗朗上口"
    else:
        quality = "宜朗诵体悟"
    return f"拼音 {py}；名章平仄「{gp}」，读音{quality}。"


def _tone_harmony_score(surname: str, given: str) -> int:
    """评估姓+名整体平仄和谐度（-8..+12），是规则评分的核心维度.

    使用缓存避免重复调用 analyze_tone。
    """
    if not surname or not given:
        return 0

    # 通过缓存获取所有字的 tone_label，无需调用 analyze_tone
    all_chars = surname + given
    labels = [_cached_tone(c)[0].tone_label for c in all_chars]
    full_pattern = "".join(labels)
    surname_pattern = full_pattern[:len(surname)]
    given_pattern = full_pattern[len(surname):]

    if len(given) == 1:
        # 单字名：姓尾与名的平仄关系
        surname_tail = surname_pattern[-1]
        given_tone = given_pattern[0]
        return 8 if surname_tail != given_tone else 2

    # 双字名
    full_alt = full_pattern in ("平仄平", "仄平仄")
    given_alt = "平仄" in given_pattern or "仄平" in given_pattern
    surname_tail = surname_pattern[-1]
    given_first = given_pattern[0]

    if full_alt:
        return 12  # 姓名整体平仄交替：最优
    if given_alt and surname_tail != given_first:
        return 10  # 名内部交替 + 姓尾与名首不同调
    if given_alt:
        return 8   # 名内部交替
    if given_pattern in ("平平仄", "仄仄平"):
        return 6   # 收束型：尾字变调
    if full_pattern in ("平平平", "仄仄仄"):
        return -8  # 全平或全仄：显著扣分
    if given_pattern in ("平平", "仄仄"):
        return -4  # 名内部同调
    return 4       # 其他非单调情况（平仄仄/仄平平等）


def _extract_cjk(text: str) -> list[str]:
    return _CJK.findall(text)


# 古汉语常见不可拆分复合词 —— 其中的字不应跨越词边界与外部分别组合
_INSEPARABLE_BIGRAMS: set[str] = {
    "君子", "小人", "天下", "圣人", "日月", "天地", "山河", "江山",
    "春秋", "文武", "父母", "兄弟", "君臣", "夫妇", "凤凰", "麒麟",
    "草木", "风雨", "雷霆", "霜雪", "星辰", "沧海", "桑田", "琴瑟",
    "社稷", "黎民", "百姓", "王侯", "将相", "公卿", "大夫",
    "逍遥", "寂寥", "徘徊", "踌躇", "彷徨", "窈窕",
    "蒹葭", "芍药", "杜若", "薜荔", "兰芷", "琼瑶",
}


def _crosses_inseparable_boundary(chars: list[str], a_idx: int, b_idx: int) -> bool:
    """检查 a,b 两个字是否跨越了不可拆分复合词的边界.

    例如 chars=['君','子','树','之'], a='子'(idx=1), b='树'(idx=2):
    - '君子'({'君','子'})在集合中，'子'是'君子'的尾部
    - '树'是下一个字，不属于'君子'
    - 因此 (子,树) 跨越了词边界 → True
    """
    n = len(chars)
    for blen in (2,):
        # 检查以 a 结尾的 bigram
        if a_idx >= blen - 1:
            bigram = chars[a_idx - blen + 1] + chars[a_idx]
            if bigram in _INSEPARABLE_BIGRAMS:
                return True
        # 检查以 b 开头的 bigram
        if b_idx <= n - blen:
            bigram = chars[b_idx] + chars[b_idx + blen - 1]
            if bigram in _INSEPARABLE_BIGRAMS:
                return True
    return False


def _adjacent_pairs(chars: list[str]) -> list[tuple[str, str]]:
    return [(chars[i], chars[i + 1]) for i in range(len(chars) - 1)]


def _char_passes_strategy(
    element_cn: str | None,
    primary: list[str],
    secondary: list[str],
    avoid: list[str] | None,
    strategy: WuxingStrategy,
) -> bool:
    if not element_cn:
        return strategy == "reference"
    if strategy == "reference":
        return True
    ok, _ = matches_xiyongshen(element_cn, primary, secondary, avoid)
    return ok


def _score_pair(
    a: str,
    b: str,
    wx_map: dict[str, str],
    fate: FateAnalysis,
    strategy: WuxingStrategy,
    *,
    adjacent: bool,
) -> int:
    """双字名硬过滤：黑名单 + 五行策略。通过返回 1（后续由 _compute_meaning_score 评分），不通过返回 0."""
    if a in _NAME_BLACKLIST or b in _NAME_BLACKLIST:
        return 0
    wa, wb = wx_map.get(a), wx_map.get(b)
    avoid = fate.xiyongshen.avoid
    if not pair_passes_strategy(
        wa, wb, fate.xiyongshen.primary, fate.xiyongshen.secondary, avoid, strategy
    ):
        return 0
    return 1  # 通过硬过滤，实际评分由 _compute_meaning_score 决定


def _score_single(
    char: str,
    wx_map: dict[str, str],
    fate: FateAnalysis,
    strategy: WuxingStrategy,
    *,
    segment_chars: list[str],
) -> int:
    """单字名硬过滤：黑名单 + 五行策略。通过返回 1（后续由 _compute_meaning_score 评分），不通过返回 0."""
    if char in _NAME_BLACKLIST:
        return 0
    w = wx_map.get(char)
    avoid = fate.xiyongshen.avoid
    if not _char_passes_strategy(
        w, fate.xiyongshen.primary, fate.xiyongshen.secondary, avoid, strategy
    ):
        return 0
    return 1  # 通过硬过滤，实际评分由 _compute_meaning_score 决定


def _compute_meaning_score(
    chars: tuple[str, ...],
    wx_map: dict[str, str],
    fate: FateAnalysis,
    strategy: WuxingStrategy,
    *,
    adjacent: bool,
    segment_chars: list[str],
    citation: Any,
    surname: str = "",
    gender: str = "male",
    is_word: bool = False,
) -> int:
    """计算候选名综合评分.

    五行 → 硬过滤（_score_single/_score_pair 返回 0 则淘汰）
    平仄 → 主要评分维度（_tone_harmony_score，-8..+12）
    结构 → 相邻 +3、整词 +2
    次要 → 性别、典籍质量、白话译文
    """
    # ── 硬过滤：五行 + 黑名单 ──
    if len(chars) == 1:
        if _score_single(chars[0], wx_map, fate, strategy, segment_chars=segment_chars) <= 0:
            return 0
    elif len(chars) == 2:
        if _score_pair(chars[0], chars[1], wx_map, fate, strategy, adjacent=adjacent) <= 0:
            return 0
    else:
        return 0

    given = "".join(chars)

    # ── 硬过滤：姓+名同音碰撞（如 李+鲤）──
    if surname and _pinyin_collides(surname, given):
        return 0

    # ── 核心评分：平仄和谐度 ──
    if surname:
        score = _tone_harmony_score(surname, given)
    else:
        score = 4  # 无姓氏时中性基础分，依赖其他维度

    # ── 结构加分 ──
    if adjacent:
        score += 3  # 同词相邻字
    if is_word:
        score += 2  # 整词候选更自然

    # ── 次要维度 ──
    score += _gender_bonus(given, gender)
    score += _book_quality_bonus(citation)
    if getattr(citation, "vernacular", ""):
        score += 1

    return score


def _build_name_pool(
    citations: list,
    wx_map: dict[str, str],
    fate: FateAnalysis,
    strategy: WuxingStrategy,
    avoid_chars: list[str] | None,
    limit: int = 40,
    surname: str = "",
    gender: str = "male",
    word_wx_map: dict[str, str] | None = None,
) -> list[ScoredName]:
    """基于预分词数据构建候选名池。

    优先使用 citation.words（分词后存储的词语列表）。
    如果 words 为空，回退到旧的字级别提取。
    支持词级别五行映射（word_wx_map），双字实词可直接作为候选名。
    """
    from app.corpus.segment import is_content_word

    avoid = set(avoid_chars or [])
    scored: list[ScoredName] = []
    seen: set[tuple[str, ...]] = set()
    primary = fate.xiyongshen.primary
    secondary = fate.xiyongshen.secondary

    for cit in citations:
        words: list[str] = getattr(cit, "words", []) or []

        if words:
            # ── 基于分词的提取：语义正确，不会产生跨越词边界的名字 ──
            # 提取实词（过滤虚词）
            content_words = [w for w in words if is_content_word(w) and not any(c in avoid for c in w)]
            if not content_words:
                continue

            # 收集所有实词中的单字和双字
            all_chars: list[str] = []
            for w in content_words:
                all_chars.extend(list(w))
            all_chars = list(dict.fromkeys(all_chars))  # 去重保序

            # ── 词级别候选名：双字实词直接作为名字 ──
            # 仅使用已标注五行（适合人名）的词作为整体候选名；
            # 未标注或标注为不适合人名的词不直接作为候选名（其单字仍可参与组合）
            if word_wx_map:
                for w in content_words:
                    if len(w) != 2:
                        continue
                    if w in _NAME_BLACKLIST:
                        continue
                    # 词未在 word_wx_map 中（未标注或标注为不宜人名）：不作为整体候选
                    if w not in word_wx_map:
                        continue
                    key = (w[0], w[1])
                    if key in seen:
                        continue
                    if not _name_is_appropriate(w):
                        seen.add(key)
                        continue
                    meaning_score = _compute_meaning_score(
                        key, wx_map, fate, strategy,
                        adjacent=True,
                        segment_chars=all_chars,
                        citation=cit, surname=surname, gender=gender,
                        is_word=True,
                    )
                    if meaning_score < MIN_MEANING_SCORE:
                        continue
                    seen.add(key)
                    scored.append(ScoredName(
                        chars=key, citation=cit,
                        meaning_score=meaning_score, adjacent=True, is_word=True,
                    ))

            # 单字名：单字实词或复合词中的单字
            for char in all_chars:
                key = (char,)
                if key in seen:
                    continue
                # 找到该字所属的词（用于 adjacent 判断）
                parent_word = next((w for w in content_words if char in w), "")
                meaning_score = _compute_meaning_score(
                    key, wx_map, fate, strategy,
                    adjacent=False,
                    segment_chars=all_chars,
                    citation=cit, surname=surname, gender=gender,
                )
                if meaning_score < MIN_MEANING_SCORE:
                    continue
                seen.add(key)
                scored.append(ScoredName(chars=key, citation=cit, meaning_score=meaning_score))

            # 双字名
            if len(all_chars) >= 2:
                # 构建相邻对：同一复合词内的两个字是相邻的
                adjacent_pairs: set[tuple[str, str]] = set()
                for w in content_words:
                    if len(w) == 2:
                        adjacent_pairs.add((w[0], w[1]))

                # 所有实词中的字两两组合
                perm_chars = all_chars[: _MAX_SEGMENT_PERM_CHARS]
                for a, b in itertools.permutations(perm_chars, 2):
                    if a == b:
                        continue
                    key = (a, b)
                    if key in seen:
                        continue
                    if not _name_is_appropriate("".join(key)):
                        seen.add(key)
                        continue
                    is_adjacent = (a, b) in adjacent_pairs
                    meaning_score = _compute_meaning_score(
                        key, wx_map, fate, strategy,
                        adjacent=is_adjacent,
                        segment_chars=all_chars,
                        citation=cit, surname=surname, gender=gender,
                    )
                    if meaning_score < MIN_MEANING_SCORE:
                        continue
                    seen.add(key)
                    scored.append(
                        ScoredName(chars=key, citation=cit, meaning_score=meaning_score, adjacent=is_adjacent)
                    )
        else:
            # ── 回退：字级别提取（旧逻辑，兼容没有 words 字段的语料）──
            for segment in re.split(r"[。！？；\n]", cit.original):
                chars = [c for c in _extract_cjk(segment) if c not in avoid]
                if not chars:
                    continue
                segment_chars = list(dict.fromkeys(chars))

                for char in segment_chars:
                    key = (char,)
                    if key in seen:
                        continue
                    meaning_score = _compute_meaning_score(
                        key, wx_map, fate, strategy,
                        adjacent=False, segment_chars=segment_chars,
                        citation=cit, surname=surname, gender=gender,
                    )
                    if meaning_score < MIN_MEANING_SCORE:
                        continue
                    seen.add(key)
                    scored.append(ScoredName(chars=key, citation=cit, meaning_score=meaning_score))

                if len(chars) < 2:
                    continue
                pairs: list[tuple[str, str, bool]] = []
                for i, (a, b) in enumerate(_adjacent_pairs(chars)):
                    if not _crosses_inseparable_boundary(chars, i, i + 1):
                        pairs.append((a, b, True))
                perm_chars = segment_chars
                if len(perm_chars) > _MAX_SEGMENT_PERM_CHARS:
                    perm_chars = perm_chars[:_MAX_SEGMENT_PERM_CHARS]
                if len(perm_chars) >= 2:
                    adjacent_set = {(a, b) for a, b, _ in pairs}
                    for a, b in itertools.permutations(perm_chars, 2):
                        if (a, b) not in adjacent_set:
                            pairs.append((a, b, False))
                for a, b, adjacent in pairs:
                    if a == b:
                        continue
                    key = (a, b)
                    if key in seen:
                        continue
                    if not _name_is_appropriate("".join(key)):
                        seen.add(key)
                        continue
                    meaning_score = _compute_meaning_score(
                        key, wx_map, fate, strategy,
                        adjacent=adjacent, segment_chars=segment_chars,
                        citation=cit, surname=surname, gender=gender,
                    )
                    if meaning_score < MIN_MEANING_SCORE:
                        continue
                    seen.add(key)
                    scored.append(
                        ScoredName(chars=key, citation=cit, meaning_score=meaning_score, adjacent=adjacent)
                    )

    scored.sort(
        key=lambda x: (-x.meaning_score, -int(x.adjacent), -int(x.is_word), -len(x.chars), random.random())
    )

    # ── 候选名池日志 ──
    import logging
    _log = logging.getLogger("uvicorn")
    word_level = sum(1 for s in scored if len(s.chars) == 2 and s.adjacent)
    single_char = sum(1 for s in scored if len(s.chars) == 1)
    double_comb = sum(1 for s in scored if len(s.chars) == 2 and not s.adjacent)
    qualified = sum(1 for s in scored if s.meaning_score >= MIN_MEANING_SCORE)
    _log.info(
        "候选名池构建完成：词级%d 单字%d 双字组合%d | 去重后共%d个 | 得分≥%d的%d个 | 返回top%d",
        word_level, single_char, double_comb,
        len(scored), MIN_MEANING_SCORE, qualified,
        min(limit, len(scored)),
    )
    return scored[:limit]


# 兼容旧测试导入
_build_pair_pool = _build_name_pool


def _wuxing_summary(chars: tuple[str, ...], wx_map: dict[str, str]) -> tuple[dict[str, str], str]:
    wx = {c: wx_map.get(c, "?") for c in chars}
    summary = "、".join(dict.fromkeys(v for v in wx.values() if v != "?"))
    given = "".join(chars)
    label = f"{given}：{summary}" if summary else given
    return wx, label


def _rule_explanation(cit: Any, given: str, fate: FateAnalysis) -> tuple[str, str]:
    """生成典籍出处说明和名字寓意解释.

    优先利用白话译文提供具体的文化意涵，避免模板化的空洞表述。
    不同名字因典籍内容和名字长度的差异，会得到有区分的解释文本。
    """
    chapter = f"{cit.chapter} · " if getattr(cit, "chapter", "") else ""
    cite = f"取自《{cit.book}》{chapter}「{cit.original}」"
    if cit.vernacular:
        cite += f" {cit.vernacular}"

    xiyong = "、".join(fate.xiyongshen.primary)
    secondary = fate.xiyongshen.secondary
    vernacular = cit.vernacular or ""
    original = cit.original or ""

    # 从白话译文中提取意象线索（取首句或含名字关键字的句子）
    imagery_clue = _extract_imagery_clue(original, vernacular, given)

    # 五行表述：融入而非堆砌
    all_wx = list(dict.fromkeys(fate.xiyongshen.primary + (secondary or [])))
    wx_phrase = f"五行应{'/'.join(all_wx)}，合命格喜{xiyong}之需" if len(all_wx) <= 2 else \
                f"五行合喜用{'/'.join(all_wx)}"

    book_ref = _book_nickname(cit.book)

    if len(given) == 1:
        meaning = _single_char_meaning(given, book_ref, original, imagery_clue, wx_phrase)
    else:
        meaning = _double_char_meaning(given, book_ref, original, imagery_clue, wx_phrase)

    return cite, meaning


def _extract_imagery_clue(original: str, vernacular: str, given: str) -> str:
    """从白话译文中提取与名字相关的意象线索."""
    if not vernacular:
        return ""

    # 白话译文通常是原文的白话翻译或注解，取最相关的片段
    # 如果白话译文较短（≤40字），直接作为意象线索
    if len(vernacular) <= 40:
        return vernacular.rstrip("。，；")

    # 尝试找包含名字中某个字的部分
    for ch in given:
        idx = vernacular.find(ch)
        if idx >= 0:
            start = max(0, idx - 8)
            end = min(len(vernacular), idx + 16)
            snippet = vernacular[start:end].strip("。，；")
            if len(snippet) >= 6:
                return snippet

    # 回退：取白话译文前30字
    return vernacular[:30].rstrip("。，；") + "…"


def _book_nickname(book: str) -> str:
    """古典书名的雅称."""
    nicknames = {
        "诗经": "《诗》",
        "楚辞": "《楚辞》",
        "论语": "《论语》",
        "孟子": "《孟子》",
        "庄子": "《庄子》",
        "老子": "《老子》",
        "周易": "《易》",
        "尚书": "《书》",
        "礼记": "《礼记》",
        "春秋": "《春秋》",
        "唐诗三百首": "唐诗",
        "宋词三百首": "宋词",
        "元曲三百首": "元曲",
        "古诗十九首": "古诗",
        "文选": "《文选》",
        "史记": "《史记》",
        "汉书": "《汉书》",
        "世说新语": "《世说》",
        "菜根谭": "《菜根谭》",
        "围炉夜话": "《围炉夜话》",
        "小窗幽记": "《小窗幽记》",
        "幽梦影": "《幽梦影》",
        "随园诗话": "《随园诗话》",
        "人间词话": "《人间词话》",
    }
    if book in nicknames:
        return nicknames[book]
    if book.startswith("《") and book.endswith("》"):
        return book
    return f"《{book}》"


def _single_char_meaning(given: str, book_ref: str, original: str, imagery: str, wx_phrase: str) -> str:
    """单字名的寓意解释（避免模板化）."""
    short_orig = original[:20].rstrip("。，；")
    if imagery:
        patterns = [
            f"{given}：{book_ref}「{short_orig}」— {imagery}，取「{given}」字，{wx_phrase}，一字见天地。",
            f"{given}：典出{book_ref}{short_orig}，{imagery}，单字{given}独运，{wx_phrase}，简而有力。",
            f"{given}：{book_ref}中{imagery}，以「{given}」字点睛，{wx_phrase}，清简含章。",
        ]
    else:
        patterns = [
            f"{given}：撷{book_ref}「{short_orig}」之英，以「{given}」立名，{wx_phrase}，一字千钧。",
            f"{given}：{book_ref}精粹所钟，{wx_phrase}，以{given}字承载，至简至深。",
        ]
    return random.choice(patterns)


def _double_char_meaning(given: str, book_ref: str, original: str, imagery: str, wx_phrase: str) -> str:
    """双字名的寓意解释（避免模板化）."""
    short_orig = original[:18].rstrip("。，；")
    if imagery:
        patterns = [
            f"{given}：{book_ref}「{short_orig}」之境 — {imagery}，「{given}」二字，{wx_phrase}，清雅脱俗。",
            f"{given}：从{book_ref}走来，{imagery}，以「{given}」为名，{wx_phrase}，如对青山。",
            f"{given}：{book_ref}中{imagery}，「{given}」取其意，{wx_phrase}，名中有画。",
            f"{given}：典出{book_ref}，{imagery}，以{given}二字传其神，{wx_phrase}。",
        ]
    else:
        patterns = [
            f"{given}：{book_ref}「{short_orig}」之意，「{given}」雅正，{wx_phrase}，气韵生动。",
            f"{given}：撷{book_ref}之华，「{given}」清雅，{wx_phrase}，余味悠长。",
            f"{given}：{book_ref}清辞，「{given}」二字，{wx_phrase}，涵养深厚。",
        ]
    return random.choice(patterns)


async def _candidate_from_scored(
    surname: str,
    item: ScoredName,
    wx_map: dict[str, str],
    fate: FateAnalysis,
    rank: int,
) -> NameCandidate:
    given = item.given
    wx, label = _wuxing_summary(item.chars, wx_map)
    cite, meaning = _rule_explanation(item.citation, given, fate)
    from app.utils.text import to_simplified
    full = surname + given
    syllables = analyze_tone(full)
    return NameCandidate(
        rank=rank,
        full_name=to_simplified(full),
        given_name=to_simplified(given),
        meaning_score=item.meaning_score,
        citation_id=item.citation.id,
        citation_book=to_simplified(item.citation.book),
        citation_text=to_simplified(item.citation.original),
        citation_explanation=to_simplified(cite),
        vernacular=to_simplified(item.citation.vernacular or item.citation.original),
        meaning=to_simplified(meaning),
        wuxing={"chars": wx, "summary": label.split("：", 1)[-1] if "：" in label else label},
        wuxing_label=label,
        tone=syllables,
        tone_comment=_tone_comment(syllables, surname),
    )


def _candidate_from_llm_item(
    surname: str,
    item: dict[str, Any],
    cit: Any,
    wx_map: dict[str, str],
    fate: FateAnalysis,
    strategy: WuxingStrategy,
    rank: int,
    *,
    gender: str = "male",
) -> NameCandidate | None:
    given = item.get("given_name", "")
    if len(given) not in (1, 2):
        return None
    chars = tuple(given)
    meaning_score = item.get("meaning_score")
    if meaning_score is None:
        meaning_score = _compute_meaning_score(
            chars,
            wx_map,
            fate,
            strategy,
            adjacent=len(chars) == 2 and chars[0] + chars[1] in cit.original.replace(" ", ""),
            segment_chars=list(dict.fromkeys(_extract_cjk(cit.original))),
            citation=cit,
            surname=surname,
            gender=gender,
        )
    if meaning_score < MIN_MEANING_SCORE_LLM:
        return None
    from app.utils.text import to_simplified
    wx, default_label = _wuxing_summary(chars, wx_map)
    full = surname + given
    syllables = analyze_tone(full)
    return NameCandidate(
        rank=rank,
        full_name=to_simplified(full),
        given_name=to_simplified(given),
        meaning_score=int(meaning_score),
        citation_id=cit.id,
        citation_book=to_simplified(cit.book),
        citation_text=to_simplified(cit.original),
        citation_explanation=to_simplified(item.get("citation_explanation", f"取自《{cit.book}》：「{cit.original}」")),
        vernacular=to_simplified(cit.vernacular or cit.original),
        meaning=to_simplified(item.get("meaning", f"{given}：寓意美好。")),
        wuxing={"chars": wx, "summary": item.get("wuxing_label", default_label).split("：", 1)[-1]},
        wuxing_label=item.get("wuxing_label", default_label),
        tone=syllables,
        tone_comment=_tone_comment(syllables, surname),
    )


def _llm_available() -> bool:
    cfg = resolve_llm_config()
    return not cfg["mock"] and bool(cfg["api_key"])


# 不适合人名使用的负面/不雅字词（含单字和组合）
_NAME_BLACKLIST: set[str] = {
    # 负面情绪
    "怨", "恨", "悲", "哀", "愁", "忧", "惧", "怕", "惮", "怖", "恼", "烦", "怒", "仇",
    # 负面形容词
    "浊", "污", "脏", "乱", "糟", "坏", "劣", "差",
    # 暴力刑罚
    "杀", "戮", "刑", "罚", "罪", "恶", "凶", "灾", "祸", "难",
    # 死亡丧葬
    "死", "亡", "丧", "葬", "殁", "殂", "殉",
    # 动物牲畜（不适合人名）
    "兽", "蹄", "狮", "狼", "狐", "鼠", "犬", "豕", "豚", "彘", "蛇", "蝎", "蛆",
    "牛", "马", "驴", "骡", "鸡", "鸭", "鹅", "鸽", "雀", "鸦", "蛙", "蛤", "鳖",
    "鼋", "龟", "鳖", "鳄", "鲸", "鲨", "蚌", "蛎",
    # 污秽肮脏
    "辱", "耻", "贱", "卑", "淫", "盗", "贼", "寇", "虏", "丐", "娼",
    "朽", "腐", "臭", "秽", "粪", "尿", "痰", "脓", "屎", "屁",
    # 鬼怪妖魔
    "鬼", "魅", "魍", "魉", "魔", "妖", "怪", "魂", "魄",
    # 病残
    "病", "疾", "痛", "疼", "痒", "残", "废", "瘸", "瞎", "聋", "哑", "瘫",
    # 负面评价
    "蠢", "笨", "傻", "呆", "痴", "愚", "惰", "懒", "贪", "吝", "诈", "伪", "虚",
    # 不适合人名组合（含历史人物称谓、不良组合等）
    "烦恼", "感襄", "无怕", "无惮", "紫裘", "燕黄", "涉西", "测鼋",
    "波浪", "湿浸", "望而", "水而", "有学", "沧浪",
    # 历史人物称谓 — 直接使用会混淆
    "孔子", "孟子", "老子", "庄子", "荀子", "墨子", "韩非",
    "秦皇", "汉武", "唐宗", "宋祖", "诸葛", "关公",
    "仲尼", "子舆", "伯阳",
    # 过于直白/普通的名词组合（缺乏人名应有的意蕴）
    "流水", "落花", "落叶", "白云", "青山", "绿水",
    # 自然现象（过于直白不适合人名）
    "雷", "电", "雹", "雾", "霾", "飓", "飚",
}

# 女性名字偏好字（温婉、美好、花卉、珍宝、自然）
_FEMALE_PREFERRED_CHARS: set[str] = {
    "秀", "丽", "美", "娟", "婷", "娜", "婉", "娴", "淑", "静", "雅", "洁",
    "花", "兰", "莲", "梅", "菊", "荷", "薇", "蓉", "萱", "芝", "桂", "芬", "芳",
    "玉", "琳", "瑶", "瑾", "瑜", "珍", "珠", "珊", "瑚", "玫", "瑰", "琪",
    "云", "月", "霞", "雯", "霓", "露", "雪", "虹", "霁",
    "凤", "燕", "莺", "鹊", "鸾", "蝶",
    "慧", "敏", "灵", "巧", "妙", "仪", "容", "姿", "韵", "彩",
    "春", "秋", "晓", "晨", "曦", "暖",
    "琴", "棋", "书", "画", "诗", "歌", "舞",
    "柔", "润", "盈", "晴", "宁", "安", "若", "如", "亦",
    "思", "念", "忆", "怀", "依", "恋",
}

# 男性名字偏好字（刚毅、道德、山川、志向、光明）
_MALE_PREFERRED_CHARS: set[str] = {
    "刚", "强", "伟", "毅", "勇", "猛", "威", "武", "豪", "杰", "雄",
    "德", "仁", "义", "礼", "智", "信", "忠", "孝", "廉", "节", "诚", "正", "直",
    "山", "峰", "岳", "峦", "岩", "岭", "江", "河", "海", "涛", "潮", "澜", "泽",
    "志", "宏", "远", "博", "达", "通", "广", "阔", "浩", "瀚",
    "明", "辉", "光", "亮", "耀", "焕", "炳", "烨", "灿",
    "龙", "虎", "鹏", "鸿", "鹰", "骏", "骥",
    "天", "宇", "霄", "昊", "乾", "坤", "辰", "星",
    "松", "柏", "竹", "树", "林", "森",
    "文", "章", "学", "才", "彦", "哲", "圣",
    "修", "建", "立", "成", "兴", "盛", "昌", "隆",
    "剑", "鼎", "铭", "钧", "锋", "锐",
    "子", "君", "卿", "侯", "伯", "彦",
}

# 性别中立或通用吉祥字
_UNISEX_CHARS: set[str] = {
    "安", "然", "之", "以", "其", "斯", "如", "若",
    "清", "澄", "澈", "泓", "淳", "源",
    "景", "观", "致", "道", "玄", "真",
    "永", "恒", "长", "久", "常", "一",
    "善", "良", "和", "平", "祥", "瑞", "吉", "庆",
    "嘉", "悦", "欣", "怡", "乐", "欢", "畅",
    "博", "厚", "高", "悠", "逸", "远", "修",
    "心", "中", "元", "本", "初", "新",
    "行", "言", "知", "闻", "观", "览",
}


def _name_is_appropriate(given: str) -> bool:
    """检查名字是否适合人名使用，含网红名过滤."""
    for word in _NAME_BLACKLIST:
        if word in given:
            return False
    # 网红风名完全禁止
    if given in _TRENDY_NAME_BLACKLIST:
        return False
    # 检查是否完全由古典虚词/指代字组成（无实义的名字）
    if _is_semantically_empty(given):
        return False
    return True


# 古典虚词、指代词、称谓用字——单独作为名字成分时无实义
_SEMANTICALLY_EMPTY_CHARS: set[str] = {
    "之", "乎", "者", "也", "矣", "焉", "哉", "兮", "耳", "而",
    "曰", "云", "谓", "言", "语", "说", "道",
    "子", "公", "王", "侯", "君", "臣", "师", "生", "夫",
    "此", "其", "彼", "是", "斯", "兹", "尔", "吾", "余", "予",
    "不", "无", "非", "未", "莫", "勿",
    "乃", "则", "且", "因", "故", "虽", "然", "若", "苟",
}


def _is_semantically_empty(given: str) -> bool:
    """检查名字是否完全由虚词/指代词组成（如'之子''也夫'等无实义组合）."""
    # 单字：如果是虚词/称谓，拒绝
    if len(given) == 1:
        return given in _SEMANTICALLY_EMPTY_CHARS
    # 双字：两个字都是虚词/称谓/指代 → 拒绝
    return all(ch in _SEMANTICALLY_EMPTY_CHARS for ch in given)


def _common_name_penalty(given: str) -> int:
    """返回名字普通程度扣分：完全匹配热门名扣10分，每含一个过度使用字扣2分."""
    penalty = 0
    if given in _COMMON_GIVEN_NAMES:
        penalty += 10
    for ch in given:
        if ch in _OVERUSED_CHARS:
            penalty += 2
    return min(penalty, 12)  # 上限12分


def _book_quality_bonus(citation: Any) -> int:
    """根据语料来源质量给予加分."""
    return BOOK_QUALITY_SCORE.get(citation.book, DEFAULT_BOOK_QUALITY) - 1


def _gender_bonus(given: str, gender: str) -> int:
    """根据性别偏好字加分：匹配性别偏好字加分，匹配异性偏好字减分."""
    if gender not in ("male", "female"):
        return 0
    preferred = _FEMALE_PREFERRED_CHARS if gender == "female" else _MALE_PREFERRED_CHARS
    opposite = _MALE_PREFERRED_CHARS if gender == "female" else _FEMALE_PREFERRED_CHARS

    bonus = 0
    for ch in given:
        if ch in preferred:
            bonus += 2
        elif ch in opposite:
            bonus -= 2  # 异性偏好字扣分
        elif ch in _UNISEX_CHARS:
            bonus += 1  # 通用吉祥字小幅加分
    return bonus


def _book_from_source(src: str) -> str:
    """从「《书名》原文句」或「书名」中提取书名."""
    if "》" in src and "《" in src:
        return src.split("》")[0].replace("《", "").strip()
    if "《" in src:
        inner = src.split("《")[1]
        return inner.split("》")[0].strip() if "》" in inner else inner.strip()
    return ""


def _free_sources_traceable(given: str, item: dict, citations: list) -> bool:
    """校验自由创作候选可溯源：每个字声称的出处（书名+原文）必须能在语料库中回查."""
    char_books: dict[str, set[str]] = {}
    for c in citations:
        for ch in (c.chars or []):
            char_books.setdefault(ch, set()).add(c.book)
    sources = [item.get("char1_source", ""), item.get("char2_source", "")]
    if len(given) == 1:
        sources = sources[:1]
    for ch, src in zip(given, sources):
        book = _book_from_source(src)
        if not book:
            return False
        if ch not in char_books or book not in char_books[ch]:
            return False
    return True


def _validate_llm_item(
    item: dict[str, Any],
    cit_map: dict[str, Any],
    wx_map: dict[str, str],
    fate: FateAnalysis,
    strategy: WuxingStrategy,
    *,
    surname: str = "",
) -> bool:
    given = item.get("given_name", "")
    if len(given) not in (1, 2):
        return False
    if not _name_is_appropriate(given):
        return False
    # 命中热门名直接拒绝
    if given in _COMMON_GIVEN_NAMES:
        return False
    # 同音碰撞检测
    if surname and _pinyin_collides(surname, given):
        return False
    cid = item.get("citation_id")
    cit = cit_map.get(cid)
    if not cit:
        return False
    if not all(ch in cit.chars for ch in given):
        return False
    if len(given) == 1:
        return _char_passes_strategy(
            wx_map.get(given[0]),
            fate.xiyongshen.primary,
            fate.xiyongshen.secondary,
            fate.xiyongshen.avoid,
            strategy,
        )
    return pair_passes_strategy(
        wx_map.get(given[0]),
        wx_map.get(given[1]),
        fate.xiyongshen.primary,
        fate.xiyongshen.secondary,
        fate.xiyongshen.avoid,
        strategy,
    )


async def _select_from_rules(
    surname: str,
    ranked: list[ScoredName],
    wx_map: dict[str, str],
    fate: FateAnalysis,
    used: set[str],
    used_books: set[str],
    start_rank: int = 1,
    name_length: str = "any",
) -> list[NameCandidate]:
    """从排名池中加权随机选取，不限制数量."""
    results: list[NameCandidate] = []
    target_unique_books = 6

    # 选取高分候选池
    candidate_pool = [item for item in ranked if item.given not in used]

    if not candidate_pool:
        return results

    # 按得分分组，组内随机打乱，高分优先但同分随机
    random.shuffle(candidate_pool)
    candidate_pool.sort(key=lambda x: (-x.meaning_score, -int(x.adjacent), random.random()))

    for item in candidate_pool:
        given = item.given
        if given in used:
            continue
        if name_length == "single" and len(given) != 1:
            continue
        if name_length == "double" and len(given) != 2:
            continue
        if item.citation.book in used_books and len(used_books) < target_unique_books:
            continue
        results.append(
            await _candidate_from_scored(surname, item, wx_map, fate, start_rank + len(results))
        )
        used.add(given)
        used_books.add(item.citation.book)

    # 放宽书籍去重限制，继续选取剩余候补
    remaining = [item for item in ranked if item.given not in used]
    random.shuffle(remaining)
    remaining.sort(key=lambda x: (-x.meaning_score, random.random()))
    for item in remaining:
        given = item.given
        if given in used:
            continue
        results.append(
            await _candidate_from_scored(surname, item, wx_map, fate, start_rank + len(results))
        )
        used.add(given)
    return results


def _finalize_candidates(
    results: list[NameCandidate],
    *,
    name_length: str = "any",
) -> list[NameCandidate]:
    qualified = [c for c in results if c.meaning_score >= MIN_MEANING_SCORE]
    # 按name_length过滤
    if name_length == "single":
        qualified = [c for c in qualified if len(c.given_name) == 1]
    elif name_length == "double":
        qualified = [c for c in qualified if len(c.given_name) == 2]
    qualified.sort(key=lambda c: (-c.meaning_score, c.rank))
    out: list[NameCandidate] = []
    for i, c in enumerate(qualified[:10], 1):
        out.append(c.model_copy(update={"rank": i}))
    return out


async def prepare_name_data(
    session: AsyncSession,
    surname: str,
    xiyongshen_primary: list[str],
    xiyongshen_secondary: list[str],
    output_count: int,
    *,
    xiyongshen_avoid: list[str] | None = None,
    avoid_chars: list[str] | None = None,
    strategy: WuxingStrategy = "strict",
    gender: str = "male",
    wx_map: dict[str, str] | None = None,
) -> NamePrecomputed:
    """预计算命名所需数据，可与 FateAnalysisAgent 并行执行.

    由于 FateAnalysisAgent 强制 xiyongshen.primary 匹配引擎输出，
    此函数使用 analysis.xiyongshen 直接计算，结果等价。
    """
    if wx_map is None:
        wx_map = await load_wuxing_map(session)

    # 加载词级别五行映射
    try:
        from app.corpus.search import load_word_wuxing_map as _load_word_wx
        word_wx_map = await _load_word_wx(session)
    except Exception:
        word_wx_map = {}

    citation_limit = _citation_limit(output_count)
    citations = await search_citations(
        session,
        xiyongshen_primary,
        xiyongshen_secondary=xiyongshen_secondary,
        limit=citation_limit,
        avoid_chars=avoid_chars,
        wx_map=wx_map,
        word_wx_map=word_wx_map,
    )
    # 构建一个临时的 FateAnalysis 用于评分（仅用到 xiyongshen 字段）
    pool_limit = _pool_limit(output_count)
    ranked = _build_name_pool_with_xy(
        citations, wx_map, xiyongshen_primary, xiyongshen_secondary,
        strategy, avoid_chars, xiyongshen_avoid,
        limit=pool_limit, surname=surname, gender=gender,
        word_wx_map=word_wx_map,
    )
    return NamePrecomputed(wx_map=wx_map, citations=citations, ranked=ranked)


def _build_name_pool_with_xy(
    citations: list,
    wx_map: dict[str, str],
    primary: list[str],
    secondary: list[str],
    strategy: WuxingStrategy,
    avoid_chars: list[str] | None,
    xiyongshen_avoid: list[str] | None = None,
    limit: int = 40,
    surname: str = "",
    gender: str = "male",
    word_wx_map: dict[str, str] | None = None,
) -> list[ScoredName]:
    """与 _build_name_pool 相同，直接接受 xiyongshen 列表，委托给 _build_name_pool."""
    from app.models.schemas import Xiyongshen
    fate_lite = FateAnalysis(
        vernacular="",
        xiyongshen=Xiyongshen(primary=primary, secondary=secondary, avoid=xiyongshen_avoid or []),
    )
    return _build_name_pool(
        citations, wx_map, fate_lite, strategy, avoid_chars,
        limit=limit, surname=surname, gender=gender,
        word_wx_map=word_wx_map,
    )




async def generate_candidates(
    session: AsyncSession,
    surname: str,
    fate: FateAnalysis,
    output_count: int,
    *,
    preferences: NamePreferences | None = None,
    gender: str = "male",
    precomputed: NamePrecomputed | None = None,
    skip_curator: bool = False,
    session_id: str = "",
    on_progress=None,
) -> list[NameCandidate]:
    import logging
    _log = logging.getLogger("uvicorn")
    t0 = time.perf_counter()

    prefs = preferences or NamePreferences()
    strategy: WuxingStrategy = prefs.wuxing_strategy
    avoid = prefs.avoid_chars

    # ── 加载用户历史名字，避免重复推荐 ──
    history_names: set[str] = set()
    if session_id:
        try:
            from app.db.session import UserNameHistory
            result = await session.execute(
                select(UserNameHistory.given_name).where(
                    UserNameHistory.session_id == session_id
                )
            )
            history_names = {r[0] for r in result.all()}
            if history_names:
                import logging
                _log = logging.getLogger("uvicorn")
                _log.info("用户历史名字 %d 个，将在候选池中过滤", len(history_names))
        except Exception:
            pass

    if precomputed is not None:
        wx_map = precomputed.wx_map
        citations = precomputed.citations
        ranked = precomputed.ranked
    else:
        wx_map = await load_wuxing_map(session)

        # 加载词级别五行映射
        try:
            from app.corpus.search import load_word_wuxing_map as _load_word_wx
            word_wx_map = await _load_word_wx(session)
        except Exception:
            word_wx_map = {}

        # 一次获取足够多的语料（大幅扩量，让 LLM 有更多素材）
        citation_limit = _citation_limit(output_count)
        citations = await search_citations(
            session,
            fate.xiyongshen.primary,
            xiyongshen_secondary=fate.xiyongshen.secondary,
            limit=citation_limit,
            avoid_chars=avoid,
            wx_map=wx_map,
            word_wx_map=word_wx_map,
        )
        pool_limit = _pool_limit(output_count)
        ranked = _build_name_pool(citations, wx_map, fate, strategy, avoid, limit=pool_limit, surname=surname, gender=gender, word_wx_map=word_wx_map)

    results: list[NameCandidate] = []
    used: set[str] = set()
    used_books: set[str] = set()
    cit_map = {c.id: c for c in citations}
    name_hints = [
        {
            "given_name": s.given,
            "citation_id": s.citation.id,
            "meaning_score": s.meaning_score,
        }
        for s in ranked[: _hint_limit(output_count)]
    ]

    # ── 五行预计算通过集（自由模式合并也需使用）──
    wx_sets = _WuxingPassSets(
        wx_map, fate.xiyongshen.primary,
        fate.xiyongshen.secondary, fate.xiyongshen.avoid, strategy,
    )

    if on_progress:
        await on_progress("names", "音韵分析", "正在分析姓与候选名的平仄搭配…")

    t_retrieval = time.perf_counter() - t0
    t_llm = 0.0
    t_curator = 0.0
    _log.info("⏱ 语料检索+候选名池构建完成：%.2fs | 池=%d个", t_retrieval, len(ranked))

    # ── 三层并行：LLM 约束模式 + 自由创作 + 规则选取同时执行 ──
    if _llm_available() and ranked:
        async def _run_constrained():
            """约束模式：3 路并行，每路使用不同的典籍子集."""
            try:
                # 将 citations 按 round-robin 分成 3 组，每组覆盖不同典籍
                buckets: list[list] = [[], [], []]
                for i, cit in enumerate(citations):
                    buckets[i % 3].append(cit)

                async def _run_one(bucket_cits: list, bucket_idx: int):
                    agent = NameComposeAgent()
                    top_c = bucket_cits[:15]  # 每组取 top 15 条作为上下文锚点

                    # 从该 bucket 对应的 ranked pool 中提取 char_pool
                    bucket_cit_ids = {c.id for c in bucket_cits}
                    char_seen: set[str] = set()
                    _char_pool: list[dict] = []
                    for s in ranked:
                        if getattr(s.citation, "id", "") not in bucket_cit_ids:
                            continue
                        for ch in s.chars:
                            if ch in char_seen:
                                continue
                            char_seen.add(ch)
                            syl, _ = _cached_tone(ch)
                            _char_pool.append({
                                "char": ch,
                                "element": wx_map.get(ch, "?"),
                                "tone_label": syl.tone_label,
                                "pinyin": syl.pinyin,
                            })
                            if len(_char_pool) >= 150:
                                break
                        if len(_char_pool) >= 150:
                            break

                    # 从该 bucket 提取 word_pool
                    _word_pool: list[dict] = []
                    for s in ranked:
                        if not s.is_word or len(s.chars) != 2:
                            continue
                        if getattr(s.citation, "id", "") not in bucket_cit_ids:
                            continue
                        _word_pool.append({
                            "word": s.given,
                            "element": wx_map.get(s.given[0], "?") + wx_map.get(s.given[1], "?"),
                            "book": getattr(s.citation, "book", ""),
                            "original_snippet": (getattr(s.citation, "original", "") or "")[:80],
                        })
                        if len(_word_pool) >= 40:
                            break

                    composed = await agent.compose(
                        surname, top_c, fate,
                        name_hints=name_hints[:100],  # 每组给 100 条 hints
                        char_pool=_char_pool,
                        word_pool=_word_pool,
                        wuxing_strategy=strategy,
                        gender=gender,
                    )
                    if on_progress:
                        await on_progress(
                            "names",
                            "约束组名",
                            f"第 {bucket_idx + 1} 路典籍意象已生成…",
                        )
                    return [("constrained", item) for item in composed]

                # 3 路并行
                all_results = await asyncio.gather(
                    _run_one(buckets[0], 0),
                    _run_one(buckets[1], 1),
                    _run_one(buckets[2], 2),
                    return_exceptions=True,
                )
                merged: list = []
                for r in all_results:
                    if isinstance(r, list):
                        merged.extend(r)
                return merged
            except Exception:
                return []

        async def _run_free():
            if not wx_map:
                return []
            try:
                free_agent = NameFreeComposeAgent()
                # 构建五行预过滤字池：只包含通过策略的字符（复用外部 wx_sets）
                _free_char_pool: list[dict] = []
                for s in ranked:
                    for ch in s.chars:
                        if not wx_sets.char_passes(ch):
                            continue
                        # check if already added
                        if any(c["char"] == ch for c in _free_char_pool):
                            continue
                        syl, base = _cached_tone(ch)
                        _free_char_pool.append({
                            "char": ch,
                            "element": wx_map.get(ch, "?"),
                            "tone_label": syl.tone_label,
                            "pinyin": syl.pinyin,
                            "source_books": [getattr(s.citation, "book", "")],
                            "sample_context": (getattr(s.citation, "original", "") or "")[:60],
                            "source_count": 1,
                        })
                free_composed = await free_agent.compose(
                    surname,
                    citations[: min(20, max(10, output_count * 2))],
                    fate,
                    wx_map=wx_map,
                    gender=gender,
                    char_pool=_free_char_pool,
                )
                return [("free", item) for item in free_composed]
            except Exception:
                return []

        async def _run_rules():
            """规则选取作为后备，与 LLM 并行执行."""
            try:
                return await _select_from_rules(
                    surname, ranked, wx_map, fate,
                    set(), set(), start_rank=1,
                    name_length=prefs.name_length,
                )
            except Exception:
                return []

        if on_progress:
            await on_progress("names", "创作候选名", "正在运用古典意象创作候选名字…")

        async def _tracked(coro, title: str, summary: str):
            """分支完成后立刻推送进度，不等待其它分支."""
            result = await coro
            if on_progress:
                await on_progress("names", title, summary)
            return result

        # 三路并行（各路完成时分别发进度）
        t_before_llm = time.perf_counter()
        constrained_results, free_results, rule_results = await asyncio.gather(
            _tracked(_run_constrained(), "约束组名", "三路典籍意象组名已完成…"),
            _tracked(_run_free(), "自由创作", "自由创作分支已完成…"),
            _tracked(_run_rules(), "规则优选", "规则层候选已就绪…"),
        )
        t_llm = time.perf_counter() - t_before_llm

        _log.info(
            "⏱ 起名三路并行完成：%.2fs | 约束LLM=%d个 自由LLM=%d个 规则选取=%d个",
            t_llm, len(constrained_results), len(free_results), len(rule_results),
        )

        if on_progress:
            await on_progress("names", "创作候选名", "候选已汇合，准备精选…")

        # 合并：LLM 约束模式优先 → 自由创作 → 规则选取补足
        for tag, item in constrained_results:
            if not _validate_llm_item(item, cit_map, wx_map, fate, strategy, surname=surname):
                continue
            given = item["given_name"]
            if given in used or given in history_names:
                continue
            cit = cit_map[item["citation_id"]]
            candidate = _candidate_from_llm_item(
                surname, item, cit, wx_map, fate, strategy, len(results) + 1,
                gender=gender,
            )
            if candidate is None:
                continue
            results.append(candidate)
            used.add(given)
            used_books.add(cit.book)

        for tag, item in free_results:
            given = item.get("given_name", "")
            if len(given) not in (1, 2):
                continue
            if not _name_is_appropriate(given):
                continue
            if given in used or given in _COMMON_GIVEN_NAMES or given in history_names:
                continue
            if not all(ch in wx_map for ch in given):
                continue
            if not _free_sources_traceable(given, item, citations):
                continue
            # 五行策略校验（当前缺失的硬过滤）
            if not wx_sets.char_passes(given[0]):
                continue
            if len(given) == 2 and not wx_sets.char_passes(given[1]):
                continue
            if len(given) == 2 and not wx_sets.pair_passes(given[0], given[1]):
                continue
            # 同音碰撞检测
            if _pinyin_collides(surname, given):
                continue
            meaning_score = item.get("meaning_score", 6)
            wx_chars = {ch: wx_map.get(ch, "?") for ch in given}
            wx_summary = "、".join(dict.fromkeys(v for v in wx_chars.values() if v != "?"))
            full = surname + given
            syllables = analyze_tone(full)
            from app.utils.text import to_simplified
            candidate = NameCandidate(
                rank=len(results) + 1,
                full_name=to_simplified(full),
                given_name=to_simplified(given),
                meaning_score=int(meaning_score),
                citation_id="free-" + given,
                citation_book=to_simplified(item.get("char1_source", "").split("》")[0].replace("《", "") if "》" in item.get("char1_source", "") else "自由创作"),
                citation_text=to_simplified(item.get("char1_source", "") + "；" + item.get("char2_source", "")),
                citation_explanation=to_simplified(f"自由创作：{item.get('creative_rationale', '')}"),
                vernacular=to_simplified(item.get("meaning", "")),
                meaning=to_simplified(item.get("meaning", f"{given}：古典意象的自由组合，寓意美好。")),
                wuxing={"chars": wx_chars, "summary": wx_summary},
                wuxing_label=f"{given}：{wx_summary}" if wx_summary else given,
                tone=syllables,
                tone_comment=_tone_comment(syllables, surname),
            )
            results.append(candidate)
            used.add(given)

        # 规则选取补足：去除与 LLM 结果重复的
        for rc in rule_results:
            if rc.given_name in used:
                continue
            rc.rank = len(results) + 1
            results.append(rc)
            used.add(rc.given_name)
    else:
        # 无 LLM 时仅用规则选取
        rule_results = await _select_from_rules(
            surname, ranked, wx_map, fate,
            used, used_books, start_rank=len(results) + 1,
            name_length=prefs.name_length,
        )
        results.extend(rule_results)

    # ── LLM 精选润色层（可跳过以加速响应）──
    t_before_curator = time.perf_counter()
    if _llm_available() and results and not skip_curator:
        if on_progress:
            await on_progress("names", "精选排名", "正在对候选名进行深度解读与排名…")
        try:
            from app.agents import NameCuratorAgent
            curator = NameCuratorAgent()
            candidate_dicts = [
                {
                    "given_name": c.given_name,
                    "full_name": c.full_name,
                    "citation_book": c.citation_book,
                    "citation_text": c.citation_text,
                    "meaning": c.meaning,
                    "meaning_score": c.meaning_score,
                    "wuxing_label": c.wuxing_label,
                    "tone_comment": c.tone_comment,
                    "tone_pattern": "".join(s.tone_label for s in c.tone) if c.tone else "",
                    "pinyin": " ".join(s.pinyin for s in c.tone[len(surname):]) if c.tone else "",
                }
                for c in results
            ]
            curated = await curator.curate(surname, candidate_dicts, fate, gender)
            if curated:
                # 应用精选结果：重新排名 + 深度解读替换 + 标记首推 + 评分替代
                kept = [c for c in curated if c.get("keep", True)]
                curated_map = {c["given_name"]: c for c in kept}
                new_results: list[NameCandidate] = []
                new_rank = 1
                for c in results:
                    cc = curated_map.get(c.given_name)
                    if cc is None:
                        continue
                    # 替换深度解读
                    if cc.get("curated_meaning"):
                        c.meaning = cc["curated_meaning"]
                    if cc.get("is_top_pick"):
                        c.meaning = "★ 首推 ★ " + c.meaning
                    # LLM curator 评分替代规则评分
                    if cc.get("meaning_score") is not None:
                        c.meaning_score = cc["meaning_score"]
                    c.rank = new_rank
                    new_results.append(c)
                    new_rank += 1
                if new_results:
                    results = new_results
        except Exception:
            pass  # 精选层失败不影响主流程

    t_curator = time.perf_counter() - t_before_curator
    final = _finalize_candidates(results, name_length=prefs.name_length)
    t_total = time.perf_counter() - t0
    _log.info(
        "⏱ 起名候选生成完成：总%.2fs | 检索%.2fs LLM%.2fs 精选%.2fs | 最终%d个 %s",
        t_total, t_retrieval, t_llm, t_curator,
        len(final), [c.full_name for c in final],
    )

    # ── LLM 反馈闭环：记录候选名到 word_wuxing + user_name_history ──
    if final and session_id:
        try:
            await _record_name_feedback(session, final, wx_map)
            await _record_user_history(session, session_id, final)
        except Exception:
            pass  # 反馈记录失败不影响主流程

    return final


# ── LLM 反馈闭环 ──

_ELEMENT_EN_TO_CN = {
    "metal": "金", "wood": "木", "water": "水", "fire": "火", "earth": "土",
}
_ELEMENT_CN_TO_EN = {v: k for k, v in _ELEMENT_EN_TO_CN.items()}


async def _record_name_feedback(
    session: AsyncSession,
    candidates: list[NameCandidate],
    wx_map: dict[str, str],
) -> None:
    """记录 LLM 返回的名字评分到 word_wuxing 表."""
    from datetime import datetime as dt, timezone

    from app.db.session import WordWuxingRecord

    now = dt.now(timezone.utc)
    for c in candidates:
        given = c.given_name
        if len(given) < 2:
            continue  # 单字名不记录到 word_wuxing

        existing = await session.get(WordWuxingRecord, given)
        if existing:
            existing.score = (existing.score or 0) + c.meaning_score
            existing.pick_count = (existing.pick_count or 0) + 1
        else:
            element_cn = wx_map.get(given[0], "?")
            if len(given) == 2:
                e2 = wx_map.get(given[1], "?")
                if e2 != "?" and e2 != element_cn:
                    element_cn = element_cn + "、" + e2
            session.add(WordWuxingRecord(
                word=given,
                element=_ELEMENT_CN_TO_EN.get(element_cn.split("、")[0], "?"),
                element_cn=element_cn,
                confidence="llm",
                source="llm_create",
                reasoning=c.meaning[:256] if c.meaning else None,
                score=c.meaning_score,
                pick_count=1,
                suitable_for_name=True,
                annotated_at=now,
            ))
    await session.commit()


async def _record_user_history(
    session: AsyncSession,
    session_id: str,
    candidates: list[NameCandidate],
) -> None:
    """记录用户报告中出现过的名字."""
    from app.db.session import UserNameHistory

    for c in candidates:
        session.add(UserNameHistory(
            session_id=session_id,
            given_name=c.given_name,
        ))
    await session.commit()
