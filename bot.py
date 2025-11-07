# bot.py
import asyncio
import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.db import ensure_order_id_floor

# ------------------ Config & Globals ------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
DB_PATH = os.getenv("DB_PATH", "data.db")

BUSINESS_NAME = os.getenv("BUSINESS_NAME", "فروشگاه پرمیوم")
CARD_NUMBER = os.getenv("CARD_NUMBER", "---- ---- ---- ----")
CARD_NAME = os.getenv("CARD_NAME", "نام دارنده کارت")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "")

SLA_HOURS_MIN = int(os.getenv("SLA_HOURS_MIN", "1"))
SLA_HOURS_MAX = int(os.getenv("SLA_HOURS_MAX", "4"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s"
)

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
rt = Router()
dp.include_router(rt)

# ------------------ Plans (Edit from .env) ------------------
_PLANS_META = [
    ("svcA_1m", "PLAN_SVCA_1M", "سرویس A — ۱ ماهه", "300000"),
    ("svcA_3m", "PLAN_SVCA_3M", "سرویس A — ۳ ماهه", "800000"),
    ("svcB_1m", "PLAN_SVCB_1M", "سرویس B — ۱ ماهه", "250000"),
]


def _plan_from_env(plan_id: str, env_prefix: str, default_title: str, default_price: str) -> dict:
    title = os.getenv(f"{env_prefix}_TITLE", default_title)
    price = os.getenv(f"{env_prefix}_PRICE", default_price)
    return {"id": plan_id, "title": title, "price": price}


PLANS = [
    _plan_from_env(plan_id, env_prefix, default_title, default_price)
    for plan_id, env_prefix, default_title, default_price in _PLANS_META
]
CURRENCY = os.getenv("CURRENCY", "تومان")  # فقط نمایش

# ------------------ DB helpers ------------------
def init_db():
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            plan_id TEXT,
            plan_title TEXT,
            price TEXT,
            receipt_file_id TEXT,
            receipt_text TEXT,
            status TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """)
        con.commit()

def db_execute(query, params=(), *, fetchone=False, fetchall=False, return_lastrowid=False):
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute(query, params)
        if return_lastrowid:
            con.commit()
            return cur.lastrowid
        if fetchone:
            return cur.fetchone()
        if fetchall:
            return cur.fetchall()
        con.commit()
        return None

# ------------------ Keyboards ------------------
def kb_home():
    b = InlineKeyboardBuilder()
    b.button(text="🛒 خرید اکانت", callback_data="buy")
    b.button(text="👤 حساب کاربری", callback_data="account")
    b.button(text="ℹ️ راهنما", callback_data="help")
    b.adjust(1)
    return b.as_markup()

def kb_plans():
    b = InlineKeyboardBuilder()
    for p in PLANS:
        b.button(
            text=f"{p['title']} — {p['price']} {CURRENCY}",
            callback_data=f"plan:{p['id']}"
        )
    b.button(text="🔙 بازگشت", callback_data="home")
    b.adjust(1)
    return b.as_markup()

def kb_admin_actions(order_id: int):
    rows = [
        [
            InlineKeyboardButton(text="✅ تأیید پرداخت", callback_data=f"admin:approve:{order_id}"),
            InlineKeyboardButton(text="❌ رد پرداخت", callback_data=f"admin:reject:{order_id}")
        ],
        [InlineKeyboardButton(text="📦 تحویل شد", callback_data=f"admin:delivered:{order_id}")],
        [InlineKeyboardButton(text="✉️ پیام به مشتری", callback_data=f"admin:msg:{order_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_account():
    b = InlineKeyboardBuilder()
    b.button(text="🔄 بروزرسانی", callback_data="account_refresh")
    b.button(text="✉️ پشتیبانی", callback_data="support")
    b.button(text="🔙 بازگشت", callback_data="home")
    b.adjust(2, 1)
    return b.as_markup()

# ------------------ States ------------------
class BuyStates(StatesGroup):
    waiting_receipt = State()

class AdminStates(StatesGroup):
    waiting_message = State()

# ------------------ Utils ------------------
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def mention(u):
    name = (u.first_name or "کاربر")
    return f'<a href="tg://user?id={u.id}">{name}</a>'

WELCOME_TEXT = (
    f"به <b>{BUSINESS_NAME}</b> خوش آمدید 👋\n\n"
    "از این ربات می‌توانید اکانت‌های پرمیوم را به‌صورت قانونی تهیه کنید.\n"
    f"⏱ زمان تحویل: بین <b>{SLA_HOURS_MIN} تا {SLA_HOURS_MAX} ساعت</b> پس از تأیید پرداخت.\n\n"
    "\n" + "\n" "ساعات کاری 9 صبح تا 9 شب"
    "یکی از گزینه‌های زیر را انتخاب کنید:"
)

HELP_TEXT = (
    "🔹 فرایند خرید:\n"
    "1) از «🛒 خرید اکانت» پلن را انتخاب کنید.\n"
    f"2) مبلغ را به کارت زیر واریز کنید و رسید را در همین چت ارسال کنید:\n"
    f"   • شماره کارت: <code>{CARD_NUMBER}</code>\n"
    f"   • به نام: {CARD_NAME}\n"
    f"3) سفارش شما بررسی می‌شود و طی {SLA_HOURS_MIN}–{SLA_HOURS_MAX} ساعت تحویل می‌گردد.\n\n"
    "🔹 پشتیبانی: روی دکمه «پشتیبانی» در صفحه حساب کاربری بزنید."
)

def fmt_order_row(row):
    created = row["created_at"].replace("T", " ")
    return (
        f"– #{row['id']} | {row['plan_title']} | {row['price']} {CURRENCY}\n"
        f"  وضعیت: <b>{row['status']}</b> | {created}"
    )

# ------------------ Handlers: Public ------------------
@rt.message(CommandStart())
async def on_start(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(WELCOME_TEXT, reply_markup=kb_home())

@rt.message(Command("help"))
async def on_help(m: Message):
    await m.answer(HELP_TEXT, reply_markup=kb_home())

@rt.callback_query(F.data == "home")
async def on_home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text(WELCOME_TEXT, reply_markup=kb_home())
    await c.answer()

@rt.callback_query(F.data == "help")
async def on_help_cb(c: CallbackQuery):
    await c.message.edit_text(HELP_TEXT, reply_markup=kb_home())
    await c.answer()

@rt.callback_query(F.data == "buy")
async def on_buy(c: CallbackQuery):
    await c.message.edit_text("لطفاً پلن موردنظر را انتخاب کنید:", reply_markup=kb_plans())
    await c.answer()

@rt.callback_query(F.data.startswith("plan:"))
async def on_plan_selected(c: CallbackQuery, state: FSMContext):
    plan_id = c.data.split(":", 1)[1]
    plan = next((p for p in PLANS if p["id"] == plan_id), None)
    if not plan:
        await c.answer("پلن یافت نشد!", show_alert=True)
        return
    await state.update_data(plan_id=plan["id"], plan_title=plan["title"], price=plan["price"])
    text = (
        f"انتخاب شما: <b>{plan['title']}</b> — {plan['price']} {CURRENCY}\n\n"
        "✅ حالا مبلغ را کارت‌به‌کارت کنید و رسید را در همین چت بفرستید.\n"
        f"• شماره کارت: <code>{CARD_NUMBER}</code>\n"
        f"• به نام: {CARD_NAME}\n\n"
        "می‌توانید رسید را به‌صورت <b>عکس</b>، <b>فایل</b> یا <b>متنِ اطلاعات تراکنش</b> ارسال کنید."
    )
    await c.message.edit_text(text)
    await state.set_state(BuyStates.waiting_receipt)
    await c.answer()

@rt.message(BuyStates.waiting_receipt)
async def on_receipt(m: Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("plan_id"):
        await m.answer("جلسه خرید یافت نشد. دوباره از «🛒 خرید اکانت» شروع کنید.")
        await state.clear()
        return

    receipt_file_id = None
    receipt_text = None

    if m.photo:
        receipt_file_id = m.photo[-1].file_id
    elif m.document:
        receipt_file_id = m.document.file_id
    elif m.text:
        receipt_text = m.text
    else:
        await m.answer("فرمت رسید نامعتبر است. لطفاً عکس، فایل یا متن ارسال کنید.")
        return

    now = datetime.now().isoformat(timespec="seconds")
    order_id = db_execute(
        """
        INSERT INTO orders (
            user_id, username, first_name,
            plan_id, plan_title, price,
            receipt_file_id, receipt_text,
            status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            m.from_user.id, m.from_user.username, m.from_user.first_name or "",
            data["plan_id"], data["plan_title"], data["price"],
            receipt_file_id, receipt_text,
            "در انتظار تایید پرداخت", now, now
        ),
        return_lastrowid=True
    )

    # پیام به کاربر
    msg = (
        f"✅ سفارش شما ثبت شد.\n\n"
        f"شناسه سفارش: <b>#{order_id}</b>\n"
        f"پلن: <b>{data['plan_title']}</b>\n"
        f"مبلغ: <b>{data['price']} {CURRENCY}</b>\n"
        f"وضعیت فعلی: <b>در انتظار تایید پرداخت</b>\n\n"
        f"⏱ زمان تحویل: {SLA_HOURS_MIN} تا {SLA_HOURS_MAX} ساعت پس از تأیید."
    )
    await m.answer(msg, reply_markup=kb_home())
    await state.clear()

    # اعلان برای ادمین‌ها
    admin_caption = (
        f"🆕 سفارش جدید #{order_id}\n"
        f"مشتری: {mention(m.from_user)} (@{m.from_user.username or '—'})\n"
        f"پلن: {data['plan_title']} | مبلغ: {data['price']} {CURRENCY}\n"
        f"زمان: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"وضعیت: در انتظار تایید پرداخت"
    )
    for admin_id in ADMIN_IDS:
        try:
            if receipt_file_id:
                await bot.send_photo(admin_id, receipt_file_id, caption=admin_caption, reply_markup=kb_admin_actions(order_id))
            else:
                await bot.send_message(admin_id, admin_caption + f"\n\n🧾 متن رسید:\n{receipt_text}", reply_markup=kb_admin_actions(order_id))
        except Exception as e:
            logging.exception(f"Failed to notify admin {admin_id}: {e}")

@rt.callback_query(F.data == "account")
async def on_account(c: CallbackQuery):
    rows = db_execute(
        "SELECT id, plan_title, price, status, created_at FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 5",
        (c.from_user.id,), fetchall=True
    )
    if not rows:
        await c.message.edit_text("هنوز سفارشی ثبت نکرده‌اید.", reply_markup=kb_home())
        await c.answer()
        return

    text = "آخرین سفارش‌های شما:\n\n" + "\n".join(fmt_order_row(r) for r in rows)
    await c.message.edit_text(text, reply_markup=kb_account())
    await c.answer()

@rt.callback_query(F.data == "account_refresh")
async def on_account_refresh(c: CallbackQuery):
    await on_account(c)

@rt.callback_query(F.data == "support")
async def on_support(c: CallbackQuery):
    if SUPPORT_USERNAME:
        await c.message.answer(f"برای پشتیبانی کلیک کنید: @{SUPPORT_USERNAME}")
    else:
        await c.message.answer("پشتیبانی هنوز تنظیم نشده است. (SUPPORT_USERNAME را در .env تنظیم کنید)")
    await c.answer()

# ------------------ Handlers: Admin ------------------
@rt.message(Command("admin"))
async def on_admin_cmd(m: Message):
    if not is_admin(m.from_user.id):
        await m.answer("دسترسی ادمین ندارید.")
        return
    # خلاصه سریع
    pending = db_execute("SELECT COUNT(*) AS c FROM orders WHERE status='در انتظار تایید پرداخت'", fetchone=True)["c"]
    text = (
        "👮‍♂️ پنل ادمین (ساده)\n"
        f"سفارش‌های منتظر تایید پرداخت: <b>{pending}</b>\n\n"
        "– برای هر سفارش جدید، اعلان دریافت می‌کنید و با دکمه‌های زیر پیام می‌گیرید.\n"
        "– دستورات کاربردی:\n"
        "/pending - لیست 10 سفارش منتظر تایید\n"
        "/search <id> - نمایش یک سفارش"
    )
    await m.answer(text)

@rt.message(Command("pending"))
async def on_admin_pending(m: Message):
    if not is_admin(m.from_user.id):
        await m.answer("دسترسی ادمین ندارید.")
        return
    rows = db_execute(
        "SELECT id, plan_title, price, status, created_at FROM orders WHERE status='در انتظار تایید پرداخت' ORDER BY id DESC LIMIT 10",
        fetchall=True
    )
    if not rows:
        await m.answer("هیچ سفارش منتظر تایید وجود ندارد.")
        return
    text = "🟡 سفارش‌های منتظر تایید:\n\n" + "\n".join(fmt_order_row(r) for r in rows)
    await m.answer(text)

@rt.message(Command("search"))
async def on_admin_search(m: Message):
    if not is_admin(m.from_user.id):
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

@rt.callback_query(F.data.startswith("admin:"))
async def on_admin_action(c: CallbackQuery, state: FSMContext):
    if not is_admin(c.from_user.id):
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
        new_status = "تایید شد (در صف تحویل)"
    elif action == "reject":
        new_status = "رد شد (نیاز به پیگیری)"
    elif action == "delivered":
        new_status = "تحویل شد"

    if new_status:
        db_execute("UPDATE orders SET status=?, updated_at=? WHERE id=?",
                   (new_status, datetime.now().isoformat(timespec="seconds"), order_id))
        await c.answer("وضعیت به‌روزرسانی شد.")
        # اطلاع به مشتری
        try:
            await bot.send_message(
                row["user_id"],
                f"وضعیت سفارش #{order_id} به «<b>{new_status}</b>» تغییر کرد."
            )
        except Exception as e:
            logging.exception(f"Notify customer failed: {e}")
        # بازآفرینی دکمه‌ها
        await c.message.edit_reply_markup(reply_markup=kb_admin_actions(order_id))
        return

@rt.message(AdminStates.waiting_message)
async def on_admin_send_message(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        await m.answer("دسترسی ادمین ندارید.")
        return
    data = await state.get_data()
    customer_id = data.get("customer_id")
    order_id = data.get("order_id")
    if not customer_id or not order_id:
        await m.answer("جلسه پیام ادمین یافت نشد.")
        await state.clear()
        return
    # ارسال پیام به مشتری
    try:
        await bot.send_message(
            customer_id,
            f"📬 پیام از پشتیبانی درباره سفارش #{order_id}:\n\n{m.text}"
        )
        await m.answer("پیام برای مشتری ارسال شد.")
    except Exception as e:
        logging.exception(f"Admin message relay failed: {e}")
        await m.answer("ارسال پیام ناموفق بود.")
    await state.clear()

# ------------------ Main ------------------
async def main():
    init_db()
    logging.info("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped.")
