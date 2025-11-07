from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from datetime import datetime

from .config import CURRENCY, ADMIN_IDS
from .db import db_execute
from .states import AdminStates
from .keyboards import kb_admin_actions
from .utils import is_admin

router = Router()

@router.message(Command("admin"))
async def on_admin_cmd(m: Message):
    if not is_admin(m.from_user.id, ADMIN_IDS):
        await m.answer("دسترسی ادمین ندارید.")
        return
    pending = db_execute(
        "SELECT COUNT(*) AS c FROM orders WHERE status='در انتظار تایید پرداخت'",
        fetchone=True,
    )["c"]
    text = (
        "👮‍♂️ پنل ادمین (ساده)\n"
        f"سفارش‌های منتظر تایید پرداخت: <b>{pending}</b>\n\n"
        "– برای هر سفارش جدید، اعلان دریافت می‌کنید و با دکمه‌های زیر پیام می‌گیرید.\n"
        "– دستورات کاربردی:\n"
        "/pending - لیست 10 سفارش منتظر تایید\n"
        "/search <id> - نمایش یک سفارش"
    )
    await m.answer(text)

@router.message(Command("pending"))
async def on_admin_pending(m: Message):
    if not is_admin(m.from_user.id, ADMIN_IDS):
        await m.answer("دسترسی ادمین ندارید.")
        return
    rows = db_execute(
        "SELECT id, plan_title, price, status, created_at FROM orders WHERE status='در انتظار تایید پرداخت' ORDER BY id DESC LIMIT 10",
        fetchall=True,
    )
    if not rows:
        await m.answer("هیچ سفارش منتظر تایید وجود ندارد.")
        return
    lines = []
    for r in rows:
        created = r["created_at"].replace("T", " ")
        lines.append(
            f"– #{r['id']} | {r['plan_title']} | {r['price']} {CURRENCY}\n  وضعیت: <b>{r['status']}</b> | {created}"
        )
    await m.answer("🟡 سفارش‌های منتظر تایید:\n\n" + "\n".join(lines))

@router.message(Command("search"))
async def on_admin_search(m: Message):
    if not is_admin(m.from_user.id, ADMIN_IDS):
        await m.answer("دسترسی ادمین ندارید.")
        return
    parts = m.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        await m.answer("استفاده درست: /search 123")
        return
    oid = int(parts[1])
    row = db_execute("SELECT * FROM orders WHERE id=?", (oid,), fetchone=True)
    if not row:
        await m.answer("سفارش یافت نشد.")
        return
    text = (
        f"سفارش #{row['id']}\n"
        f"مشتری: <code>{row['user_id']}</code> @{row['username'] or '—'}\n"
        f"پلن: {row['plan_title']} | مبلغ: {row['price']} {CURRENCY}\n"
        f"وضعیت: {row['status']}\n"
        f"ایجاد: {row['created_at'].replace('T',' ')}\n"
    )
    await m.answer(text, reply_markup=kb_admin_actions(row["id"]))

@router.callback_query(F.data.startswith("admin:"))
async def on_admin_action(c: CallbackQuery, state: FSMContext):
    if not is_admin(c.from_user.id, ADMIN_IDS):
        await c.answer("دسترسی ادمین ندارید.", show_alert=True)
        return

    _, action, oid_str = c.data.split(":")
    order_id = int(oid_str)
    row = db_execute("SELECT * FROM orders WHERE id=?", (order_id,), fetchone=True)
    if not row:
        await c.answer("سفارش یافت نشد.", show_alert=True)
        return

    if action == "msg":
        await state.set_state(AdminStates.waiting_message)
        await state.update_data(order_id=order_id, customer_id=row["user_id"])
        await c.message.answer(f"پیام خود برای مشتری سفارش #{order_id} را ارسال کنید.")
        await c.answer()
        return

    new_status = None
    if action == "approve":
        new_status = "پرداخت تایید شد"
    elif action == "reject":
        new_status = "رد شد (نیاز به پیگیری)"
    elif action == "delivered":
        new_status = "تحویل شد"

    if new_status:
        db_execute(
            "UPDATE orders SET status=?, updated_at=? WHERE id=?",
            (new_status, datetime.now().isoformat(timespec="seconds"), order_id),
        )
        await c.answer("وضعیت به‌روزرسانی شد.")
        try:
            await c.bot.send_message(
                row["user_id"],
                f"وضعیت سفارش #{order_id} به «<b>{new_status}</b>» تغییر کرد.",
            )
        except Exception:
            pass
        await c.message.edit_reply_markup(reply_markup=kb_admin_actions(order_id))

@router.message(AdminStates.waiting_message)
async def on_admin_send_message(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id, ADMIN_IDS):
        await m.answer("دسترسی ادمین ندارید.")
        return
    data = await state.get_data()
    customer_id = data.get("customer_id")
    order_id = data.get("order_id")
    if not customer_id or not order_id:
        await m.answer("جلسه پیام ادمین یافت نشد.")
        await state.clear()
        return
    try:
        await m.bot.send_message(
            customer_id,
            f"📬 پیام از پشتیبانی درباره سفارش #{order_id}:\n\n{m.text}",
        )
        await m.answer("پیام برای مشتری ارسال شد.")
    except Exception:
        await m.answer("ارسال پیام ناموفق بود.")
    await state.clear()
