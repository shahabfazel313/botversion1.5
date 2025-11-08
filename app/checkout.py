from aiogram.types import Message

from .config import CURRENCY
from .db import get_order
from .keyboards import ik_cart_actions

def _status_fa(code: str) -> str:
    return {
        "AWAITING_PAYMENT": "در انتظار پرداخت",
        "PENDING_CONFIRM": "در انتظار تایید پرداخت",
        "PENDING_PLAN": "در انتظار تایید طرح",
        "PLAN_CONFIRMED": "طرح تایید شد",
        "APPROVED": "پرداخت تایید شد",
        "IN_PROGRESS": "در حال انجام",
        "READY_TO_DELIVER": "آماده تحویل",
        "DELIVERED": "تحویل شد",
        "COMPLETED": "تکمیل‌شده",
        "EXPIRED": "منقضی",
        "REJECTED": "رد شده",
        "CANCELED": "لغو شده",
    }.get(code, code)

def _order_title(service_category: str, code: str) -> str:
    if service_category == "AI":
        return {"team":"اکانت ChatGPT Team", "plus":"اکانت ChatGPT Plus", "google":"اکانت Google AI Pro"}.get(code, "سرویس هوش مصنوعی")
    if service_category == "TG":
        if code.startswith("premium_"):
            period = code.split("_")[1]
            label = {"3m":"۳ ماهه","6m":"۶ ماهه","12m":"۱۲ ماهه"}.get(period, period)
            return f"تلگرام پرمیوم ({label})"
        if code == "ready_pre": return "اکانت تلگرام آماده (از پیش ساخته‌شده)"
        if code == "ready_country": return "اکانت تلگرام آماده (کشور دلخواه)"
    return "سفارش"

async def send_checkout_prompt(msg: Message, order_id: int):
    o = get_order(order_id)
    if not o:
        await msg.answer("سفارش پیدا نشد.")
        return
    title = _order_title(o.get("service_category",""), o.get("service_code",""))
    try:
        total = int(o.get("amount_total") or 0)
    except (TypeError, ValueError):
        total = 0
    try:
        subtotal = int(o.get("amount_subtotal") or total)
    except (TypeError, ValueError):
        subtotal = total
    try:
        discount_amount = int(o.get("discount_amount") or 0)
    except (TypeError, ValueError):
        discount_amount = 0
    status = _status_fa(o.get("status") or "")
    lines = [
        f"📦 <b>{title}</b>",
        f"شماره سفارش: <code>#{o['id']}</code>",
    ]
    if discount_amount > 0:
        lines.append(f"قیمت اصلی: <b>{subtotal} {CURRENCY}</b>")
        lines.append(f"تخفیف: <b>{discount_amount} {CURRENCY}</b>")
        lines.append(f"مبلغ قابل پرداخت: <b>{total} {CURRENCY}</b>")
        discount_code = str(o.get("discount_code") or "").strip()
        if discount_code:
            lines.append(f"کد تخفیف: <code>{discount_code}</code>")
    else:
        lines.append(f"مبلغ: <b>{total} {CURRENCY}</b>")
    lines.append(f"وضعیت: <b>{status}</b>")
    lines.append("")
    lines.append("برای ادامه، روش پرداخت را انتخاب کنید:")
    enable_plan = (
        o.get("service_category") == "AI"
        and (o.get("payment_type") or "") != "FIRST_PLAN_BILLING"
    )
    await msg.answer("\n".join(lines), reply_markup=ik_cart_actions(o["id"], enable_plan=enable_plan))
