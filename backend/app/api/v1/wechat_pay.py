"""微信支付."""

from __future__ import annotations

import base64
import json
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import OrderRecord, ReportRecord, get_session_factory
from app.services.pricing import get_active_plan

router = APIRouter(prefix="/api/v1/payment", tags=["payment"])


async def get_db():
    factory = get_session_factory()
    async with factory() as session:
        yield session

# ── Models ──


class WechatPrepayRequest(BaseModel):
    report_id: str
    plan_sku: str


class WechatPrepayResponse(BaseModel):
    """返回给小程序 wx.requestPayment 的参数."""
    timeStamp: str
    nonceStr: str
    package: str
    signType: str
    paySign: str
    order_id: str
    _dev_mode: bool = False


class WechatCallbackRequest(BaseModel):
    id: str
    create_time: str
    resource_type: str
    event_type: str
    summary: str
    resource: dict


# ── Helpers ──


def _generate_nonce() -> str:
    return uuid.uuid4().hex[:32]


def _load_private_key(path: str):
    """加载商户私钥（PKCS#8 PEM 格式）."""
    key_data = Path(path).read_bytes()
    return serialization.load_pem_private_key(key_data, password=None)


def _wechat_pay_v3_sign(
    method: str,
    url_path: str,
    body: str,
    nonce: str,
    timestamp: int,
    private_key_path: str,
) -> str:
    """生成 WeChat Pay API v3 Authorization 签名。

    签名串格式: HTTP方法\nURL路径\n时间戳\n随机串\n请求体\n
    """
    sign_str = f"{method}\n{url_path}\n{timestamp}\n{nonce}\n{body}\n"
    private_key = _load_private_key(private_key_path)
    signature = private_key.sign(
        sign_str.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def _wechat_pay_auth_headers(
    method: str,
    url_path: str,
    body: str,
) -> dict:
    """构建 WeChat Pay API v3 请求头（含 Authorization 签名）."""
    settings = get_settings()
    nonce = _generate_nonce()
    timestamp = int(time.time())

    sign = _wechat_pay_v3_sign(
        method, url_path, body, nonce, timestamp,
        settings.wechat_mch_private_key_path,
    )
    auth = (
        f'WECHATPAY2-SHA256-RSA2048 mchid="{settings.wechat_mch_id}",'
        f'nonce_str="{nonce}",'
        f'timestamp="{timestamp}",'
        f'serial_no="{settings.wechat_mch_serial_no}",'
        f'signature="{sign}"'
    )
    return {
        "Authorization": auth,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


async def _create_prepay(openid: str, order_id: str, amount_cents: int, description: str) -> dict:
    """调用微信支付 JSAPI 下单接口."""
    settings = get_settings()

    # Dev 模式检测：mock openid 或未配置微信支付
    is_dev_openid = openid.startswith("dev_openid_")
    dev_mode = is_dev_openid
    if not settings.wechat_mch_id:
        dev_mode = True
    elif not settings.wechat_app_id:
        dev_mode = True
    elif not settings.wechat_mch_private_key_path:
        dev_mode = True
    elif not settings.wechat_mch_serial_no:
        dev_mode = True

    if dev_mode:
        return {
            "prepay_id": f"dev_mock_{order_id}",
            "_dev_mode": True,
        }

    url_path = "/v3/pay/transactions/jsapi"
    url = f"https://api.mch.weixin.qq.com{url_path}"
    payload = {
        "appid": settings.wechat_app_id,
        "mchid": settings.wechat_mch_id,
        "description": description,
        "out_trade_no": order_id,
        "notify_url": settings.wechat_pay_notify_url,
        "amount": {"total": amount_cents, "currency": "CNY"},
        "payer": {"openid": openid},
    }
    body = json.dumps(payload, ensure_ascii=False)

    headers = _wechat_pay_auth_headers("POST", url_path, body)

    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.post(url, content=body.encode("utf-8"), headers=headers)
        if resp.status_code not in (200, 202, 204):
            detail = resp.text[:300] if resp.text else "unknown error"
            raise HTTPException(
                502,
                f"微信支付下单失败 [{resp.status_code}]: {detail}",
            )
        data = resp.json()

    if "prepay_id" not in data:
        raise HTTPException(400, f"微信支付下单失败: {data.get('message', 'unknown')}")
    return data


def _sign_prepay(prepay_id: str) -> dict:
    """生成 wx.requestPayment 所需的签名字段（小程序端调起支付参数签名）."""
    settings = get_settings()
    nonce = _generate_nonce()
    timestamp = str(int(time.time()))
    package = f"prepay_id={prepay_id}"

    # wx.requestPayment 签名串: appId\ntimeStamp\nnonceStr\npackage\n
    sign_str = f"{settings.wechat_app_id}\n{timestamp}\n{nonce}\n{package}\n"

    try:
        private_key = _load_private_key(settings.wechat_mch_private_key_path)
        signature = private_key.sign(
            sign_str.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        pay_sign = base64.b64encode(signature).decode("utf-8")
    except Exception:
        pay_sign = ""

    return {
        "timeStamp": timestamp,
        "nonceStr": nonce,
        "package": package,
        "signType": "RSA",
        "paySign": pay_sign,
    }


# ── Routes ──


@router.post("/wechat-prepay", response_model=WechatPrepayResponse)
async def wechat_prepay(
    req: WechatPrepayRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """创建微信支付预支付订单."""
    # 从 header 获取 openid（由登录拦截器注入或前端传入）
    openid = request.headers.get("X-Openid", "")
    dev_mode = openid.startswith("dev_openid_")
    if not openid:
        raise HTTPException(401, "请先微信登录")
    if dev_mode:
        import logging
        logging.getLogger("uvicorn").info(f"Dev mode payment with mock openid: {openid}")

    # 获取定价方案
    plan = await get_active_plan(db, req.plan_sku)
    if not plan:
        raise HTTPException(404, "定价方案不存在")

    # 检查报告
    report = await db.get(ReportRecord, req.report_id)
    if not report:
        raise HTTPException(404, "报告不存在")

    order_id = f"WX{int(time.time() * 1000)}{uuid.uuid4().hex[:8].upper()}"

    # 保存订单
    order = OrderRecord(
        id=order_id,
        report_id=req.report_id,
        session_id=report.session_id,
        plan_id=plan.id,
        sku=plan.sku,
        price_cents=plan.price_cents,
        currency=plan.currency,
        status="pending",
        payment_channel="wechat",
    )
    db.add(order)
    await db.commit()

    # 调用微信支付下单
    prepay = await _create_prepay(openid, order_id, plan.price_cents, plan.name)

    # Dev 模式：微信支付未配置，自动标记支付成功供本地调试
    if prepay.get("_dev_mode"):
        order.status = "paid"
        report.paid = True
        await db.commit()

        return WechatPrepayResponse(
            timeStamp=str(int(time.time())),
            nonceStr=_generate_nonce(),
            package=f"prepay_id={prepay['prepay_id']}",
            signType="RSA",
            paySign="",
            order_id=order_id,
            _dev_mode=True,
        )

    sign_params = _sign_prepay(prepay["prepay_id"])
    return WechatPrepayResponse(order_id=order_id, **sign_params)


@router.post("/wechat-callback")
async def wechat_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """微信支付回调通知."""
    body = await request.body()
    # 生产环境需验证签名
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "invalid body")

    event_type = data.get("event_type", "")
    resource = data.get("resource", {})

    if event_type == "TRANSACTION.SUCCESS":
        # 解密 resource（生产环境需 AES-256-GCM 解密）
        try:
            ciphertext = resource.get("ciphertext", "{}")
            tx_data = json.loads(ciphertext)
        except Exception:
            tx_data = resource

        out_trade_no = tx_data.get("out_trade_no", "")
        if out_trade_no:
            order = await db.get(OrderRecord, out_trade_no)
            if order and order.status != "paid":
                order.status = "paid"
                report = await db.get(ReportRecord, order.report_id)
                if report:
                    report.paid = True
                await db.commit()

    return {"code": "SUCCESS", "message": "OK"}
