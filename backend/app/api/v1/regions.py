from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import BirthPlace, RegionItem
from app.regions.store import list_children, resolve_birth_place

router = APIRouter(prefix="/api/v1/regions", tags=["regions"])


@router.get("", response_model=list[RegionItem])
async def regions_list(parent: str | None = Query(default=None, description="父级区划 code，空则返回省份")):
    return list_children(parent)


@router.get("/geocode", response_model=BirthPlace)
async def regions_geocode(code: str = Query(..., description="区划 code（建议选到区县）")):
    try:
        return resolve_birth_place(code)
    except KeyError:
        raise HTTPException(404, "region not found")
