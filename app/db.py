import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from typing import Any, Iterable
from .config import DB_PATH, ORDER_ID_MIN_VALUE, PAYMENT_TIMEOUT_MIN

def _connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def db_execute(
    sql,
    params=(),
    *,
    fetchone=False,
    fetchall=False,
    return_lastrowid=False,
    commit: bool | None = None,
):
    with closing(_connect()) as con:
        cur = con.cursor()
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.execute(sql, params)
        do_commit = True if commit is None else bool(commit)
        if do_commit:
            con.commit()
        if return_lastrowid:
            return cur.lastrowid
        if fetchone:
            r = cur.fetchone()
            return dict(r) if r else None
        if fetchall:
            return [dict(x) for x in cur.fetchall()]
    return None


def _ensure_order_sequence_min(min_order_id: int) -> None:
    """Ensure that the next order ID is at least ``min_order_id``."""

    try:
        target = int(min_order_id or 0)
    except (TypeError, ValueError):
        target = 0
    if target <= 0:
        return

    target_seq = target - 1
    with closing(_connect()) as con:
        cur = con.cursor()
        cur.execute("SELECT IFNULL(MAX(id), 0) FROM orders")
        current_max = cur.fetchone()[0] or 0
        if current_max >= target:
            return
        try:
            cur.execute("SELECT seq FROM sqlite_sequence WHERE name='orders'")
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO sqlite_sequence(name, seq) VALUES(?, ?)",
                    ("orders", target_seq),
                )
            else:
                cur.execute(
                    "UPDATE sqlite_sequence SET seq=? WHERE name='orders'",
                    (target_seq,),
                )
            con.commit()
        except sqlite3.OperationalError:
            # sqlite_sequence may not exist yet (e.g., fresh database with no inserts)
            # In such case, inserting a dummy row and deleting it establishes the sequence.
            cur.execute(
                "INSERT INTO orders(id) VALUES(?)",
                (target_seq,),
            )
            con.commit()
            cur.execute("DELETE FROM orders WHERE id=?", (target_seq,))
            con.commit()


def ensure_order_id_floor(min_order_id: int | None = None) -> None:
    """Public helper to enforce the minimum order identifier."""

    if min_order_id is None:
        min_order_id = ORDER_ID_MIN_VALUE
    _ensure_order_sequence_min(min_order_id)
            
def _table_exists(con, name):
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None

def _col_exists(con, table, col):
    cur = con.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    return col in cols

def init_db():
    with closing(_connect()) as con:
        cur = con.cursor()
        # users
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT, first_name TEXT,
            wallet_balance INTEGER DEFAULT 0,
            ref_by INTEGER, ref_count INTEGER DEFAULT 0,
            earnings_total INTEGER DEFAULT 0,
            created_at TEXT, updated_at TEXT
        );
        """)
        # orders (افزودن ستون‌ها اگر نبودند)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, username TEXT, first_name TEXT,
            plan_id TEXT, plan_title TEXT, price TEXT,
            receipt_file_id TEXT, receipt_text TEXT,
            status TEXT, created_at TEXT, updated_at TEXT
        );
        """)
        # service messages (requests sent from bot)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS service_messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                first_name TEXT,
                category TEXT,
                message_text TEXT,
                attachment_file_id TEXT,
                created_at TEXT,
                updated_at TEXT,
                is_resolved INTEGER DEFAULT 0
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_service_messages_category ON service_messages(category);"
        )

        # ارتقا
        add_cols = [
            ("orders", "service_category", "TEXT"),
            ("orders", "service_code", "TEXT"),
            ("orders", "account_mode", "TEXT"),
            ("orders", "customer_email", "TEXT"),
            ("orders", "customer_secret_encrypted", "TEXT"),
            ("orders", "amount_total", "INTEGER"),
            ("orders", "currency", "TEXT"),
            ("orders", "payment_type", "TEXT"),
            ("orders", "wallet_used_amount", "INTEGER DEFAULT 0"),
            ("orders", "wallet_reserved_amount", "INTEGER DEFAULT 0"),
            ("orders", "await_deadline", "TEXT"),
            ("orders", "notes", "TEXT"),
            ("orders", "customer_message", "TEXT"),
            ("orders", "manager_note", "TEXT"),
            ("orders", "internal_cost", "INTEGER DEFAULT 0"),
            ("orders", "net_revenue", "INTEGER DEFAULT 0"),
            ("users", "contact_phone", "TEXT"),
            ("users", "contact_verified", "INTEGER DEFAULT 0"),
            ("users", "contact_shared_at", "TEXT"),
            ("users", "is_blocked", "INTEGER DEFAULT 0"),
            ("service_messages", "updated_at", "TEXT"),
            ("coupons", "is_active", "INTEGER DEFAULT 1"),
        ]
        for t, c, typ in add_cols:
            if _table_exists(con, t) and not _col_exists(con, t, c):
                cur.execute(f"ALTER TABLE {t} ADD COLUMN {c} {typ};")

        # wallet transactions
        cur.execute("""
        CREATE TABLE IF NOT EXISTS wallet_tx(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            order_id INTEGER,
            amount INTEGER NOT NULL,
            type TEXT NOT NULL, -- CREDIT/DEBIT/RESERVE/REFUND
            note TEXT,
            created_at TEXT
        );
        """)
        # ایندکس‌های مفید
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_wallet_user ON wallet_tx(user_id);")

        # order manager message history
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS order_manager_messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                user_id INTEGER,
                message_text TEXT,
                created_at TEXT
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_order_manager_messages_order ON order_manager_messages(order_id);"
        )

        # service message replies
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS service_message_replies(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_message_id INTEGER NOT NULL,
                user_id INTEGER,
                message_text TEXT,
                created_at TEXT
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_service_message_replies_msg ON service_message_replies(service_message_id);"
        )

        # direct messages from managers to users
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_manager_messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                message_text TEXT,
                created_at TEXT
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_manager_messages_user ON user_manager_messages(user_id);"
        )

        # coupons
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS coupons(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                amount INTEGER NOT NULL,
                usage_limit INTEGER NOT NULL,
                used_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                expires_at TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS coupon_redemptions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                coupon_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                redeemed_at TEXT,
                UNIQUE(coupon_id, user_id),
                FOREIGN KEY(coupon_id) REFERENCES coupons(id) ON DELETE CASCADE
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_coupon ON coupon_redemptions(coupon_id);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_user ON coupon_redemptions(user_id);"
        )
        con.commit()

def ensure_user(user_id: int, username: str, first_name: str):
    now = datetime.now().isoformat(timespec="seconds")
    row = db_execute("SELECT user_id FROM users WHERE user_id=?", (user_id,), fetchone=True)
    if not row:
        db_execute(
            "INSERT INTO users(user_id, username, first_name, created_at, updated_at) VALUES(?,?,?,?,?)",
            (user_id, username, first_name or "", now, now)
        )
    else:
        db_execute(
            "UPDATE users SET username=?, first_name=?, updated_at=? WHERE user_id=?",
            (username, first_name or "", now, user_id),
        )

def get_user(user_id: int):
    return db_execute("SELECT * FROM users WHERE user_id=?", (user_id,), fetchone=True)


def is_user_contact_verified(user_id: int) -> bool:
    user = get_user(user_id)
    if not user:
        return False
    return bool(int(user.get("contact_verified") or 0))


def set_user_contact_verified(user_id: int, phone_number: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    db_execute(
        "UPDATE users SET contact_phone=?, contact_verified=1, contact_shared_at=?, updated_at=? WHERE user_id=?",
        (phone_number or "", now, now, user_id),
    )

def change_wallet(user_id: int, delta: int, tx_type: str, note: str = "", order_id: int | None = None):
    # delta: مثبت => افزایش موجودی، منفی => کسر
    u = get_user(user_id)
    if not u:
        return False
    new_bal = int(u["wallet_balance"]) + int(delta)
    if new_bal < 0:
        return False
    now = datetime.now().isoformat(timespec="seconds")
    db_execute("UPDATE users SET wallet_balance=?, updated_at=? WHERE user_id=?", (new_bal, now, user_id))
    db_execute(
        "INSERT INTO wallet_tx(user_id, order_id, amount, type, note, created_at) VALUES(?,?,?,?,?,?)",
        (user_id, order_id, abs(delta), tx_type, note, now)
    )
    return True

def create_order(
    user,
    title: str,
    amount_total: int,
    currency: str,
    service_category: str,
    service_code: str,
    account_mode: str | None = None,
    customer_email: str | None = None,
    notes: str | None = None,
    customer_secret: str | None = None,
) -> int | None:
    if amount_total <= 0:
        return None
    now = datetime.now()
    ensure_order_id_floor()
    oid = db_execute("""
        INSERT INTO orders(
            user_id, username, first_name,
            plan_id, plan_title, price,
            status, created_at, updated_at,
            amount_total, currency, service_category, service_code,
            account_mode, customer_email, notes,
            customer_secret_encrypted
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        user["user_id"], user["username"], user["first_name"] or "",
        None, title, str(amount_total),
        "AWAITING_PAYMENT", now.isoformat(timespec="seconds"), now.isoformat(timespec="seconds"),
        amount_total, currency, service_category, service_code,
        account_mode or "", customer_email or "", notes or "",
        customer_secret or ""
    ), return_lastrowid=True)
    # تنظیم ددلاین ۱۵ دقیقه
    await_deadline = (now + timedelta(minutes=PAYMENT_TIMEOUT_MIN)).isoformat(timespec="seconds")
    db_execute("UPDATE orders SET await_deadline=? WHERE id=?", (await_deadline, oid))
    return oid

def set_order_status(order_id: int, status: str):
    db_execute("UPDATE orders SET status=?, updated_at=? WHERE id=?", (status, datetime.now().isoformat(timespec="seconds"), order_id))

def set_order_receipt(order_id: int, file_id: str | None, text: str | None):
    db_execute("UPDATE orders SET receipt_file_id=?, receipt_text=?, updated_at=? WHERE id=?",
               (file_id, text, datetime.now().isoformat(timespec="seconds"), order_id))

def set_order_payment_type(order_id: int, ptype: str):
    db_execute("UPDATE orders SET payment_type=?, updated_at=? WHERE id=?", (ptype, datetime.now().isoformat(timespec="seconds"), order_id))

def set_order_wallet_reserved(order_id: int, amount: int):
    db_execute("UPDATE orders SET wallet_reserved_amount=?, updated_at=? WHERE id=?", (amount, datetime.now().isoformat(timespec="seconds"), order_id))

def set_order_wallet_used(order_id: int, amount: int):
    db_execute("UPDATE orders SET wallet_used_amount=?, updated_at=? WHERE id=?", (amount, datetime.now().isoformat(timespec="seconds"), order_id))

def set_order_customer_message(order_id: int, message: str | None):
    db_execute(
        "UPDATE orders SET customer_message=?, updated_at=? WHERE id=?",
        (message or "", datetime.now().isoformat(timespec="seconds"), order_id),
    )

def set_order_manager_note(order_id: int, note: str | None):
    db_execute(
        "UPDATE orders SET manager_note=?, updated_at=? WHERE id=?",
        (note or "", datetime.now().isoformat(timespec="seconds"), order_id),
    )


def add_order_manager_message(order_id: int, user_id: int | None, message: str) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    return db_execute(
        """
        INSERT INTO order_manager_messages(order_id, user_id, message_text, created_at)
        VALUES(?,?,?,?)
        """,
        (order_id, user_id, message or "", now),
        return_lastrowid=True,
    )


def list_order_manager_messages(order_id: int, limit: int = 50) -> list[dict[str, Any]]:
    return db_execute(
        """
        SELECT * FROM order_manager_messages
        WHERE order_id=?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (order_id, limit),
        fetchall=True,
    )


def add_user_manager_message(user_id: int, message_text: str) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    return db_execute(
        """
        INSERT INTO user_manager_messages(user_id, message_text, created_at)
        VALUES(?,?,?)
        """,
        (user_id, message_text or "", now),
        return_lastrowid=True,
    )


def list_user_manager_messages(user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    return db_execute(
        """
        SELECT * FROM user_manager_messages
        WHERE user_id=?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (user_id, limit),
        fetchall=True,
    )


def set_order_financials(order_id: int, cost_amount: int) -> None:
    order = get_order(order_id)
    if not order:
        return
    try:
        cost = max(int(cost_amount or 0), 0)
    except (TypeError, ValueError):
        cost = 0
    total = int(order.get("amount_total") or order.get("price") or 0)
    net = max(total - cost, 0)
    db_execute(
        "UPDATE orders SET internal_cost=?, net_revenue=?, updated_at=? WHERE id=?",
        (cost, net, datetime.now().isoformat(timespec="seconds"), order_id),
    )

def set_order_customer_secret(order_id: int, secret: str | None):
    db_execute(
        "UPDATE orders SET customer_secret_encrypted=?, updated_at=? WHERE id=?",
        (secret or "", datetime.now().isoformat(timespec="seconds"), order_id),
    )

def get_order(order_id: int):
    return db_execute("SELECT * FROM orders WHERE id=?", (order_id,), fetchone=True)

def user_has_delivered_order(user_id: int) -> bool:
    row = db_execute(
        """
        SELECT 1 FROM orders
        WHERE user_id=? AND status IN ('DELIVERED','COMPLETED')
        LIMIT 1
        """,
        (user_id,),
        fetchone=True,
    )
    return bool(row)

def list_cart_orders(user_id: int):
    return db_execute("""
        SELECT * FROM orders
        WHERE user_id=? AND status='AWAITING_PAYMENT' AND (await_deadline IS NULL OR await_deadline > ?)
        ORDER BY await_deadline ASC
    """, (user_id, datetime.now().isoformat(timespec="seconds")), fetchall=True)

def expire_orders_and_refund():
    # سفارش‌های در انتظار پرداخت که ددلاین گذشته
    expired = db_execute("""
        SELECT * FROM orders
        WHERE status='AWAITING_PAYMENT' AND await_deadline IS NOT NULL AND await_deadline <= ?
    """, (datetime.now().isoformat(timespec="seconds"),), fetchall=True)
    for o in expired:
        rid = int(o["id"])
        reserved = int(o.get("wallet_reserved_amount") or 0)
        if reserved > 0:
            # refund
            change_wallet(o["user_id"], reserved, "REFUND", note=f"Expire order #{rid}", order_id=rid)
            set_order_wallet_reserved(rid, 0)
        set_order_status(rid, "EXPIRED")
    return expired


def create_coupon(code: str, amount: int, usage_limit: int, expires_at: str | None = None) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    normalized = (code or "").strip().upper()
    if not normalized:
        raise ValueError("Coupon code cannot be empty")
    return db_execute(
        """
        INSERT INTO coupons(code, amount, usage_limit, used_count, expires_at, created_at, updated_at, is_active)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (normalized, int(amount), int(usage_limit), 0, expires_at, now, now, 1),
        return_lastrowid=True,
    )


def update_coupon(
    coupon_id: int,
    *,
    code: str,
    amount: int,
    usage_limit: int,
    expires_at: str | None,
    is_active: bool | int | None = None,
) -> bool:
    now = datetime.now().isoformat(timespec="seconds")
    normalized = (code or "").strip().upper()
    if not normalized:
        return False
    updates = ["code=?", "amount=?", "usage_limit=?", "expires_at=?", "updated_at=?"]
    params: list[Any] = [normalized, int(amount), int(usage_limit), expires_at, now]
    if is_active is not None:
        updates.append("is_active=?")
        params.append(1 if bool(is_active) else 0)
    params.append(coupon_id)
    db_execute(
        f"""
        UPDATE coupons
        SET {', '.join(updates)}
        WHERE id=?
        """,
        tuple(params),
    )
    return True


def set_coupon_active(coupon_id: int, active: bool) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    db_execute(
        "UPDATE coupons SET is_active=?, updated_at=? WHERE id=?",
        (1 if active else 0, now, coupon_id),
    )


def list_coupons(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    rows = db_execute(
        """
        SELECT * FROM coupons
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
        fetchall=True,
    ) or []
    for row in rows:
        if not row.get("expires_at"):
            row["expires_at"] = None
        row["is_active"] = bool(int(row.get("is_active") or 0))
    return rows


def get_coupon(coupon_id: int):
    row = db_execute("SELECT * FROM coupons WHERE id=?", (coupon_id,), fetchone=True)
    if row:
        if not row.get("expires_at"):
            row["expires_at"] = None
        row["is_active"] = bool(int(row.get("is_active") or 0))
    return row


def list_coupon_redemptions(coupon_id: int) -> list[dict[str, Any]]:
    return db_execute(
        """
        SELECT user_id, amount, redeemed_at
        FROM coupon_redemptions
        WHERE coupon_id=?
        ORDER BY redeemed_at DESC
        """,
        (coupon_id,),
        fetchall=True,
    ) or []


def get_coupon_by_code(code: str):
    normalized = (code or "").strip().upper()
    if not normalized:
        return None
    row = db_execute("SELECT * FROM coupons WHERE UPPER(code)=?", (normalized,), fetchone=True)
    if row:
        if not row.get("expires_at"):
            row["expires_at"] = None
        row["is_active"] = bool(int(row.get("is_active") or 0))
    return row


def redeem_coupon(user_id: int, code: str) -> tuple[bool, dict[str, Any] | None, str | None]:
    normalized = (code or "").strip().upper()
    if not normalized:
        return False, None, "کد کوپن نامعتبر است."

    coupon = get_coupon_by_code(normalized)
    if not coupon:
        return False, None, "چنین کدی وجود ندارد."

    if not coupon.get("is_active"):
        return False, None, "این کوپن غیرفعال است."

    try:
        amount = int(coupon.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        return False, None, "مبلغ این کوپن معتبر نیست."

    limit = int(coupon.get("usage_limit") or 0)
    used = int(coupon.get("used_count") or 0)
    if limit and used >= limit:
        return False, None, "ظرفیت استفاده از این کوپن تکمیل شده است."

    expires_at = coupon.get("expires_at")
    if expires_at:
        try:
            expire_dt = datetime.fromisoformat(str(expires_at))
            if datetime.now() > expire_dt:
                return False, None, "تاریخ انقضای این کوپن گذشته است."
        except ValueError:
            pass

    already = db_execute(
        "SELECT id FROM coupon_redemptions WHERE coupon_id=? AND user_id=?",
        (coupon["id"], user_id),
        fetchone=True,
    )
    if already:
        return False, None, "این کد قبلاً اعمال شده است."

    success = change_wallet(user_id, amount, "CREDIT", note=f"COUPON:{coupon['code']}")
    if not success:
        return False, None, "امکان واریز مبلغ کوپن وجود ندارد."

    now = datetime.now().isoformat(timespec="seconds")
    db_execute(
        """
        INSERT INTO coupon_redemptions(coupon_id, user_id, amount, redeemed_at)
        VALUES(?,?,?,?)
        """,
        (coupon["id"], user_id, amount, now),
    )
    db_execute(
        "UPDATE coupons SET used_count=used_count+1, updated_at=? WHERE id=?",
        (now, coupon["id"]),
    )
    user = get_user(user_id)
    balance = int(user.get("wallet_balance") or 0) if user else 0
    return True, {"amount": amount, "balance": balance, "code": coupon["code"]}, None


# ====== Stats & History ======
def get_user_stats(user_id: int):
    u = db_execute("SELECT * FROM users WHERE user_id=?", (user_id,), fetchone=True) or {}
    total = db_execute("SELECT COUNT(*) AS c FROM orders WHERE user_id=?", (user_id,), fetchone=True)["c"]
    # در حال انجام: پس از تایید پرداخت تا قبل از تحویل
    inprog = db_execute("""
        SELECT COUNT(*) AS c FROM orders
        WHERE user_id=? AND status IN ('PENDING_CONFIRM','PENDING_PLAN','APPROVED','IN_PROGRESS','READY_TO_DELIVER')
    """, (user_id,), fetchone=True)["c"]
    done = db_execute("""
        SELECT COUNT(*) AS c FROM orders
        WHERE user_id=? AND status IN ('DELIVERED','COMPLETED')
    """, (user_id,), fetchone=True)["c"]
    return {
        "wallet_balance": int(u.get("wallet_balance") or 0),
        "ref_count": int(u.get("ref_count") or 0),
        "earnings_total": int(u.get("earnings_total") or 0),
        "orders_total": int(total or 0),
        "orders_inprog": int(inprog or 0),
        "orders_done": int(done or 0),
    }

def list_orders_by_category(user_id: int, category: str, limit: int = 10, offset: int = 0):
    where = "user_id=?"
    params = [user_id]
    if category == "inprog":
        where += " AND status IN ('PENDING_CONFIRM','PENDING_PLAN','APPROVED','IN_PROGRESS','READY_TO_DELIVER')"
    elif category == "done":
        where += " AND status IN ('DELIVERED','COMPLETED')"
    elif category == "all":
        where += " AND 1=1"
    else:
        where += " AND 1=0"  # ناشناخته

    sql = f"SELECT * FROM orders WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    return db_execute(sql, tuple(params), fetchall=True)

def count_orders_by_category(user_id: int, category: str):
    where = "user_id=?"
    params = [user_id]
    if category == "inprog":
        where += " AND status IN ('PENDING_CONFIRM','PENDING_PLAN','APPROVED','IN_PROGRESS','READY_TO_DELIVER')"
    elif category == "done":
        where += " AND status IN ('DELIVERED','COMPLETED')"
    elif category == "all":
        where += " AND 1=1"
    else:
        where += " AND 1=0"
    sql = f"SELECT COUNT(*) AS c FROM orders WHERE {where}"
    r = db_execute(sql, tuple(params), fetchone=True)
    return int(r["c"] if r else 0)

# ===== User phone verification (auto-migrate columns if missing) =====
def set_user_phone_verified(user_id: int, phone: str):
    # add columns if not exists (SQLite trick: try/except)
    try:
        db_execute("ALTER TABLE users ADD COLUMN phone TEXT", (), commit=True)
    except Exception:
        pass
    try:
        db_execute("ALTER TABLE users ADD COLUMN phone_verified INTEGER DEFAULT 0", (), commit=True)
    except Exception:
        pass
    db_execute("UPDATE users SET phone=?, phone_verified=1 WHERE id=?", (phone, user_id))
    return True


# ===== Admin web helpers =====

ORDER_STATUS_LABELS: dict[str, str] = {
    "AWAITING_PAYMENT": "در انتظار پرداخت",
    "PENDING_CONFIRM": "در انتظار تایید پرداخت",
    "PENDING_PLAN": "در انتظار تایید طرح",
    "PLAN_CONFIRMED": "طرح تایید شد",
    "APPROVED": "پرداخت تایید شد",
    "IN_PROGRESS": "در حال انجام",
    "READY_TO_DELIVER": "آماده تحویل",
    "DELIVERED": "تحویل شد",
    "COMPLETED": "تکمیل‌شده",
    "EXPIRED": "منقضی",
    "REJECTED": "رد شده",
    "CANCELED": "لغو شده",
}

PAYMENT_TYPE_LABELS: dict[str, str] = {
    "CARD": "پرداخت کارت",
    "WALLET": "کیف پول",
    "MIXED": "ترکیبی",
    "FIRST_PLAN": "طرح خرید اول",
}


def _build_where(parts: Iterable[str]) -> str:
    clauses = [p for p in parts if p]
    return " AND ".join(clauses) if clauses else "1=1"


def get_dashboard_snapshot():
    now = datetime.now()
    last_7_days = (now - timedelta(days=7)).isoformat(timespec="seconds")
    last_30_days = (now - timedelta(days=30)).isoformat(timespec="seconds")

    totals = db_execute(
        "SELECT COUNT(*) AS total FROM orders",
        fetchone=True,
    ) or {"total": 0}
    users = db_execute("SELECT COUNT(*) AS total FROM users", fetchone=True) or {"total": 0}
    status_counts = {
        row["status"]: row["c"]
        for row in db_execute(
            "SELECT status, COUNT(*) AS c FROM orders GROUP BY status",
            fetchall=True,
        )
    }
    awaiting = status_counts.get("AWAITING_PAYMENT", 0)
    pending = status_counts.get("PENDING_CONFIRM", 0)
    in_queue = sum(
        status_counts.get(code, 0)
        for code in ("APPROVED", "IN_PROGRESS", "READY_TO_DELIVER")
    )
    delivered = sum(
        status_counts.get(code, 0)
        for code in ("DELIVERED", "COMPLETED")
    )

    revenue_total = db_execute(
        """
        SELECT COALESCE(SUM(amount_total), 0) AS total
        FROM orders
        WHERE status IN ('APPROVED','IN_PROGRESS','READY_TO_DELIVER','DELIVERED','COMPLETED')
        """,
        fetchone=True,
    )["total"]
    revenue_30 = db_execute(
        """
        SELECT COALESCE(SUM(amount_total), 0) AS total
        FROM orders
        WHERE created_at >= ?
    """,
        (last_30_days,),
        fetchone=True,
    )["total"]
    new_orders_week = db_execute(
        "SELECT COUNT(*) AS c FROM orders WHERE created_at >= ?",
        (last_7_days,),
        fetchone=True,
    )["c"]

    wallet_totals = {
        row["type"]: row["total"]
        for row in db_execute(
            "SELECT type, COALESCE(SUM(amount), 0) AS total FROM wallet_tx GROUP BY type",
            fetchall=True,
        )
    }

    return {
        "orders_total": totals["total"],
        "users_total": users["total"],
        "awaiting_payment": awaiting,
        "pending_confirm": pending,
        "in_queue": in_queue,
        "delivered": delivered,
        "revenue_total": revenue_total or 0,
        "revenue_30_days": revenue_30 or 0,
        "new_orders_week": new_orders_week or 0,
        "wallet_totals": wallet_totals,
        "status_counts": status_counts,
    }


def list_recent_orders(limit: int = 8):
    return db_execute(
        "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?",
        (limit,),
        fetchall=True,
    )


def list_recent_users(limit: int = 6):
    return db_execute(
        "SELECT * FROM users ORDER BY created_at DESC LIMIT ?",
        (limit,),
        fetchall=True,
    )


def list_recent_wallet_tx(limit: int = 10):
    return db_execute(
        "SELECT * FROM wallet_tx ORDER BY created_at DESC LIMIT ?",
        (limit,),
        fetchall=True,
    )


def list_orders(
    *,
    status: str | None = None,
    search: str | None = None,
    limit: int = 20,
    offset: int = 0,
    user_id: int | None = None,
):
    where_parts: list[str] = []
    params: list[Any] = []

    if user_id is not None:
        where_parts.append("user_id=?")
        params.append(user_id)
    if status and status != "all":
        where_parts.append("status=?")
        params.append(status)

    if search:
        term = search.strip()
        if term.startswith("#"):
            term = term[1:]
        if term.isdigit():
            where_parts.append("id=?")
            params.append(int(term))
        else:
            like = f"%{term.lower()}%"
            where_parts.append(
                "(LOWER(username) LIKE ? OR LOWER(first_name) LIKE ? OR LOWER(plan_title) LIKE ? OR LOWER(customer_email) LIKE ?)"
            )
            params.extend([like, like, like, like])

    where_sql = _build_where(where_parts)
    sql = f"SELECT * FROM orders WHERE {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return db_execute(sql, tuple(params), fetchall=True)


def count_orders(status: str | None = None, search: str | None = None, user_id: int | None = None) -> int:
    where_parts: list[str] = []
    params: list[Any] = []
    if user_id is not None:
        where_parts.append("user_id=?")
        params.append(user_id)
    if status and status != "all":
        where_parts.append("status=?")
        params.append(status)
    if search:
        term = search.strip()
        if term.startswith("#"):
            term = term[1:]
        if term.isdigit():
            where_parts.append("id=?")
            params.append(int(term))
        else:
            like = f"%{term.lower()}%"
            where_parts.append(
                "(LOWER(username) LIKE ? OR LOWER(first_name) LIKE ? OR LOWER(plan_title) LIKE ? OR LOWER(customer_email) LIKE ?)"
            )
            params.extend([like, like, like, like])

    where_sql = _build_where(where_parts)
    sql = f"SELECT COUNT(*) AS c FROM orders WHERE {where_sql}"
    result = db_execute(sql, tuple(params), fetchone=True)
    return int(result["c"] if result else 0)


def update_order_notes(order_id: int, notes: str) -> None:
    set_order_manager_note(order_id, notes)


def list_wallet_tx_for_order(order_id: int) -> list[dict[str, Any]]:
    return db_execute(
        "SELECT * FROM wallet_tx WHERE order_id=? ORDER BY created_at DESC",
        (order_id,),
        fetchall=True,
    )


def list_users(search: str | None = None, limit: int = 20, offset: int = 0):
    where_parts: list[str] = []
    params: list[Any] = []
    if search:
        term = search.strip()
        like = f"%{term.lower()}%"
        if term.isdigit():
            where_parts.append("user_id=?")
            params.append(int(term))
        where_parts.append("(LOWER(username) LIKE ? OR LOWER(first_name) LIKE ?)")
        params.extend([like, like])
    where_sql = _build_where(where_parts)
    sql = f"SELECT * FROM users WHERE {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return db_execute(sql, tuple(params), fetchall=True)


def count_users(search: str | None = None) -> int:
    where_parts: list[str] = []
    params: list[Any] = []
    if search:
        term = search.strip()
        like = f"%{term.lower()}%"
        if term.isdigit():
            where_parts.append("user_id=?")
            params.append(int(term))
        where_parts.append("(LOWER(username) LIKE ? OR LOWER(first_name) LIKE ?)")
        params.extend([like, like])
    where_sql = _build_where(where_parts)
    sql = f"SELECT COUNT(*) AS c FROM users WHERE {where_sql}"
    result = db_execute(sql, tuple(params), fetchone=True)
    return int(result["c"] if result else 0)


def set_user_blocked(user_id: int, blocked: bool) -> None:
    db_execute(
        "UPDATE users SET is_blocked=?, updated_at=? WHERE user_id=?",
        (1 if blocked else 0, datetime.now().isoformat(timespec="seconds"), user_id),
    )


def is_user_blocked(user_id: int) -> bool:
    user = get_user(user_id)
    if not user:
        return False
    return bool(int(user.get("is_blocked") or 0))


def list_wallet_tx_for_user(user_id: int, limit: int = 20):
    return db_execute(
        "SELECT * FROM wallet_tx WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
        fetchall=True,
    )


def get_wallet_summary():
    totals = db_execute(
        "SELECT type, COALESCE(SUM(amount), 0) AS total FROM wallet_tx GROUP BY type",
        fetchall=True,
    )
    by_type = {row["type"]: row["total"] for row in totals}
    balance_total = db_execute(
        "SELECT COALESCE(SUM(wallet_balance), 0) AS total FROM users",
        fetchone=True,
    )["total"]
    return {
        "by_type": by_type,
        "user_balances": balance_total or 0,
    }


def create_service_message(
    user_id: int,
    username: str | None,
    first_name: str | None,
    category: str,
    message_text: str,
    attachment_file_id: str | None = None,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    return db_execute(
        """
        INSERT INTO service_messages(user_id, username, first_name, category, message_text, attachment_file_id, created_at, updated_at)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            user_id,
            username or "",
            first_name or "",
            category,
            message_text or "",
            attachment_file_id or "",
            now,
            now,
        ),
        return_lastrowid=True,
    )


def list_service_messages(
    *,
    category: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where_parts: list[str] = []
    params: list[Any] = []
    if category:
        where_parts.append("category=?")
        params.append(category)
    where_sql = _build_where(where_parts)
    sql = f"SELECT * FROM service_messages WHERE {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return db_execute(sql, tuple(params), fetchall=True)


def count_service_messages(category: str | None = None) -> int:
    where_parts: list[str] = []
    params: list[Any] = []
    if category:
        where_parts.append("category=?")
        params.append(category)
    where_sql = _build_where(where_parts)
    sql = f"SELECT COUNT(*) AS c FROM service_messages WHERE {where_sql}"
    result = db_execute(sql, tuple(params), fetchone=True)
    return int(result["c"] if result else 0)


def get_service_message(message_id: int) -> dict[str, Any] | None:
    return db_execute(
        "SELECT * FROM service_messages WHERE id=?",
        (message_id,),
        fetchone=True,
    )


def add_service_message_reply(message_id: int, user_id: int | None, text: str) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    return db_execute(
        """
        INSERT INTO service_message_replies(service_message_id, user_id, message_text, created_at)
        VALUES(?,?,?,?)
        """,
        (message_id, user_id, text or "", now),
        return_lastrowid=True,
    )


def list_service_message_replies(message_id: int) -> list[dict[str, Any]]:
    return db_execute(
        """
        SELECT * FROM service_message_replies
        WHERE service_message_id=?
        ORDER BY created_at DESC
        """,
        (message_id,),
        fetchall=True,
    )


def set_service_message_status(message_id: int, resolved: bool) -> None:
    db_execute(
        "UPDATE service_messages SET is_resolved=?, updated_at=? WHERE id=?",
        (1 if resolved else 0, datetime.now().isoformat(timespec="seconds"), message_id),
    )
