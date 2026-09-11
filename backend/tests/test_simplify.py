"""繁转简测试."""

from app.models.schemas import NameCandidate, ReportFull
from app.report.simplify_report import simplify_candidate, simplify_report
from app.text.simplify import to_simplified


def test_to_simplified_traditional_poetry():
    text = "關關雎鳩，在河之洲。窈窕淑女，君子好逑。"
    out = to_simplified(text)
    assert "关关雎鸠" in out
    assert "君子好逑" in out
    assert "關" not in out


def test_simplify_candidate():
    c = NameCandidate(
        rank=1,
        full_name="侯明悠",
        given_name="明悠",
        citation_id="x",
        citation_book="中庸",
        citation_text="博也，厚也，高也，明也，悠也，久也。",
        citation_explanation="取自《中庸》：「天地之道，博也，厚也，高也，明也，悠也，久也。」",
        vernacular="",
        meaning="明悠：光明悠远。",
        wuxing={"chars": {}, "summary": "火"},
        wuxing_label="明悠：火",
    )
    s = simplify_candidate(c)
    assert s.full_name == c.full_name


def test_simplify_report_roundtrip():
    minimal = ReportFull(
        id="t",
        surname="侯",
        bazi={
            "beijing_time": "1988-01-12T17:55:00",
            "true_solar_time": "1988-01-12T16:50:00",
            "lunar_year": "丁卯",
            "lunar_month": "十一月",
            "lunar_day": "廿三日",
            "lunar_hour": "申时",
            "pillars": {},
            "zodiac": "兔",
            "element_counts": {"wood": 1, "fire": 1, "earth": 1, "metal": 1, "water": 1},
            "season_strength": {"wood": "囚", "fire": "休", "earth": "旺", "metal": "相", "water": "死"},
            "relations": {"clash": [], "combine": [], "harm": []},
            "day_master": {"stem": "丙", "element": "fire", "element_cn": "火"},
            "gender": "male",
        },
        fate_analysis={"vernacular": "綜合來看", "xiyongshen": {"primary": ["火"]}},
        naming_advice="建議",
        candidates=[],
    )
    out = simplify_report(minimal)
    assert out.fate_analysis.vernacular == "综合来看"
