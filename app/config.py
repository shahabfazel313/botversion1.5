import os
from dotenv import load_dotenv
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

load_dotenv()

# --- Telegram & App config ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
DB_PATH = os.getenv("DB_PATH", "data.db")

BUSINESS_NAME = os.getenv("BUSINESS_NAME", "فروشگاه پرمیوم")
CARD_NUMBER = os.getenv("CARD_NUMBER", "---- ---- ---- ----")
CARD_NAME = os.getenv("CARD_NAME", "نام دارنده کارت")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "")

SLA_HOURS_MIN = int(os.getenv("SLA_HOURS_MIN", "1"))
SLA_HOURS_MAX = int(os.getenv("SLA_HOURS_MAX", "4"))
PAYMENT_TIMEOUT_MIN = int(os.getenv("PAYMENT_TIMEOUT_MIN", "15"))
ORDER_ID_MIN_VALUE = int(os.getenv("ORDER_ID_MIN_VALUE", "0"))

REQUIRED_CHANNEL_ID = os.getenv("REQUIRED_CHANNEL_ID", "").strip()
REQUIRED_CHANNEL_LINK = os.getenv("REQUIRED_CHANNEL_LINK", "").strip()
FORCE_JOIN_MESSAGE = os.getenv(
    "FORCE_JOIN_MESSAGE",
    "برای استفاده از امکانات ربات ابتدا در کانال زیر عضو شوید.",
)

# --- Default bot properties (aiogram 3.7+) ---
DEFAULT_BOT_PROPS = DefaultBotProperties(parse_mode=ParseMode.HTML)

# --- Plans (قدیمی؛ برای سازگاری) ---
_LEGACY_PLANS_META = [
    ("svcA_1m", "PLAN_SVCA_1M", "سرویس A — ۱ ماهه", "300000"),
    ("svcA_3m", "PLAN_SVCA_3M", "سرویس A — ۳ ماهه", "800000"),
    ("svcB_1m", "PLAN_SVCB_1M", "سرویس B — ۱ ماهه", "250000"),
]


def _plan_from_env(plan_id: str, env_prefix: str, default_title: str, default_price: str) -> dict:
    """Build a plan definition using environment overrides."""

    title = os.getenv(f"{env_prefix}_TITLE", default_title)
    price = os.getenv(f"{env_prefix}_PRICE", default_price)
    return {"id": plan_id, "title": title, "price": price}


PLANS = [
    _plan_from_env(plan_id, env_prefix, default_title, default_price)
    for plan_id, env_prefix, default_title, default_price in _LEGACY_PLANS_META
]
CURRENCY = os.getenv("CURRENCY", "تومان")

# ====== محصولات و خدمات ======
AI_PLANS = {
    "gpt_team": {
        "title": "اکانت ChatGPT Team",
        "desc": os.getenv("DESC_GPT_TEAM", "اکانت رسمی با دسترسی به GPT-5، GPT-5 Pro، GPT-5 Thinking، GPT-4o ، و ابزارهای حرفه‌ای مثل Data Analysis، Voice/Realtime و تولید تصویر ""\n" + "\n""اکانت اخصاصی فقط برای شما""\n" + "\n""قیمت با تخفیف ویژه فقط و فقط 500.000 تومان"),
        "photo_id": os.getenv("PHOTO_GPT_TEAM", ""),
    },
    "gpt_plus": {
        "title": "اکانت ChatGPT Plus",
        "desc": os.getenv("DESC_GPT_PLUS", "دسترسی سریع‌تر و مدل‌های پیشرفته.""\n" + "\n""اکانت اخصاصی فقط برای شما"),
        "photo_id": os.getenv("PHOTO_GPT_PLUS", ""),
    },
    "google_pro": {
        "title": "اکانت Google AI Pro",
        "desc": os.getenv("DESC_GOOGLE_PRO", "دسترسی به مدل Gemini 2.5 Pro با قابلیت‌های پیشرفته در تحلیل و تولید محتوا""\n" + "\n""امکان استفاده از ابزارهای ویدیوسازی مانند Veo 2 و Flow""\n" + "\n""اکانت اخصاصی فقط برای شما"),
        "photo_id": os.getenv("PHOTO_GOOGLE_PRO", ""),
    },
}

TG_READY_PREBUILT = {
    "title": "اکانت تلگرام از پیش ساخته‌شده",
    "desc": os.getenv("DESC_TG_READY_PRE", "اکانت آماده استفاده،اختصاصی ، تحویل سریع."),
    "photo_id": os.getenv("PHOTO_TG_READY_PRE", ""),
}

BUILD_BOT_DESC = os.getenv(
    "DESC_BUILD_BOT",
    "طراحی و پیاده‌سازی ربات تلگرام اختصاصی متناسب با نیاز شما.",
)
BUILD_BOT_BASE_PRICE = os.getenv("PRICE_BUILD_BOT_BASE", "0")

OTHER_SERVICES_DESC = os.getenv(
    "TEXT_OTHER_SERVICES",
    "اگر محصول یا خدمت مد نظر خود را پیدا نکردید، درخواستتان را ثبت کنید تا بررسی کنیم.",
)

# ---- Admin Web Panel ----
ADMIN_WEB_USER = os.getenv("ADMIN_WEB_USER", "admin")
ADMIN_WEB_PASS = os.getenv("ADMIN_WEB_PASS", "admin")
ADMIN_WEB_BIND = os.getenv("ADMIN_WEB_BIND", "127.0.0.1")
ADMIN_WEB_PORT = int(os.getenv("ADMIN_WEB_PORT", "8080"))
ADMIN_WEB_SECRET = os.getenv("ADMIN_WEB_SECRET", BOT_TOKEN[::-1] + "_secret")
