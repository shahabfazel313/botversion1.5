from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import secrets
import sqlite3
import string
from aiogram import Bot
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from ..catalog import list_admin_rows, set_variant_settings
from ..config import ADMIN_WEB_PASS, ADMIN_WEB_SECRET, ADMIN_WEB_USER, BOT_TOKEN, CURRENCY
from ..db import (
    ORDER_STATUS_LABELS,
    PAYMENT_TYPE_LABELS,
    change_wallet,
    count_orders,
    count_users,
    get_dashboard_snapshot,
    get_order,
    get_user,
    get_user_stats,
    get_wallet_summary,
    init_db,
    list_orders,
    list_recent_orders,
    list_recent_users,
    list_recent_wallet_tx,
    list_users,
    list_wallet_tx_for_order,
    list_wallet_tx_for_user,
    list_service_messages,
    count_service_messages,
    get_service_message,
    list_service_message_replies,
    add_service_message_reply,
    set_service_message_status,
    set_order_payment_type,
    set_order_status,
    set_order_wallet_reserved,
    set_order_wallet_used,
    update_order_notes,
    set_user_blocked,
    add_order_manager_message,
    add_user_manager_message,
    create_coupon,
    get_coupon,
    list_coupons,
    list_coupon_redemptions,
    set_coupon_active,
    list_order_manager_messages,
    list_user_manager_messages,
    set_order_financials,
)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

ORDER_STATUS_CHOICES = list(ORDER_STATUS_LABELS.items())
PAYMENT_TYPE_CHOICES = [("", "—")] + list(PAYMENT_TYPE_LABELS.items())

SERVICE_MESSAGE_LABELS = {
    "BUILD_BOT": "ساخت ربات تلگرام",
    "OTHER_SERVICE": "خدمات دیگر",
    "TG_READY_COUNTRY": "اکانت تلگرام (کشور دلخواه)",
}


bot = Bot(BOT_TOKEN, parse_mode="HTML")
TELEGRAM_API_BASE = "https://api.telegram.org"


def _format_amount(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "0"
    return f"{number:,}".replace(",", "،")


def _format_datetime(value: Any) -> str:
    if not value:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    try:
        return datetime.fromisoformat(str(value)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value)


def _generate_coupon_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(max(4, length)))


def _flash(request: Request, text: str, category: str = "success") -> None:
    messages = request.session.get("messages") or []
    messages.append({"text": text, "category": category})
    request.session["messages"] = messages


def _render(request: Request, template_name: str, context: dict[str, Any] | None = None):
    ctx = {
        "request": request,
        "messages": request.session.pop("messages", []),
        "order_status_choices": ORDER_STATUS_CHOICES,
        "order_status_labels": ORDER_STATUS_LABELS,
        "payment_type_choices": PAYMENT_TYPE_CHOICES,
        "payment_type_labels": PAYMENT_TYPE_LABELS,
        "theme": request.session.get("theme", "light"),
        "service_message_labels": SERVICE_MESSAGE_LABELS,
    }
    if context:
        ctx.update(context)
    return templates.TemplateResponse(template_name, ctx)


async def _notify_user(user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except Exception:
        pass


async def _telegram_file_response(file_id: str) -> StreamingResponse:
    if not file_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="فایل یافت نشد")
    try:
        async with httpx.AsyncClient() as client:
            meta = await client.get(
                f"{TELEGRAM_API_BASE}/bot{BOT_TOKEN}/getFile",
                params={"file_id": file_id},
                timeout=10.0,
            )
            if meta.status_code != 200:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="فایل در تلگرام یافت نشد")
            data = meta.json().get("result") or {}
            file_path = data.get("file_path")
            if not file_path:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="مسیر فایل یافت نشد")
            file_url = f"{TELEGRAM_API_BASE}/file/bot{BOT_TOKEN}/{file_path}"
            stream = await client.get(file_url, timeout=30.0, stream=True)
            if stream.status_code != 200:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="دانلود فایل ممکن نشد")

            filename = Path(file_path).name

            async def iterator():
                async with stream:
                    async for chunk in stream.aiter_bytes():
                        yield chunk

            return StreamingResponse(
                iterator(),
                media_type=stream.headers.get("content-type", "application/octet-stream"),
                headers={"Content-Disposition": f"inline; filename={filename}"},
            )
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="خطا در ارتباط با تلگرام") from exc
    except Exception as exc:  # pragma: no cover - safety net
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="دانلود فایل با خطا مواجه شد") from exc


def _login_required(request: Request) -> str:
    user = request.session.get("auth_user")
    if user:
        return user
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    login_url = request.url_for("login")
    location = login_url
    if next_path:
        location = f"{login_url}?next={quote(next_path)}"
    raise HTTPException(status.HTTP_303_SEE_OTHER, headers={"Location": location})


def create_admin_app() -> FastAPI:
    app = FastAPI(title="Premium Bot Admin", docs_url=None, redoc_url=None)
    app.add_middleware(SessionMiddleware, secret_key=ADMIN_WEB_SECRET, same_site="lax")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.on_event("startup")
    async def _startup() -> None:  # pragma: no cover - io side effect
        init_db()

    @app.on_event("shutdown")
    async def _shutdown() -> None:  # pragma: no cover - io side effect
        await bot.session.close()

    @app.get("/", include_in_schema=False)
    async def index(request: Request):
        if request.session.get("auth_user"):
            return RedirectResponse(request.url_for("dashboard"), status.HTTP_303_SEE_OTHER)
        return RedirectResponse(request.url_for("login"), status.HTTP_303_SEE_OTHER)

    @app.get("/login", name="login")
    async def login_page(request: Request, next: str | None = None):
        if request.session.get("auth_user"):
            target = next or request.url_for("dashboard")
            return RedirectResponse(target, status.HTTP_303_SEE_OTHER)
        return _render(request, "login.html", {"next": next or ""})

    @app.post("/login")
    async def login_submit(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        next: str = Form("")
    ):
        if username == ADMIN_WEB_USER and password == ADMIN_WEB_PASS:
            request.session["auth_user"] = username
            _flash(request, "با موفقیت وارد شدید.")
            target = next or request.url_for("dashboard")
            return RedirectResponse(target, status.HTTP_303_SEE_OTHER)
        return _render(
            request,
            "login.html",
            {
                "error": "نام کاربری یا رمز عبور اشتباه است.",
                "next": next,
                "username": username,
            },
        )

    @app.get("/logout")
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse(request.url_for("login"), status.HTTP_303_SEE_OTHER)

    @app.post("/toggle-theme")
    async def toggle_theme(request: Request):
        current = request.session.get("theme", "light")
        request.session["theme"] = "dark" if current != "dark" else "light"
        referer = request.headers.get("referer")
        target = referer or request.url_for("dashboard")
        return RedirectResponse(target, status.HTTP_303_SEE_OTHER)

    @app.get("/dashboard", name="dashboard")
    async def dashboard(request: Request, user: str = Depends(_login_required)):
        snapshot = get_dashboard_snapshot()
        snapshot["messages_total"] = count_service_messages()
        recent_orders = list_recent_orders()
        recent_users = list_recent_users()
        recent_wallet = list_recent_wallet_tx()
        return _render(
            request,
            "dashboard.html",
            {
                "title": "داشبورد",
                "snapshot": snapshot,
                "recent_orders": recent_orders,
                "recent_users": recent_users,
                "recent_wallet": recent_wallet,
                "format_amount": _format_amount,
                "format_datetime": _format_datetime,
                "nav": "dashboard",
            },
        )

    @app.get("/orders")
    async def orders_page(
        request: Request,
        user: str = Depends(_login_required),
        status_filter: str = Query("all", alias="status"),
        q: str = Query("", alias="q"),
        page: int = Query(1, ge=1),
    ):
        per_page = 20
        total = count_orders(status=status_filter, search=q or None)
        pages = max((total + per_page - 1) // per_page, 1)
        page = min(page, pages)
        offset = (page - 1) * per_page
        items = list_orders(status=status_filter, search=q or None, limit=per_page, offset=offset)
        return _render(
            request,
            "orders.html",
            {
                "title": "مدیریت سفارش‌ها",
                "orders": items,
                "total": total,
                "page": page,
                "pages": pages,
                "status_filter": status_filter,
                "query": q,
                "format_amount": _format_amount,
                "format_datetime": _format_datetime,
                "nav": "orders",
            },
        )

    @app.get("/messages", name="messages")
    async def messages_page(
        request: Request,
        user: str = Depends(_login_required),
        category: str = Query("all"),
        page: int = Query(1, ge=1),
    ):
        per_page = 20
        filter_value = None if category == "all" else category
        total = count_service_messages(filter_value)
        pages = max((total + per_page - 1) // per_page, 1)
        page = min(page, pages)
        offset = (page - 1) * per_page
        items = list_service_messages(category=filter_value, limit=per_page, offset=offset)
        return _render(
            request,
            "messages.html",
            {
                "title": "پیام‌های دریافتی",
                "messages_list": items,
                "total": total,
                "page": page,
                "pages": pages,
                "category": category,
                "nav": "messages",
                "format_datetime": _format_datetime,
            },
        )

    @app.get("/products", name="products_page")
    async def products_page(request: Request, user: str = Depends(_login_required)):
        rows = list_admin_rows()
        return _render(
            request,
            "products.html",
            {
                "title": "مدیریت محصولات",
                "products": rows,
                "currency": CURRENCY,
                "nav": "products",
            },
        )

    @app.post("/products")
    async def products_update(request: Request, user: str = Depends(_login_required)):
        form = await request.form()
        rows = list_admin_rows()
        for row in rows:
            for variant in row["variants"]:
                code = variant["code"]
                price_value = str(form.get(f"price_{code}", "0")).strip()
                available = form.get(f"avail_{code}") == "on"
                set_variant_settings(code, price_value or "0", available)
        _flash(request, "تغییرات محصولات ذخیره شد.")
        return RedirectResponse(request.url_for("products_page"), status.HTTP_303_SEE_OTHER)

    @app.get("/orders/{order_id}")
    async def order_detail(request: Request, order_id: int, user: str = Depends(_login_required)):
        order = get_order(order_id)
        if not order:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="سفارش یافت نشد")
        customer = get_user(order.get("user_id")) if order.get("user_id") else None
        wallet_history = list_wallet_tx_for_order(order_id)
        related_orders = []
        if order.get("user_id"):
            related_orders = [
                o for o in list_orders(user_id=order["user_id"], limit=5) if o["id"] != order_id
            ]
        manager_messages = list_order_manager_messages(order_id, limit=50)
        order_title = order.get("plan_title") or order.get("service_code") or f"سفارش #{order_id}"
        return _render(
            request,
            "order_detail.html",
            {
                "title": f"سفارش #{order_id}",
                "order": order,
                "customer": customer,
                "wallet_history": wallet_history,
                "related_orders": related_orders,
                "manager_messages": manager_messages,
                "order_title": order_title,
                "format_amount": _format_amount,
                "format_datetime": _format_datetime,
                "nav": "orders",
            },
        )

    @app.get("/orders/{order_id}/receipt")
    async def order_receipt(order_id: int, user: str = Depends(_login_required)):
        order = get_order(order_id)
        if not order or not order.get("receipt_file_id"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="رسید برای این سفارش وجود ندارد")
        return await _telegram_file_response(order["receipt_file_id"])

    @app.get("/messages/{message_id}/attachment")
    async def message_attachment(message_id: int, user: str = Depends(_login_required)):
        message = get_service_message(message_id)
        if not message or not message.get("attachment_file_id"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="پیوست یافت نشد")
        return await _telegram_file_response(message["attachment_file_id"])

    @app.get("/messages/{message_id}")
    async def message_detail(
        request: Request,
        message_id: int,
        user: str = Depends(_login_required),
    ):
        message = get_service_message(message_id)
        if not message:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="پیام یافت نشد")
        replies = list_service_message_replies(message_id)
        customer = get_user(message.get("user_id")) if message.get("user_id") else None
        category_label = SERVICE_MESSAGE_LABELS.get(message.get("category"), message.get("category"))
        return _render(
            request,
            "message_detail.html",
            {
                "title": f"پیام #{message_id}",
                "message": message,
                "replies": replies,
                "customer": customer,
                "category_label": category_label,
                "format_datetime": _format_datetime,
                "nav": "messages",
            },
        )

    @app.post("/messages/{message_id}/reply")
    async def message_reply(
        request: Request,
        message_id: int,
        user: str = Depends(_login_required),
        reply_text: str = Form(...),
    ):
        message = get_service_message(message_id)
        if not message:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="پیام یافت نشد")
        text = (reply_text or "").strip()
        if not text:
            _flash(request, "متن پیام نمی‌تواند خالی باشد.", "error")
            return RedirectResponse(request.url_for("message_detail", message_id=message_id), status.HTTP_303_SEE_OTHER)
        add_service_message_reply(message_id, message.get("user_id"), text)
        user_id = message.get("user_id")
        if user_id:
            category_label = SERVICE_MESSAGE_LABELS.get(message.get("category"), message.get("category"))
            await _notify_user(
                user_id,
                f"📨 پاسخ مدیریت درباره درخواست «{category_label}»:\n\n{text}",
            )
        _flash(request, "پاسخ برای مشتری ارسال شد.")
        return RedirectResponse(request.url_for("message_detail", message_id=message_id), status.HTTP_303_SEE_OTHER)

    @app.post("/messages/{message_id}/status")
    async def message_status(
        request: Request,
        message_id: int,
        user: str = Depends(_login_required),
        new_status: str = Form(...),
    ):
        message = get_service_message(message_id)
        if not message:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="پیام یافت نشد")
        resolved = (new_status or "").lower() == "closed"
        set_service_message_status(message_id, resolved)
        label = "بسته" if resolved else "باز"
        _flash(request, f"وضعیت پیام به «{label}» تغییر کرد.")
        return RedirectResponse(request.url_for("message_detail", message_id=message_id), status.HTTP_303_SEE_OTHER)

    @app.post("/orders/{order_id}/update")
    async def update_order(
        request: Request,
        order_id: int,
        user: str = Depends(_login_required),
        action: str = Form(...),
        status_value: str = Form(""),
        payment_type: str = Form(""),
        manager_note: str = Form(""),
        cost_amount: str = Form("0"),
    ):
        order = get_order(order_id)
        if not order:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="سفارش یافت نشد")

        order_title = order.get("plan_title") or order.get("service_code") or f"سفارش #{order_id}"
        user_id = order.get("user_id")
        action = (action or "").strip().lower()

        if action == "status":
            if status_value not in ORDER_STATUS_LABELS:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="وضعیت نامعتبر است")

            original_status = order.get("status")
            plan_approval = status_value == "PLAN_CONFIRMED"
            if plan_approval and original_status != "PENDING_PLAN":
                _flash(request, "امکان تایید طرح وجود ندارد (وضعیت فعلی مجاز نیست).", "error")
                return RedirectResponse(request.url_for("order_detail", order_id=order_id), status.HTTP_303_SEE_OTHER)

            new_status = status_value
            if new_status in {"APPROVED", "PLAN_CONFIRMED"}:
                new_status = "IN_PROGRESS"
            if new_status not in ORDER_STATUS_LABELS:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="وضعیت نامعتبر است")

            status_changed = original_status != new_status
            if status_changed:
                set_order_status(order_id, new_status)

            if status_changed and new_status in {"IN_PROGRESS", "READY_TO_DELIVER", "DELIVERED", "COMPLETED"}:
                reserved_amount = int(order.get("wallet_reserved_amount") or 0)
                if reserved_amount > 0:
                    used_amount = int(order.get("wallet_used_amount") or 0)
                    set_order_wallet_reserved(order_id, 0)
                    set_order_wallet_used(order_id, used_amount + reserved_amount)

            updated = get_order(order_id)
            if status_changed and updated and user_id:
                if plan_approval:
                    product_title = updated.get("plan_title") or updated.get("service_code") or order_title
                    await _notify_user(
                        user_id,
                        (
                            f"✅ طرح خرید اول سفارش شما تایید شد و در حال انجام می‌باشد.\n"
                            f"سفارش #{order_id} - {product_title}"
                        ),
                    )
                elif new_status == "REJECTED":
                    reserved_amount = int(updated.get("wallet_reserved_amount") or 0)
                    used_amount = int(updated.get("wallet_used_amount") or 0)
                    total_amount = int(updated.get("amount_total") or 0)
                    card_part = max(total_amount - reserved_amount - used_amount, 0)
                    refund_total = 0
                    if reserved_amount > 0:
                        change_wallet(
                            user_id,
                            reserved_amount,
                            "REFUND",
                            note=f"Order #{order_id} rejected",
                            order_id=order_id,
                        )
                        set_order_wallet_reserved(order_id, 0)
                        refund_total += reserved_amount
                    if used_amount > 0:
                        change_wallet(
                            user_id,
                            used_amount,
                            "REFUND",
                            note=f"Order #{order_id} rejected",
                            order_id=order_id,
                        )
                        set_order_wallet_used(order_id, 0)
                        refund_total += used_amount
                    if card_part > 0:
                        change_wallet(
                            user_id,
                            card_part,
                            "CREDIT",
                            note=f"Order #{order_id} card refund",
                            order_id=order_id,
                        )
                        refund_total += card_part
                    await _notify_user(
                        user_id,
                        (
                            f"❌ سفارش «{order_title}» (#{order_id}) رد شد و مبلغ {refund_total} تومان به کیف پول شما واریز شد.\n"
                            "لطفاً در صورت نیاز با پشتیبانی تماس بگیرید."
                        ),
                    )
                elif new_status == "IN_PROGRESS":
                    await _notify_user(
                        user_id,
                        f"✅ پرداخت سفارش «{order_title}» (#{order_id}) تایید شد و در حال انجام است.",
                    )
                elif new_status == "COMPLETED":
                    manager_note_text = (updated.get("manager_note") or "").strip()
                    message = f"🎉 سفارش «{order_title}» (#{order_id}) تکمیل شد."
                    if manager_note_text:
                        message += f"\n\nپیام مدیر:\n{manager_note_text}"
                    await _notify_user(user_id, message)
                else:
                    label = ORDER_STATUS_LABELS.get(new_status, new_status)
                    await _notify_user(
                        user_id,
                        f"📦 وضعیت سفارش «{order_title}» (#{order_id}) به «{label}» تغییر کرد.",
                    )

            _flash(request, "وضعیت سفارش به‌روزرسانی شد.")

        elif action == "payment":
            normalized_payment = payment_type or None
            if (order.get("payment_type") or None) != normalized_payment:
                set_order_payment_type(order_id, normalized_payment)
                _flash(request, "نوع پرداخت سفارش به‌روزرسانی شد.")
            else:
                _flash(request, "تغییری در نوع پرداخت ایجاد نشد.", "info")

        elif action == "plan_confirm":
            if order.get("status") != "PENDING_PLAN":
                _flash(request, "امکان تایید طرح وجود ندارد (وضعیت نامعتبر است).", "error")
            else:
                set_order_status(order_id, "IN_PROGRESS")
                updated = get_order(order_id)
                if user_id:
                    product_title = updated.get("plan_title") or updated.get("service_code") or order_title
                    await _notify_user(
                        user_id,
                        (
                            f"✅ طرح خرید اول سفارش شما تایید شد و در حال انجام می‌باشد.\n"
                            f"سفارش #{order_id} - {product_title}"
                        ),
                    )
                _flash(request, "طرح خرید اول تایید و سفارش در حال انجام شد.")

        elif action == "manager_note":
            text = (manager_note or "").strip()
            if not text:
                _flash(request, "متن پیام مدیر نمی‌تواند خالی باشد.", "error")
            else:
                update_order_notes(order_id, text)
                add_order_manager_message(order_id, user_id, text)
                if user_id:
                    await _notify_user(
                        user_id,
                        f"📬 پیام جدید درباره سفارش «{order_title}» (#{order_id}):\n\n{text}",
                    )
                _flash(request, "پیام مدیر برای مشتری ارسال شد.")

        elif action == "financial":
            try:
                cost_value = int(cost_amount)
            except (TypeError, ValueError):
                cost_value = 0
            set_order_financials(order_id, cost_value)
            _flash(request, "اطلاعات مالی سفارش ذخیره شد.")

        else:
            _flash(request, "درخواست نامعتبر بود.", "error")

        return RedirectResponse(request.url_for("order_detail", order_id=order_id), status.HTTP_303_SEE_OTHER)

    @app.get("/users")
    async def users_page(
        request: Request,
        user: str = Depends(_login_required),
        q: str = Query("", alias="q"),
        page: int = Query(1, ge=1),
    ):
        per_page = 20
        total = count_users(search=q or None)
        pages = max((total + per_page - 1) // per_page, 1)
        page = min(page, pages)
        offset = (page - 1) * per_page
        items = list_users(search=q or None, limit=per_page, offset=offset)
        return _render(
            request,
            "users.html",
            {
                "title": "مدیریت کاربران",
                "users": items,
                "total": total,
                "page": page,
                "pages": pages,
                "query": q,
                "format_datetime": _format_datetime,
                "format_amount": _format_amount,
                "nav": "users",
            },
        )

    @app.get("/users/{user_id}")
    async def user_detail(request: Request, user_id: int, user: str = Depends(_login_required)):
        profile = get_user(user_id)
        if not profile:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="کاربر یافت نشد")
        stats = get_user_stats(user_id)
        orders = list_orders(user_id=user_id, limit=10)
        wallet_history_rows = list_wallet_tx_for_user(user_id, limit=25)
        wallet_history: list[dict[str, Any]] = []
        for tx in wallet_history_rows:
            note = str(tx.get("note") or "")
            display_type = tx.get("type") or ""
            coupon_code: str | None = None
            if note.startswith("COUPON:"):
                coupon_code = note.split(":", 1)[1] if ":" in note else ""
                display_type = "Coupon"
            wallet_history.append(
                {
                    **tx,
                    "display_type": display_type,
                    "coupon_code": coupon_code.strip() if coupon_code else None,
                }
            )
        manager_messages = list_user_manager_messages(user_id, limit=20)
        return _render(
            request,
            "user_detail.html",
            {
                "title": f"کاربر {user_id}",
                "profile": profile,
                "stats": stats,
                "orders": orders,
                "wallet_history": wallet_history,
                "manager_messages": manager_messages,
                "format_datetime": _format_datetime,
                "format_amount": _format_amount,
                "nav": "users",
            },
        )

    @app.post("/users/{user_id}/wallet-adjust")
    async def adjust_wallet(
        request: Request,
        user_id: int,
        user: str = Depends(_login_required),
        action: str = Form(...),
        amount: int = Form(...),
        note: str = Form(""),
    ):
        profile = get_user(user_id)
        if not profile:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="کاربر یافت نشد")
        if amount <= 0:
            _flash(request, "مبلغ باید بزرگتر از صفر باشد.", "error")
            return RedirectResponse(request.url_for("user_detail", user_id=user_id), status.HTTP_303_SEE_OTHER)

        tx_type = "CREDIT"
        delta = amount
        if action == "debit":
            tx_type = "DEBIT"
            delta = -amount
        elif action == "refund":
            tx_type = "REFUND"
        elif action == "reserve":
            tx_type = "RESERVE"
        success = change_wallet(user_id, delta, tx_type, note=note or "")
        if not success:
            _flash(request, "امکان اعمال تغییر وجود ندارد (موجودی کافی نیست؟)", "error")
        else:
            _flash(request, "تغییر موجودی با موفقیت ثبت شد.")
            new_profile = get_user(user_id)
            balance = int(new_profile.get("wallet_balance") if new_profile else 0)
            sign = "+" if delta > 0 else "-"
            await _notify_user(
                user_id,
                (
                    f"📢 موجودی کیف پول شما {sign}{abs(delta)} تومان تغییر کرد.\n"
                    f"موجودی فعلی: {balance} تومان."
                ),
            )
        return RedirectResponse(request.url_for("user_detail", user_id=user_id), status.HTTP_303_SEE_OTHER)

    @app.post("/users/{user_id}/message")
    async def send_user_message(
        request: Request,
        user_id: int,
        user: str = Depends(_login_required),
        message_text: str = Form(...),
    ):
        profile = get_user(user_id)
        if not profile:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="کاربر یافت نشد")
        text = (message_text or "").strip()
        if not text:
            _flash(request, "متن پیام نمی‌تواند خالی باشد.", "error")
            return RedirectResponse(request.url_for("user_detail", user_id=user_id), status.HTTP_303_SEE_OTHER)

        add_user_manager_message(user_id, text)
        await _notify_user(user_id, f"📬 پیام مدیر\n\n{text}")
        _flash(request, "پیام برای کاربر ارسال شد.")
        return RedirectResponse(request.url_for("user_detail", user_id=user_id), status.HTTP_303_SEE_OTHER)

    @app.post("/users/{user_id}/block")
    async def toggle_block(
        request: Request,
        user_id: int,
        user: str = Depends(_login_required),
        action: str = Form(...),
    ):
        profile = get_user(user_id)
        if not profile:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="کاربر یافت نشد")
        if action == "block":
            set_user_blocked(user_id, True)
            _flash(request, "کاربر مسدود شد.")
            await _notify_user(user_id, "⛔️ دسترسی شما به خدمات ربات توسط مدیریت مسدود شد.")
        elif action == "unblock":
            set_user_blocked(user_id, False)
            _flash(request, "کاربر از حالت مسدود خارج شد.")
            await _notify_user(user_id, "✅ دسترسی شما به خدمات ربات دوباره فعال شد.")
        else:
            _flash(request, "درخواست نامعتبر بود.", "error")
        return RedirectResponse(request.url_for("user_detail", user_id=user_id), status.HTTP_303_SEE_OTHER)

    @app.get("/wallet")
    async def wallet_page(request: Request, user: str = Depends(_login_required)):
        summary = get_wallet_summary()
        recent = list_recent_wallet_tx(limit=50)
        return _render(
            request,
            "wallet.html",
            {
                "title": "گزارش کیف پول",
                "summary": summary,
                "transactions": recent,
                "format_amount": _format_amount,
                "format_datetime": _format_datetime,
                "nav": "wallet",
            },
        )

    @app.get("/coupons")
    async def coupons_page(request: Request, user: str = Depends(_login_required)):
        coupons = list_coupons(limit=200)
        now_dt = datetime.now()
        for item in coupons:
            try:
                item["amount"] = int(item.get("amount") or 0)
            except (TypeError, ValueError):
                item["amount"] = 0
            try:
                item["usage_limit"] = int(item.get("usage_limit") or 0)
            except (TypeError, ValueError):
                item["usage_limit"] = 0
            try:
                item["used_count"] = int(item.get("used_count") or 0)
            except (TypeError, ValueError):
                item["used_count"] = 0
            expires_at = item.get("expires_at")
            expires_value = ""
            is_expired = False
            if expires_at:
                try:
                    exp_dt = datetime.fromisoformat(str(expires_at))
                    is_expired = exp_dt < now_dt
                    expires_value = exp_dt.strftime("%Y-%m-%d")
                except ValueError:
                    expires_value = str(expires_at)[:10]
            item["expires_value"] = expires_value
            item["is_expired"] = is_expired
            item["remaining"] = max(item["usage_limit"] - item["used_count"], 0)
            item["is_active"] = bool(item.get("is_active"))
            redemptions = list_coupon_redemptions(item.get("id")) if item.get("id") else []
            item["redeemed_users"] = [row.get("user_id") for row in redemptions if row.get("user_id") is not None]
        return _render(
            request,
            "coupons.html",
            {
                "title": "مدیریت کوپن‌ها",
                "coupons": coupons,
                "format_amount": _format_amount,
                "format_datetime": _format_datetime,
                "nav": "coupons",
            },
        )

    @app.post("/coupons/create")
    async def coupon_create(
        request: Request,
        user: str = Depends(_login_required),
        code: str = Form(""),
        amount: int = Form(...),
        usage_limit: int = Form(...),
        expires_on: str = Form(""),
    ):
        try:
            if amount <= 0 or usage_limit <= 0:
                raise ValueError("invalid numbers")
        except Exception:
            _flash(request, "ورودی‌ها معتبر نیستند.", "error")
            return RedirectResponse(request.url_for("coupons_page"), status.HTTP_303_SEE_OTHER)

        normalized_code = (code or "").strip().upper()
        if not normalized_code:
            normalized_code = _generate_coupon_code()

        expires_at: str | None = None
        expires_input = (expires_on or "").strip()
        if expires_input:
            expires_at = f"{expires_input}T23:59:59"

        try:
            create_coupon(normalized_code, amount, usage_limit, expires_at)
        except sqlite3.IntegrityError:
            _flash(request, "این کد قبلاً ثبت شده است.", "error")
        except ValueError:
            _flash(request, "کد کوپن معتبر نیست.", "error")
        else:
            _flash(request, f"کوپن {normalized_code} ایجاد شد.")

        return RedirectResponse(request.url_for("coupons_page"), status.HTTP_303_SEE_OTHER)

    @app.post("/coupons/{coupon_id}/update")
    async def coupon_update(
        request: Request,
        coupon_id: int,
        user: str = Depends(_login_required),
        code: str = Form(...),
        amount: int = Form(...),
        usage_limit: int = Form(...),
        expires_on: str = Form(""),
    ):
        coupon = get_coupon(coupon_id)
        if not coupon:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="کوپن یافت نشد")

        try:
            if amount <= 0 or usage_limit <= 0:
                raise ValueError
        except Exception:
            _flash(request, "مقادیر وارد شده معتبر نیست.", "error")
            return RedirectResponse(request.url_for("coupons_page"), status.HTTP_303_SEE_OTHER)

        used_count = int(coupon.get("used_count") or 0)
        if usage_limit < used_count:
            _flash(request, "تعداد قابل استفاده نمی‌تواند کمتر از تعداد استفاده شده باشد.", "error")
            return RedirectResponse(request.url_for("coupons_page"), status.HTTP_303_SEE_OTHER)

        expires_at: str | None = None
        expires_input = (expires_on or "").strip()
        if expires_input:
            expires_at = f"{expires_input}T23:59:59"

        normalized_code = (code or "").strip().upper()
        if not normalized_code:
            _flash(request, "کد کوپن نمی‌تواند خالی باشد.", "error")
            return RedirectResponse(request.url_for("coupons_page"), status.HTTP_303_SEE_OTHER)
        try:
            success = update_coupon(
                coupon_id,
                code=normalized_code,
                amount=amount,
                usage_limit=usage_limit,
                expires_at=expires_at,
            )
        except sqlite3.IntegrityError:
            _flash(request, "کد وارد شده تکراری است.", "error")
            return RedirectResponse(request.url_for("coupons_page"), status.HTTP_303_SEE_OTHER)

        if not success:
            _flash(request, "به‌روزرسانی کوپن ممکن نشد.", "error")
        else:
            _flash(request, "اطلاعات کوپن بروزرسانی شد.")

        return RedirectResponse(request.url_for("coupons_page"), status.HTTP_303_SEE_OTHER)

    @app.post("/coupons/{coupon_id}/toggle")
    async def coupon_toggle(
        request: Request,
        coupon_id: int,
        user: str = Depends(_login_required),
    ):
        coupon = get_coupon(coupon_id)
        if not coupon:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="کوپن یافت نشد")

        is_active = bool(coupon.get("is_active"))
        set_coupon_active(coupon_id, not is_active)
        state_text = "فعال" if not is_active else "غیرفعال"
        _flash(request, f"کوپن {coupon.get('code')} {state_text} شد.")

        return RedirectResponse(request.url_for("coupons_page"), status.HTTP_303_SEE_OTHER)


    return app


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["money"] = _format_amount
templates.env.filters["dt"] = _format_datetime


app = create_admin_app()


__all__ = ["create_admin_app", "app"]
