from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from . import router
from ..db import ensure_user
from ..keyboards import reply_main
from .channel_gate import ensure_member_for_message
from ..texts import HELP_TEXT, WELCOME_TEXT


@router.message(CommandStart())
async def on_start(message: Message, state: FSMContext) -> None:
    ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name or "",
    )
    if not await ensure_member_for_message(message):
        await state.clear()
        return
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=reply_main())


@router.message(Command("help"))
async def on_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=reply_main())
