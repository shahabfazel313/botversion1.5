from __future__ import annotations

from html import escape
from html import escape
from typing import Any

from ..config import CURRENCY, ADMIN_IDS


def _price_to_int(value: str) -> int:
    value = (value or "").strip()
    if value.isdigit():
        return int(value)
    try:
        return int("".join(ch for ch in value if ch.isdigit()))
    except Exception:
        return 0


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


def _order_title(service_category: str, code: str, notes: str | None = None) -> str:
    if service_category == "AI":
        return {
            "team": "اکانت ChatGPT Team",
            "plus": "اکانت ChatGPT Plus",
            "google": "اکانت Google AI Pro",
        }.get(code, "سرویس هوش مصنوعی")
    if service_category == "TG":
        if code.startswith("premium_"):
            months = code.split("_")[1]
            mapping = {"3m": "۳ ماهه", "6m": "۶ ماهه", "12m": "۱۲ ماهه"}
            label = mapping.get(months, months)
            return f"تلگرام پرمیوم ({label})"
        if code == "ready_pre":
            return "اکانت تلگرام آماده (از پیش ساخته‌شده)"
        if code == "ready_country":
            return "اکانت تلگرام آماده (کشور دلخواه)"
    return "سفارش"


async def _notify_admins(bot: Any, text: str) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass


def _fmt_order_for_user(order: dict[str, Any]) -> str:
    title = _order_title(
        order.get("service_category", ""),
        order.get("service_code", ""),
        order.get("notes"),
    )
    amount = int(order.get("amount_total") or order.get("price") or 0)
    payment_type = order.get("payment_type") or "—"
    wallet_used = int(order.get("wallet_used_amount") or 0)
    status = _status_fa(order.get("status") or "")
    created = (order.get("created_at") or "").replace("T", " ")
    payment_label = {
        "CARD": "کارت",
        "WALLET": "کیف پول",
        "MIXED": "ترکیبی",
        "FIRST_PLAN": "طرح خرید اول",
    }.get(payment_type, "—")
    account_mode = (order.get("account_mode") or "").upper()
    account_mode_label = {
        "MY_ACCOUNT": "روی اکانت خودم",
        "PREBUILT": "اکانت آماده",
    }.get(account_mode)

    details: list[str] = []
    if account_mode_label:
        details.append(f"🔧 حالت اکانت: <b>{account_mode_label}</b>")

    customer_email = (order.get("customer_email") or "").strip()
    if account_mode == "MY_ACCOUNT" and customer_email:
        details.append(f"🔐 اکانت ثبت‌شده: <code>{escape(customer_email)}</code>")

    notes_raw = (order.get("notes") or "").strip()
    if notes_raw:
        desired_id = ""
        remainder = ""
        if notes_raw.startswith("desired_id="):
            desired_part = notes_raw.split("=", 1)[1]
            desired_id, _, rest = desired_part.partition("\n")
            desired_id = desired_id.strip()
            remainder = rest.strip()
        else:
            remainder = notes_raw

        if desired_id:
            display_id = desired_id if desired_id.startswith("@") else f"@{desired_id}"
            details.append(f"👤 آیدی درخواستی: <code>{escape(display_id)}</code>")

        if remainder:
            label = "📝 اطلاعات تحویل" if account_mode == "PREBUILT" else "📝 یادداشت سفارش"
            details.append(f"{label}: {escape(remainder)}")

    details_text = "\n" + "\n".join(details) if details else ""

    return (
        f"📦 <b>{title}</b>\n"
        f"شماره سفارش: <code>#{order['id']}</code>\n"
        f"مبلغ: <b>{amount} {CURRENCY}</b>\n"
        f"نوع پرداخت: <b>{payment_label}</b>\n"
        f"مقدار استفاده‌شده از کیف پول: <b>{wallet_used} {CURRENCY}</b>\n"
        f"وضعیت: <b>{status}</b>\n"
        f"تاریخ ثبت: <b>{created}</b>"
        f"{details_text}"
    )


__all__ = [
    "_fmt_order_for_user",
    "_notify_admins",
    "_order_title",
    "_price_to_int",
    "_status_fa",
]
