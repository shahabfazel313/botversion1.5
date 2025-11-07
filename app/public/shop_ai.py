from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from . import router
from ..catalog import AI_VARIANT_MAP, get_variant
from ..config import AI_PLANS, CURRENCY
from ..db import create_order, ensure_user, get_user
from ..keyboards import ik_ai_buy_modes, ik_ai_confirm_purchase, ik_ai_main, ik_cart_actions, reply_main
from ..states import ShopStates
from ..utils import is_valid_email


@router.callback_query(F.data == "shop:ai")
async def cb_shop_ai(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("🤖 لطفاً پلن مورد نظر خود را انتخاب کنید:", reply_markup=ik_ai_main())
    await callback.answer()


@router.callback_query(F.data == "ai:back")
async def cb_ai_back(callback: CallbackQuery, state: FSMContext) -> None:
    await cb_shop_ai(callback, state)
    await callback.answer()


_PLAN_KEY_MAP = {"team": "gpt_team", "plus": "gpt_plus", "google": "google_pro"}


def _ai_plan_config(code: str) -> dict:
    return AI_PLANS[_PLAN_KEY_MAP[code]]


def _ai_plan_description(code: str) -> str:
    plan = _ai_plan_config(code)
    return f"<b>{plan['title']}</b>\n\n{plan['desc']}"


def _variant_data(plan_code: str, mode: str) -> dict[str, object]:
    try:
        variant_code = AI_VARIANT_MAP[plan_code][mode]
    except KeyError as exc:
        raise KeyError(f"Unknown variant for plan {plan_code}:{mode}") from exc
    return get_variant(variant_code)


def _mode_buttons(plan_code: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for mode, variant_code in AI_VARIANT_MAP.get(plan_code, {}).items():
        variant = get_variant(variant_code)
        if variant["available"]:
            callback = f"ai:{plan_code}:mode:{mode}"
            text = variant["button_label"]
        else:
            callback = f"ai:{plan_code}:mode:{mode}:unavailable"
            text = variant["unavailable_label"]
        items.append({"mode": mode, "callback": callback, "text": text})
    return items


def _price_line(amount: int) -> str:
    if amount <= 0:
        return "💰 قیمت: <b>تنظیم نشده</b>"
    return f"💰 قیمت: <b>{amount}</b> {CURRENCY}"


def _mode_label(mode: str) -> str:
    return {
        "my": "روی اکانت خودم",
        "pre": "اکانت از پیش ساخته‌شده",
    }.get(mode, mode)


def _unavailable_text(variant: dict[str, object]) -> str:
    label = str(variant.get("unavailable_label") or "")
    if "به‌زودی" in label:
        return "این گزینه به‌زودی فعال می‌شود."
    return "این گزینه در حال حاضر ناموجود است."


async def _alert_unavailable(callback: CallbackQuery, variant: dict[str, object]) -> None:
    text = _unavailable_text(variant)
    await callback.answer(text, show_alert=True)
    await callback.message.answer(text, reply_markup=reply_main())


async def _message_unavailable(message: Message, variant: dict[str, object]) -> None:
    await message.answer(_unavailable_text(variant), reply_markup=reply_main())


@router.callback_query(F.data == "ai:team")
async def cb_ai_team(callback: CallbackQuery, state: FSMContext) -> None:
    description = _ai_plan_description("team")
    await callback.message.edit_text(
        f"{description}\n\nلطفاً حالت خرید را انتخاب کنید:",
        reply_markup=ik_ai_buy_modes("team", _mode_buttons("team")),
    )
    await callback.answer()


@router.callback_query(F.data == "ai:plus")
async def cb_ai_plus(callback: CallbackQuery, state: FSMContext) -> None:
    description = _ai_plan_description("plus")
    await callback.message.edit_text(
        f"{description}\n\nلطفاً حالت خرید را انتخاب کنید:",
        reply_markup=ik_ai_buy_modes("plus", _mode_buttons("plus")),
    )
    await callback.answer()


@router.callback_query(F.data == "ai:google")
async def cb_ai_google(callback: CallbackQuery, state: FSMContext) -> None:
    description = _ai_plan_description("google")
    await callback.message.edit_text(
        f"{description}\n\nلطفاً حالت خرید را انتخاب کنید:",
        reply_markup=ik_ai_buy_modes("google", _mode_buttons("google")),
    )
    await callback.answer()


@router.callback_query(F.data == "ai:team:back")
async def cb_ai_team_back(callback: CallbackQuery, state: FSMContext) -> None:
    await cb_shop_ai(callback, state)


@router.callback_query(F.data == "ai:plus:back")
async def cb_ai_plus_back(callback: CallbackQuery, state: FSMContext) -> None:
    await cb_shop_ai(callback, state)


@router.callback_query(F.data == "ai:google:back")
async def cb_ai_google_back(callback: CallbackQuery, state: FSMContext) -> None:
    await cb_shop_ai(callback, state)


@router.callback_query(F.data == "ai:team:mode:my:back")
async def cb_ai_team_mode_my_back(callback: CallbackQuery, state: FSMContext) -> None:
    await cb_ai_team(callback, state)


@router.callback_query(F.data == "ai:team:mode:pre:back")
async def cb_ai_team_mode_pre_back(callback: CallbackQuery, state: FSMContext) -> None:
    await cb_ai_team(callback, state)


@router.callback_query(F.data == "ai:plus:mode:my:back")
async def cb_ai_plus_mode_my_back(callback: CallbackQuery, state: FSMContext) -> None:
    await cb_ai_plus(callback, state)


@router.callback_query(F.data == "ai:plus:mode:pre:back")
async def cb_ai_plus_mode_pre_back(callback: CallbackQuery, state: FSMContext) -> None:
    await cb_ai_plus(callback, state)


@router.callback_query(F.data == "ai:google:mode:my:back")
async def cb_ai_google_mode_my_back(callback: CallbackQuery, state: FSMContext) -> None:
    await cb_ai_google(callback, state)


@router.callback_query(F.data == "ai:google:mode:pre:back")
async def cb_ai_google_mode_pre_back(callback: CallbackQuery, state: FSMContext) -> None:
    await cb_ai_google(callback, state)


@router.callback_query(F.data == "ai:team:mode:my")
async def cb_ai_team_mode_my(callback: CallbackQuery, state: FSMContext) -> None:
    variant = _variant_data("team", "my")
    if not variant["available"]:
        await _alert_unavailable(callback, variant)
        return
    amount = int(variant["amount"])
    description = _ai_plan_description("team")
    price_line = _price_line(amount)
    await callback.message.answer(
        f"{description}\n\nحالت انتخابی: <b>{_mode_label('my')}</b>\n{price_line}",
        reply_markup=ik_ai_confirm_purchase("team", "my"),
    )
    await callback.answer()


@router.message(ShopStates.ai_team_wait_email)
async def on_ai_team_email(message: Message, state: FSMContext) -> None:
    email = (message.text or "").strip()
    if not is_valid_email(email):
        await message.answer("ایمیل نامعتبر است. دوباره وارد کنید:")
        return
    ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name or "",
    )
    variant = _variant_data("team", "my")
    if not variant["available"]:
        await _message_unavailable(message, variant)
        await state.clear()
        return
    amount = int(variant["amount"])
    if amount <= 0:
        await message.answer("قیمت این سرویس هنوز تنظیم نشده است.", reply_markup=reply_main())
        await state.clear()
        return
    user = get_user(message.from_user.id)
    order_id = create_order(
        user=user,
        title="اکانت ChatGPT Team",
        amount_total=amount,
        currency=CURRENCY,
        service_category="AI",
        service_code="team",
        account_mode="MY_ACCOUNT",
        customer_email=email,
        notes="",
    )
    await message.answer(
        f"✅ سفارش #{order_id} ایجاد شد و به «🧺 سبد خرید» اضافه شد.\n"
        f"برای ادامه، روش پرداخت را انتخاب کنید:",
        reply_markup=ik_cart_actions(order_id, enable_plan=True),
    )
    await state.clear()


@router.callback_query(F.data == "ai:team:mode:pre")
async def cb_ai_team_mode_pre(callback: CallbackQuery, state: FSMContext) -> None:
    variant = _variant_data("team", "pre")
    if not variant["available"]:
        await _alert_unavailable(callback, variant)
        return
    amount = int(variant["amount"])
    description = _ai_plan_description("team")
    price_line = _price_line(amount)
    await callback.message.answer(
        f"{description}\n\nحالت انتخابی: <b>{_mode_label('pre')}</b>\n{price_line}",
        reply_markup=ik_ai_confirm_purchase("team", "pre"),
    )
    await callback.answer()


@router.callback_query(F.data == "ai:team:mode:my:buy")
async def cb_ai_team_mode_my_buy(callback: CallbackQuery, state: FSMContext) -> None:
    variant = _variant_data("team", "my")
    if not variant["available"]:
        await _alert_unavailable(callback, variant)
        return
    if int(variant["amount"]) <= 0:
        await callback.message.answer("قیمت این سرویس هنوز تنظیم نشده است.", reply_markup=reply_main())
        await callback.answer()
        return
    await state.update_data(pending_service="AI", pending_code="team")
    await callback.message.answer("ایمیل متصل به ChatGPT خود را وارد کنید:")
    await state.set_state(ShopStates.ai_team_wait_email)
    await callback.answer()


@router.callback_query(F.data == "ai:team:mode:pre:buy")
async def cb_ai_team_mode_pre_buy(callback: CallbackQuery, state: FSMContext) -> None:
    ensure_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name or "")
    variant = _variant_data("team", "pre")
    if not variant["available"]:
        await _alert_unavailable(callback, variant)
        return
    amount = int(variant["amount"])
    if amount <= 0:
        await callback.message.answer("قیمت این سرویس هنوز تنظیم نشده است.", reply_markup=reply_main())
        await callback.answer()
        return
    user = get_user(callback.from_user.id)
    order_id = create_order(
        user=user,
        title="اکانت ChatGPT Team",
        amount_total=amount,
        currency=CURRENCY,
        service_category="AI",
        service_code="team",
        account_mode="PREBUILT",
        customer_email=None,
        notes="",
    )
    await callback.message.answer(
        f"✅ سفارش #{order_id} ایجاد شد و به «🧺 سبد خرید» اضافه شد.\n"
        f"برای ادامه، روش پرداخت را انتخاب کنید:",
        reply_markup=ik_cart_actions(order_id, enable_plan=True),
    )
    await callback.answer()


@router.callback_query(F.data == "ai:plus:mode:my")
async def cb_ai_plus_mode_my(callback: CallbackQuery, state: FSMContext) -> None:
    variant = _variant_data("plus", "my")
    if not variant["available"]:
        await _alert_unavailable(callback, variant)
        return
    amount = int(variant["amount"])
    description = _ai_plan_description("plus")
    price_line = _price_line(amount)
    await callback.message.answer(
        f"{description}\n\nحالت انتخابی: <b>{_mode_label('my')}</b>\n{price_line}",
        reply_markup=ik_ai_confirm_purchase("plus", "my"),
    )
    await callback.answer()


@router.message(ShopStates.ai_plus_wait_email)
async def on_ai_plus_email(message: Message, state: FSMContext) -> None:
    email = (message.text or "").strip()
    if not is_valid_email(email):
        await message.answer("ایمیل نامعتبر است. دوباره وارد کنید:")
        return
    await state.update_data(customer_email=email)
    await message.answer("حالا رمز اکانت را وارد کنید (حداقل ۸ کاراکتر):")
    await state.set_state(ShopStates.ai_plus_wait_password)


@router.message(ShopStates.ai_plus_wait_password)
async def on_ai_plus_password(message: Message, state: FSMContext) -> None:
    password = (message.text or "").strip()
    if len(password) < 8:
        await message.answer("رمز خیلی کوتاه است. دوباره وارد کنید (حداقل ۸ کاراکتر):")
        return
    ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name or "",
    )
    data = await state.get_data()
    variant = _variant_data("plus", "my")
    if not variant["available"]:
        await _message_unavailable(message, variant)
        await state.clear()
        return
    amount = int(variant["amount"])
    if amount <= 0:
        await message.answer("قیمت این سرویس هنوز تنظیم نشده است.", reply_markup=reply_main())
        await state.clear()
        return
    user = get_user(message.from_user.id)
    order_id = create_order(
        user=user,
        title="اکانت ChatGPT Plus",
        amount_total=amount,
        currency=CURRENCY,
        service_category="AI",
        service_code="plus",
        account_mode="MY_ACCOUNT",
        customer_email=data.get("customer_email"),
        notes="(پسورد به‌صورت امن در مراحل بعد ذخیره/مدیریت می‌شود)",
        customer_secret=password,
    )
    await message.answer(
        f"✅ سفارش #{order_id} ایجاد شد و به «🧺 سبد خرید» اضافه شد.\n"
        f"برای ادامه، روش پرداخت را انتخاب کنید:",
        reply_markup=ik_cart_actions(order_id, enable_plan=True),
    )
    await state.clear()


@router.callback_query(F.data == "ai:plus:mode:pre")
async def cb_ai_plus_mode_pre(callback: CallbackQuery, state: FSMContext) -> None:
    variant = _variant_data("plus", "pre")
    if not variant["available"]:
        await _alert_unavailable(callback, variant)
        return
    amount = int(variant["amount"])
    description = _ai_plan_description("plus")
    price_line = _price_line(amount)
    await callback.message.answer(
        f"{description}\n\nحالت انتخابی: <b>{_mode_label('pre')}</b>\n{price_line}",
        reply_markup=ik_ai_confirm_purchase("plus", "pre"),
    )
    await callback.answer()


@router.callback_query(F.data == "ai:plus:mode:my:buy")
async def cb_ai_plus_mode_my_buy(callback: CallbackQuery, state: FSMContext) -> None:
    variant = _variant_data("plus", "my")
    if not variant["available"]:
        await _alert_unavailable(callback, variant)
        return
    if int(variant["amount"]) <= 0:
        await callback.message.answer("قیمت این سرویس هنوز تنظیم نشده است.", reply_markup=reply_main())
        await callback.answer()
        return
    await state.update_data(pending_service="AI", pending_code="plus")
    await callback.message.answer("ایمیل متصل به ChatGPT خود را وارد کنید:")
    await state.set_state(ShopStates.ai_plus_wait_email)
    await callback.answer()


@router.callback_query(F.data == "ai:plus:mode:pre:buy")
async def cb_ai_plus_mode_pre_buy(callback: CallbackQuery, state: FSMContext) -> None:
    ensure_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name or "")
    variant = _variant_data("plus", "pre")
    if not variant["available"]:
        await _alert_unavailable(callback, variant)
        return
    amount = int(variant["amount"])
    if amount <= 0:
        await callback.message.answer("قیمت این سرویس هنوز تنظیم نشده است.", reply_markup=reply_main())
        await callback.answer()
        return
    user = get_user(callback.from_user.id)
    order_id = create_order(
        user=user,
        title="اکانت ChatGPT Plus",
        amount_total=amount,
        currency=CURRENCY,
        service_category="AI",
        service_code="plus",
        account_mode="PREBUILT",
        customer_email=None,
        notes="",
    )
    await callback.message.answer(
        f"✅ سفارش #{order_id} ایجاد شد و به «🧺 سبد خرید» اضافه شد.\n"
        f"برای ادامه، روش پرداخت را انتخاب کنید:",
        reply_markup=ik_cart_actions(order_id, enable_plan=True),
    )
    await callback.answer()


@router.callback_query(F.data == "ai:google:mode:pre")
async def cb_ai_google_mode_pre(callback: CallbackQuery, state: FSMContext) -> None:
    variant = _variant_data("google", "pre")
    if not variant["available"]:
        await _alert_unavailable(callback, variant)
        return
    amount = int(variant["amount"])
    description = _ai_plan_description("google")
    price_line = _price_line(amount)
    await callback.message.answer(
        f"{description}\n\nحالت انتخابی: <b>{_mode_label('pre')}</b>\n{price_line}",
        reply_markup=ik_ai_confirm_purchase("google", "pre"),
    )
    await callback.answer()


@router.callback_query(F.data == "ai:google:mode:pre:buy")
async def cb_ai_google_mode_pre_buy(callback: CallbackQuery, state: FSMContext) -> None:
    ensure_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name or "")
    variant = _variant_data("google", "pre")
    if not variant["available"]:
        await _alert_unavailable(callback, variant)
        return
    amount = int(variant["amount"])
    if amount <= 0:
        await callback.message.answer("قیمت این سرویس هنوز تنظیم نشده است.", reply_markup=reply_main())
        await callback.answer()
        return
    user = get_user(callback.from_user.id)
    order_id = create_order(
        user=user,
        title="اکانت Google AI Pro",
        amount_total=amount,
        currency=CURRENCY,
        service_category="AI",
        service_code="google",
        account_mode="PREBUILT",
        customer_email=None,
        notes="",
    )
    await callback.message.answer(
        f"✅ سفارش #{order_id} ایجاد شد و به «🧺 سبد خرید» اضافه شد.\n"
        f"برای ادامه، روش پرداخت را انتخاب کنید:",
        reply_markup=ik_cart_actions(order_id, enable_plan=True),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^ai:(team|plus|google):mode:(my|pre):unavailable$"))
async def cb_ai_mode_unavailable(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    plan_code = parts[1]
    mode = parts[3]
    variant = _variant_data(plan_code, mode)
    await _alert_unavailable(callback, variant)
