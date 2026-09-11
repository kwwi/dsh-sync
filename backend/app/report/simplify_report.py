"""报告展示前统一繁转简."""

from __future__ import annotations

from app.models.schemas import (
    BaziChart,
    FateAnalysis,
    HiddenStemItem,
    NameCandidate,
    Pillar,
    ReportFull,
    ReportPreview,
    ReportSection,
    ToneSyllable,
)
from app.text.simplify import to_simplified


def _s(text: str) -> str:
    return to_simplified(text)


def simplify_pillar(p: Pillar) -> Pillar:
    return p.model_copy(
        update={
            "stem": _s(p.stem),
            "branch": _s(p.branch),
            "ganzhi": _s(p.ganzhi),
            "ten_god": _s(p.ten_god),
            "growth_stage": _s(p.growth_stage),
            "hidden_stems": [
                HiddenStemItem(stem=_s(h.stem), element=h.element, ten_god=_s(h.ten_god))
                for h in p.hidden_stems
            ],
        }
    )


def simplify_bazi(chart: BaziChart) -> BaziChart:
    dm = dict(chart.day_master)
    if "element_cn" in dm:
        dm["element_cn"] = _s(str(dm["element_cn"]))
    if "strength" in dm:
        dm["strength"] = _s(str(dm["strength"]))
    return chart.model_copy(
        update={
            "lunar_year": _s(chart.lunar_year),
            "lunar_month": _s(chart.lunar_month),
            "lunar_day": _s(chart.lunar_day),
            "lunar_hour": _s(chart.lunar_hour),
            "zodiac": _s(chart.zodiac),
            "pillars": {k: simplify_pillar(v) for k, v in chart.pillars.items()},
            "day_master": dm,
        }
    )


def simplify_fate(fate: FateAnalysis) -> FateAnalysis:
    return fate.model_copy(
        update={
            "professional": _s(fate.professional),
            "vernacular": _s(fate.vernacular),
            "reasoning_chain": [_s(x) for x in fate.reasoning_chain],
        }
    )


def simplify_candidate(c: NameCandidate) -> NameCandidate:
    return c.model_copy(
        update={
            "full_name": _s(c.full_name),
            "given_name": _s(c.given_name),
            "citation_book": _s(c.citation_book),
            "citation_text": _s(c.citation_text),
            "citation_explanation": _s(c.citation_explanation),
            "vernacular": _s(c.vernacular),
            "meaning": _s(c.meaning),
            "wuxing_label": _s(c.wuxing_label),
            "tone_comment": _s(c.tone_comment),
            "tone": [
                ToneSyllable(char=_s(t.char), pinyin=t.pinyin, tone_label=_s(t.tone_label))
                for t in c.tone
            ],
        }
    )


def simplify_report(full: ReportFull) -> ReportFull:
    return full.model_copy(
        update={
            "bazi": simplify_bazi(full.bazi),
            "birth_summary": {k: _s(v) for k, v in full.birth_summary.items()},
            "bazi_chart_text": _s(full.bazi_chart_text),
            "wuxing_analysis": _s(full.wuxing_analysis),
            "fate_analysis": simplify_fate(full.fate_analysis),
            "naming_advice": _s(full.naming_advice),
            "candidates": [simplify_candidate(c) for c in full.candidates],
            "sections": [
                ReportSection(title=_s(s.title), content=_s(s.content)) for s in full.sections
            ],
            "disclaimer": _s(full.disclaimer),
        }
    )


def simplify_preview(preview: ReportPreview) -> ReportPreview:
    return preview.model_copy(
        update={
            "birth_summary": {k: _s(v) for k, v in preview.birth_summary.items()},
            "bazi_summary": {k: _s(v) for k, v in preview.bazi_summary.items()},
            "fate_vernacular_excerpt": _s(preview.fate_vernacular_excerpt),
            "fate_professional_excerpt": _s(preview.fate_professional_excerpt),
            "naming_advice_excerpt": _s(preview.naming_advice_excerpt),
            "candidates_preview": [simplify_candidate(c) for c in preview.candidates_preview],
            "unlock_hint": _s(preview.unlock_hint),
        }
    )
