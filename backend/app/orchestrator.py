"""起名编排器."""

from __future__ import annotations

import asyncio
import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import FateAnalysisAgent, QAAgent
from app.bazi.analysis import analyze_bazi_rules
from app.bazi.engine import calculate_bazi
from app.db.session import ReportRecord, new_id
from app.models.schemas import (
    FateAnalysis,
    NameCandidate,
    ReportFull,
    ReportGenerateRequest,
    ReportPreview,
    ReportSection,
)
from app.report.candidates import NamePrecomputed, generate_candidates, prepare_name_data
from app.report.progress import ProgressCallback, emit_progress
from app.report.simplify_report import simplify_report
from app.report.narrative import (
    build_birth_summary,
    build_fate_analysis,
    build_naming_advice,
    format_bazi_chart,
    format_wuxing_analysis,
)


async def generate_report(
    session: AsyncSession,
    req: ReportGenerateRequest,
    session_id: str,
    on_progress: ProgressCallback | None = None,
) -> ReportFull:
    import logging
    import time
    _log = logging.getLogger("uvicorn")
    t_start = time.time()
    _log.info(
        "起名报告生成开始：姓氏=%s 性别=%s 期望=%d个 | session=%s",
        req.surname, req.gender, req.output_count, session_id[:8],
    )

    await emit_progress(on_progress, "bazi", "八字排盘", "正在换算真太阳时并排定四柱干支…")

    chart = calculate_bazi(
        req.birth_datetime,
        longitude=req.birth_place.longitude,
        latitude=req.birth_place.latitude,
        gender=req.gender,
    )
    t_bazi = time.time() - t_start
    _log.info("⏱ 八字排盘完成：%.2fs", t_bazi)
    pillars = chart.pillars
    ganzhi = f"{pillars['year'].ganzhi} {pillars['month'].ganzhi} {pillars['day'].ganzhi} {pillars['hour'].ganzhi}"
    await emit_progress(
        on_progress,
        "bazi",
        "八字排盘",
        f"四柱：{ganzhi}；生肖{chart.zodiac}；日主{chart.day_master['element_cn']}（{chart.day_master.get('strength', '—')}）",
    )

    await emit_progress(on_progress, "analysis", "命格分析", "正在推算五行旺衰、日主强弱、调候与格局…")
    analysis = analyze_bazi_rules(chart)
    t_analysis = time.time() - t_start
    _log.info("⏱ 命格规则分析完成：%.2fs（累计 %.2fs）", t_analysis - t_bazi, t_analysis)
    xy = analysis.xiyongshen
    await emit_progress(
        on_progress,
        "analysis",
        "命格分析",
        f"日主{analysis.strength.level}（{analysis.strength.score}分）；"
        f"格局{analysis.pattern.name}；喜用{'/'.join(xy.primary)}"
        + (f"，次喜{'/'.join(xy.secondary)}" if xy.secondary else ""),
    )

    birth_summary = build_birth_summary(chart, req.birth_place)
    bazi_chart_text = format_bazi_chart(chart)
    wuxing_analysis = format_wuxing_analysis(chart, analysis)

    await emit_progress(on_progress, "fate", "命理解读", "正在结合典籍规则推导喜用神与通俗结论…")

    # ── 并行：FateAnalysisAgent (LLM) + 命名数据准备 (DB/CPU) ──
    # 由于 FateAnalysisAgent 强制 xiyongshen.primary = engine_xy.primary，
    # 命名数据准备可以直接使用 analysis.xiyongshen，无需等待 LLM 结果
    prefs = req.preferences
    avoid = prefs.avoid_chars if prefs else None
    strategy = prefs.wuxing_strategy if prefs else "strict"

    async def _run_fate_agent():
        fate_agent = FateAnalysisAgent()
        try:
            return await fate_agent.analyze(chart)
        except Exception:
            return build_fate_analysis(chart, analysis)

    async def _run_prepare():
        return await prepare_name_data(
            session,
            req.surname,
            analysis.xiyongshen.primary,
            analysis.xiyongshen.secondary,
            req.output_count,
            xiyongshen_avoid=analysis.xiyongshen.avoid,
            avoid_chars=avoid,
            strategy=strategy,
            gender=req.gender,
        )

    fate_task = asyncio.create_task(_run_fate_agent())
    prepare_task = asyncio.create_task(_run_prepare())

    t_before_parallel = time.time()
    fate = await fate_task
    t_fate_llm = time.time() - t_before_parallel
    precomputed: NamePrecomputed = await prepare_task
    t_prepare_total = time.time() - t_before_parallel
    t_elapsed = time.time() - t_start
    _log.info(
        "⏱ 并行阶段完成：命理LLM=%.2fs 数据准备=%.2fs | 累计%.2fs | 候选名池=%d个",
        t_fate_llm, t_prepare_total, t_elapsed, len(precomputed.ranked),
    )

    from app.utils.text import to_simplified
    fate_excerpt = to_simplified(fate.vernacular[:100] + ("…" if len(fate.vernacular) > 100 else ""))
    await emit_progress(on_progress, "fate", "命理解读", fate_excerpt)

    await emit_progress(on_progress, "names", "语料检索", "正在从典籍库中匹配五行喜用的字词…")
    t_before_candidates = time.perf_counter()
    candidates = await generate_candidates(
        session,
        req.surname,
        fate,
        req.output_count,
        preferences=prefs,
        gender=req.gender,
        precomputed=precomputed,
        session_id=session_id,
        on_progress=on_progress,
    )
    t_candidates = time.perf_counter() - t_before_candidates
    names_preview = "、".join(c.full_name for c in candidates[:10]) if candidates else "（暂无）"
    _log.info("⏱ 典籍起名完成：%.2fs | 输出%d个候选名", t_candidates, len(candidates))
    await emit_progress(
        on_progress,
        "names",
        "典籍起名",
        f"已生成 {len(candidates)} 个备选名：{names_preview}",
    )

    await emit_progress(on_progress, "finalize", "汇总报告", "正在进行质检并保存完整报告…")

    # QA 质检改为后台执行，不阻塞报告返回
    async def _background_qa():
        try:
            qa = QAAgent()
            await qa.check(json.dumps({"count": len(candidates)}, ensure_ascii=False))
        except Exception:
            pass
    asyncio.create_task(_background_qa())

    naming_advice = to_simplified(build_naming_advice(fate))
    sections = [
        ReportSection(title="基本信息", content=to_simplified(_format_birth_block(birth_summary))),
        ReportSection(title="八字命盘", content=to_simplified(bazi_chart_text)),
        ReportSection(title="五行分析", content=to_simplified(wuxing_analysis + "\n\n" + fate.professional)),
        ReportSection(title="取名建议", content=naming_advice),
        ReportSection(title="备选名字", content=_format_candidates_block(candidates)),
    ]

    report_id = new_id()
    full = ReportFull(
        id=report_id,
        surname=req.surname,
        bazi=chart,
        birth_summary=birth_summary,
        bazi_chart_text=bazi_chart_text,
        wuxing_analysis=wuxing_analysis,
        fate_analysis=fate,
        naming_advice=naming_advice,
        candidates=candidates,
        sections=sections,
        paid=False,
    )
    full = simplify_report(full)
    session.add(ReportRecord(
        id=report_id,
        session_id=session_id,
        surname=req.surname,
        payload=full.model_dump(mode="json"),
        paid=False,
    ))
    await session.commit()
    await emit_progress(on_progress, "finalize", "汇总报告", "报告已生成，即将为您呈现。")

    t_total = time.time() - t_start
    names = [c.full_name for c in candidates[:10]]
    _log.info(
        "⏱ 起名报告生成完成：总耗时=%.1fs | 八字=%.2fs 命格=%.2fs 并行=%.2fs 起名=%.2fs | 候选=%d个 %s",
        t_total, t_bazi, t_analysis - t_bazi, t_prepare_total, t_candidates,
        len(candidates), names,
    )
    return full


def _format_birth_block(summary: dict[str, str]) -> str:
    lines = [f"性别：{summary.get('性别', '')}"]
    if summary.get("出生地点"):
        lines.append(f"出生地点：{summary['出生地点']}。")
    if summary.get("出生公历_北京"):
        lines.append(f"出生公历：{summary['出生公历_北京']}")
    if summary.get("出生公历_真太阳"):
        lines.append(f"出生公历：{summary['出生公历_真太阳']}")
    if summary.get("出生农历"):
        lines.append(f"出生农历：{summary['出生农历']}")
    if summary.get("生辰八字"):
        lines.append(f"生辰八字：{summary['生辰八字']}")
    if summary.get("生肖"):
        lines.append(f"生肖：{summary['生肖']}")
    return "\n".join(lines)


def _format_candidates_block(candidates: list[NameCandidate]) -> str:
    blocks = []
    for i, c in enumerate(candidates, 1):
        blocks.append(
            f"{i}、{c.full_name}。\n"
            f"{c.citation_explanation or c.citation_text}\n"
            f"{c.meaning}\n"
            f"[五行属性] {c.wuxing_label or c.wuxing.get('summary', '')}\n"
            f"[音韵] {c.tone_comment}"
        )
    return "\n\n".join(blocks)


def to_preview(full: ReportFull) -> ReportPreview:
    excerpt = full.fate_analysis.vernacular[:120] + ("..." if len(full.fate_analysis.vernacular) > 120 else "")
    prof_excerpt = (full.wuxing_analysis[:100] + "...") if full.wuxing_analysis else ""
    preview_candidates = []
    for c in full.candidates[:1]:
        preview_candidates.append(NameCandidate(
            rank=c.rank,
            full_name=c.full_name,
            given_name=c.given_name,
            citation_id=c.citation_id,
            citation_book=c.citation_book,
            citation_text="（解锁后可见全文）",
            citation_explanation="",
            vernacular=c.vernacular[:50] + "..." if len(c.vernacular) > 50 else c.vernacular,
            meaning=c.meaning,
            wuxing=c.wuxing,
            wuxing_label=c.wuxing_label,
            tone=c.tone,
            tone_comment="",
        ))
    pillars = full.bazi.pillars
    return ReportPreview(
        id=full.id,
        surname=full.surname,
        birth_summary=full.birth_summary,
        bazi_summary={
            "四柱": f"{pillars['year'].ganzhi} {pillars['month'].ganzhi} {pillars['day'].ganzhi} {pillars['hour'].ganzhi}",
            "农历": f"{full.bazi.lunar_year}年{full.bazi.lunar_month}{full.bazi.lunar_day} {full.bazi.lunar_hour}",
        },
        fate_vernacular_excerpt=excerpt,
        fate_professional_excerpt=prof_excerpt,
        naming_advice_excerpt=full.fate_analysis.vernacular[:80],
        candidates_preview=preview_candidates,
        paid=full.paid,
    )
