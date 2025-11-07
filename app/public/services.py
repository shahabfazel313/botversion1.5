from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from . import router
from .helpers import _notify_admins, _price_to_int
from ..config import (
    ADMIN_IDS,
    BUILD_BOT_BASE_PRICE,
    BUILD_BOT_DESC,
    CURRENCY,
    OTHER_SERVICES_DESC,
)
from ..db import create_service_message, ensure_user, get_user
from ..keyboards import ik_build_actions, ik_other_services_actions, reply_main
from ..states import ShopStates
from ..utils import mention


def _format_price_label(value: str) -> str:
    amount = _price_to_int(value)
    if amount <= 0:
        return "💰 قیمت پایه پس از بررسی اعلام می‌شود."
    formatted = f"{amount:,}".replace(",", "٬")
    return f"💰 قیمت پایه: <b>{formatted} {CURRENCY}</b>"


@router.callback_query(F.data == "shop:buildbot")
async def cb_shop_buildbot(callback: CallbackQuery, state: FSMContext) -> None:
    description = BUILD_BOT_DESC.strip()
    price_line = _format_price_label(BUILD_BOT_BASE_PRICE)
    text = (
        "🤖 <b>ساخت ربات تلگرام برای شما</b>\n\n"
        f"{description}\n\n"
        f"{price_line}\n\n"
        "برای شروع، روی دکمهٔ «📝 ثبت درخواست» بزنید و توضیحات خود را ارسال کنید."
    )
    await callback.message.edit_text(text, reply_markup=ik_build_actions())
    await callback.answer()


@router.callback_query(F.data == "build:request")
async def cb_build_request(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer(
        "لطفاً توضیحات ربات مورد نظر، امکانات و نیازهای خود را به‌صورت کامل ارسال کنید.")
    await state.set_state(ShopStates.buildbot_wait_requirements)
    await callback.answer()


@router.message(ShopStates.buildbot_wait_requirements)
async def on_buildbot_requirements(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("لطفاً توضیحات ربات را به‌صورت متن ارسال کنید.")
        return
    if text == "انصراف":
        await message.answer("درخواست ساخت ربات لغو شد.", reply_markup=reply_main())
        await state.clear()
        return
    ensure_user(message.from_user.id, message.from_user.username, message.from_user.first_name or "")
    user = get_user(message.from_user.id) or {}
    phone = user.get("contact_phone") or ""
    admin_text = (
        "🤖 <b>درخواست جدید ساخت ربات تلگرام</b>\n"
        f"مشتری: {mention(message.from_user)} (@{message.from_user.username or '—'})\n"
    )
    if phone:
        admin_text += f"📱 شماره تماس: <code>{phone}</code>\n"
    admin_text += "\n" + text
    create_service_message(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        "BUILD_BOT",
        text,
    )
    await _notify_admins(message.bot, admin_text)
    await message.answer(
        "✅ درخواست شما ثبت شد. در اسرع وقت توسط پشتیبانی بررسی و با شما تماس گرفته می‌شود.",
        reply_markup=reply_main(),
    )
    await state.clear()


@router.callback_query(F.data == "shop:other")
async def cb_shop_other(callback: CallbackQuery, state: FSMContext) -> None:
    description = OTHER_SERVICES_DESC.strip()
    text = (
        "🧰 <b>خدمات دیگر</b>\n\n"
        f"{description}\n\n"
        "از دکمهٔ زیر برای ثبت درخواست محصول یا خدمت استفاده کنید."
    )
    await callback.message.edit_text(text, reply_markup=ik_other_services_actions())
    await callback.answer()


@router.callback_query(F.data == "other:request")
async def cb_other_request(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer(
        "لطفاً توضیح دهید چه محصول یا خدمتی نیاز دارید تا کارشناسان ما بررسی کنند.")
    await state.set_state(ShopStates.other_wait_request)
    await callback.answer()


@router.message(ShopStates.other_wait_request)
async def on_other_request(message: Message, state: FSMContext) -> None:
    payload = message.text or message.caption or ""
    text = payload.strip()
    if not text:
        await message.answer("لطفاً توضیحات خود را به‌صورت متن ارسال کنید.")
        return
    if text == "انصراف":
        await message.answer("درخواست شما لغو شد.", reply_markup=reply_main())
        await state.clear()
        return
    ensure_user(message.from_user.id, message.from_user.username, message.from_user.first_name or "")
    user = get_user(message.from_user.id) or {}
    phone = user.get("contact_phone") or ""
    await state.update_data(other_request_text=text, other_request_phone=phone)
    await message.answer(
        "اگر تصویری مرتبط با درخواست خود دارید ارسال کنید. در غیر این صورت عبارت «تمام» را بنویسید.")
    await state.set_state(ShopStates.other_wait_attachment)


@router.message(ShopStates.other_wait_attachment)
async def on_other_request_attachment(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    base_text = data.get("other_request_text") or ""
    phone = data.get("other_request_phone") or ""
    user = message.from_user

    attachment_id = None
    extra_text = ""

    if message.text:
        text = (message.text or "").strip()
        if text.lower() in {"تمام", "پایان", "ندارم", "بدون عکس", "skip"}:
            pass
        else:
            extra_text = text
    elif message.photo:
        attachment_id = message.photo[-1].file_id
        extra_text = (message.caption or "").strip()
    elif message.document:
        attachment_id = message.document.file_id
        extra_text = (message.caption or "").strip()
    else:
        await message.answer("نوع فایل پشتیبانی نمی‌شود. لطفاً متن یا تصویر ارسال کنید.")
        return

    final_text = base_text
    if extra_text:
        final_text = f"{base_text}\n\n{extra_text}" if base_text else extra_text

    ensure_user(user.id, user.username, user.first_name or "")
    admin_text = (
        "🧰 <b>درخواست خدمات دیگر</b>\n"
        f"مشتری: {mention(user)} (@{user.username or '—'})\n"
    )
    if phone:
        admin_text += f"📱 شماره تماس: <code>{phone}</code>\n"
    if attachment_id:
        admin_text += "📎 دارای پیوست تصویر/فایل\n"
    admin_text += "\n" + (final_text or "—")

    create_service_message(
        user.id,
        user.username,
        user.first_name,
        "OTHER_SERVICE",
        final_text,
        attachment_file_id=attachment_id,
    )

    if attachment_id and message.photo:
        for admin_id in ADMIN_IDS:
            try:
                await message.bot.send_photo(admin_id, attachment_id, caption=admin_text)
            except Exception:
                pass
    elif attachment_id and message.document:
        for admin_id in ADMIN_IDS:
            try:
                await message.bot.send_document(admin_id, attachment_id, caption=admin_text)
            except Exception:
                pass
    else:
        await _notify_admins(message.bot, admin_text)

    await message.answer(
        "✅ درخواست شما ثبت شد. همکاران ما پس از بررسی با شما تماس خواهند گرفت.",
        reply_markup=reply_main(),
    )
    await state.clear()
