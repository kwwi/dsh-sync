"""报告流式生成测试."""

import json
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_report_generate_stream_emits_progress():
    payload = {
        "surname": "李",
        "gender": "male",
        "birth_datetime": "1988-01-12T17:55:00+08:00",
        "birth_place": {
            "province": "贵州省",
            "city": "毕节市",
            "district": "黔西县",
            "longitude": 106.03,
            "latitude": 27.01,
        },
        "output_count": 1,
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream(
            "POST",
            "/api/v1/report/generate/stream",
            json=payload,
            headers={"X-Session-Id": "stream-test-session"},
        ) as resp:
            assert resp.status_code == 200
            body = ""
            async for chunk in resp.aiter_text():
                body += chunk
            assert "event: progress" in body
            assert "event: done" in body
            assert "report_id" in body
            assert "八字排盘" in body or "bazi" in body
