"""定价服务."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import OrderRecord, PricingPlanRecord, PromoCodeRecord, ReportRecord, new_id
from app.models.schemas import PricingPlan

DEFAULT_PLAN_SKU = "report_full"

DEFAULT_PLANS = [
    {
        "sku": DEFAULT_PLAN_SKU,
        "name": "完整起名报告",
        "description": "解锁全部备选名、典籍出处与换一批",
        "price_cents": 990,
        "channel": "all",
        "sort_order": 0,
        "metadata_json": {"original_price_cents": 1990},
    },
]


def plan_is_free(price_cents: int) -> bool:
    return price_cents <= 0


async def seed_pricing_if_empty(session: AsyncSession) -> None:
    existing = await session.scalar(select(PricingPlanRecord.id).limit(1))
    if existing:
        return
    for p in DEFAULT_PLANS:
        session.add(PricingPlanRecord(id=new_id(), **p))
    session.add(PromoCodeRecord(
        code="DEMO-FREE", discount_type="free", max_uses=9999,
        created_at=datetime.now(timezone.utc),
    ))
    await session.commit()


async def get_active_plan(session: AsyncSession, sku: str = DEFAULT_PLAN_SKU) -> PricingPlanRecord | None:
    await seed_pricing_if_empty(session)
    return await session.scalar(
        select(PricingPlanRecord).where(
            PricingPlanRecord.sku == sku,
            PricingPlanRecord.is_active.is_(True),
        )
    )


async def is_full_report_free(session: AsyncSession) -> bool:
    plan = await get_active_plan(session)
    return plan is not None and plan_is_free(plan.price_cents)


async def unlock_report(
    session: AsyncSession,
    report_id: str,
    session_id: str,
    *,
    plan_id: str,
    sku: str,
    price_cents: int,
    payment_channel: str,
) -> bool:
    """原子解锁报告：使用 UPDATE WHERE paid=false 避免竞态条件."""
    report = await session.get(ReportRecord, report_id)
    if not report:
        return False
    if report.paid:
        return True

    # 原子更新：仅当 paid=false 时才设置为 true
    result = await session.execute(
        update(ReportRecord)
        .where(ReportRecord.id == report_id, ReportRecord.paid.is_(False))
        .values(paid=True)
    )
    if result.rowcount == 0:
        # 另一个并发请求已经解锁，刷新并返回
        await session.refresh(report)
        return True

    # 更新 payload 中的 paid 标志
    payload = dict(report.payload)
    payload["paid"] = True
    await session.execute(
        update(ReportRecord)
        .where(ReportRecord.id == report_id)
        .values(payload=payload)
    )

    # 检查是否已有订单（幂等性），避免重复创建
    existing_order = await session.scalar(
        select(OrderRecord.id).where(
            OrderRecord.report_id == report_id,
            OrderRecord.status == "paid",
        ).limit(1)
    )
    if not existing_order:
        order = OrderRecord(
            id=new_id(),
            report_id=report_id,
            session_id=session_id,
            plan_id=plan_id,
            sku=sku,
            price_cents=price_cents,
            status="paid",
            payment_channel=payment_channel,
            paid_at=datetime.now(timezone.utc),
        )
        session.add(order)

    await session.commit()
    return True


async def list_active_plans(session: AsyncSession, channel: str = "web") -> list[PricingPlan]:
    await seed_pricing_if_empty(session)
    result = await session.execute(
        select(PricingPlanRecord).where(PricingPlanRecord.is_active.is_(True)).order_by(PricingPlanRecord.sort_order)
    )
    plans = []
    for row in result.scalars().all():
        if row.channel not in (channel, "all", "miniprogram"):
            continue
        plans.append(PricingPlan(
            id=row.id,
            sku=row.sku,
            name=row.name,
            description=row.description,
            price_cents=row.price_cents,
            currency=row.currency,
            channel=row.channel,
            is_free=plan_is_free(row.price_cents),
            metadata=row.metadata_json or {},
        ))
    return plans


async def checkout(session: AsyncSession, report_id: str, session_id: str, plan_sku: str) -> OrderRecord:
    plan = await get_active_plan(session, plan_sku)
    if not plan:
        raise ValueError("plan not found")

    # 幂等性：如果已有 paid 订单，直接返回
    existing = await session.scalar(
        select(OrderRecord)
        .where(OrderRecord.report_id == report_id, OrderRecord.status == "paid")
        .order_by(OrderRecord.created_at.desc())
    )
    if existing:
        return existing

    if plan_is_free(plan.price_cents):
        await unlock_report(
            session, report_id, session_id,
            plan_id=plan.id, sku=plan.sku,
            price_cents=0, payment_channel="free",
        )
        order = await session.scalar(
            select(OrderRecord)
            .where(OrderRecord.report_id == report_id, OrderRecord.status == "paid")
            .order_by(OrderRecord.created_at.desc())
        )
        if order:
            return order
        # 极端情况 fallback：unlock_report 成功但未创建订单
        order = OrderRecord(
            id=new_id(), report_id=report_id, session_id=session_id,
            plan_id=plan.id, sku=plan.sku, price_cents=0,
            status="paid", payment_channel="free",
            paid_at=datetime.now(timezone.utc),
        )
        session.add(order)
        await session.commit()
        return order

    # 付费计划：检查是否有未支付的 pending 订单，避免重复创建
    pending = await session.scalar(
        select(OrderRecord)
        .where(OrderRecord.report_id == report_id, OrderRecord.status == "pending")
        .order_by(OrderRecord.created_at.desc())
    )
    if pending:
        return pending

    order = OrderRecord(
        id=new_id(), report_id=report_id, session_id=session_id,
        plan_id=plan.id, sku=plan.sku, price_cents=plan.price_cents,
        status="pending",
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order


async def redeem_code(session: AsyncSession, report_id: str, code: str, session_id: str) -> bool:
    await seed_pricing_if_empty(session)
    promo = await session.get(PromoCodeRecord, code.upper())
    if not promo or not promo.is_active or promo.used_count >= promo.max_uses:
        return False
    if promo.expires_at and promo.expires_at < datetime.now(timezone.utc):
        return False
    report = await session.get(ReportRecord, report_id)
    if not report:
        return False

    # 同一 session 同一优惠码仅可使用一次
    existing = await session.scalar(
        select(OrderRecord.id).where(
            OrderRecord.report_id == report_id,
            OrderRecord.payment_channel == "redeem",
        ).limit(1)
    )
    if existing:
        return False

    promo.used_count += 1
    return await unlock_report(
        session, report_id, session_id,
        plan_id=promo.plan_id or "", sku=DEFAULT_PLAN_SKU,
        price_cents=0, payment_channel="redeem",
    )
