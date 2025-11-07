from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from . import router
from .helpers import _fmt_order_for_user
from ..config import CURRENCY
from ..db import count_orders_by_category, get_user_stats, list_orders_by_category
from ..keyboards import ik_history_menu, ik_history_more, ik_profile_actions


@router.callback_query(F.data == "hist:menu")
async def cb_hist_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer("🧾 تاریخچه سفارشات — یک دسته را انتخاب کنید:", reply_markup=ik_history_menu())
    await callback.answer()


@router.callback_query(F.data == "hist:back")
async def cb_hist_back(callback: CallbackQuery, state: FSMContext) -> None:
    stats = get_user_stats(callback.from_user.id)
    await callback.message.answer(
        "👤 <b>اطلاعات کاربری</b>\n"
        f"• موجودی کیف پول: <b>{stats['wallet_balance']} {CURRENCY}</b>\n"
        f"• تعداد سفارش‌ها: <b>{stats['orders_total']}</b>\n"
        f"• سفارشات در حال انجام: <b>{stats['orders_inprog']}</b>\n"
        f"• سفارشات تکمیل‌شده: <b>{stats['orders_done']}</b>\n"
        f"• تعداد زیرمجموعه‌ها: <b>{stats['ref_count']}</b>\n"
        f"• درآمد شما: <b>{stats['earnings_total']} {CURRENCY}</b>",
        reply_markup=ik_profile_actions(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("hist:show:"))
async def cb_hist_show(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, category, page_token = callback.data.split(":")
    page = int(page_token.replace("p", "")) if page_token.startswith("p") else 1
    page_size = 10
    offset = (page - 1) * page_size

    category_label = {
        "inprog": "🟡 سفارشات در حال انجام",
        "done": "✅ سفارشات تکمیل‌شده",
        "all": "📚 تمام سفارشات",
    }.get(category, category)

    total = count_orders_by_category(callback.from_user.id, category)
    rows = list_orders_by_category(callback.from_user.id, category, limit=page_size, offset=offset)

    if page == 1:
        await callback.message.answer(f"{category_label} — مجموع: {total}")

    if not rows:
        if page == 1:
            await callback.message.answer("موردی یافت نشد.", reply_markup=ik_history_menu())
        else:
            await callback.message.answer("مورد دیگری برای نمایش نیست.", reply_markup=ik_history_more(category, page))
        await callback.answer()
        return

    for order in rows:
        await callback.message.answer(_fmt_order_for_user(order))

    has_more = (offset + len(rows)) < total
    if has_more:
        await callback.message.answer("—", reply_markup=ik_history_more(category, page + 1))
    else:
        await callback.message.answer("پایان لیست.", reply_markup=ik_history_menu())

    await callback.answer()
