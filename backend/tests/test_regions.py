import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_regions_provinces(client):
    r = await client.get("/api/v1/regions")
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 31
    assert any(x["name"] == "贵州省" for x in data)


@pytest.mark.asyncio
async def test_regions_children_and_geocode(client):
    provinces = (await client.get("/api/v1/regions")).json()
    gz = next(x for x in provinces if x["name"] == "贵州省")
    cities = (await client.get("/api/v1/regions", params={"parent": gz["code"]})).json()
    zy = next(x for x in cities if "遵义" in x["name"])
    districts = (await client.get("/api/v1/regions", params={"parent": zy["code"]})).json()
    tz = next(x for x in districts if x["name"] == "桐梓县")

    geo = (await client.get("/api/v1/regions/geocode", params={"code": tz["code"]})).json()
    assert geo["province"] == "贵州省"
    assert geo["city"] == "遵义市"
    assert geo["district"] == "桐梓县"
    assert 106 < geo["longitude"] < 107
    assert 28 < geo["latitude"] < 29
