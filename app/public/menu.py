from datetime import datetime

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from . import router
from .channel_gate import ensure_member_for_message
from .helpers import _order_title, _status_fa
from ..config import CURRENCY, SUPPORT_USERNAME
from ..db import ensure_user, get_user_stats, list_cart_orders
from ..keyboards import (
    REPLY_BTN_CART,
    REPLY_BTN_PRODUCTS,
    REPLY_BTN_PROFILE,
    REPLY_BTN_SUPPORT,
    ik_cart_actions,
    ik_profile_actions,
    ik_shop_main,
    reply_main,
)


@router.message(F.text == REPLY_BTN_PRODUCTS)
async def on_reply_products(message: Message, state: FSMContext) -> None:
    if not await ensure_member_for_message(message):
        return
    await message.answer("به بخش خرید خوش آمدید:", reply_markup=ik_shop_main())


@router.message(F.text == REPLY_BTN_CART)
async def on_reply_cart(message: Message, state: FSMContext) -> None:
    if not await ensure_member_for_message(message):
        return
    ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name or "",
    )
    orders = list_cart_orders(message.from_user.id)
    if not orders:
        await message.answer("🧺 سبد خرید شما خالی است.", reply_markup=reply_main())
        return

    now = datetime.now()
    for order in orders:
        ttl = ""
        if order.get("await_deadline"):
            try:
                deadline = datetime.fromisoformat(order["await_deadline"])
                remain = (deadline - now).total_seconds()
                if remain < 0:
                    remain = 0
                minutes = int(remain // 60)
                seconds = int(remain % 60)
                ttl = f"\n⏳ مهلت باقی‌مانده: {minutes:02d}:{seconds:02d}"
            except Exception:
                pass
        title = _order_title(
            order.get("service_category", ""),
            order.get("service_code", ""),
            order.get("notes"),
        )
        amount = int(order.get("amount_total") or 0)
        reserved = int(order.get("wallet_reserved_amount") or 0)
        remaining = max(amount - reserved, 0)
        text = (
            f"🧺 سفارش #{order['id']} — <b>{title}</b>\n"
            f"مبلغ کل: <b>{amount} {CURRENCY}</b>\n"
            f"از کیف پول رزرو شده: <b>{reserved} {CURRENCY}</b>\n"
            f"باقیمانده برای پرداخت کارت: <b>{remaining} {CURRENCY}</b>\n"
            f"وضعیت: <b>{_status_fa(order['status'])}</b>{ttl}"
        )
        enable_plan = order.get("service_category") == "AI"
        await message.answer(text, reply_markup=ik_cart_actions(order["id"], enable_plan=enable_plan))


@router.message(F.text == REPLY_BTN_PROFILE)
async def on_reply_profile(message: Message, state: FSMContext) -> None:
    if not await ensure_member_for_message(message):
        return
    ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name or "",
    )
    stats = get_user_stats(message.from_user.id)
    await message.answer(
        "👤 <b>اطلاعات کاربری</b>\n"
        f"• موجودی کیف پول: <b>{stats['wallet_balance']} {CURRENCY}</b>\n"
        f"• تعداد سفارش‌ها: <b>{stats['orders_total']}</b>\n"
        f"• سفارشات در حال انجام: <b>{stats['orders_inprog']}</b>\n"
        f"• سفارشات تکمیل‌شده: <b>{stats['orders_done']}</b>\n"
        f"• تعداد زیرمجموعه‌ها: <b>{stats['ref_count']}</b>\n"
        f"• درآمد شما: <b>{stats['earnings_total']} {CURRENCY}</b>",
        reply_markup=ik_profile_actions(),
    )


@router.message(F.text == REPLY_BTN_SUPPORT)
async def on_reply_support(message: Message) -> None:
    if not await ensure_member_for_message(message):
        return
    if SUPPORT_USERNAME:
        await message.answer(
            f"برای پشتیبانی کلیک/پیام دهید: @{SUPPORT_USERNAME}",
            reply_markup=reply_main(),
        )
    else:
        await message.answer(
            "پشتیبانی هنوز تنظیم نشده است. (SUPPORT_USERNAME را در .env تنظیم کنید)",
            reply_markup=reply_main(),
        )


@router.callback_query(F.data == "shop:main")
async def cb_shop_main(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("به بخش خرید خوش آمدید:")
    await callback.message.answer("منو:", reply_markup=ik_shop_main())
    await callback.answer()
