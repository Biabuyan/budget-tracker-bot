"""
database.py — SQLite database manager for Budget Tracker Bot
"""

import sqlite3
import os
from datetime import datetime, date
from typing import Optional


DB_PATH = os.path.join(os.path.dirname(__file__), "../data/budget.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables on first run."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS transactions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT NOT NULL,
                amount      REAL NOT NULL,
                merchant    TEXT,
                category    TEXT DEFAULT 'Uncategorized',
                description TEXT,
                email_uid   TEXT UNIQUE,           -- prevents duplicate imports
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS budgets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                category    TEXT NOT NULL UNIQUE,
                monthly_limit REAL NOT NULL,
                updated_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS settings (
                key         TEXT PRIMARY KEY,
                value       TEXT
            );
        """)
        # Insert default global budget if not set
        conn.execute("""
            INSERT OR IGNORE INTO settings (key, value)
            VALUES ('monthly_budget', '3000'), ('currency', '$')
        """)
        conn.commit()
    print("✅ Database initialised.")


# ── Transactions ──────────────────────────────────────────────

def add_transaction(date_str: str, amount: float, merchant: str,
                    category: str, description: str,
                    email_uid: Optional[str] = None) -> Optional[int]:
    """Insert a transaction. Returns new row id, or None if duplicate."""
    try:
        with get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO transactions (date, amount, merchant, category, description, email_uid)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (date_str, amount, merchant, category, description, email_uid))
            conn.commit()
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None   # duplicate email_uid


def get_today_transactions() -> list:
    today = date.today().isoformat()
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM transactions WHERE date = ? ORDER BY created_at DESC
        """, (today,)).fetchall()


def get_month_transactions(year: int = None, month: int = None) -> list:
    now = datetime.now()
    y = year or now.year
    m = month or now.month
    prefix = f"{y}-{m:02d}"
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM transactions
            WHERE date LIKE ?
            ORDER BY date DESC, created_at DESC
        """, (f"{prefix}%",)).fetchall()


def get_category_totals(year: int = None, month: int = None) -> list:
    now = datetime.now()
    y = year or now.year
    m = month or now.month
    prefix = f"{y}-{m:02d}"
    with get_conn() as conn:
        return conn.execute("""
            SELECT category, SUM(amount) as total, COUNT(*) as count
            FROM transactions
            WHERE date LIKE ?
            GROUP BY category
            ORDER BY total DESC
        """, (f"{prefix}%",)).fetchall()


def get_monthly_trend(months: int = 6) -> list:
    """Return total spending per month for the last N months."""
    with get_conn() as conn:
        return conn.execute("""
            SELECT substr(date, 1, 7) as month, SUM(amount) as total
            FROM transactions
            GROUP BY month
            ORDER BY month DESC
            LIMIT ?
        """, (months,)).fetchall()


def get_daily_totals_this_month() -> list:
    now = datetime.now()
    prefix = f"{now.year}-{now.month:02d}"
    with get_conn() as conn:
        return conn.execute("""
            SELECT date, SUM(amount) as total
            FROM transactions
            WHERE date LIKE ?
            GROUP BY date
            ORDER BY date ASC
        """, (f"{prefix}%",)).fetchall()


# ── Budgets ───────────────────────────────────────────────────

def set_budget(category: str, limit: float):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO budgets (category, monthly_limit)
            VALUES (?, ?)
            ON CONFLICT(category) DO UPDATE SET monthly_limit=?, updated_at=datetime('now')
        """, (category, limit, limit))
        conn.commit()


def get_budgets() -> list:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM budgets ORDER BY category").fetchall()


# ── Settings ──────────────────────────────────────────────────

def get_setting(key: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=?
        """, (key, value, value))
        conn.commit()
