"""管理端定价 API."""

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routes import get_db
from app.config import get_settings
from app.db.session import PricingPlanRecord
from app.models.schemas import AdminPricingPlanUpdate

router = APIRouter(prefix="/api/v1/admin/pricing", tags=["admin"])


def verify_admin(x_admin_key: str = Header(...)):
    if x_admin_key != get_settings().admin_api_key:
        raise HTTPException(403, "forbidden")


@router.get("/plans")
async def admin_list_plans(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    result = await db.execute(select(PricingPlanRecord))
    return [
        {
            "id": r.id,
            "sku": r.sku,
            "name": r.name,
            "price_cents": r.price_cents,
            "is_active": r.is_active,
            "metadata": r.metadata_json,
        }
        for r in result.scalars().all()
    ]


@router.put("/plans/{plan_id}")
async def admin_update_plan(
    plan_id: str,
    body: AdminPricingPlanUpdate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    row = await db.get(PricingPlanRecord, plan_id)
    if not row:
        raise HTTPException(404)
    if body.name is not None:
        row.name = body.name
    if body.description is not None:
        row.description = body.description
    if body.price_cents is not None:
        row.price_cents = body.price_cents
    if body.is_active is not None:
        row.is_active = body.is_active
    if body.metadata is not None:
        row.metadata_json = body.metadata
    await db.commit()
    return {"ok": True, "price_cents": row.price_cents}
