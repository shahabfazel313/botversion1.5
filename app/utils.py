import re

def is_admin(uid: int, admin_ids: list[int]) -> bool:
    return uid in admin_ids

def mention(u) -> str:
    name = (u.first_name or "کاربر")
    return f'<a href="tg://user?id={u.id}">{name}</a>'

def is_valid_email(s: str) -> bool:
    if not s: return False
    return re.match(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", s) is not None

def is_valid_tg_id(s: str) -> bool:
    if not s: return False
    if s.startswith("@"): return False
    # حروف/عدد/خط‌زیر/نقطه، حداقل 5
    return re.match(r"^[A-Za-z0-9_.]{5,}$", s) is not None
