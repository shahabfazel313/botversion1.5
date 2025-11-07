from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv, set_key

ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT_DIR / ".env"
_ENV_FILE_MTIME: float | None = None


def _refresh_env(force: bool = False) -> None:
    """Reload .env values into the current process when the file changes."""

    global _ENV_FILE_MTIME
    try:
        mtime = ENV_FILE.stat().st_mtime
    except FileNotFoundError:
        mtime = None
    if force or _ENV_FILE_MTIME is None or mtime != _ENV_FILE_MTIME:
        load_dotenv(dotenv_path=str(ENV_FILE), override=True)
        _ENV_FILE_MTIME = mtime


@dataclass(frozen=True)
class VariantMeta:
    code: str
    group: str
    display_name: str
    button_label: str
    price_keys: tuple[str, ...]
    default_price: str
    availability_key: str
    default_available: bool
    unavailable_label: str | None = None


def _price_to_int(value: str) -> int:
    value = (value or "").strip()
    if value.isdigit():
        return int(value)
    try:
        digits = "".join(ch for ch in value if ch.isdigit())
        return int(digits) if digits else 0
    except Exception:
        return 0


def _env_value(keys: Sequence[str], default: str) -> str:
    for key in keys:
        value = os.getenv(key)
        if value not in (None, ""):
            return value
    return default


def _env_bool(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None or value == "":
        return default
    value = value.strip().lower()
    return value not in {"0", "false", "no", "off"}


_VARIANTS: dict[str, VariantMeta] = {
    "tg_premium_3m": VariantMeta(
        code="tg_premium_3m",
        group="tg_premium_3m",
        display_name="تلگرام پرمیوم 3 ماه",
        button_label="3 ماهه",
        price_keys=("PRICE_TG_PREMIUM_3M",),
        default_price="0",
        availability_key="AVAILABLE_TG_PREMIUM_3M",
        default_available=True,
    ),
    "tg_premium_6m": VariantMeta(
        code="tg_premium_6m",
        group="tg_premium_6m",
        display_name="تلگرام پرمیوم 6 ماه",
        button_label="6 ماهه",
        price_keys=("PRICE_TG_PREMIUM_6M",),
        default_price="0",
        availability_key="AVAILABLE_TG_PREMIUM_6M",
        default_available=True,
    ),
    "tg_premium_12m": VariantMeta(
        code="tg_premium_12m",
        group="tg_premium_12m",
        display_name="تلگرام پرمیوم 12 ماه",
        button_label="12 ماهه",
        price_keys=("PRICE_TG_PREMIUM_12M",),
        default_price="0",
        availability_key="AVAILABLE_TG_PREMIUM_12M",
        default_available=True,
    ),
    "tg_ready_pre": VariantMeta(
        code="tg_ready_pre",
        group="tg_ready_pre",
        display_name="اکانت آماده تلگرام",
        button_label="اکانت از پیش ساخته‌شده",
        price_keys=("PRICE_TG_READY_PRE",),
        default_price="0",
        availability_key="AVAILABLE_TG_READY_PRE",
        default_available=True,
    ),
    "gpt_team_my": VariantMeta(
        code="gpt_team_my",
        group="gpt_team",
        display_name="اکانت ChatGPT Team (روی اکانت خودم)",
        button_label="روی اکانت خودم",
        price_keys=("PRICE_GPT_TEAM_MY", "PRICE_GPT_TEAM"),
        default_price="0",
        availability_key="AVAILABLE_GPT_TEAM_MY",
        default_available=True,
    ),
    "gpt_team_pre": VariantMeta(
        code="gpt_team_pre",
        group="gpt_team",
        display_name="اکانت ChatGPT Team (اکانت از پیش ساخته‌شده)",
        button_label="اکانت از پیش ساخته‌شده",
        price_keys=("PRICE_GPT_TEAM_PRE", "PRICE_GPT_TEAM"),
        default_price="0",
        availability_key="AVAILABLE_GPT_TEAM_PRE",
        default_available=True,
    ),
    "gpt_plus_my": VariantMeta(
        code="gpt_plus_my",
        group="gpt_plus",
        display_name="اکانت ChatGPT Plus (روی اکانت خودم)",
        button_label="روی اکانت خودم",
        price_keys=("PRICE_GPT_PLUS_MY", "PRICE_GPT_PLUS"),
        default_price="0",
        availability_key="AVAILABLE_GPT_PLUS_MY",
        default_available=True,
    ),
    "gpt_plus_pre": VariantMeta(
        code="gpt_plus_pre",
        group="gpt_plus",
        display_name="اکانت ChatGPT Plus (اکانت از پیش ساخته‌شده)",
        button_label="اکانت از پیش ساخته‌شده",
        price_keys=("PRICE_GPT_PLUS_PRE", "PRICE_GPT_PLUS"),
        default_price="0",
        availability_key="AVAILABLE_GPT_PLUS_PRE",
        default_available=True,
    ),
    "google_pro_my": VariantMeta(
        code="google_pro_my",
        group="google_pro",
        display_name="اکانت Google AI Pro (روی اکانت خودم)",
        button_label="روی اکانت خودم",
        price_keys=("PRICE_GOOGLE_PRO_MY", "PRICE_GOOGLE_PRO"),
        default_price="0",
        availability_key="AVAILABLE_GOOGLE_PRO_MY",
        default_available=False,
        unavailable_label="روی اکانت خودم (به‌زودی)",
    ),
    "google_pro_pre": VariantMeta(
        code="google_pro_pre",
        group="google_pro",
        display_name="اکانت Google AI Pro (اکانت از پیش ساخته‌شده)",
        button_label="اکانت از پیش ساخته‌شده",
        price_keys=("PRICE_GOOGLE_PRO_PRE", "PRICE_GOOGLE_PRO"),
        default_price="0",
        availability_key="AVAILABLE_GOOGLE_PRO_PRE",
        default_available=True,
    ),
}


_ADMIN_ROWS: list[tuple[str, list[str]]] = [
    ("tg_premium_3m", ["tg_premium_3m"]),
    ("tg_premium_6m", ["tg_premium_6m"]),
    ("tg_premium_12m", ["tg_premium_12m"]),
    ("tg_ready_pre", ["tg_ready_pre"]),
    ("gpt_team", ["gpt_team_my", "gpt_team_pre"]),
    ("gpt_plus", ["gpt_plus_my", "gpt_plus_pre"]),
    ("google_pro", ["google_pro_my", "google_pro_pre"]),
]


_ADMIN_TITLES: dict[str, str] = {
    "tg_premium_3m": "تلگرام پرمیوم 3 ماه",
    "tg_premium_6m": "تلگرام پرمیوم 6 ماهه",
    "tg_premium_12m": "تلگرام پرمیوم 12 ماهه",
    "tg_ready_pre": "اکانت آماده تلگرام",
    "gpt_team": "اکانت ChatGPT Team",
    "gpt_plus": "اکانت ChatGPT Plus",
    "google_pro": "اکانت Google AI Pro",
}


def get_variant(variant_code: str) -> dict[str, object]:
    _refresh_env()
    if variant_code not in _VARIANTS:
        raise KeyError(f"Unknown product variant: {variant_code}")
    meta = _VARIANTS[variant_code]
    price_str = _env_value(meta.price_keys, meta.default_price)
    amount = _price_to_int(price_str)
    available = _env_bool(meta.availability_key, meta.default_available)
    unavailable_label = meta.unavailable_label or f"{meta.button_label} (ناموجود)"
    return {
        "code": meta.code,
        "group": meta.group,
        "display_name": meta.display_name,
        "button_label": meta.button_label,
        "price": price_str,
        "amount": amount,
        "available": available,
        "availability_key": meta.availability_key,
        "price_key": meta.price_keys[0],
        "unavailable_label": unavailable_label,
    }


def get_variant_price_amount(variant_code: str) -> int:
    return int(get_variant(variant_code)["amount"])


def get_variant_price_text(variant_code: str) -> str:
    return str(get_variant(variant_code)["price"])


def is_variant_available(variant_code: str) -> bool:
    return bool(get_variant(variant_code)["available"])


def set_variant_settings(variant_code: str, price: str, available: bool) -> None:
    data = get_variant(variant_code)
    sanitized = str(_price_to_int(price))
    price_key = data["price_key"]
    availability_key = data["availability_key"]
    set_key(str(ENV_FILE), price_key, sanitized)
    os.environ[price_key] = sanitized
    set_key(str(ENV_FILE), availability_key, "1" if available else "0")
    os.environ[availability_key] = "1" if available else "0"
    _refresh_env(force=True)


def list_admin_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for group_code, variant_codes in _ADMIN_ROWS:
        title = _ADMIN_TITLES.get(group_code, group_code)
        variants = [get_variant(code) for code in variant_codes]
        rows.append({"code": group_code, "title": title, "variants": variants})
    return rows


AI_VARIANT_MAP: dict[str, dict[str, str]] = {
    "team": {"my": "gpt_team_my", "pre": "gpt_team_pre"},
    "plus": {"my": "gpt_plus_my", "pre": "gpt_plus_pre"},
    "google": {"my": "google_pro_my", "pre": "google_pro_pre"},
}


TG_PREMIUM_VARIANTS: dict[str, str] = {
    "3m": "tg_premium_3m",
    "6m": "tg_premium_6m",
    "12m": "tg_premium_12m",
}


__all__ = [
    "AI_VARIANT_MAP",
    "TG_PREMIUM_VARIANTS",
    "get_variant",
    "get_variant_price_amount",
    "get_variant_price_text",
    "is_variant_available",
    "list_admin_rows",
    "set_variant_settings",
]
