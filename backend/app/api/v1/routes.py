from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response, StreamingResponse
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.bazi.engine import calculate_bazi
from app.db.session import OrderRecord, ReportRecord, SessionRecord, get_session_factory, new_id
from app.models.schemas import BaziCalculateRequest, BaziChart
from app.orchestrator import generate_report, to_preview
from app.report.simplify_report import simplify_preview, simplify_report
from app.models.schemas import (
    CheckoutRequest,
    RedeemRequest,
    ReportGenerateRequest,
    ReportFull,
    ReportPreview,
)
from app.services.pricing import checkout, get_active_plan, is_full_report_free, list_active_plans, redeem_code, unlock_report

router = APIRouter(prefix="/api/v1")


async def get_db():
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def get_session_id(x_session_id: str | None = Header(default=None)) -> str:
    if x_session_id:
        return x_session_id
    return new_id()


@router.get("/health")
async def health():
    from app.config import get_settings
    from app.llm.config import resolve_llm_config
    cfg = resolve_llm_config()
    s = get_settings()
    return {
        "status": "ok",
        "llm": {"provider": cfg["provider"], "model": cfg["model"], "mock": cfg["mock"]},
        "env": s.app_env,
    }


@router.post("/bazi/calculate", response_model=BaziChart)
async def bazi_calculate(req: BaziCalculateRequest):
    return calculate_bazi(
        req.birth_datetime,
        longitude=req.longitude,
        latitude=req.latitude,
        gender=req.gender,
        use_true_solar=req.use_true_solar,
    )


@router.post("/report/generate")
async def report_generate(
    req: ReportGenerateRequest,
    db: AsyncSession = Depends(get_db),
    session_id: str = Depends(get_session_id),
):
    if not await db.get(SessionRecord, session_id):
        db.add(SessionRecord(id=session_id))
        await db.commit()
    full = await generate_report(db, req, session_id)
    return {"report_id": full.id, "status": "completed"}


@router.post("/report/generate/stream")
async def report_generate_stream(
    req: ReportGenerateRequest,
    session_id: str = Depends(get_session_id),
):
    """SSE 流式返回推算进度，结束时 event=done 含 report_id."""

    async def event_stream():
        import asyncio

        queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()

        async def on_progress(step: str, title: str, summary: str) -> None:
            await queue.put(("progress", {"step": step, "title": title, "summary": summary}))

        async def worker() -> None:
            try:
                factory = get_session_factory()
                async with factory() as db:
                    if not await db.get(SessionRecord, session_id):
                        db.add(SessionRecord(id=session_id))
                        await db.commit()
                    full = await generate_report(db, req, session_id, on_progress=on_progress)
                    await queue.put(("done", {"report_id": full.id, "status": "completed"}))
            except Exception as exc:
                await queue.put(("error", {"message": str(exc)}))

        task = asyncio.create_task(worker())
        try:
            while True:
                kind, payload = await queue.get()
                yield f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if kind in ("done", "error"):
                    break
        finally:
            await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/report/{report_id}")
async def get_report(
    report_id: str,
    tier: str = "preview",
    db: AsyncSession = Depends(get_db),
    session_id: str = Depends(get_session_id),
):
    row = await db.get(ReportRecord, report_id)
    if not row:
        raise HTTPException(404, "report not found")
    if row.session_id != session_id:
        raise HTTPException(403, "access denied")
    full = simplify_report(ReportFull(**row.payload))
    full.paid = row.paid
    if tier == "full":
        if not row.paid:
            # 仅当报告属于当前 session 或计划免费时才自动解锁
            if await is_full_report_free(db):
                # 检查是否已有 paid 订单，避免重复创建
                already_paid = await db.scalar(
                    select(OrderRecord.id).where(
                        OrderRecord.report_id == report_id,
                        OrderRecord.status == "paid",
                    ).limit(1)
                )
                if not already_paid:
                    plan = await get_active_plan(db)
                    if plan:
                        await unlock_report(
                            db, report_id, session_id,
                            plan_id=plan.id, sku=plan.sku,
                            price_cents=0, payment_channel="free",
                        )
                row = await db.get(ReportRecord, report_id)
                full.paid = row.paid if row else True
        if not row.paid:
            raise HTTPException(402, "payment required")
        full.paid = True
        return full
    return simplify_preview(to_preview(full))


@router.get("/pricing/plans")
async def pricing_plans(channel: str = "web", db: AsyncSession = Depends(get_db)):
    return await list_active_plans(db, channel)


@router.post("/payment/checkout")
async def payment_checkout(
    req: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
    session_id: str = Depends(get_session_id),
):
    # 校验报告存在且属于当前 session
    report = await db.get(ReportRecord, req.report_id)
    if not report:
        raise HTTPException(404, "report not found")
    if report.session_id != session_id:
        raise HTTPException(403, "access denied")
    try:
        order = await checkout(db, req.report_id, session_id, req.plan_sku)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "order_id": order.id,
        "price_cents": order.price_cents,
        "status": order.status,
        "free": order.price_cents <= 0 and order.status == "paid",
    }


@router.post("/payment/redeem")
async def payment_redeem(
    req: RedeemRequest,
    db: AsyncSession = Depends(get_db),
    session_id: str = Depends(get_session_id),
):
    # 校验报告存在且属于当前 session
    report = await db.get(ReportRecord, req.report_id)
    if not report:
        raise HTTPException(404, "report not found")
    if report.session_id != session_id:
        raise HTTPException(403, "access denied")
    ok = await redeem_code(db, req.report_id, req.code, session_id)
    if not ok:
        raise HTTPException(400, "invalid code")
    return {"unlocked": True}


@router.get("/corpus/search")
async def corpus_search(
    primary: str = "火",
    db: AsyncSession = Depends(get_db),
):
    from app.corpus.search import search_citations
    rows = await search_citations(db, [primary])
    return [{"id": r.id, "book": r.book, "original": r.original} for r in rows]


# ── 报告历史 & 下载 & 过期清理 ──

REPORT_RETENTION_DAYS = 3


async def _cleanup_expired_reports(db: AsyncSession) -> int:
    """删除超过保留期的报告，返回删除数量."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=REPORT_RETENTION_DAYS)
    result = await db.execute(
        delete(ReportRecord).where(ReportRecord.created_at < cutoff)
    )
    await db.commit()
    return result.rowcount or 0


@router.get("/reports/history")
async def report_history(
    db: AsyncSession = Depends(get_db),
    session_id: str = Depends(get_session_id),
):
    """获取当前会话的历史报告列表（3天内的报告）."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=REPORT_RETENTION_DAYS)

    rows = await db.execute(
        select(ReportRecord)
        .where(
            ReportRecord.session_id == session_id,
            ReportRecord.created_at >= cutoff,
        )
        .order_by(ReportRecord.created_at.desc())
        .limit(50)
    )
    history = []
    for row in rows.scalars().all():
        payload = row.payload or {}
        birth = payload.get("birth_summary", {})
        candidates = payload.get("candidates", [])
        first_name = candidates[0].get("full_name", "") if candidates else ""
        history.append({
            "id": row.id,
            "surname": row.surname,
            "paid": row.paid,
            "created_at": row.created_at.isoformat(),
            "birth_date": birth.get("出生公历_北京", "") or birth.get("出生公历_真太阳", ""),
            "first_name": first_name,
            "candidate_count": len(candidates),
        })
    return history


@router.get("/report/{report_id}/download")
async def download_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    session_id: str = Depends(get_session_id),
    sid: str | None = None,
):
    """下载完整报告 PDF（支持 ?sid= 参数，兼容 wx.downloadFile 无自定义 header）."""
    effective_sid = sid or session_id
    row = await db.get(ReportRecord, report_id)
    if not row:
        raise HTTPException(404, "report not found")
    if row.session_id != effective_sid:
        raise HTTPException(403, "access denied")
    if not row.paid:
        raise HTTPException(402, "payment required")

    full = simplify_report(ReportFull(**row.payload))
    birth = full.birth_summary or {}

    # 生成 PDF
    pdf_bytes = _generate_report_pdf(full, birth)

    from urllib.parse import quote
    raw_name = f"起名报告_{full.surname}_{birth.get('生辰八字', '')}"
    safe_name = "naming_report.pdf"
    encoded = quote(raw_name, safe="")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"; filename*=UTF-8\'\'{encoded}.pdf',
        },
    )


def _find_chinese_font() -> str | None:
    """查找系统可用的中文字体."""
    import platform
    candidates = []
    if platform.system() == "Darwin":
        candidates = [
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Supplemental/Songti.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        ]
    for path in candidates:
        if __import__("os").path.exists(path):
            return path
    return None


def _generate_report_pdf(full: ReportFull, birth: dict) -> bytes:
    """生成起名报告 PDF."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    # 注册中文字体
    font_path = _find_chinese_font()
    if font_path:
        pdf.add_font("cjk", "", font_path, uni=True)
        pdf.add_font("cjk", "B", font_path, uni=True)
        body_font = "cjk"
    else:
        body_font = "Helvetica"

    # 页面可用宽度
    pw = pdf.w - pdf.l_margin - pdf.r_margin

    def _w(text: str, size: int = 10, bold: bool = False):
        style = "B" if bold else ""
        pdf.set_font(body_font, style, size)
        line_h = size * 0.7
        pdf.multi_cell(pw, line_h, text, align="L")
        pdf.ln(1)

    def _section(title: str):
        pdf.ln(3)
        pdf.set_fill_color(139, 69, 19)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font(body_font, "B", 13)
        pdf.cell(pw, 9, f"  {title}", fill=True, ln=True)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)

    # 标题
    pdf.set_font(body_font, "B", 18)
    pdf.cell(pw, 12, "智能起名报告", align="C", ln=True)
    pdf.set_font(body_font, "", 8)
    pdf.set_text_color(128, 128, 128)
    pdf.cell(pw, 6, "本报告基于传统文化与经典文献生成，仅供文化参考", align="C", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)

    # 基本信息
    _section("基本信息")
    for key in ["性别", "出生地点", "出生公历_北京", "出生公历_真太阳", "出生农历", "生辰八字", "生肖"]:
        if birth.get(key):
            _w(f"{key}：{birth[key]}", 10)

    # 八字命盘
    if full.bazi_chart_text:
        _section("八字命盘")
        _w(full.bazi_chart_text, 9)

    # 五行分析
    if full.wuxing_analysis:
        _section("五行分析")
        _w(full.wuxing_analysis, 9)
        if full.fate_analysis and full.fate_analysis.professional:
            _section("专业解读")
            _w(full.fate_analysis.professional, 9)

    # 命格简析
    _section("命格简析")
    vernacular = full.fate_analysis.vernacular if full.fate_analysis else ""
    _w(vernacular, 10)

    # 取名建议
    if full.naming_advice:
        _section("取名建议")
        _w(full.naming_advice, 9)

    # 备选名字
    _section("备选名字")
    for i, c in enumerate(full.candidates, 1):
        # 检查剩余空间，不足 40mm 时换页，避免名字条目被截断
        if pdf.get_y() > pdf.h - 40:
            pdf.add_page()

        pdf.set_font(body_font, "B", 11)
        pdf.cell(pw, 7, f"{i}、{c.full_name}", ln=True)
        pdf.set_font(body_font, "", 9)
        line_h = 5.5

        if c.citation_explanation:
            pdf.set_text_color(120, 120, 120)
            pdf.multi_cell(pw, line_h, c.citation_explanation)
            pdf.set_text_color(0, 0, 0)
        if c.meaning:
            pdf.multi_cell(pw, line_h, c.meaning)

        tags = []
        if c.wuxing_label:
            tags.append(f"[五行] {c.wuxing_label}")
        if c.tone_comment:
            tags.append(f"[音韵] {c.tone_comment}")
        if tags:
            pdf.set_text_color(100, 100, 100)
            pdf.multi_cell(pw, line_h, "  ".join(tags))
            pdf.set_text_color(0, 0, 0)
        pdf.ln(5)

    # 页脚
    pdf.ln(6)
    pdf.set_font(body_font, "", 7)
    pdf.set_text_color(160, 160, 160)
    pdf.cell(pw, 5, "— 本报告由智能起名生成，仅供文化参考 —", align="C", ln=True)

    return bytes(pdf.output())
