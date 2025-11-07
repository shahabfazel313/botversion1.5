from aiogram import Router

router = Router()

# Import handler modules so that they register callbacks on the shared router.
from . import start  # noqa: F401
from . import menu  # noqa: F401
from . import shop_ai  # noqa: F401
from . import shop_tg  # noqa: F401
from . import services  # noqa: F401
from . import verification  # noqa: F401
from . import cart  # noqa: F401
from . import history  # noqa: F401
from . import profile  # noqa: F401
from . import channel_gate  # noqa: F401

from ..middlewares import BlockedUserMiddleware

router.include_router(channel_gate.router)

router.message.outer_middleware(BlockedUserMiddleware())
router.callback_query.outer_middleware(BlockedUserMiddleware())

__all__ = ["router"]
