"""Agents."""

from __future__ import annotations

import json

from sqlalchemy import select

from app.bazi.analysis import analyze_bazi_rules
from app.llm.client import LLMClient, get_llm_client
from app.llm.json_util import parse_llm_json
from app.llm.config import resolve_llm_config
from app.models.schemas import BaziChart, FateAnalysis, Xiyongshen
from app.report.narrative import build_fate_analysis


class FateAnalysisAgent:
    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or get_llm_client()
        self.model = resolve_llm_config()["model_fate"]

    async def analyze(self, chart: BaziChart) -> FateAnalysis:
        analysis = analyze_bazi_rules(chart)
        rule_fate = build_fate_analysis(chart, analysis)
        engine_xy = analysis.xiyongshen

        system = (
            "你是命理解读助手。必须基于引擎给出的结构化分析输出 JSON，"
            "含 vernacular, xiyongshen, reasoning_chain, professional。"
            f"喜用神 primary 必须为 {engine_xy.primary}，secondary 建议为 {engine_xy.secondary}，"
            f"avoid 为 {engine_xy.avoid}。不得与引擎结论冲突，可润色通俗语言。"
        )
        payload = {
            "chart_summary": {
                "day_master": chart.day_master,
                "pillars": {k: v.ganzhi for k, v in chart.pillars.items()},
                "clashes": chart.relations.clash,
            },
            "engine_analysis": analysis.model_dump(),
        }
        prompt = f"分析命格: {json.dumps(payload, ensure_ascii=False)}"

        import logging
        _log = logging.getLogger("uvicorn")
        dm = chart.day_master
        _log.info(
            "命理LLM 请求：日主=%s(%s) 格局=%s 喜用=%s",
            dm.get("element_cn", "?"), dm.get("tiangan", "?"),
            analysis.pattern.name, engine_xy.primary,
        )
        try:
            resp = await self.client.chat(
                [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.2,
            )
            data = parse_llm_json(resp.content, fallback=None)
        except Exception:
            data = None

        if not data:
            _log.warning("命理LLM 返回为空，使用规则推算结果")
            return rule_fate

        _log.debug(
            "命理LLM 返回：vernacular=%d字 professional=%d字",
            len(data.get("vernacular", "") or ""),
            len(data.get("professional", "") or ""),
        )

        xy_raw = data.get("xiyongshen", {})
        xy = Xiyongshen(
            primary=engine_xy.primary,
            secondary=xy_raw.get("secondary") or engine_xy.secondary,
            avoid=xy_raw.get("avoid") or engine_xy.avoid,
        )
        if xy_raw.get("primary") and xy_raw["primary"] != engine_xy.primary:
            xy.primary = engine_xy.primary

        vernacular = data.get("vernacular", "") or rule_fate.vernacular
        if len(vernacular) < 15:
            vernacular = rule_fate.vernacular

        professional = data.get("professional", "") or rule_fate.professional
        if len(professional) < 50:
            professional = rule_fate.professional

        return FateAnalysis(
            professional=professional,
            vernacular=vernacular,
            xiyongshen=xy,
            reasoning_chain=data.get("reasoning_chain") or rule_fate.reasoning_chain,
        )

    def analyze_sync_rules(self, chart: BaziChart) -> FateAnalysis:
        analysis = analyze_bazi_rules(chart)
        return build_fate_analysis(chart, analysis)


class NameComposeAgent:
    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or get_llm_client()
        self.model = resolve_llm_config()["model_compose"]

    async def compose(
        self,
        surname: str,
        citations: list,
        fate: FateAnalysis,
        *,
        name_hints: list[dict] | None = None,
        pair_hints: list[dict] | None = None,
        char_pool: list[dict] | None = None,
        word_pool: list[dict] | None = None,
        wuxing_strategy: str = "strict",
        gender: str = "male",
    ) -> list[dict]:
        from app.tone.engine import analyze_tone, tone_pattern

        hints = name_hints or pair_hints or []

        # 分析姓氏音韵
        surname_syl = analyze_tone(surname)
        surname_tone = tone_pattern(surname_syl)
        surname_pinyin = " ".join(s.pinyin for s in surname_syl)

        gender_cn = "男孩" if gender == "male" else "女孩"

        # ── 性别风格引导 ──
        if gender == "female":
            gender_guide = (
                "【性别与风格】这是为女孩起名。"
                "选字应体现温婉聪慧、清雅灵动的气质。意象方向：\n"
                "· 自然花卉：兰、芷、薇、棠、荷、莲、萱、荇、蒹葭\n"
                "· 珍宝雅器：瑶、瑾、瑜、琳、琪、璇、琴、瑟、韶\n"
                "· 月色清辉：月、胧、霁、雯、霓、霄、露、霜、雪\n"
                "· 才情灵慧：慧、敏、诗、画、书、墨、弦、弈、笙\n"
                "避免过于刚猛杀伐或粗犷的字（如：刚、武、虎、剑、锋、鼎、钧、霆、霸）。\n"
                "名字应给人「如月清辉、似水柔情」的美感。"
            )
        else:
            gender_guide = (
                "【性别与风格】这是为男孩起名。"
                "选字应体现刚毅仁德、志向高远的气质。意象方向：\n"
                "· 山川河岳：岳、峥、岚、峻、泽、渊、澜、泓、瀚\n"
                "· 日月星辰：曦、晖、晟、曜、辰、霄、乾、坤、宇\n"
                "· 德行修养：德、仁、义、信、诚、谦、慎、恪、肃\n"
                "· 文采志向：文、章、博、远、修、彦、哲、策、韬\n"
                "避免过于阴柔妩媚的字（如：媚、娇、艳、婷、娜、婉、娟、姣、婳）。\n"
                "名字应给人「如松挺拔、似海深沉」的气度。"
            )

        # 构建 payload
        payload = {
            "surname": surname,
            "gender": gender_cn,
            "surname_pinyin": surname_pinyin,
            "surname_tone": surname_tone + "（" + "、".join(s.tone_label for s in surname_syl) + "）",
            "citations": [
                {
                    "id": c.id,
                    "book": c.book,
                    "chapter": getattr(c, "chapter", ""),
                    "original": c.original,
                    "vernacular": c.vernacular,
                    "chars": c.chars,
                    "words": getattr(c, "words", []) or [],
                }
                for c in citations
            ],
            "char_pool": char_pool or [],
            "word_pool": word_pool or [],
            "xiyongshen": fate.xiyongshen.model_dump(),
            "wuxing_strategy": wuxing_strategy,
            "name_hints": hints,
        }

        # ── 创意增强 System Prompt ──
        system = (
            "你是中华典籍起名大师。从 char_pool/word_pool 中选字词，为" + gender_cn + "创造出令人眼前一亮的名字。\n\n"

            "【核心规则】\n"
            "1. 只能从 char_pool 选字或 word_pool 选取整体词，禁止编造未出现的字词\n"
            "2. char_pool 和 word_pool 已按五行喜用预过滤，无需再核对五行\n"
            "3. 避免高频俗名(子涵/浩然/宇轩/一诺/欣怡/梓涵等)\n"
            "4. 禁止负面字(怨恨悲愁忧)、暴力字(杀戮刑)、污秽字、动物牲畜字\n"
            "5. ⚠️ 选字必须代表引文的「核心意象」，不是「任意出现的字」：\n"
            "   - 禁止选人名/称谓（如'孟子曰'中'孟''子'是称谓，不是立意）\n"
            "   - 禁止选虚词（之乎者也矣焉哉兮曰云谓）\n"
            "   - 只能选承载该句「诗意核心」的实词：自然的意象、德行的品格、美好的事物\n"
            "6. ⚠️ 禁止跨越复合词边界取字：如果两个字在原文中分属不同的词语，不能强行拼在一起\n"
            "7. ✨ 优先使用整体词作名：word_pool 中的双字词（如'蒹葭''逍遥'）整体适合作名，\n"
            "   可直接输出，整体意象比拆字拼凑更有文化底蕴。\n"
            "8. 允许输出单字名：精炼的单字也可以成为好名字（如'洵''晔''珩'）\n\n"

            "【音韵为第一维度 — 务必严格遵守】\n"
            "姓" + surname_tone + "(" + surname_pinyin + ")。姓+名整体平仄交替（如'仄平仄'/'平仄平'）为最佳。\n"
            "· 单字名：名与姓末字平仄不同为佳（如姓仄+名平，或姓平+名仄）\n"
            "· 双字名：名内平仄交替（平仄或仄平）为佳\n"
            "· 禁止姓末字与名中字同音（如姓李名鲤、姓王名望），这会导致读音含混不清\n"
            "· 全平或全仄（如'平平平'/'仄仄仄'）应避开，读起来单调乏味\n\n"

            "【创意策略 — 务必运用】\n"
            "· 意象碰撞：将不同意象的字组合创造新的意境，如「霁」(雨后天晴)+「渊」(深水)=清朗深邃\n"
            "· 虚实相生：一个具体意象字+一个抽象意境字，如「松」(具象)+「意」(抽象)\n"
            "· 反常用字：提取典籍中有美感但不常见的字，如「栩」「洵」「晔」「翊」「珩」\n"
            "· 画面命名：组合后应让人「看到」一幅画面，而非解释一个道理\n"
            "· 双声叠韵：两个字的声母或韵母呼应但不重复，如「清澄」(同韵)\n"
            "· 姓氏联动：若「姓+单字」或「姓+双字词」能构成有美好寓意的词语或经典意象，优先采用。\n"
            "  例如：白+鹭=白鹭、林+栖=林栖、江+月=江月、柳+依=柳依、云+舟=云舟。\n"
            "  姓氏应成为名字意境的一部分，让姓名浑然天成、过目不忘。\n\n"

            "【选字品味】\n"
            "· 自然意象 > 品德修养 > 文采才智 > 吉祥祝愿\n"
            "· 多用山水云月星风雨露雪霜等自然字，天然有画面感\n"
            "· 用典需巧妙：\"出自诗经\"不如\"一读便有诗经的味道\"\n\n"

            "【风格多样】输出所有评分≥6的候选名，不限数量，覆盖至少2-3种风格：\n"
            "· 清逸型：自然意象，如山水画意\n"
            "· 儒雅型：古典书卷气\n"
            "· 刚健型：气魄宏大\n"
            "· 温润型：柔和雅致\n"
            "· 新奇型：字面新鲜但不怪异\n\n"

            + gender_guide + "\n"

            "【输出 JSON】\n"
            '{{"candidates":[\n'
            '  {{"given_name":"名","citation_id":"语料id",\n'
            '   "citation_explanation":"取自《书》原文解读+命名关联",\n'
            '   "meaning":"寓意解读(40-80字，要求见下)",\n'
            '   "meaning_score":8,"wuxing_label":"名：火木","style":"清逸|儒雅|刚健|温润|新奇"}}\n'
            "]}}\n\n"

            "【meaning 寓意解读 — 写作铁律】\n"
            "每个名字的 meaning 是一段 40-80 字的文学化解读，必须做到：\n"
            "1. 紧扣典籍原文意象展开，引用原文中的画面/情境，而非泛泛而谈\n"
            "2. 自然融入五行与命格呼应，如「木火相生」「得水之润」，而非「五行属木」「契合命格」\n"
            "3. 文字要有画面感和文学感染力，让人读后「看见」名字中的意境\n"
            "4. 风格与名字气质一致：清逸如山水画，儒雅如松间读书，刚健如临风玉树\n\n"
            "【严禁套话】以下表述及变体一律不得出现：\n"
            "· 「意象采撷」「契合命格」「寓意XX隽永」「寓意XX凝练」\n"
            "· 「从《X》中撷取」「撷自《X》」「典出《X》」作为解释正文开头\n"
            "· 任何两个名字的 meaning 第一句话不能有相同的句式结构\n\n"
            "【正例 — 好的解读】\n"
            "· 「云栖」：白云栖于山岫，不言高而自高。水木清华间，自有一份超然物外的从容。\n"
            "· 「霁舟」：雨过天青，一叶扁舟浮于江上。火土相生，恰是拨云见日的豁达。\n"
            "【反例 — 套话模板，禁止】\n"
            "· 「云栖」：从《X》意象采撷，契合命格喜水木，寓意清雅隽永。✗\n\n"

            "【评分 0-10】意象美4+文化底蕴3+音韵3。<6分不输出。不限数量，按分降序。\n"
            "追求创造「语嫣」「清照」级别的经典好名——看似平常，回味无穷。"
        )

        import logging
        _log = logging.getLogger("uvicorn")
        _log.info(
            "起名LLM(约束模式) 请求：姓=%s 性别=%s 喜用=%s 语料=%d条",
            surname, gender_cn, fate.xiyongshen.primary, len(citations),
        )
        resp = await self.client.chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            model=self.model,
            temperature=0.85,  # 高温度增加创造性和多样性
        )
        data = parse_llm_json(resp.content, fallback={"candidates": []})
        candidates = data.get("candidates", [])
        names = [c.get("given_name", "?") for c in candidates[:8]]
        _log.info(
            "起名LLM(约束模式) 返回：%d个候选 %s",
            len(candidates), names,
        )
        return candidates


class NameFreeComposeAgent:
    """自由创作模式：不拘泥于单条典籍，从语料字池中自由组合新名，要求古典审美论证."""

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or get_llm_client()
        self.model = resolve_llm_config()["model_compose"]

    async def compose(
        self,
        surname: str,
        citations: list,
        fate: FateAnalysis,
        *,
        wx_map: dict[str, str] | None = None,
        gender: str = "male",
        char_pool: list[dict] | None = None,
    ) -> list[dict]:
        """从语料字符池中自由组合新名.

        与 NameComposeAgent 的区别：不要求两个字符来自同一条 citation，
        而是允许从整个语料库中选字自由组合，但要求给出古典审美论证。

        char_pool 若由调用方传入，则跳过池构建（已做五行预过滤）。
        """
        from app.tone.engine import analyze_tone, tone_pattern

        # 若调用方已传入预过滤字池，直接使用；否则从 citations 构建
        if char_pool is None:
            # 收集所有可用字符及出处信息
            all_chars_map: dict[str, list[dict]] = {}
            for c in citations:
                for ch in (c.chars or []):
                    if ch not in all_chars_map:
                        all_chars_map[ch] = []
                    all_chars_map[ch].append({
                        "char": ch,
                        "book": c.book,
                        "chapter": getattr(c, "chapter", ""),
                        "original_preview": (c.original or "")[:60],
                    })

            # 五行信息
            char_wuxing_info: dict[str, str] = {}
            if wx_map:
                for ch in all_chars_map:
                    if ch in wx_map:
                        char_wuxing_info[ch] = wx_map[ch]

            # 构建字池摘要（每个字带出处和五行）
            char_pool = []
            for ch, sources in all_chars_map.items():
                books = list(set(s["book"] for s in sources))[:2]
                wu = char_wuxing_info.get(ch, "?")
                char_pool.append({
                    "char": ch,
                    "element": wu,
                    "source_books": books,
                    "sample_context": sources[0]["original_preview"] if sources else "",
                    "source_count": len(sources),
                })

            # 按品质排序：来源多的字优先
            char_pool.sort(key=lambda x: (-x["source_count"], x["char"]))

        # 截断字池
        char_pool = char_pool[:350]

        surname_syl = analyze_tone(surname)
        surname_tone = tone_pattern(surname_syl)
        surname_pinyin = " ".join(s.pinyin for s in surname_syl)

        gender_cn = "男孩" if gender == "male" else "女孩"
        gender_guide = (
            "这是为女孩起名。追求「笑语嫣然」「清丽脱俗」的意境。"
            "适合的字风：花卉自然（兰/芷/薇/棠）、珍宝才艺（瑶/瑾/琴/韶）、月色清辉（霁/雯/露/霜）。"
            "避免刚猛杀伐的字。"
        ) if gender == "female" else (
            "这是为男孩起名。追求「气宇轩昂」「温润如玉」的意境。"
            "适合的字风：山川河岳（岳/峥/渊/澜）、日月星辰（曦/晟/曜/霄）、德行志向（德/谦/修/彦）。"
            "避免阴柔妩媚的字。"
        )

        payload = {
            "surname": surname,
            "gender": gender_cn,
            "surname_pinyin": surname_pinyin,
            "surname_tone": f"{surname_tone}（{'、'.join(s.tone_label for s in surname_syl)}）",
            "char_pool": char_pool,
            "xiyongshen": {
                "primary": fate.xiyongshen.primary,
                "secondary": fate.xiyongshen.secondary,
            },
        }

        system = (
            "你是中华起名创意大师。从 char_pool 中自由选两字，为" + gender_cn + "创造令人惊艳的新名。\n\n"

            "【创作哲学】\n"
            "像金庸创造「语嫣」——两个字分别来自不同典籍，组合出全新的古典意境。\n"
            "你需要在 char_pool 中寻找最美的字，并像诗人一样将它们编织在一起。\n"
            "char_pool 已按五行喜用预过滤，无需再核对五行。\n\n"

            "【音韵为第一维度 — 务必严格遵守】\n"
            "姓{surname_tone}({surname_pinyin})。姓+名整体平仄交替（如'仄平仄'/'平仄平'）为最佳。\n"
            "· 名内平仄交替（平仄或仄平）为佳\n"
            "· 禁止姓末字与名中字同音（如姓李名鲤），这会导致读音含混不清\n"
            "· 全平或全仄应避开，读起来单调乏味\n\n"

            "【创意法则】\n"
            "· 陌生化美学：选不常见但有质感的好字（如栩、洵、晔、翊、珩、珣、琤）\n"
            "· 意象碰撞：「霁」(初晴)+「舟」(小舟)=雨过天晴泛舟湖上\n"
            "· 虚实交织：一个具象字+一个意境字，如「舟意」「云栖」\n"
            "· 通感命名：视觉字+听觉字，如「清响」「朗吟」\n"
            "· 留白之美：名字不必说完，给人想象空间，「清和」比「清平」更有余韵\n"
            "· 姓氏联动：优先让「姓+名」整体构成美好意象——姓氏应融入意境而非孤立存在。\n"
            "  例如白+鹭=白鹭（诗中有画）、杨+柳=杨柳（春风拂岸）、江+月=江月（水月相映）、\n"
            "  林+栖=林栖（幽居山林）、叶+知秋=叶知秋（一叶知秋）。这是起名的最高境界。\n\n"

            "【规则】\n"
            "1. 每个字必须在 char_pool 中出现\n"
            "2. 音韵和谐(平仄相间)、意境优美\n"
            "3. 每个字引用其古典出处作为论证\n"
            "4. 禁负面字、暴力字、污秽字、网红风、直白名词\n"
            "5. 禁高频名(子涵/浩然/宇轩/一诺/欣怡等)\n"
            "6. ⚠️ 选字必须代表出处中的「核心诗意」，不是任意出现的字\n"
            "7. 输出前默读全名，去掉拗口或歧义的组合\n\n"

            + gender_guide + "\n"

            "【输出 JSON】\n"
            "{{\"candidates\":[\n"
            "  {{\"given_name\":\"名\",\"char1_source\":\"字1出处(书名+原文句)\",\n"
            "    \"char2_source\":\"字2出处(书名+原文句)\",\n"
            "    \"meaning\":\"寓意解读(40-80字，要求见下)\",\n"
            "    \"meaning_score\":8,\"wuxing_label\":\"名：火木\",\n"
            "    \"style\":\"清逸|儒雅|刚健|温润|灵秀|新奇\",\n"
            "    \"creative_rationale\":\"为什么这两个字放在一起是美的(20-30字，要有说服力)\"}}\n"
            "]}}\n\n"

            "【meaning 寓意解读 — 写作铁律】\n"
            "每个名字的 meaning 是一段 40-80 字的文学化解读，必须做到：\n"
            "1. 逐字展开：先讲第一个字的意象（引用 char1_source），再讲第二个字（引用 char2_source）\n"
            "2. 再讲组合：二字放在一起，形成了怎样的画面和意境\n"
            "3. 自然融入五行与命格呼应，如「木火相生」「得水之润」，而非「五行属木」「契合命格」\n"
            "4. 落笔到人格期许，文字要有余韵\n\n"
            "【严禁套话】同约束模式。\n\n"
            "【正例 — 好的解读】\n"
            "· 「霁舟」：霁是雨过天青，舟是一叶渡江——二字相合，\n"
            "   便是一幅「风雨初歇、轻舟已过」的画面。火土相生，恰是拨云见日的豁达。\n\n"

            "【评分 0-10】意象美4+组合新颖3+音韵3。<6分不输出。不限数量，按分降序。\n"
            "目标是让用户看到名字时「哇」一声——意想不到却回味悠长。"
        ).format(
            surname_tone=surname_tone,
            surname_pinyin=surname_pinyin,
        )

        import logging
        _log = logging.getLogger("uvicorn")
        _log.info(
            "起名LLM(自由模式) 请求：姓=%s 性别=%s 喜用=%s 字池=%d字",
            surname, gender_cn, fate.xiyongshen.primary, len(char_pool),
        )
        resp = await self.client.chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            model=self.model,
            temperature=0.8,  # 自由创作需要更高温度
        )
        data = parse_llm_json(resp.content, fallback={"candidates": []})
        candidates = data.get("candidates", [])
        names = [c.get("given_name", "?") for c in candidates[:8]]
        _log.info(
            "起名LLM(自由模式) 返回：%d个候选 %s",
            len(candidates), names,
        )
        return candidates


class WordWuxingAgent:
    """词级别五行属性标注 —— 基于LLM判断词的整体意象五行归属."""

    _WUXING_GUIDE = (
        "【人名适合性预判】先判断词是否适合作人名。标记 suitable_for_name=false 的类型：\n"
        "- 负面/死亡/病残/污秽/鬼怪/牲畜（非祥瑞）/历史人物称谓/虚词指代/负面评价\n"
        "- 过于宏大的名词（天下/社稷/朝廷等）、无实义的动作状态词（徘徊/踌躇等）\n"
        "不适合人名的词不填五行字段。\n"
        "\n"
        "【五行标注】仅对 suitable_for_name=true 的词标注五行（按典籍语境，非拆单字）：\n"
        "木=草木/仁德/春季 | 火=光明/热烈/夏季 | 土=厚重/包容/季末\n"
        "金=坚毅/收敛/秋季 | 水=流动/智慧/冬季\n"
        "兼有多种倾向时标 primary+secondary，primary_weight=0.5-1.0。勿强行拆分。"
    )

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or get_llm_client()
        cfg = resolve_llm_config()
        self.model = cfg.get("model_wuxing") or cfg["model_compose"]

    async def annotate_words(
        self, words: list[str], contexts: dict[str, list[dict]] | None = None,
    ) -> list[dict]:
        """批量标注词的五行属性，附带典籍上下文."""
        if not words:
            return []

        batch = words[:50]
        ctx = contexts or {}

        system = (
            "你是古汉语五行专家。" + self._WUXING_GUIDE + "\n"
            "输出 JSON 数组（每个词必须包含 suitable_for_name 字段）：\n"
            '[{"word":"词","suitable_for_name":true,"primary":"木","secondary":["火"],'
            '"primary_weight":0.7,"confidence":"high","reasoning":"≤30字"},\n'
            ' {"word":"词","suitable_for_name":false,"reasoning":"≤20字说明为何不宜人名"}]'
        )
        # 构建带上下文的用户消息
        lines = []
        for i, w in enumerate(batch, 1):
            lines.append(f"{i}. {w}")
            for c in ctx.get(w, [])[:3]:
                book = c.get("book", "")
                orig = c.get("original", "")[:50]
                lines.append(f"   出处：《{book}》「{orig}」")
        user = "\n".join(lines)

        try:
            resp = await self.client.chat(
                [{"role": "system", "content": system},
                 {"role": "user", "content": user}],
                model=self.model,
                temperature=0.1,
            )
            data = parse_llm_json(resp.content, fallback=[])
            if isinstance(data, dict):
                data = data.get("words", data.get("results", []))
            result = data if isinstance(data, list) else []
            if not result:
                import logging
                _log = logging.getLogger("uvicorn")
                _log.warning(
                    "词五行LLM返回空结果：raw=%s",
                    (resp.content or "")[:500],
                )
            return result
        except Exception as exc:
            import logging
            _log = logging.getLogger("uvicorn")
            _log.warning("词五行LLM调用异常：%s", exc)
            return []

    async def annotate_all_corpus_words(
        self, session, *, batch_size: int = 50
    ) -> int:
        """收集语料库中所有实词及其典籍上下文，分批标注并写入 word_wuxing 表."""
        from app.corpus.search import load_word_wuxing_map as _load_map
        from app.corpus.segment import is_content_word
        from app.db.session import CitationRecord

        existing = await _load_map(session)

        # 收集待标注词及上下文
        stmt = select(CitationRecord)
        result = await session.execute(stmt)
        pending: set[str] = set()
        word_contexts: dict[str, list[dict]] = {}

        for row in result.scalars().all():
            words = row.words or []
            for w in words:
                if is_content_word(w) and len(w) >= 2 and w not in existing:
                    pending.add(w)
                    if len(word_contexts.get(w, [])) < 3:
                        word_contexts.setdefault(w, []).append({
                            "book": row.book,
                            "original": (row.original or "")[:80],
                        })

        if not pending:
            return 0

        words_list = sorted(pending)
        print(f"待标注词: {len(words_list)} 个（含典籍上下文）")
        total_annotated = 0

        for i in range(0, len(words_list), batch_size):
            batch = words_list[i : i + batch_size]
            annotations = await self.annotate_words(batch, contexts=word_contexts)
            if not annotations:
                continue
            from datetime import datetime, timezone
            from app.db.session import WordWuxingRecord
            now = datetime.now(timezone.utc)
            el_en_map = {"木": "wood", "火": "fire", "土": "earth", "金": "metal", "水": "water"}
            for ann in annotations:
                word = ann.get("word", "")
                if not word:
                    continue

                # 人名适合性检查
                suitable = ann.get("suitable_for_name")
                if suitable is False:
                    await session.merge(WordWuxingRecord(
                        word=word, element="", element_cn="",
                        confidence="llm", source="llm_annotation",
                        contexts=word_contexts.get(word, [])[:3],
                        suitable_for_name=False, annotated_at=now,
                        reasoning=ann.get("reasoning", ""),
                    ))
                    print(f"  {word} → [不宜人名] {ann.get('reasoning','')}")
                    continue

                primary = ann.get("primary", "")
                if primary not in el_en_map:
                    continue
                secondary = ann.get("secondary") or []
                secondary = [s for s in secondary if s in el_en_map]
                pw = ann.get("primary_weight")
                if pw is not None:
                    pw = max(0.5, min(1.0, float(pw)))
                await session.merge(WordWuxingRecord(
                    word=word,
                    element=el_en_map[primary],
                    element_cn=primary,
                    secondary_cn=",".join(secondary) if secondary else None,
                    primary_weight=pw,
                    confidence=ann.get("confidence", "medium"),
                    source="llm_annotation",
                    contexts=word_contexts.get(word, [])[:3],
                    suitable_for_name=True,
                    annotated_at=now,
                    reasoning=ann.get("reasoning", ""),
                ))
                tag = f" +{','.join(secondary)}" if secondary else ""
                print(f"  {word} → {primary}{tag} (w={pw}) {ann.get('reasoning','')}")
                total_annotated += 1
            await session.commit()

        return total_annotated


class QAAgent:
    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or get_llm_client()
        self.model = resolve_llm_config()["model_qa"]

    async def check(self, report_summary: str) -> dict:
        resp = await self.client.chat(
            [{"role": "user", "content": f"质检报告: {report_summary}"}],
            model=self.model,
            temperature=0.1,
        )
        return parse_llm_json(resp.content, fallback={"pass": True, "reasons": []})


class NameCuratorAgent:
    """候选名精选润色层：深度解读 + 重新排名 + 首推标记."""

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or get_llm_client()
        cfg = resolve_llm_config()
        self.model = cfg.get("model_curator") or cfg["model_compose"]

    async def curate(
        self,
        surname: str,
        candidates: list[dict],
        fate: FateAnalysis,
        gender: str,
    ) -> list[dict]:
        """对候选名进行深度解读、评分和重新排名."""
        if not candidates:
            return candidates

        gender_cn = "男孩" if gender == "male" else "女孩"
        xy = fate.xiyongshen

        system = (
            "你是起名策展人。以寓意与音韵为第一维度，对候选名评估、精选和排名。\n\n"

            "【评估维度】\n"
            "· 寓意深度(1-5)：名字的意象是否深远、有文化厚度\n"
            "· 音韵和谐(1-5)：姓+名的整体平仄是否流畅优美、朗朗上口。平仄交替者高分，全平/全仄者低分\n"
            "· 姓名一体感：姓+名是否浑然天成（如白鹭、江月），最高+1分\n\n"

            "【输出 JSON】\n"
            '{{"curated":[\n'
            '  {{"given_name":"名","keep":true,"is_top_pick":false,\n'
            '    "meaning_score":8,\n'
            '    "scores":{{"imagery":4,"culture":4,"rhythm":4,"practicality":4}},\n'
            '    "curated_meaning":"精炼优雅的深度解读(50-80字)",\n'
            '    "one_liner":"推荐语(≤15字)","reasoning":"音韵+寓意理由",\n'
            '    "style_tag":"儒雅|清逸|刚健|温润|灵秀"}}\n'
            "]}}\n\n"

            "【规则】\n"
            "· 对所有候选名评分，评分高的全部保留(keep=true)，不限数量\n"
            "· 标记1-2个综合最佳为 is_top_pick=true\n"
            "· meaning_score 0-10，寓意深厚且平仄和谐者高分；该分数将作为最终排名依据\n"
            "· 风格重复的保留意境更深者\n"
            "· 拒绝(keep=false)：历史人物称谓、直白名词、负面歧义、像头衔的名字\n"
            "· 优先保留姓+名构成美好整体意象的候选\n"
            "· curated_meaning 要有文化深度和感染力\n"
            "· 按 meaning_score 降序排列"
        )

        payload = {
            "surname": surname,
            "gender": gender_cn,
            "xiyongshen": {"primary": xy.primary, "secondary": xy.secondary},
            "candidates": [
                {
                    "given_name": c.get("given_name", ""),
                    "full_name": c.get("full_name", ""),
                    "citation_book": c.get("citation_book", ""),
                    "citation_text": c.get("citation_text", ""),
                    "meaning": c.get("meaning", ""),
                    "wuxing_label": c.get("wuxing_label", ""),
                    "tone_comment": c.get("tone_comment", ""),
                    "tone_pattern": c.get("tone_pattern", ""),
                    "pinyin": c.get("pinyin", ""),
                    "meaning_score": c.get("meaning_score", 0),
                }
                for c in candidates
            ],
        }

        import logging
        _log = logging.getLogger("uvicorn")
        _log.info(
            "精选LLM 请求：候选=%d个",
            len(candidates),
        )
        try:
            resp = await self.client.chat(
                [{"role": "system", "content": system},
                 {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                model=self.model,
                temperature=0.3,
            )
            data = parse_llm_json(resp.content, fallback={})
            curated = data.get("curated", [])
            if curated:
                keep_count = sum(1 for c in curated if c.get("keep", True))
                top_picks = [c.get("given_name", "?") for c in curated if c.get("is_top_pick")]
                _log.info(
                    "精选LLM 返回：keep=%d个 top_pick=%d个 %s",
                    keep_count, len(top_picks), top_picks,
                )
                # Sort: top_picks first, then by keep status
                curated.sort(key=lambda x: (
                    not x.get("keep", True),
                    not x.get("is_top_pick", False),
                    -(sum(x.get("scores", {}).values()) / max(len(x.get("scores", {})), 1)),
                ))
                return curated
        except Exception:
            _log.warning("精选LLM 异常，跳过精选层")
            pass
        return candidates
