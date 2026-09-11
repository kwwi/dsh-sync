import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_report_flow_preview_and_redeem():
    transport = ASGITransport(app=app)
    headers = {"X-Session-Id": "test-session-e2e"}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        gen = await client.post(
            "/api/v1/report/generate",
            headers=headers,
            json={
                "surname": "侯",
                "gender": "male",
                "birth_datetime": "1988-01-12T17:55:00+08:00",
                "birth_place": {"longitude": 106.03, "latitude": 27.01},
                "output_count": 3,
            },
        )
        assert gen.status_code == 200
        report_id = gen.json()["report_id"]

        preview = await client.get(f"/api/v1/report/{report_id}?tier=preview", headers=headers)
        assert preview.status_code == 200
        assert preview.json()["paid"] is False

        full_before = await client.get(f"/api/v1/report/{report_id}?tier=full", headers=headers)
        assert full_before.status_code == 402

        redeem = await client.post(
            "/api/v1/payment/redeem",
            headers=headers,
            json={"report_id": report_id, "code": "DEMO-FREE"},
        )
        assert redeem.status_code == 200

        full = await client.get(f"/api/v1/report/{report_id}?tier=full", headers=headers)
        assert full.status_code == 200
        body = full.json()
        assert len(body["candidates"]) >= 1
        for c in body["candidates"]:
            assert c.get("citation_id")
            assert 1 <= len(c.get("given_name", "")) <= 2
            assert c.get("meaning_score", 0) >= 5


@pytest.mark.asyncio
async def test_pricing_plans():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/pricing/plans")
        assert r.status_code == 200
        plans = r.json()
        assert any(p["sku"] == "report_full" for p in plans)


@pytest.mark.asyncio
async def test_free_checkout_when_price_zero():
    from app.config import get_settings

    transport = ASGITransport(app=app)
    headers = {"X-Session-Id": "test-session-free", "X-Admin-Key": get_settings().admin_api_key}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        plans = await client.get("/api/v1/pricing/plans")
        plan_id = next(p["id"] for p in plans.json() if p["sku"] == "report_full")
        await client.put(
            f"/api/v1/admin/pricing/plans/{plan_id}",
            headers=headers,
            json={"price_cents": 0},
        )

        gen = await client.post(
            "/api/v1/report/generate",
            headers=headers,
            json={
                "surname": "侯",
                "gender": "male",
                "birth_datetime": "1988-01-12T17:55:00+08:00",
                "birth_place": {"longitude": 106.03},
                "output_count": 3,
            },
        )
        report_id = gen.json()["report_id"]

        checkout_res = await client.post(
            "/api/v1/payment/checkout",
            headers=headers,
            json={"report_id": report_id, "plan_sku": "report_full"},
        )
        assert checkout_res.status_code == 200
        body = checkout_res.json()
        assert body["price_cents"] == 0
        assert body["free"] is True
        assert body["status"] == "paid"

        full = await client.get(f"/api/v1/report/{report_id}?tier=full", headers=headers)
        assert full.status_code == 200
        body = full.json()
        assert len(body["candidates"]) >= 1
        for c in body["candidates"]:
            assert c.get("citation_id")
            assert 1 <= len(c.get("given_name", "")) <= 2
            assert c.get("meaning_score", 0) >= 5

        await client.put(
            f"/api/v1/admin/pricing/plans/{plan_id}",
            headers=headers,
            json={"price_cents": 990},
        )
