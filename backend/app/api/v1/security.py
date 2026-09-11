"""内容安全审核."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(prefix="/api/v1/security", tags=["security"])

# ── Models ──


class ContentCheckRequest(BaseModel):
    content: str
    scene: int = 1  # 1=资料, 2=评论, 3=论坛, 4=社交日志
    openid: str = ""


class ContentCheckResponse(BaseModel):
    passed: bool
    label: int = 0  # 100=正常, 20001=广告, 20002=色情, 20003=敏感, etc.
    suggestion: str = ""
    detail: str = ""


# ── Routes ──


@router.post("/content-check", response_model=ContentCheckResponse)
async def content_check(req: ContentCheckRequest):
    """调用微信 msgSecCheck 进行内容安全审核."""
    settings = get_settings()

    if not settings.wechat_app_id or not settings.wechat_app_secret:
        # 未配置微信时放行（开发/测试环境）
        return ContentCheckResponse(passed=True, label=100, suggestion="pass", detail="dev mode bypass")

    # 获取 access_token
    token = await _get_access_token()
    if not token:
        raise HTTPException(500, "获取 access_token 失败")

    # 调用 msgSecCheck
    url = f"https://api.weixin.qq.com/wxa/msg_sec_check?access_token={token}"
    payload = {
        "content": req.content[:500],  # 限制长度
        "version": 2,
        "scene": req.scene,
        "openid": req.openid,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        data = resp.json()

    errcode = data.get("errcode", -1)
    if errcode != 0:
        raise HTTPException(500, f"内容审核调用失败: {data.get('errmsg', 'unknown')}")

    result = data.get("result", {})
    label = result.get("label", 100)
    suggest = result.get("suggest", "pass")

    return ContentCheckResponse(
        passed=(suggest == "pass" and label == 100),
        label=label,
        suggestion=suggest,
        detail=str(result.get("detail", "")),
    )


# ── Helpers ──

_access_token_cache: dict = {"token": "", "expires": 0}


async def _get_access_token() -> str:
    """获取微信全局 access_token（带缓存）."""
    import time

    now = int(time.time())
    if _access_token_cache["token"] and _access_token_cache["expires"] > now + 60:
        return _access_token_cache["token"]

    settings = get_settings()
    url = "https://api.weixin.qq.com/cgi-bin/token"
    params = {
        "grant_type": "client_credential",
        "appid": settings.wechat_app_id,
        "secret": settings.wechat_app_secret.get_secret_value(),
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        data = resp.json()

    if "access_token" in data:
        _access_token_cache["token"] = data["access_token"]
        _access_token_cache["expires"] = now + data.get("expires_in", 7200)
        return data["access_token"]

    return ""
