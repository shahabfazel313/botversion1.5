from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from . import router
from ..db import ensure_user, set_user_contact_verified
from ..keyboards import reply_main, reply_request_contact
from ..states import VerifyStates


@router.message(VerifyStates.wait_contact)
async def on_wait_contact(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text == "انصراف":
        await message.answer("درخواست احراز هویت لغو شد.", reply_markup=reply_main())
        await state.clear()
        return
    if not message.contact:
        await message.answer(
            "برای تکمیل احراز هویت، لطفاً با استفاده از دکمهٔ «📱 اشتراک‌گذاری شماره من» شماره خود را ارسال کنید.",
            reply_markup=reply_request_contact(),
        )
        return
    if message.contact.user_id != message.from_user.id:
        await message.answer(
            "لطفاً شماره مرتبط با همین حساب را از طریق دکمهٔ اشتراک‌گذاری ارسال کنید.",
            reply_markup=reply_request_contact(),
        )
        return
    ensure_user(message.from_user.id, message.from_user.username, message.from_user.first_name or "")
    set_user_contact_verified(message.from_user.id, message.contact.phone_number)
    await message.answer(
        "✅ احراز هویت شما با موفقیت انجام شد. اکنون می‌توانید از بخش سبد خرید را ادامه دهید.",
        reply_markup=reply_main(),
    )
    await state.clear()
