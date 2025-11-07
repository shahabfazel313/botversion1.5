import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand, BotCommandScopeDefault, MenuButtonCommands
from .config import BOT_TOKEN, DEFAULT_BOT_PROPS
from .db import init_db, expire_orders_and_refund
from .public import router as public_router
from .admin import router as admin_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")

async def setup_bot_menu(bot: Bot):
    # دستورات (کامندها) که در دکمهٔ Menu نمایش داده می‌شود
    commands = [
        BotCommand(command="start", description="شروع ربات"),
        BotCommand(command="products", description="محصولات و خدمات"),
        BotCommand(command="cart", description="سبد خرید"),
        BotCommand(command="profile", description="اطلاعات کاربری"),
        BotCommand(command="support", description="پشتیبانی"),
        BotCommand(command="help", description="راهنما"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    # دکمهٔ Menu را روی نمایشِ همین کامندها می‌گذاریم
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

async def expire_loop(bot: Bot):
    while True:
        try:
            expired = expire_orders_and_refund()
            for o in expired:
                uid = o["user_id"]; oid = o["id"]
                try:
                    await bot.send_message(uid, f"⏰ سفارش #{oid} به دلیل عدم پرداخت در ۱۵ دقیقه منقضی شد.")
                except Exception:
                    pass
            if expired:
                logging.info("Expired orders: %s", [e["id"] for e in expired])
        except Exception as e:
            logging.exception("expire_loop error: %s", e)
        await asyncio.sleep(30)

async def main():
    init_db()
    bot = Bot(BOT_TOKEN, default=DEFAULT_BOT_PROPS)
    dp = Dispatcher()
    dp.include_router(public_router)
    dp.include_router(admin_router)

    # منو را ست کن
    await setup_bot_menu(bot)

    # تسک انقضا
    asyncio.create_task(expire_loop(bot))

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
