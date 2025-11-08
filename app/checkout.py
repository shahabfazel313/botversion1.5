from typing import Any

from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from .db import get_order
from .config import CURRENCY

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

def _kb_checkout(oid: int, *, enable_plan: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="💳 پرداخت کارت", callback_data=f"cart:paycard:{oid}"),
            InlineKeyboardButton(text="👛 کیف پول", callback_data=f"cart:paywallet:{oid}"),
        ],
    ]
    mix_row = [InlineKeyboardButton(text="🔀 پرداخت ترکیبی", callback_data=f"cart:paymix:{oid}")]
    if enable_plan:
        mix_row.append(InlineKeyboardButton(text="✨ طرح خرید اول", callback_data=f"cart:payplan:{oid}"))
    rows.append(mix_row)
    rows.append([InlineKeyboardButton(text="❌ لغو سفارش", callback_data=f"cart:cancel:{oid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def build_checkout_summary(order: dict[str, Any], *, include_footer: bool = True) -> str:
    title = _order_title(order.get("service_category", ""), order.get("service_code", ""))
    amount_total = int(order.get("amount_total") or 0)
    amount_original = int(order.get("amount_original") or 0)
    discount_amount = int(order.get("discount_amount") or 0)
    status = _status_fa(order.get("status") or "")
    lines = [
        f"📦 <b>{title}</b>",
        f"شماره سفارش: <code>#{order['id']}</code>",
    ]
    if discount_amount > 0:
        original_display = amount_original if amount_original else amount_total + discount_amount
        lines.append(f"مبلغ اولیه: <b>{original_display} {CURRENCY}</b>")
        lines.append(f"تخفیف: <b>-{discount_amount} {CURRENCY}</b>")
        lines.append(f"مبلغ قابل پرداخت: <b>{amount_total} {CURRENCY}</b>")
        code_value = (order.get("discount_code") or "").strip()
        if code_value:
            lines.append(f"کد تخفیف: <code>{code_value}</code>")
    else:
        lines.append(f"مبلغ: <b>{amount_total} {CURRENCY}</b>")
    lines.append(f"وضعیت: <b>{status}</b>")
    if include_footer:
        lines.append("\nبرای ادامه، روش پرداخت را انتخاب کنید:")
    return "\n".join(lines)


async def send_checkout_prompt(msg: Message, order_id: int):
    o = get_order(order_id)
    if not o:
        await msg.answer("سفارش پیدا نشد.")
        return
    text = build_checkout_summary(o)
    enable_plan = o.get("service_category") == "AI"
    await msg.answer(text, reply_markup=_kb_checkout(o["id"], enable_plan=enable_plan))
