"""调价 CLI."""

import asyncio
import sys

from sqlalchemy import select

from app.db.session import PricingPlanRecord, get_session_factory, init_db


async def set_price(sku: str, price_cents: int) -> None:
    await init_db()
    factory = get_session_factory()
    async with factory() as session:
        row = await session.scalar(select(PricingPlanRecord).where(PricingPlanRecord.sku == sku))
        if not row:
            print(f"plan {sku} not found")
            return
        row.price_cents = price_cents
        await session.commit()
        print(f"updated {sku} -> {price_cents} cents")


if __name__ == "__main__":
    sku = sys.argv[1] if len(sys.argv) > 1 else "report_full"
    cents = int(sys.argv[2]) if len(sys.argv) > 2 else 990
    asyncio.run(set_price(sku, cents))
