"""古汉语分词 —— 基于标点切分 + 复合词词典 + jieba 兜底.

将 "荏染柔木，君子树之。往来行言，心焉数之。" 切分为：
["荏染", "柔木", "君子", "树", "之", "往来", "行", "言", "心", "焉", "数", "之"]
"""

from __future__ import annotations

import re
from functools import lru_cache

# 古汉语常见双字复合词 —— 遇到时优先作为一个词，不拆分
_CLASSICAL_COMPOUNDS: set[str] = {
    # 人物伦理
    "君子", "小人", "圣人", "贤人", "大人", "丈人", "夫子", "弟子",
    # 历史人物（应作为整体识别，避免单独用其名）
    "孔子", "孟子", "老子", "庄子", "荀子", "墨子", "韩非", "孙子",
    "秦皇", "汉武", "唐宗", "宋祖", "诸葛", "关公", "仲尼", "子舆",
    "父母", "兄弟", "夫妇", "君臣", "父子", "朋友", "宾客", "仇雠",
    # 天地自然
    "天下", "天地", "日月", "星辰", "风雨", "雷霆", "霜雪", "云霞",
    "山海", "山河", "江山", "江湖", "沧海", "桑田", "草木", "花鸟",
    "蒹葭", "芍药", "杜若", "薜荔", "兰芷", "琼瑶", "玫瑰", "麒麟", "凤凰",
    # 时间
    "春秋", "朝夕", "旦暮", "寒暑", "古今",
    # 德行修养
    "仁义", "道德", "礼乐", "忠信", "孝悌", "廉耻", "恭敬", "宽恕",
    "刚毅", "木讷", "温良", "恭俭", "谦让",
    # 政事
    "社稷", "黎民", "百姓", "王侯", "将相", "公卿", "大夫", "诸侯",
    "天下", "国家", "朝廷", "宗庙",
    # 文艺
    "琴瑟", "钟鼓", "笙箫", "文章", "诗书", "礼乐",
    # 状态/动作（连绵词/叠韵词）
    "逍遥", "寂寥", "徘徊", "踌躇", "彷徨", "窈窕", "婆娑", "蹉跎",
    "辗转", "缱绻", "缠绵", "朦胧", "浩荡", "慷慨", "澎湃",
    # 常见虚词组合
    "可以", "足以", "是以", "是故", "于是", "然而", "然后", "虽然",
    "以为", "所以", "至于", "至于", "而已", "而已",
    # 诗经常见
    "关关", "雎鸠", "窈窕", "参差", "寤寐", "琴瑟", "桃夭",
    # 楚辞常见
    "离骚", "九歌", "天问", "招魂",
    "江离", "辟芷", "秋兰", "宿莽", "木兰", "秋菊",
    "鸾鸟", "凤皇", "蛟龙", "骐骥",
}

# 单字虚词/指代词 —— 分词后保留但标记为虚词（命名时不优先使用）
_FUNCTION_CHARS: set[str] = {
    "之", "乎", "者", "也", "矣", "焉", "哉", "兮", "耳", "而",
    "曰", "云", "谓",
    "此", "其", "彼", "是", "斯", "兹", "尔", "吾", "余", "予",
    "不", "无", "非", "未", "莫", "勿",
    "乃", "则", "且", "因", "故", "虽", "然", "若", "苟",
    "于", "以", "为", "与", "及", "自", "从", "由",
    "所", "何", "孰", "安", "奚", "胡", "曷",
}

_CJK = re.compile(r"[一-鿿]")


@lru_cache(maxsize=2048)
def segment_sentence(text: str) -> list[str]:
    """将一句古文切分为词语列表.

    策略: 先匹配已知复合词 → 剩余单字各自成词
    """
    if not text:
        return []

    # 仅保留汉字
    clean = "".join(_CJK.findall(text))
    if not clean:
        return []

    words: list[str] = []
    i = 0
    n = len(clean)

    while i < n:
        # 尝试匹配双字复合词
        if i + 1 < n and clean[i : i + 2] in _CLASSICAL_COMPOUNDS:
            words.append(clean[i : i + 2])
            i += 2
        else:
            words.append(clean[i])
            i += 1

    return words


def segment_citation(original: str) -> list[str]:
    """对一条语料的原文进行分词，返回该语料中包含的所有独立词语."""
    all_words: list[str] = []
    for sentence in re.split(r"[。！？；\n，、：\"''（）《》]", original):
        words = segment_sentence(sentence.strip())
        all_words.extend(words)
    # 去重保持顺序
    seen: set[str] = set()
    unique: list[str] = []
    for w in all_words:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return unique


def is_content_word(word: str) -> bool:
    """判断一个词是否是实词（适合用于命名）."""
    if len(word) == 1:
        return word not in _FUNCTION_CHARS
    # 双字复合词均为实词（已在 _CLASSICAL_COMPOUNDS 中）
    return True


def extract_content_words(words: list[str]) -> list[str]:
    """从词语列表中提取实词（过滤虚词）."""
    return [w for w in words if is_content_word(w)]


def words_to_chars(words: list[str]) -> list[str]:
    """将词语列表展平为单字列表（用于向后兼容 chars 字段）."""
    chars: list[str] = []
    for w in words:
        chars.extend(list(w))
    return list(dict.fromkeys(chars))  # 去重保持顺序


# ── LLM 分词 ──

_SEGMENT_SYSTEM_PROMPT = (
    "你是古汉语分词专家。将古文按词切分，用 / 分隔每个词。\n"
    "\n"
    "核心原则：古汉语以单字为基本单位，但当两个字在语义上紧密结合、\n"
    "共同表达一个完整概念时，应作为一个词。宁可稍紧（多合成词），\n"
    "不可太散（全都单字）。\n"
    "\n"
    "切分规则（按优先级）：\n"
    "1. 典故词、专名作为一个词：\n"
    "   南冠（囚犯典故）、西陸（秋天）、東君（太阳神）、青陽（春天）\n"
    "   人名：孔子、屈原、李白\n"
    "   地名：长安、洛阳、金陵\n"
    "   书名：诗经、楚辞、论语\n"
    "2. 偏正结构（修饰+中心）紧密时作为一个词：\n"
    "   形容词+名词：蟬聲、客思、秋風、明月、孤雲、寒江\n"
    "   名词+名词：松風、竹露、山月、江雪\n"
    "   方位+名词：南冠、西陸、東籬、北窗\n"
    "3. 动宾/动补结构紧密时作为一个词：\n"
    "   望月、聽雨、歸雁、落花、斷腸\n"
    "4. 连绵词、叠词不可拆分：\n"
    "   徘徊、窈窕、婆娑、逍遙、澎湃、慷慨\n"
    "   關關、夭夭、蒼蒼、悠悠、蕭蕭\n"
    "5. 数词+量词作为一个词：三人、萬里、千載、百尺\n"
    "6. 虚词（之乎者也矣焉哉而於以等）单独成词\n"
    "7. 标点符号保留不变，单独作为一个分隔单元\n"
    "\n"
    "示例：\n"
    "「荏染柔木，君子树之」→ 荏染/柔木/君子/树/之\n"
    "「西陸蟬聲唱，南冠客思侵」→ 西陸/蟬聲/唱/，/南冠/客思/侵\n"
    "「明月松間照，清泉石上流」→ 明月/松間/照/，/清泉/石上/流\n"
    "「蒹葭蒼蒼，白露為霜」→ 蒹葭/蒼蒼/，/白露/為/霜\n"
    "\n"
    "只输出 / 分隔的词序列，不要解释，不要编号。"
)


def _parse_llm_segmentation(raw: str, original: str) -> list[str]:
    """解析LLM分词输出，返回词列表（去重保持顺序）."""
    # 取第一行（防止LLM添加多余文字）
    line = raw.strip().split("\n")[0].strip()
    words = [w.strip() for w in line.split("/") if w.strip()]
    # 验证：去除标点后，词序列汉字拼合必须等于原文汉字序列
    joined_cjk = "".join(_CJK.findall("".join(words)))
    clean_orig = "".join(_CJK.findall(original))
    if joined_cjk != clean_orig:
        # LLM输出的汉字序列与原文不符，回退到词典分词
        return segment_citation(original)
    # 过滤掉纯标点词，保留含汉字的词
    content_words = [w for w in words if _CJK.search(w)]
    seen: set[str] = set()
    unique: list[str] = []
    for w in content_words:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return unique


async def segment_citation_llm(
    original: str,
    client=None,
) -> list[str]:
    """使用LLM对一条语料原文进行分词.

    短文本直接发送；长文本拆分为短句后并发调用LLM，再合并去重。
    """
    if client is None:
        from app.llm.client import get_llm_client
        client = get_llm_client()
    from app.llm.config import resolve_llm_config
    model = resolve_llm_config().get("model_wuxing") or resolve_llm_config()["model_compose"]

    # 按标点拆分为短句
    sentences = [s.strip() for s in re.split(r"[。！？；\n]", original) if s.strip()]
    if not sentences:
        return segment_citation(original)

    # 单句或短文本：直接发送
    if len(sentences) == 1:
        try:
            resp = await client.chat(
                [{"role": "system", "content": _SEGMENT_SYSTEM_PROMPT},
                 {"role": "user", "content": sentences[0]}],
                model=model,
                temperature=0.1,
            )
            return _parse_llm_segmentation(resp.content, sentences[0])
        except Exception:
            return segment_citation(original)

    # 多句：并发调用（每句一次LLM调用）
    import asyncio

    async def _segment_one(seg: str) -> list[str]:
        try:
            resp = await client.chat(
                [{"role": "system", "content": _SEGMENT_SYSTEM_PROMPT},
                 {"role": "user", "content": seg}],
                model=model,
                temperature=0.1,
            )
            return _parse_llm_segmentation(resp.content, seg)
        except Exception:
            return segment_citation(seg)

    results = await asyncio.gather(*[_segment_one(s) for s in sentences])

    # 合并去重
    all_words: list[str] = []
    seen: set[str] = set()
    for words in results:
        for w in words:
            if w not in seen:
                seen.add(w)
                all_words.append(w)
    return all_words


async def segment_citations_batch(
    originals: list[str],
    client=None,
) -> list[list[str]]:
    """批量分词——逐条调用 segment_citation_llm（共用同一分词逻辑）."""
    if not originals:
        return []
    if client is None:
        from app.llm.client import get_llm_client
        client = get_llm_client()

    results = []
    for text in originals:
        try:
            words = await segment_citation_llm(text, client=client)
        except Exception:
            words = segment_citation(text)
        results.append(words)
    return results
