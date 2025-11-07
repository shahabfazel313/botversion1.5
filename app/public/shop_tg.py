from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from . import router
from .helpers import _order_title
from ..catalog import TG_PREMIUM_VARIANTS, get_variant
from ..config import ADMIN_IDS, CURRENCY, TG_READY_PREBUILT
from ..db import create_order, create_service_message, ensure_user, get_user
from ..keyboards import (
    ik_tg_main,
    ik_tg_premium_durations,
    ik_tg_ready_options,
    ik_cart_actions,
    ik_ready_pre_actions,
    reply_main,
)
from ..states import ShopStates
from ..utils import is_valid_tg_id, mention


def _premium_variant(period: str) -> dict[str, object]:
    return get_variant(TG_PREMIUM_VARIANTS[period])


def _format_variant_price(variant: dict[str, object]) -> str:
    if not variant["available"]:
        return "ناموجود"
    amount = int(variant["amount"])
    if amount <= 0:
        return "قیمت تنظیم نشده"
    return f"{amount} {CURRENCY}"


def _variant_unavailable_text() -> str:
    return "این گزینه در حال حاضر ناموجود است."


async def _alert_variant_unavailable(callback: CallbackQuery) -> None:
    text = _variant_unavailable_text()
    await callback.answer(text, show_alert=True)
    await callback.message.answer(text, reply_markup=reply_main())


async def _message_variant_unavailable(message: Message) -> None:
    await message.answer(_variant_unavailable_text(), reply_markup=reply_main())


@router.callback_query(F.data == "shop:tg")
async def cb_shop_tg(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("📣 خدمات تلگرام:", reply_markup=ik_tg_main())
    await callback.answer()


@router.callback_query(F.data == "tg:back")
async def cb_tg_back(callback: CallbackQuery, state: FSMContext) -> None:
    await cb_shop_tg(callback, state)


@router.callback_query(F.data == "tg:premium")
async def cb_tg_premium(callback: CallbackQuery, state: FSMContext) -> None:
    lines = []
    for period, label in [("3m", "3 ماهه"), ("6m", "6 ماهه"), ("12m", "12 ماهه")]:
        variant = _premium_variant(period)
        price_text = _format_variant_price(variant)
        lines.append(f"• {label}: {price_text}")
    text ="تلگرام پرمیوم (بدون لاگین)\n" + "\n""بدون لاگین به معنای این هست که نیاز به ورود به حساب شما نیست\n"+ "\n""\
    یکی را انتخاب کنید: \n" + "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=ik_tg_premium_durations())
    await callback.answer()


@router.callback_query(F.data.in_({"tg:premium:3m", "tg:premium:6m", "tg:premium:12m"}))
async def cb_tg_premium_choose(callback: CallbackQuery, state: FSMContext) -> None:
    period = callback.data.split(":")[2]
    variant = _premium_variant(period)
    if not variant["available"]:
        await _alert_variant_unavailable(callback)
        return
    if int(variant["amount"]) <= 0:
        await callback.message.answer("قیمت این سرویس هنوز تنظیم نشده است.", reply_markup=reply_main())
        await callback.answer()
        return
    await state.update_data(pending_service="TG", pending_code=f"premium_{period}")
    await callback.message.answer("لطفاً آیدی دلخواه خود را (بدون @) ارسال کنید:")
    await state.set_state(ShopStates.tg_premium_wait_id)
    await callback.answer()


@router.message(ShopStates.tg_premium_wait_id)
async def on_tg_premium_id(message: Message, state: FSMContext) -> None:
    user_id_text = (message.text or "").strip()
    if not is_valid_tg_id(user_id_text):
        await message.answer("آیدی نامعتبر است. بدون @ و حداقل ۵ کاراکتر (حروف/عدد/_.). دوباره ارسال کنید:")
        return
    ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name or "",
    )
    data = await state.get_data()
    code = data.get("pending_code")
    period = code.split("_")[1]
    variant = _premium_variant(period)
    if not variant["available"]:
        await _message_variant_unavailable(message)
        await state.clear()
        return
    amount = int(variant["amount"])
    if amount <= 0:
        await message.answer("قیمت این سرویس هنوز تنظیم نشده است.", reply_markup=reply_main())
        await state.clear()
        return
    user = get_user(message.from_user.id)
    title = _order_title("TG", f"premium_{period}")
    order_id = create_order(
        user=user,
        title=title,
        amount_total=amount,
        currency=CURRENCY,
        service_category="TG",
        service_code=f"premium_{period}",
        account_mode="",
        customer_email=None,
        notes=f"desired_id={user_id_text}",
    )
    await message.answer(
        f"✅ سفارش #{order_id} ایجاد شد و به «🧺 سبد خرید» اضافه شد.\n"
        f"برای ادامه، روش پرداخت را انتخاب کنید:",
        reply_markup=ik_cart_actions(order_id),
    )
    await state.clear()


@router.callback_query(F.data == "tg:stars")
async def cb_tg_stars(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("🎯 Stars — Coming soon", reply_markup=ik_tg_main())
    await callback.answer()


@router.callback_query(F.data == "tg:ready")
async def cb_tg_ready(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("اکانت آماده تلگرام:", reply_markup=ik_tg_ready_options())
    await callback.answer()


@router.callback_query(F.data == "tg:ready:pre")
async def cb_tg_ready_pre(callback: CallbackQuery, state: FSMContext) -> None:
    item = TG_READY_PREBUILT
    variant = get_variant("tg_ready_pre")
    if not variant["available"]:
        await _alert_variant_unavailable(callback)
        return
    price_display = _format_variant_price(variant)
    caption = (
        f"<b>{item['title']}</b>\n\n{item['desc']}\n\n"
        f"💰 قیمت: <b>{price_display}</b>"
    )
    await callback.message.edit_text(caption, reply_markup=ik_ready_pre_actions())
    await callback.answer()


@router.callback_query(F.data == "tg:ready:country")
async def cb_tg_ready_country(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer("لطفاً کشور/جزئیات مورد نظر خود را به‌صورت متن ارسال کنید:")
    await state.set_state(ShopStates.ready_country_wait_text)
    await callback.answer()


@router.message(ShopStates.ready_country_wait_text)
async def on_ready_country_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("لطفاً جزئیات را به‌صورت متن ارسال کنید:")
        return
    ensure_user(message.from_user.id, message.from_user.username, message.from_user.first_name or "")
    create_service_message(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        "TG_READY_COUNTRY",
        text,
    )
    note = f"📩 درخواست اکانت با کشور دلخواه از {mention(message.from_user)}:\n\n{text}"
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(admin_id, note)
        except Exception:
            pass
    await message.answer("✅ درخواست شما ثبت شد؛ در اسرع وقت پاسخ دریافت می‌کنید.", reply_markup=reply_main())
    await state.clear()


@router.callback_query(F.data == "tg:ready:pre:buy")
async def cb_tg_ready_pre_buy(callback: CallbackQuery, state: FSMContext) -> None:
    ensure_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name or "")
    variant = get_variant("tg_ready_pre")
    if not variant["available"]:
        await _alert_variant_unavailable(callback)
        return
    amount = int(variant["amount"])
    if amount <= 0:
        await callback.message.answer("قیمت این سرویس هنوز تنظیم نشده است.", reply_markup=reply_main())
        await callback.answer()
        return

    user = get_user(callback.from_user.id)
    title = _order_title("TG", "ready_pre")
    order_id = create_order(
        user=user,
        title=title,
        amount_total=amount,
        currency=CURRENCY,
        service_category="TG",
        service_code="ready_pre",
        account_mode="PREBUILT",
        customer_email=None,
        notes="",
    )
    await callback.message.answer(
        f"✅ سفارش #{order_id} ایجاد شد و به «🧺 سبد خرید» اضافه شد.\n"
        f"برای ادامه، روش پرداخت را انتخاب کنید:",
        reply_markup=ik_cart_actions(order_id),
    )
    await callback.answer()
