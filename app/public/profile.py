from __future__ import annotations

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from . import router
from ..db import ensure_user, redeem_coupon
from ..keyboards import ik_coupon_controls
from ..states import ProfileStates
from ..config import CURRENCY


def _format_amount(value: int) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    return f"{number:,}".replace(",", "،")


@router.callback_query(F.data == "profile:coupon")
async def cb_profile_coupon(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileStates.wait_coupon_code)
    await state.update_data(coupon_code="")
    await callback.message.answer(
        "🎟️ لطفاً کد کوپن خود را به صورت پیام ارسال کنید و سپس دکمه «اعمال» را بزنید.",
        reply_markup=ik_coupon_controls(),
    )
    await callback.answer("پس از ارسال کد، دکمه اعمال را انتخاب کنید.", show_alert=True)


@router.message(ProfileStates.wait_coupon_code)
async def on_coupon_code(message: Message, state: FSMContext) -> None:
    code = (message.text or "").strip()
    if not code:
        await message.reply("لطفاً فقط متن کد کوپن را ارسال کنید.")
        return
    await state.update_data(coupon_code=code)
    await message.reply("کد دریافت شد، اکنون دکمه «اعمال» را لمس کنید.")


@router.callback_query(ProfileStates.wait_coupon_code, F.data == "profile:coupon:submit")
async def cb_coupon_submit(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    code = (data or {}).get("coupon_code", "").strip()
    if not code:
        await callback.answer("لطفاً ابتدا کد کوپن را ارسال کنید.", show_alert=True)
        return

    ensure_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name or "")
    success, result, error = redeem_coupon(callback.from_user.id, code)
    if not success:
        await callback.answer(error or "امکان اعمال کوپن نبود.", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_reply_markup()
    amount = result.get("amount", 0)
    balance = result.get("balance", 0)
    code_value = result.get("code", code).upper()
    await callback.answer(
        (
            f"✅ کوپن {code_value} با موفقیت اعمال شد.\n"
            f"{_format_amount(amount)} {CURRENCY} به کیف پول شما اضافه شد.\n"
            f"موجودی جدید: {_format_amount(balance)} {CURRENCY}"
        ),
        show_alert=True,
    )


@router.callback_query(ProfileStates.wait_coupon_code, F.data == "profile:coupon:cancel")
async def cb_coupon_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_reply_markup()
    await callback.answer("فرآیند اعمال کوپن لغو شد.", show_alert=True)

