from __future__ import annotations

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from typing import Any, Awaitable, Callable, Dict

from .db import is_user_blocked


class BlockedUserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user and is_user_blocked(user.id):
            if isinstance(event, Message):
                await event.answer("⛔️ دسترسی شما به خدمات ربات محدود شده است. لطفاً با پشتیبانی تماس بگیرید.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔️ دسترسی شما محدود شده است.", show_alert=True)
            return None
        return await handler(event, data)


__all__ = ["BlockedUserMiddleware"]
