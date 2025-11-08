from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from . import router
from .helpers import _notify_admins, _order_title
from ..checkout import send_checkout_prompt
from ..config import ADMIN_IDS, CARD_NAME, CARD_NUMBER, CURRENCY
from ..db import (
    apply_discount_to_order,
    change_wallet,
    confirm_order_discount,
    get_order,
    get_user,
    is_user_contact_verified,
    release_order_discount,
    set_order_customer_message,
    set_order_payment_type,
    set_order_receipt,
    set_order_status,
    set_order_wallet_reserved,
    set_order_wallet_used,
    user_has_delivered_order,
)
from ..keyboards import (
    ik_cart_actions,
    ik_card_receipt_prompt,
    ik_discount_controls,
    ik_discount_prompt,
    ik_plan_review,
    ik_receipt_review,
    ik_wallet_confirm,
    reply_main,
    reply_request_contact,
)
from ..states import CheckoutStates, VerifyStates
from ..utils import mention


async def _require_contact_verification(callback: CallbackQuery, state: FSMContext) -> bool:
    if is_user_contact_verified(callback.from_user.id):
        return True
    await state.set_state(VerifyStates.wait_contact)
    await callback.message.answer(
        "جهت استفاده از ربات نیاز به احراز هویت می‌باشد. لطفاً با استفاده از دکمهٔ زیر شماره خود را به اشتراک بگذارید.",
        reply_markup=reply_request_contact(),
    )
    await callback.answer()
    return False


async def _ensure_discount_ready(
    callback: CallbackQuery, state: FSMContext, order: dict[str, object], method: str
) -> bool:
    order_id = int(order["id"])
    try:
        discount_amount = int(order.get("discount_amount") or 0)
    except (TypeError, ValueError):
        discount_amount = 0
    try:
        discount_id = int(order.get("discount_code_id") or 0)
    except (TypeError, ValueError):
        discount_id = 0
    data = await state.get_data()
    discount_flow = data.get("discount_flow") or {}
    if int(discount_flow.get("order_id") or 0) != order_id:
        discount_flow = {"order_id": order_id}
    status = discount_flow.get("status")
    if discount_amount > 0 and discount_id:
        if status != "applied":
            discount_flow["status"] = "applied"
            await state.update_data(discount_flow=discount_flow)
        return True
    if status in {"declined", "applied"}:
        return True
    if status == "await_code":
        await callback.answer(
            "لطفاً ابتدا کد تخفیف را وارد و اعمال کنید یا بازگشت را بزنید.",
            show_alert=True,
        )
        return False
    if status == "prompt" and discount_flow.get("method") == method:
        await callback.answer("لطفاً ابتدا مشخص کنید کد تخفیف دارید یا خیر.", show_alert=True)
        return False
    discount_flow["status"] = "prompt"
    discount_flow["method"] = method
    await state.update_data(discount_flow=discount_flow, discount_code_value=None)
    await callback.message.answer(
        "آیا کد تخفیف دارید؟",
        reply_markup=ik_discount_prompt(order_id, method),
    )
    await callback.answer()
    return False


async def _start_card_payment(callback: CallbackQuery, state: FSMContext, order_id: int) -> None:
    order = get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("سفارش نامعتبر یا منقضی است.", show_alert=True)
        return
    if order.get("status") != "AWAITING_PAYMENT":
        await callback.answer("سفارش قابل پرداخت نیست.", show_alert=True)
        return
    if not await _ensure_discount_ready(callback, state, order, "card"):
        return
    set_order_payment_type(order_id, "CARD")
    await state.update_data(
        order_receipt_for=order_id,
        receipt_file_id=None,
        receipt_text=None,
        receipt_comment="",
        receipt_kind="",
    )
    await callback.message.answer(
        f"💳 پرداخت کارت‌به‌کارت برای سفارش #{order_id}\n"
        f"• شماره کارت: <code>{CARD_NUMBER}</code>\n"
        f"• به نام: {CARD_NAME}\n\n"
        "پس از پرداخت، تصویر یا فایل رسید را ارسال کنید. برای لغو می‌توانید از دکمه زیر استفاده کنید.",
        reply_markup=ik_card_receipt_prompt(order_id),
    )
    await callback.message.answer(f"🧾 رسید کارت سفارش #{order_id} را ارسال کنید.")
    await state.set_state(CheckoutStates.wait_card_receipt)
    await callback.answer()
    return True


async def _start_wallet_payment(callback: CallbackQuery, state: FSMContext, order: dict[str, Any]) -> bool:
    order_id = int(order["id"])
    amount = int(order.get("amount_total") or 0)
    user = get_user(callback.from_user.id)
    if int(user["wallet_balance"]) < amount:
        await callback.answer("موجودی کیف پول کافی نیست.", show_alert=True)
        return False
    await state.update_data(
        wallet_for=order_id,
        wallet_amount=amount,
        wallet_comment="",
    )
    await state.set_state(CheckoutStates.wait_wallet_comment)
    await callback.message.answer(
        f"👛 پرداخت با کیف پول برای سفارش #{order_id}\n"
        "اگر توضیحاتی برای سفارش خود دارید بنویسید. پس از پایان روی «تایید پرداخت» بزنید.",
        reply_markup=ik_wallet_confirm(order_id),
    )
    await callback.answer()
    return True


async def _start_mixed_payment(callback: CallbackQuery, state: FSMContext, order: dict[str, Any]) -> bool:
    order_id = int(order["id"])
    await state.update_data(mixed_for=order_id)
    await state.set_state(CheckoutStates.wait_mixed_amount)
    user = get_user(callback.from_user.id)
    balance = int(user.get("wallet_balance") or 0)
    await callback.message.answer(
        f"👛 موجودی کیف پول شما: {balance} {CURRENCY}\nچه مقدار از کیف پول پرداخت شود؟ (فقط عدد به تومان)",
    )
    await callback.answer()
    return True


async def _continue_payment(callback: CallbackQuery, state: FSMContext, method: str, order_id: int) -> None:
    order = get_order(order_id)
    if not order or order.get("user_id") != callback.from_user.id:
        await callback.answer("سفارش معتبر نیست یا یافت نشد.", show_alert=True)
        return
    if not _order_ready_for_payment(order):
        await callback.answer("این سفارش در حال حاضر قابل پرداخت نیست.", show_alert=True)
        return
    started = False
    if method == "card":
        started = await _start_card_payment(callback, state, order)
    elif method == "wallet":
        started = await _start_wallet_payment(callback, state, order)
    elif method == "mixed":
        started = await _start_mixed_payment(callback, state, order)
    if not started:
        summary = build_checkout_summary(order)
        enable_plan = order.get("service_category") == "AI"
        await callback.message.answer(summary, reply_markup=ik_cart_actions(order_id, enable_plan=enable_plan))

@router.callback_query(F.data.startswith("cart:paycard:"))
async def cb_cart_paycard(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_contact_verification(callback, state):
        return
    order_id = int(callback.data.split(":")[2])
    order = get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id or not _order_ready_for_payment(order):
        await callback.answer("سفارش نامعتبر یا منقضی است.", show_alert=True)
        return
    if await _prompt_discount_choice(callback, state, order, "card"):
        return
    await _start_card_payment(callback, state, order)


async def _start_wallet_payment(callback: CallbackQuery, state: FSMContext, order_id: int) -> None:
    order = get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("سفارش نامعتبر یا منقضی است.", show_alert=True)
        return
    if order.get("status") != "AWAITING_PAYMENT":
        await callback.answer("سفارش قابل پرداخت نیست.", show_alert=True)
        return
    if not await _ensure_discount_ready(callback, state, order, "wallet"):
        return
    amount = int(order.get("amount_total") or 0)
    user = get_user(callback.from_user.id)
    if int(user["wallet_balance"]) < amount:
        await callback.answer("موجودی کیف پول کافی نیست.", show_alert=True)
        return
    await state.update_data(wallet_for=order_id, wallet_amount=amount, wallet_comment="")
    await state.set_state(CheckoutStates.wait_wallet_comment)
    await callback.message.answer(
        f"👛 پرداخت با کیف پول برای سفارش #{order_id}\n"
        "اگر توضیحاتی برای سفارش خود دارید بنویسید. پس از پایان روی «تایید پرداخت» بزنید.",
        reply_markup=ik_wallet_confirm(order_id),
    )
    await callback.answer()


async def _start_mix_payment(callback: CallbackQuery, state: FSMContext, order_id: int) -> None:
    order = get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("سفارش نامعتبر یا منقضی است.", show_alert=True)
        return
    if order.get("status") != "AWAITING_PAYMENT":
        await callback.answer("سفارش قابل پرداخت نیست.", show_alert=True)
        return
    if not await _ensure_discount_ready(callback, state, order, "mix"):
        return
    user = get_user(callback.from_user.id)
    balance = int(user.get("wallet_balance") or 0)
    total = int(order.get("amount_total") or 0)
    await state.update_data(mixed_for=order_id)
    await state.set_state(CheckoutStates.wait_mixed_amount)
    await callback.message.answer(
        f"🔄 پرداخت ترکیبی برای سفارش #{order_id}\n"
        f"موجودی کیف پول شما: <b>{balance} {CURRENCY}</b>\n"
        f"مبلغ قابل پرداخت: <b>{total} {CURRENCY}</b>\n"
        "چه مقدار از کیف پول پرداخت شود؟ (فقط عدد به تومان)",
    )
    await callback.answer()


async def _run_payment_method(
    callback: CallbackQuery, state: FSMContext, method: str, order_id: int
) -> None:
    if method == "card":
        await _start_card_payment(callback, state, order_id)
    elif method == "wallet":
        await _start_wallet_payment(callback, state, order_id)
    elif method == "mix":
        await _start_mix_payment(callback, state, order_id)
    else:
        await callback.answer("روش پرداخت نامعتبر است.", show_alert=True)


@router.callback_query(F.data.startswith("cart:paycard:"))
async def cb_cart_paycard(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_contact_verification(callback, state):
        return
    try:
        order_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("سفارش نامعتبر است.", show_alert=True)
        return
    await _start_card_payment(callback, state, order_id)


@router.message(CheckoutStates.wait_card_receipt)
async def on_card_receipt(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data.get("order_receipt_for")
    order = get_order(int(order_id)) if order_id else None
    if not order or order["user_id"] != message.from_user.id:
        await message.answer("سفارش یافت نشد یا معتبر نیست.", reply_markup=reply_main())
        await state.clear()
        return

    file_id = None
    text = None
    receipt_kind = ""
    caption_seed = ""
    if message.photo:
        file_id = message.photo[-1].file_id
        receipt_kind = "photo"
        caption_seed = (message.caption or "").strip()
    elif message.document:
        file_id = message.document.file_id
        receipt_kind = "document"
        caption_seed = (message.caption or "").strip()
    elif message.text:
        text = (message.text or "").strip()
    else:
        await message.answer("فرمت رسید نامعتبر است. لطفاً عکس، فایل یا متن ارسال کنید.")
        return

    await state.update_data(
        receipt_file_id=file_id,
        receipt_text=text,
        receipt_comment=caption_seed,
        receipt_kind=receipt_kind,
    )
    await message.answer(
        "اگر توضیحاتی برای سفارش خود دارید بنویسید. در صورت نداشتن توضیح عبارت «بدون توضیح» را ارسال کنید."
    )
    if caption_seed:
        await message.answer("✏️ توضیح همراه رسید ذخیره شد. برای تغییر، متن جدید ارسال کنید یا «بدون توضیح» بنویسید.")
    await state.set_state(CheckoutStates.wait_card_comment)


@router.message(CheckoutStates.wait_card_comment)
async def on_card_comment(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data.get("order_receipt_for")
    order = get_order(int(order_id)) if order_id else None
    if not order or order["user_id"] != message.from_user.id:
        await message.answer("سفارش یافت نشد یا معتبر نیست.", reply_markup=reply_main())
        await state.clear()
        return

    text = (message.text or "").strip()
    if not text:
        await message.answer("لطفاً توضیح را به‌صورت متن ارسال کنید یا عبارت «بدون توضیح» را وارد کنید.")
        return
    lowered = text.lower()
    if lowered in {"بدون توضیح", "بدون توضیحات", "ندارم", "-", "تمام"}:
        comment = ""
    else:
        comment = text
    await state.update_data(receipt_comment=comment)
    preview_lines = [
        f"🧾 پیش‌نمایش ثبت رسید سفارش #{order_id}",
        "رسید شما آماده ثبت است.",
    ]
    if comment:
        preview_lines.append("📝 توضیحات شما:\n" + comment)
    else:
        preview_lines.append("📝 توضیحات شما: —")
    preview_lines.append("برای ادامه یکی از گزینه‌های زیر را انتخاب کنید.")
    await message.answer("\n\n".join(preview_lines), reply_markup=ik_receipt_review(int(order_id)))
    await state.set_state(CheckoutStates.wait_card_confirm)


@router.callback_query(F.data.startswith("cart:rcpt:edit:"))
async def cb_receipt_edit(callback: CallbackQuery, state: FSMContext) -> None:
    order_id = int(callback.data.split(":")[3])
    data = await state.get_data()
    current = data.get("order_receipt_for")
    if not current or int(current) != order_id:
        await callback.answer("برای ویرایش ابتدا رسید را دوباره ارسال کنید.", show_alert=True)
        return
    await state.set_state(CheckoutStates.wait_card_comment)
    await callback.message.answer("توضیح جدید خود را ارسال کنید. برای حذف توضیح عبارت «بدون توضیح» را بنویسید.")
    await callback.answer()


@router.callback_query(F.data.startswith("cart:rcpt:confirm:"))
async def cb_receipt_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    order_id = int(callback.data.split(":")[3])
    data = await state.get_data()
    current = data.get("order_receipt_for")
    if not current or int(current) != order_id:
        await callback.answer("رسید برای این سفارش پیدا نشد.", show_alert=True)
        return
    order = get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("سفارش یافت نشد یا منقضی شده است.", show_alert=True)
        await state.clear()
        return

    receipt_file_id = data.get("receipt_file_id")
    receipt_text = data.get("receipt_text")
    receipt_comment = data.get("receipt_comment") or ""
    receipt_kind = data.get("receipt_kind")

    set_order_receipt(order_id, receipt_file_id, receipt_text)
    set_order_customer_message(order_id, receipt_comment)
    set_order_status(order_id, "PENDING_CONFIRM")
    confirm_order_discount(order_id)

    await callback.message.answer(
        f"✅ رسید سفارش #{order_id} ثبت شد.\nوضعیت: «در انتظار تایید پرداخت»",
        reply_markup=reply_main(),
    )
    await callback.answer()
    await state.clear()

    admin_caption = (
        f"🧾 رسید جدید برای سفارش #{order_id}\n"
        f"مشتری: {mention(callback.from_user)} (@{callback.from_user.username or '—'})\n"
        f"وضعیت: در انتظار تایید پرداخت"
    )
    if receipt_comment:
        admin_caption += f"\n\n📝 توضیح مشتری:\n{receipt_comment}"

    for admin_id in ADMIN_IDS:
        try:
            if receipt_file_id and receipt_kind == "photo":
                await callback.bot.send_photo(admin_id, receipt_file_id, caption=admin_caption)
            elif receipt_file_id and receipt_kind == "document":
                await callback.bot.send_document(admin_id, receipt_file_id, caption=admin_caption)
            else:
                text_body = admin_caption
                if receipt_text:
                    text_body += f"\n\nمتن رسید:\n{receipt_text}"
                await callback.bot.send_message(admin_id, text_body)
        except Exception:
            pass


@router.callback_query(F.data.startswith("cart:paywallet:"))
async def cb_cart_paywallet(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_contact_verification(callback, state):
        return
    try:
        order_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("سفارش نامعتبر است.", show_alert=True)
        return
    await _start_wallet_payment(callback, state, order_id)


@router.message(CheckoutStates.wait_wallet_comment)
async def on_wallet_comment(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data.get("wallet_for")
    order = get_order(int(order_id)) if order_id else None
    if not order or order["user_id"] != message.from_user.id:
        await message.answer("سفارش معتبر نیست یا منقضی شده است.", reply_markup=reply_main())
        await state.clear()
        return
    if not message.text:
        await message.answer("لطفاً توضیحات خود را به‌صورت متن ارسال کنید یا برای ادامه دکمه «تایید پرداخت» را بزنید.")
        return
    text = (message.text or "").strip()
    if text.lower() in {"بدون توضیح", "بدون توضیحات", "ندارم", "-", "تمام"}:
        comment = ""
    else:
        comment = text
    await state.update_data(wallet_comment=comment)
    await message.answer("📝 توضیح شما ذخیره شد. برای نهایی کردن پرداخت روی «تایید پرداخت» بزنید.")


@router.callback_query(F.data.startswith("cart:wallet:confirm:"))
async def cb_wallet_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    order_id = int(callback.data.split(":")[3])
    data = await state.get_data()
    current = data.get("wallet_for")
    if not current or int(current) != order_id:
        await callback.answer("پرداخت کیف پول برای این سفارش فعال نیست.", show_alert=True)
        return
    order = get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id or not _order_ready_for_payment(order):
        await callback.answer("سفارش قابل پرداخت نیست.", show_alert=True)
        await state.clear()
        return
    amount = int(order["amount_total"] or data.get("wallet_amount") or 0)
    user = get_user(callback.from_user.id)
    if int(user["wallet_balance"]) < amount:
        await callback.answer("موجودی کیف پول کافی نیست.", show_alert=True)
        return
    if not change_wallet(callback.from_user.id, -amount, "DEBIT", note=f"Order #{order_id}", order_id=order_id):
        await callback.answer("عدم امکان کسر از کیف پول.", show_alert=True)
        return
    comment = data.get("wallet_comment") or ""
    set_order_wallet_used(order_id, amount)
    set_order_payment_type(order_id, "WALLET")
    set_order_customer_message(order_id, comment)
    set_order_status(order_id, "IN_PROGRESS")
    confirm_order_discount(order_id)
    await callback.message.answer(
        f"✅ پرداخت کیف پول برای سفارش #{order_id} انجام شد.\nوضعیت: «در حال انجام»",
        reply_markup=reply_main(),
    )
    await callback.answer()
    await state.clear()
    notice = f"👛 پرداخت کیف پول — سفارش #{order_id} توسط {mention(callback.from_user)}"
    if comment:
        notice += f"\n\n📝 توضیح مشتری:\n{comment}"
    await _notify_admins(callback.bot, notice)


@router.callback_query(F.data.startswith("cart:payplan:"))
async def cb_cart_payplan(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_contact_verification(callback, state):
        return
    order_id = int(callback.data.split(":")[2])
    order = get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id or order["status"] != "AWAITING_PAYMENT":
        await callback.answer("سفارش نامعتبر یا منقضی است.", show_alert=True)
        return
    if order.get("service_category") != "AI":
        await callback.answer("این طرح فقط برای سفارش‌های بخش هوش مصنوعی در دسترس است.", show_alert=True)
        return
    if user_has_delivered_order(callback.from_user.id):
        await callback.answer("شما قبلاً از این طرح استفاده کرده‌اید.", show_alert=True)
        await callback.message.answer("⚠️ شما قبلاً سفارش تحویل‌شده دارید و امکان استفاده مجدد از طرح خرید اول وجود ندارد.")
        return
    set_order_payment_type(order_id, "FIRST_PLAN")
    await state.update_data(plan_for=order_id, plan_comment="")
    await state.set_state(CheckoutStates.wait_plan_comment)
    await callback.message.answer(
        "✨ طرح خرید اول فعال شد.\n"
        "اگر توضیحاتی برای سفارش خود دارید بنویسید. در صورت نداشتن توضیح عبارت «بدون توضیح» را ارسال کنید."
    )
    await callback.answer()


@router.message(CheckoutStates.wait_plan_comment)
async def on_plan_comment(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data.get("plan_for")
    order = get_order(int(order_id)) if order_id else None
    if not order or order["user_id"] != message.from_user.id:
        await message.answer("سفارش یافت نشد یا معتبر نیست.", reply_markup=reply_main())
        await state.clear()
        return
    if not message.text:
        await message.answer("لطفاً توضیحات خود را به‌صورت متن ارسال کنید یا عبارت «بدون توضیح» را وارد کنید.")
        return
    text = (message.text or "").strip()
    if text.lower() in {"بدون توضیح", "بدون توضیحات", "ندارم", "-", "تمام"}:
        comment = ""
    else:
        comment = text
    await state.update_data(plan_comment=comment)
    preview_lines = [
        f"✨ طرح خرید اول — سفارش #{order_id}",
        "درخواست شما آماده ارسال برای تایید است.",
    ]
    if comment:
        preview_lines.append("📝 توضیحات شما:\n" + comment)
    else:
        preview_lines.append("📝 توضیحات شما: —")
    preview_lines.append("برای ادامه یکی از گزینه‌های زیر را انتخاب کنید.")
    await message.answer("\n\n".join(preview_lines), reply_markup=ik_plan_review(int(order_id)))
    await state.set_state(CheckoutStates.wait_plan_confirm)


@router.callback_query(F.data.startswith("cart:plan:edit:"))
async def cb_plan_edit(callback: CallbackQuery, state: FSMContext) -> None:
    order_id = int(callback.data.split(":")[3])
    data = await state.get_data()
    current = data.get("plan_for")
    if not current or int(current) != order_id:
        await callback.answer("برای ویرایش ابتدا طرح را دوباره ثبت کنید.", show_alert=True)
        return
    await state.set_state(CheckoutStates.wait_plan_comment)
    await callback.message.answer("توضیح جدید خود را ارسال کنید. برای حذف توضیح عبارت «بدون توضیح» را بنویسید.")
    await callback.answer()


@router.callback_query(F.data.startswith("cart:plan:confirm:"))
async def cb_plan_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    order_id = int(callback.data.split(":")[3])
    data = await state.get_data()
    current = data.get("plan_for")
    if not current or int(current) != order_id:
        await callback.answer("طرح خرید اول برای این سفارش فعال نیست.", show_alert=True)
        return
    order = get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id or order["status"] != "AWAITING_PAYMENT":
        await callback.answer("سفارش یافت نشد یا منقضی شده است.", show_alert=True)
        await state.clear()
        return
    if order.get("service_category") != "AI":
        await callback.answer("طرح خرید اول برای این سفارش فعال نیست.", show_alert=True)
        await state.clear()
        return
    comment = data.get("plan_comment") or ""
    set_order_customer_message(order_id, comment)
    set_order_status(order_id, "PENDING_PLAN")
    set_order_payment_type(order_id, "FIRST_PLAN")
    await callback.message.answer(
        f"✅ درخواست طرح خرید اول برای سفارش #{order_id} ثبت شد.\nوضعیت: «در انتظار تایید طرح»",
        reply_markup=reply_main(),
    )
    await callback.answer()
    await state.clear()

    title = _order_title(order.get("service_category", ""), order.get("service_code", ""), order.get("notes"))
    notice = (
        f"✨ طرح خرید اول — سفارش #{order_id}\n"
        f"مشتری: {mention(callback.from_user)} (@{callback.from_user.username or '—'})\n"
        f"محصول: {title}"
    )
    if comment:
        notice += f"\n\n📝 توضیح مشتری:\n{comment}"
    await _notify_admins(callback.bot, notice)


@router.callback_query(F.data.startswith("cart:paymix:"))
async def cb_cart_paymix(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_contact_verification(callback, state):
        return
    try:
        order_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("سفارش نامعتبر است.", show_alert=True)
        return
    await _start_mix_payment(callback, state, order_id)


def _parse_discount_payload(data: str) -> tuple[str | None, int | None]:
    parts = data.split(":")
    if len(parts) < 5:
        return None, None
    method = parts[3]
    try:
        order_id = int(parts[4])
    except (TypeError, ValueError):
        return method, None
    return method, order_id


@router.callback_query(F.data.startswith("cart:discount:yes:"))
async def cb_discount_yes(callback: CallbackQuery, state: FSMContext) -> None:
    method, order_id = _parse_discount_payload(callback.data)
    if method not in {"card", "wallet", "mix"} or not order_id:
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    order = get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("سفارش یافت نشد یا منقضی شده است.", show_alert=True)
        return
    if order.get("status") != "AWAITING_PAYMENT":
        await callback.answer("در حال حاضر امکان ثبت تخفیف نیست.", show_alert=True)
        return
    try:
        existing_discount = int(order.get("discount_amount") or 0)
        discount_id = int(order.get("discount_code_id") or 0)
    except (TypeError, ValueError):
        existing_discount = 0
        discount_id = 0
    if existing_discount > 0 and discount_id:
        await callback.answer("برای این سفارش قبلاً تخفیف اعمال شده است.", show_alert=True)
        return
    await state.update_data(
        discount_flow={"order_id": order_id, "status": "await_code", "method": method},
        discount_code_value=None,
    )
    await state.set_state(CheckoutStates.wait_discount_code)
    await callback.message.answer(
        "کد تخفیف خود را وارد کنید و سپس روی «اعمال» بزنید.",
        reply_markup=ik_discount_controls(order_id, method),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cart:discount:no:"))
async def cb_discount_no(callback: CallbackQuery, state: FSMContext) -> None:
    method, order_id = _parse_discount_payload(callback.data)
    if method not in {"card", "wallet", "mix"} or not order_id:
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    order = get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("سفارش یافت نشد یا منقضی شده است.", show_alert=True)
        return
    if order.get("status") != "AWAITING_PAYMENT":
        await callback.answer("در حال حاضر امکان ادامه وجود ندارد.", show_alert=True)
        return
    await state.update_data(
        discount_flow={"order_id": order_id, "status": "declined", "method": method},
        discount_code_value=None,
    )
    await state.set_state(None)
    await _run_payment_method(callback, state, method, order_id)


@router.callback_query(F.data.startswith("cart:discount:cancel:"))
async def cb_discount_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    method, order_id = _parse_discount_payload(callback.data)
    if method not in {"card", "wallet", "mix"} or not order_id:
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    order = get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("سفارش یافت نشد یا منقضی شده است.", show_alert=True)
        await state.set_state(None)
        return
    if order.get("status") != "AWAITING_PAYMENT":
        await callback.answer("در حال حاضر امکان ثبت تخفیف نیست.", show_alert=True)
        await state.set_state(None)
        return
    await state.update_data(
        discount_flow={"order_id": order_id, "status": "prompt", "method": method},
        discount_code_value=None,
    )
    await state.set_state(None)
    await callback.message.answer(
        "آیا کد تخفیف دارید؟",
        reply_markup=ik_discount_prompt(order_id, method),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cart:discount:apply:"))
async def cb_discount_apply(callback: CallbackQuery, state: FSMContext) -> None:
    method, order_id = _parse_discount_payload(callback.data)
    if method not in {"card", "wallet", "mix"} or not order_id:
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    order = get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("سفارش یافت نشد یا منقضی شده است.", show_alert=True)
        await state.set_state(None)
        return
    if order.get("status") != "AWAITING_PAYMENT":
        await callback.answer("در حال حاضر امکان ثبت تخفیف نیست.", show_alert=True)
        await state.set_state(None)
        return
    try:
        existing_discount = int(order.get("discount_amount") or 0)
        discount_id = int(order.get("discount_code_id") or 0)
    except (TypeError, ValueError):
        existing_discount = 0
        discount_id = 0
    if existing_discount > 0 and discount_id:
        await callback.answer("برای این سفارش تخفیف ثبت شده است.", show_alert=True)
        await state.set_state(None)
        return
    data = await state.get_data()
    discount_flow = data.get("discount_flow") or {}
    if int(discount_flow.get("order_id") or 0) != order_id:
        await callback.answer("اطلاعات کد تخفیف یافت نشد.", show_alert=True)
        return
    code_value = str((data.get("discount_code_value") or "").strip())
    if not code_value:
        await callback.answer("ابتدا کد تخفیف را وارد کنید.", show_alert=True)
        return
    success, summary, error = apply_discount_to_order(order_id, callback.from_user.id, code_value)
    if not success:
        await callback.answer(error or "امکان اعمال این کد وجود ندارد.", show_alert=True)
        return
    await state.update_data(
        discount_flow={"order_id": order_id, "status": "applied", "method": method},
        discount_code_value=None,
    )
    await state.set_state(None)
    summary_lines = ["🎉 کد تخفیف با موفقیت اعمال شد."]
    if summary:
        title = str(summary.get("title") or "").strip()
        code = str(summary.get("code") or code_value).strip()
        if title:
            summary_lines.append(f"نام کد: {title}")
        if code:
            summary_lines.append(f"کد: <code>{code}</code>")
        try:
            discount_amount = int(summary.get("discount_amount") or 0)
        except (TypeError, ValueError):
            discount_amount = 0
        try:
            total_amount = int(summary.get("amount_total") or 0)
        except (TypeError, ValueError):
            total_amount = 0
        summary_lines.append(f"تخفیف: {discount_amount} {CURRENCY}")
        summary_lines.append(f"مبلغ قابل پرداخت: {total_amount} {CURRENCY}")
    await callback.message.answer("\n".join(summary_lines))
    await send_checkout_prompt(callback.message, order_id)
    await _run_payment_method(callback, state, method, order_id)


@router.message(CheckoutStates.wait_discount_code)
async def on_discount_code(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    discount_flow = data.get("discount_flow") or {}
    order_id = discount_flow.get("order_id")
    if not order_id:
        await message.answer("سفارش یافت نشد.", reply_markup=reply_main())
        await state.clear()
        return
    order = get_order(int(order_id))
    if not order or order["user_id"] != message.from_user.id or order.get("status") != "AWAITING_PAYMENT":
        await message.answer("سفارش معتبر نیست یا منقضی شده است.", reply_markup=reply_main())
        await state.clear()
        return
    if not message.text:
        await message.answer("لطفاً کد تخفیف را به صورت متن وارد کنید.")
        return
    code = message.text.strip()
    if not code:
        await message.answer("لطفاً کد تخفیف را به صورت متن وارد کنید.")
        return
    await state.update_data(discount_code_value=code)
    method = discount_flow.get("method") or "card"
    await message.answer(
        f"کد «{code}» ثبت شد. برای ادامه روی «اعمال» بزنید.",
        reply_markup=ik_discount_controls(int(order_id), method),
    )

@router.message(CheckoutStates.wait_mixed_amount)
async def on_mixed_amount(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("لطفاً فقط عدد (تومان) وارد کنید:")
        return
    amt_wallet = int(text)
    data = await state.get_data()
    order_id = int(data.get("mixed_for"))
    order = get_order(order_id)
    if not order or order["user_id"] != message.from_user.id or not _order_ready_for_payment(order):
        await message.answer("سفارش نامعتبر یا منقضی است.", reply_markup=reply_main())
        await state.clear()
        return
    total = int(order["amount_total"] or 0)
    user = get_user(message.from_user.id)
    if amt_wallet <= 0 or amt_wallet > total:
        await message.answer("مقدار نامعتبر است.")
        return
    if int(user["wallet_balance"]) < amt_wallet:
        await message.answer("موجودی کیف پول کافی نیست.")
        return
    if not change_wallet(
        message.from_user.id,
        -amt_wallet,
        "RESERVE",
        note=f"Reserve for order #{order_id}",
        order_id=order_id,
    ):
        await message.answer("امکان رزرو کیف پول نیست.")
        return
    set_order_wallet_reserved(order_id, amt_wallet)
    set_order_payment_type(order_id, "MIXED")
    await state.update_data(
        order_receipt_for=order_id,
        receipt_file_id=None,
        receipt_text=None,
        receipt_comment="",
        receipt_kind="",
    )
    await message.answer(
        f"✅ {amt_wallet} {CURRENCY} از کیف پول رزرو شد.\n"
        "باقیمانده را کارت‌به‌کارت پرداخت کنید و پس از پرداخت رسید را ارسال کنید.",
        reply_markup=ik_card_receipt_prompt(order_id),
    )
    await message.answer(f"🧾 رسید کارت سفارش #{order_id} را ارسال کنید.")
    await state.set_state(CheckoutStates.wait_card_receipt)


@router.callback_query(F.data.startswith("cart:cancel:"))
async def cb_cart_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    order_id = int(callback.data.split(":")[2])
    order = get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id or order["status"] not in ("AWAITING_PAYMENT", "PENDING_CONFIRM"):
        await callback.answer("قابل لغو نیست.", show_alert=True)
        return
    reserved = int(order.get("wallet_reserved_amount") or 0)
    if reserved > 0:
        change_wallet(callback.from_user.id, reserved, "REFUND", note=f"Cancel order #{order_id}", order_id=order_id)
        set_order_wallet_reserved(order_id, 0)
    release_order_discount(order_id)
    set_order_status(order_id, "CANCELED")
    await state.update_data(discount_flow=None, discount_code_value=None)
    await callback.message.answer(f"❌ سفارش #{order_id} لغو شد.", reply_markup=reply_main())
    await callback.answer()
