from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.types import CallbackQuery, Message

from ..config import FORCE_JOIN_MESSAGE, REQUIRED_CHANNEL_ID, REQUIRED_CHANNEL_LINK
from ..keyboards import ik_force_join, reply_main

router = Router()


def _channel_target():
    if not REQUIRED_CHANNEL_ID:
        return None
    if REQUIRED_CHANNEL_ID.startswith("@"):
        return REQUIRED_CHANNEL_ID
    numeric = REQUIRED_CHANNEL_ID
    if numeric.startswith("-"):
        numeric = numeric[1:]
    if numeric.isdigit():
        try:
            return int(REQUIRED_CHANNEL_ID)
        except ValueError:
            return REQUIRED_CHANNEL_ID
    return REQUIRED_CHANNEL_ID


CHANNEL_TARGET = _channel_target()


def _join_url() -> str:
    if REQUIRED_CHANNEL_LINK:
        return REQUIRED_CHANNEL_LINK
    if isinstance(CHANNEL_TARGET, str) and CHANNEL_TARGET.startswith("@"):
        return f"https://t.me/{CHANNEL_TARGET[1:]}"
    return ""


async def _is_member(message_source, user_id: int) -> bool:
    if not CHANNEL_TARGET:
        return True
    try:
        member = await message_source.get_chat_member(CHANNEL_TARGET, user_id)
    except Exception:
        return False
    status = getattr(member, "status", None)
    return status in {
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.RESTRICTED,
    }


def _join_keyboard():
    return ik_force_join(_join_url())


async def ensure_member_for_message(message: Message) -> bool:
    if await _is_member(message.bot, message.from_user.id):
        return True
    await message.answer(FORCE_JOIN_MESSAGE, reply_markup=_join_keyboard())
    return False


async def ensure_member_for_callback(callback: CallbackQuery) -> bool:
    if await _is_member(callback.message.bot, callback.from_user.id):
        return True
    await callback.answer("برای استفاده از ربات ابتدا در کانال عضو شوید.", show_alert=True)
    await callback.message.answer(FORCE_JOIN_MESSAGE, reply_markup=_join_keyboard())
    return False


@router.callback_query(F.data == "forcejoin:check")
async def on_force_join_check(callback: CallbackQuery) -> None:
    if await _is_member(callback.message.bot, callback.from_user.id):
        await callback.answer("عضویت تایید شد ✅")
        await callback.message.answer(
            "✅ عضویت شما تایید شد. خوش آمدید!",
            reply_markup=reply_main(),
        )
    else:
        await callback.answer("شما هنوز عضو نشده‌اید.", show_alert=True)
        await callback.message.answer(
            "شما هنوز عضو کانال نشده‌اید. لطفاً ابتدا عضو شوید و مجدداً امتحان کنید.",
            reply_markup=_join_keyboard(),
        )


__all__ = [
    "router",
    "ensure_member_for_message",
    "ensure_member_for_callback",
]