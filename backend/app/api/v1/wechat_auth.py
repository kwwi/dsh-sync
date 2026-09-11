"""微信登录."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import SessionRecord, get_session_factory

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


async def get_db():
    factory = get_session_factory()
    async with factory() as session:
        yield session

_USER_SESSION_MAP: dict[str, str] = {}  # openid -> session_id mapping

# ── Request/Response models ──


class WechatLoginRequest(BaseModel):
    code: str


class WechatLoginResponse(BaseModel):
    session_id: str
    openid: str
    is_new_user: bool


# ── Helpers ──


async def _code2session(code: str) -> dict[str, Any]:
    """调用微信 code2session 接口换取 openid 和 session_key."""
    settings = get_settings()
    url = "https://api.weixin.qq.com/sns/jscode2session"
    params = {
        "appid": settings.wechat_app_id,
        "secret": settings.wechat_app_secret.get_secret_value(),
        "js_code": code,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        data = resp.json()
    if "errcode" in data and data["errcode"] != 0:
        raise HTTPException(400, f"微信登录失败: {data.get('errmsg', 'unknown')}")
    return data


def _hmac_sha256(key: bytes, msg: str) -> str:
    return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()


def _generate_session_id(openid: str) -> str:
    """基于 openid 生成稳定的 session_id（跨日/重启保持一致，报告历史才可回查）."""
    settings = get_settings()
    secret = settings.wechat_app_secret.get_secret_value().encode()
    return f"wx-{_hmac_sha256(secret, openid)[:16]}"


# ── Routes ──


@router.post("/wechat-login", response_model=WechatLoginResponse)
async def wechat_login(req: WechatLoginRequest, db: AsyncSession = Depends(get_db)):
    """微信小程序登录：code换取openid，返回session_id."""
    wx_data = await _code2session(req.code)
    openid = wx_data["openid"]

    # 检查是否已有活跃 session
    existing_sid = _USER_SESSION_MAP.get(openid)
    is_new = False

    if existing_sid:
        # 验证 session 是否还存在
        existing = await db.get(SessionRecord, existing_sid)
        if existing:
            return WechatLoginResponse(session_id=existing_sid, openid=openid, is_new_user=False)

    # 创建新 session
    session_id = _generate_session_id(openid)
    db.add(SessionRecord(id=session_id))
    _USER_SESSION_MAP[openid] = session_id
    is_new = True
    await db.commit()

    return WechatLoginResponse(session_id=session_id, openid=openid, is_new_user=is_new)
