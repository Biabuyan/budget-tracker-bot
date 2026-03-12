"""
database.py — PostgreSQL database manager for Budget Tracker Bot (multi-user)

Uses SQLAlchemy for connection pooling and schema management.
Tables: users, user_settings, gmail_connections, transactions, budgets
"""

import os
import logging
from datetime import datetime, date
from typing import Optional
from contextlib import contextmanager

from sqlalchemy import (
    create_engine, text, Column, BigInteger, Text, Numeric, Date,
    DateTime, func, UniqueConstraint,
)
from sqlalchemy.orm import sessionmaker, declarative_base

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Railway gives postgres:// but SQLAlchemy needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = None
SessionLocal = None
Base = declarative_base()


# ── ORM Models ────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    telegram_user_id = Column(BigInteger, unique=True, nullable=False)
    telegram_username = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class UserSetting(Base):
    __tablename__ = "user_settings"
    user_id = Column(BigInteger, primary_key=True)
    monthly_budget = Column(Numeric)
    base_currency = Column(Text, default="$")
    timezone = Column(Text, default="UTC")


class GmailConnection(Base):
    __tablename__ = "gmail_connections"
    user_id = Column(BigInteger, primary_key=True)
    google_email = Column(Text)
    refresh_token_encrypted = Column(Text)
    access_token_encrypted = Column(Text)
    token_expiry = Column(DateTime(timezone=True))


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    source_message_id = Column(Text)
    merchant = Column(Text)
    amount = Column(Numeric)
    currency = Column(Text, default="$")
    category = Column(Text, default="Uncategorized")
    transaction_date = Column(Date)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("user_id", "source_message_id", name="uq_user_source_msg"),
    )


class Budget(Base):
    __tablename__ = "budgets"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    category = Column(Text, nullable=False)
    monthly_limit = Column(Numeric, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_user_budget_cat"),
    )


# ── Engine / Session ──────────────────────────────────────────

def init_db():
    """Create engine, session factory, and all tables."""
    global engine, SessionLocal

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set")

    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5)
    SessionLocal = sessionmaker(bind=engine)

    # Create tables
    Base.metadata.create_all(engine)
    logger.info("Database initialised (PostgreSQL).")


@contextmanager
def get_session():
    """Yield a SQLAlchemy session with auto-commit/rollback."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── Users ─────────────────────────────────────────────────────

def get_or_create_user(telegram_user_id: int, telegram_username: str = None) -> int:
    """Return internal user.id, creating the row if needed."""
    with get_session() as s:
        user = s.query(User).filter_by(telegram_user_id=telegram_user_id).first()
        if user:
            if telegram_username and user.telegram_username != telegram_username:
                user.telegram_username = telegram_username
            s.flush()
            return user.id
        new_user = User(
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
        )
        s.add(new_user)
        s.flush()
        uid = new_user.id
        # Create default settings row
        s.add(UserSetting(user_id=uid, monthly_budget=3000, base_currency="$"))
        return uid


def get_user_id(telegram_user_id: int) -> Optional[int]:
    """Lookup internal user id by Telegram user id. Returns None if not found."""
    with get_session() as s:
        user = s.query(User).filter_by(telegram_user_id=telegram_user_id).first()
        return user.id if user else None


# ── User Settings ─────────────────────────────────────────────

def get_monthly_budget(user_id: int) -> float:
    with get_session() as s:
        row = s.query(UserSetting).filter_by(user_id=user_id).first()
        return float(row.monthly_budget) if row and row.monthly_budget else 3000.0


def set_monthly_budget(user_id: int, amount: float):
    with get_session() as s:
        row = s.query(UserSetting).filter_by(user_id=user_id).first()
        if row:
            row.monthly_budget = amount
        else:
            s.add(UserSetting(user_id=user_id, monthly_budget=amount))


def get_base_currency(user_id: int) -> str:
    with get_session() as s:
        row = s.query(UserSetting).filter_by(user_id=user_id).first()
        return row.base_currency if row and row.base_currency else "$"


def set_base_currency(user_id: int, currency: str):
    with get_session() as s:
        row = s.query(UserSetting).filter_by(user_id=user_id).first()
        if row:
            row.base_currency = currency
        else:
            s.add(UserSetting(user_id=user_id, base_currency=currency))


# ── Gmail Connections ─────────────────────────────────────────

def save_gmail_connection(user_id: int, google_email: str,
                          refresh_token_enc: str, access_token_enc: str,
                          token_expiry: datetime):
    with get_session() as s:
        row = s.query(GmailConnection).filter_by(user_id=user_id).first()
        if row:
            row.google_email = google_email
            row.refresh_token_encrypted = refresh_token_enc
            row.access_token_encrypted = access_token_enc
            row.token_expiry = token_expiry
        else:
            s.add(GmailConnection(
                user_id=user_id,
                google_email=google_email,
                refresh_token_encrypted=refresh_token_enc,
                access_token_encrypted=access_token_enc,
                token_expiry=token_expiry,
            ))


def get_gmail_connection(user_id: int) -> Optional[dict]:
    with get_session() as s:
        row = s.query(GmailConnection).filter_by(user_id=user_id).first()
        if not row:
            return None
        return {
            "user_id": row.user_id,
            "google_email": row.google_email,
            "refresh_token_encrypted": row.refresh_token_encrypted,
            "access_token_encrypted": row.access_token_encrypted,
            "token_expiry": row.token_expiry,
        }


def get_all_gmail_connections() -> list[dict]:
    """Return all Gmail connections (for scheduler polling)."""
    with get_session() as s:
        rows = s.query(GmailConnection).all()
        return [
            {
                "user_id": r.user_id,
                "google_email": r.google_email,
                "refresh_token_encrypted": r.refresh_token_encrypted,
                "access_token_encrypted": r.access_token_encrypted,
                "token_expiry": r.token_expiry,
            }
            for r in rows
        ]


def update_gmail_tokens(user_id: int, access_token_enc: str, token_expiry: datetime):
    with get_session() as s:
        row = s.query(GmailConnection).filter_by(user_id=user_id).first()
        if row:
            row.access_token_encrypted = access_token_enc
            row.token_expiry = token_expiry


def delete_gmail_connection(user_id: int):
    with get_session() as s:
        s.query(GmailConnection).filter_by(user_id=user_id).delete()


# ── Transactions ──────────────────────────────────────────────

def add_transaction(user_id: int, date_str: str, amount: float,
                    merchant: str, category: str,
                    description: str = "",
                    source_message_id: Optional[str] = None,
                    currency: str = "$") -> Optional[int]:
    """Insert a transaction. Returns new row id, or None if duplicate."""
    try:
        with get_session() as s:
            tx = Transaction(
                user_id=user_id,
                transaction_date=date_str,
                amount=amount,
                merchant=merchant,
                category=category,
                currency=currency,
                description=description,
                source_message_id=source_message_id,
            )
            s.add(tx)
            s.flush()
            return tx.id
    except Exception as e:
        if "uq_user_source_msg" in str(e) or "duplicate" in str(e).lower():
            return None  # duplicate
        raise


def get_today_transactions(user_id: int) -> list[dict]:
    today = date.today()
    with get_session() as s:
        rows = s.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.transaction_date == today,
        ).order_by(Transaction.currency, Transaction.created_at.desc()).all()
        return [_tx_to_dict(r) for r in rows]


def get_month_transactions(user_id: int,
                           year: int = None, month: int = None) -> list[dict]:
    now = datetime.now()
    y = year or now.year
    m = month or now.month
    start = date(y, m, 1)
    if m == 12:
        end = date(y + 1, 1, 1)
    else:
        end = date(y, m + 1, 1)
    with get_session() as s:
        rows = s.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.transaction_date >= start,
            Transaction.transaction_date < end,
        ).order_by(Transaction.currency, Transaction.transaction_date.desc()).all()
        return [_tx_to_dict(r) for r in rows]


def get_category_totals(user_id: int,
                        year: int = None, month: int = None) -> list[dict]:
    now = datetime.now()
    y = year or now.year
    m = month or now.month
    start = date(y, m, 1)
    end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    with get_session() as s:
        rows = s.execute(text("""
            SELECT category, SUM(amount) as total, COUNT(*) as count
            FROM transactions
            WHERE user_id = :uid
              AND transaction_date >= :start AND transaction_date < :end
            GROUP BY category ORDER BY total DESC
        """), {"uid": user_id, "start": start, "end": end}).fetchall()
        return [{"category": r[0], "total": float(r[1]), "count": r[2]} for r in rows]


def get_category_totals_by_currency(user_id: int,
                                    year: int = None, month: int = None) -> list[dict]:
    now = datetime.now()
    y = year or now.year
    m = month or now.month
    start = date(y, m, 1)
    end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    with get_session() as s:
        rows = s.execute(text("""
            SELECT currency, category, SUM(amount) as total, COUNT(*) as count
            FROM transactions
            WHERE user_id = :uid
              AND transaction_date >= :start AND transaction_date < :end
            GROUP BY currency, category
            ORDER BY currency ASC, total DESC
        """), {"uid": user_id, "start": start, "end": end}).fetchall()
        return [{"currency": r[0], "category": r[1],
                 "total": float(r[2]), "count": r[3]} for r in rows]


def get_monthly_trend(user_id: int, months: int = 6) -> list[dict]:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT TO_CHAR(transaction_date, 'YYYY-MM') as month,
                   SUM(amount) as total
            FROM transactions
            WHERE user_id = :uid
            GROUP BY month ORDER BY month DESC LIMIT :lim
        """), {"uid": user_id, "lim": months}).fetchall()
        return [{"month": r[0], "total": float(r[1])} for r in rows]


def get_daily_totals_this_month(user_id: int) -> list[dict]:
    now = datetime.now()
    start = date(now.year, now.month, 1)
    end = date(now.year + 1, 1, 1) if now.month == 12 else date(now.year, now.month + 1, 1)
    with get_session() as s:
        rows = s.execute(text("""
            SELECT transaction_date::text as date, SUM(amount) as total
            FROM transactions
            WHERE user_id = :uid
              AND transaction_date >= :start AND transaction_date < :end
            GROUP BY transaction_date ORDER BY transaction_date ASC
        """), {"uid": user_id, "start": start, "end": end}).fetchall()
        return [{"date": r[0], "total": float(r[1])} for r in rows]


def get_daily_totals_by_currency(user_id: int) -> list[dict]:
    now = datetime.now()
    start = date(now.year, now.month, 1)
    end = date(now.year + 1, 1, 1) if now.month == 12 else date(now.year, now.month + 1, 1)
    with get_session() as s:
        rows = s.execute(text("""
            SELECT transaction_date::text as date, currency, SUM(amount) as total
            FROM transactions
            WHERE user_id = :uid
              AND transaction_date >= :start AND transaction_date < :end
            GROUP BY transaction_date, currency
            ORDER BY transaction_date ASC, currency ASC
        """), {"uid": user_id, "start": start, "end": end}).fetchall()
        return [{"date": r[0], "currency": r[1], "total": float(r[2])} for r in rows]


def get_monthly_trend_by_currency(user_id: int, months: int = 6) -> list[dict]:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT TO_CHAR(transaction_date, 'YYYY-MM') as month,
                   currency, SUM(amount) as total
            FROM transactions
            WHERE user_id = :uid
            GROUP BY month, currency
            ORDER BY month DESC, currency ASC
            LIMIT :lim
        """), {"uid": user_id, "lim": months * 10}).fetchall()
        return [{"month": r[0], "currency": r[1], "total": float(r[2])} for r in rows]


# ── Budgets ───────────────────────────────────────────────────

def set_budget(user_id: int, category: str, limit: float):
    with get_session() as s:
        s.execute(text("""
            INSERT INTO budgets (user_id, category, monthly_limit)
            VALUES (:uid, :cat, :lim)
            ON CONFLICT (user_id, category)
            DO UPDATE SET monthly_limit = :lim, updated_at = NOW()
        """), {"uid": user_id, "cat": category, "lim": limit})


def get_budgets(user_id: int) -> list[dict]:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT category, monthly_limit FROM budgets
            WHERE user_id = :uid ORDER BY category
        """), {"uid": user_id}).fetchall()
        return [{"category": r[0], "monthly_limit": float(r[1])} for r in rows]


# ── Telegram user_id → internal user_id lookup for scheduler ──

def get_telegram_user_id_for(user_id: int) -> Optional[int]:
    """Return telegram_user_id given internal user_id."""
    with get_session() as s:
        user = s.query(User).filter_by(id=user_id).first()
        return user.telegram_user_id if user else None


# ── Helpers ───────────────────────────────────────────────────

def _tx_to_dict(t: Transaction) -> dict:
    return {
        "id": t.id,
        "user_id": t.user_id,
        "date": str(t.transaction_date) if t.transaction_date else "",
        "amount": float(t.amount) if t.amount else 0.0,
        "merchant": t.merchant or "",
        "category": t.category or "Uncategorized",
        "currency": t.currency or "$",
        "description": t.description or "",
        "source_message_id": t.source_message_id,
    }
