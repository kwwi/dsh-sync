"""Pydantic 数据模型."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class HiddenStemItem(BaseModel):
    stem: str
    element: str
    ten_god: str


class Pillar(BaseModel):
    stem: str
    branch: str
    ganzhi: str
    stem_element: str
    ten_god: str
    hidden_stems: list[HiddenStemItem]
    growth_stage: str


class ElementCounts(BaseModel):
    wood: int
    fire: int
    earth: int
    metal: int
    water: int


class SeasonStrength(BaseModel):
    wood: str
    fire: str
    earth: str
    metal: str
    water: str


class Relations(BaseModel):
    clash: list[str] = Field(default_factory=list)
    combine: list[str] = Field(default_factory=list)
    harm: list[str] = Field(default_factory=list)
    punishment: list[str] = Field(default_factory=list)
    three_combine: list[str] = Field(default_factory=list)
    stem_combine: list[str] = Field(default_factory=list)


class BaziChart(BaseModel):
    beijing_time: str
    true_solar_time: str
    lunar_year: str
    lunar_month: str
    lunar_day: str
    lunar_hour: str
    pillars: dict[str, Pillar]
    zodiac: str
    element_counts: ElementCounts
    season_strength: SeasonStrength
    relations: Relations
    day_master: dict[str, Any]
    gender: str
    confidence: str = "full"


class BirthPlace(BaseModel):
    province: str = ""
    city: str = ""
    district: str = ""
    longitude: float = 120.0
    latitude: float = 30.0


class RegionItem(BaseModel):
    code: str
    name: str
    longitude: float | None = None
    latitude: float | None = None
    has_children: bool = False


class NamePreferences(BaseModel):
    name_length: Literal["single", "double", "any"] = "double"
    style_tags: list[str] = Field(default_factory=list)
    wuxing_strategy: Literal["strict", "moderate", "reference"] = "strict"
    avoid_chars: list[str] = Field(default_factory=list)
    generation_char: str | None = None


class BaziCalculateRequest(BaseModel):
    birth_datetime: datetime
    longitude: float = 120.0
    latitude: float = 30.0
    gender: Literal["male", "female"] = "male"
    use_true_solar: bool = True


class ReportGenerateRequest(BaseModel):
    surname: str
    gender: Literal["male", "female"] = "male"
    birth_datetime: datetime
    birth_place: BirthPlace = Field(default_factory=BirthPlace)
    preferences: NamePreferences = Field(default_factory=NamePreferences)
    output_count: int = Field(default=10, ge=1, le=10)


class Xiyongshen(BaseModel):
    primary: list[str]
    secondary: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)


class DayMasterStrength(BaseModel):
    score: int
    level: Literal["极强", "偏强", "平和", "偏弱", "极弱"]
    de_ling: bool
    de_di: int
    de_shi: int
    reasoning: list[str] = Field(default_factory=list)


class PatternResult(BaseModel):
    name: str
    formed: bool
    confidence: Literal["high", "medium", "low"] = "medium"
    reasoning: list[str] = Field(default_factory=list)


class TuneResult(BaseModel):
    primary: list[str] = Field(default_factory=list)
    secondary: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    stems_needed: list[str] = Field(default_factory=list)
    present: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    classical_note: str = ""
    summary: str = ""


class LevelResult(BaseModel):
    """滴天髓格局层次评估结果."""
    tendencies: list[str] = Field(default_factory=list)
    diseases: list[str] = Field(default_factory=list)
    cures: list[str] = Field(default_factory=list)
    verdict: str = ""


class ShenshaItem(BaseModel):
    """单颗神煞."""
    name: str
    pillar: str = ""
    note: str = ""


class ShenshaResult(BaseModel):
    items: list[ShenshaItem] = Field(default_factory=list)
    summary: str = ""


class BaziAnalysis(BaseModel):
    season_strength: SeasonStrength
    strength: DayMasterStrength
    tune: TuneResult
    pattern: PatternResult
    xiyongshen: Xiyongshen
    level: LevelResult | None = None
    shensha: ShenshaResult | None = None
    reasoning_chain: list[str] = Field(default_factory=list)


class DayunStep(BaseModel):
    """单步大运."""
    index: int
    ganzhi: str
    start_age: float
    end_age: float


class DayunResult(BaseModel):
    direction: str = ""
    start_age: float = 0.0
    steps: list[DayunStep] = Field(default_factory=list)
    current: DayunStep | None = None
    current_year_ganzhi: str = ""


class FateAnalysis(BaseModel):
    professional: str = ""
    vernacular: str
    xiyongshen: Xiyongshen
    reasoning_chain: list[str] = Field(default_factory=list)


class ToneSyllable(BaseModel):
    char: str
    pinyin: str
    tone_label: str


class NameCandidate(BaseModel):
    rank: int = 0
    full_name: str
    given_name: str
    meaning_score: int = 0
    citation_id: str
    citation_book: str
    citation_text: str
    citation_explanation: str = ""
    vernacular: str
    meaning: str
    wuxing: dict[str, Any]
    wuxing_label: str = ""
    tone: list[ToneSyllable] = Field(default_factory=list)
    tone_comment: str = ""
    is_word_name: bool = False
    source_word: str | None = None


class ReportSection(BaseModel):
    title: str
    content: str


class ReportFull(BaseModel):
    id: str
    surname: str
    bazi: BaziChart
    birth_summary: dict[str, str] = Field(default_factory=dict)
    bazi_chart_text: str = ""
    wuxing_analysis: str = ""
    fate_analysis: FateAnalysis
    naming_advice: str
    candidates: list[NameCandidate]
    sections: list[ReportSection] = Field(default_factory=list)
    paid: bool = False
    disclaimer: str = "本报告基于传统文化与经典文献，仅供参考，不构成命理或医学建议。"


class ReportPreview(BaseModel):
    id: str
    surname: str
    bazi_summary: dict[str, str]
    birth_summary: dict[str, str] = Field(default_factory=dict)
    fate_vernacular_excerpt: str
    fate_professional_excerpt: str = ""
    naming_advice_excerpt: str
    candidates_preview: list[NameCandidate]
    paid: bool = False
    unlock_hint: str = "解锁完整报告可查看八字命盘、五行分析与全部备选名详解"


class PricingPlan(BaseModel):
    id: str
    sku: str
    name: str
    description: str
    price_cents: int
    currency: str = "CNY"
    channel: str = "all"
    is_free: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class CheckoutRequest(BaseModel):
    report_id: str
    plan_sku: str = "report_full"


class RedeemRequest(BaseModel):
    report_id: str
    code: str


class AdminPricingPlanUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price_cents: int | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None
