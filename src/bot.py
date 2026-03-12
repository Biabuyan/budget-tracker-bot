"""
bot.py — Budget Tracker Telegram Bot (multi-user, OAuth)

Commands: /start /help /today /month /budget /dashboard /connectgmail /disconnectgmail
"""

import os
import asyncio
import logging
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TimedOut, NetworkError
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

load_dotenv()
import src.database as db
from src.dashboard import generate_dashboard

logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
APP_BASE_URL = os.getenv("APP_BASE_URL", "")


# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

def h(text: str) -> str:
    """Escape HTML special chars."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_amount(amount: float, currency: str = "$") -> str:
    return f"{currency}{amount:,.2f}"


def fmt_tx(row: dict) -> str:
    cur = row.get("currency", "$")
    return (
        f"  • <b>{h(row['merchant'])}</b> — {h(fmt_amount(row['amount'], cur))}\n"
        f"    <i>{h(row['category'])}</i> | {row['date']}"
    )


def build_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📊 Dashboard", callback_data="dashboard"),
        InlineKeyboardButton("📅 This Month", callback_data="month"),
    ]])


def _get_user(update: Update) -> int:
    """Ensure user exists in DB and return internal user_id."""
    tg_user = update.effective_user
    return db.get_or_create_user(
        telegram_user_id=tg_user.id,
        telegram_username=tg_user.username,
    )


def _get_currency(user_id: int) -> str:
    return db.get_base_currency(user_id)


# ─────────────────────────────────────────────────────────────
#  /start  —  register user if new
# ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = _get_user(update)
    text = (
        "👋 <b>Welcome to Budget Tracker Bot!</b>\n\n"
        "I automatically import your bank email receipts via Gmail "
        "and help you track spending. Here's what I can do:\n\n"
        "📌 /today — Today's transactions\n"
        "📅 /month — This month's summary\n"
        "💰 /budget — View or set category budgets\n"
        "📊 /dashboard — Full visual spending dashboard\n"
        "📧 /connectgmail — Connect your Gmail for auto-import\n"
        "❓ /help — Show this help\n\n"
        "<i>After connecting Gmail, receipts are imported automatically.</i>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ─────────────────────────────────────────────────────────────
#  /help
# ─────────────────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 <b>Budget Tracker Bot — Help</b>\n\n"
        "<b>Commands:</b>\n"
        "/today — Transactions recorded today\n"
        "/month — Monthly spending breakdown\n"
        "/budget — View/set budgets per category\n"
        "  ↳ Set: <code>/budget Food 500</code>\n"
        "/dashboard — Send spending dashboard image\n"
        "/connectgmail — Link your Gmail for auto-import\n"
        "/disconnectgmail — Unlink Gmail\n\n"
        "<b>How it works:</b>\n"
        "1. Connect your Gmail with /connectgmail\n"
        "2. The bot polls your inbox every 5 min\n"
        "3. Transactions are parsed &amp; categorised automatically\n"
        "4. You get a notification for each new transaction\n\n"
        "<b>Tip:</b> Set budgets with <code>/budget Category Amount</code>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ─────────────────────────────────────────────────────────────
#  /connectgmail
# ─────────────────────────────────────────────────────────────

async def cmd_connectgmail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = _get_user(update)
    tg_id = update.effective_user.id

    # Check if already connected
    conn = db.get_gmail_connection(user_id)
    if conn and conn.get("google_email"):
        await update.message.reply_text(
            f"📧 Gmail already connected: <b>{h(conn['google_email'])}</b>\n"
            f"Use /disconnectgmail to unlink first.",
            parse_mode="HTML",
        )
        return

    if not APP_BASE_URL:
        await update.message.reply_text(
            "❌ OAuth is not configured. APP_BASE_URL is missing.",
        )
        return

    url = f"{APP_BASE_URL}/auth/google/start?telegram_user_id={tg_id}"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔗 Connect Gmail", url=url)
    ]])
    await update.message.reply_text(
        "📧 <b>Connect Gmail</b>\n\n"
        "Click the button below to authorize Gmail access.\n"
        "This lets the bot read bank receipt emails automatically.\n\n"
        "<i>Only gmail.readonly access is requested.</i>",
        parse_mode="HTML",
        reply_markup=kb,
    )


# ─────────────────────────────────────────────────────────────
#  /disconnectgmail
# ─────────────────────────────────────────────────────────────

async def cmd_disconnectgmail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = _get_user(update)
    conn = db.get_gmail_connection(user_id)
    if not conn:
        await update.message.reply_text("ℹ️ No Gmail account is connected.")
        return
    db.delete_gmail_connection(user_id)
    await update.message.reply_text("✅ Gmail disconnected successfully.")


# ─────────────────────────────────────────────────────────────
#  /today
# ─────────────────────────────────────────────────────────────

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = _get_user(update)
    currency = _get_currency(user_id)
    rows = db.get_today_transactions(user_id)
    today = datetime.now().strftime("%A, %d %b %Y")

    if not rows:
        await update.message.reply_text(
            f"📭 <b>No transactions yet today</b>\n<i>{today}</i>",
            parse_mode="HTML",
        )
        return

    by_currency = defaultdict(list)
    for row in rows:
        by_currency[row.get("currency", currency)].append(row)

    lines = [f"📋 <b>Today's Transactions</b>\n<i>{today}</i>\n"]

    for cur in sorted(by_currency.keys()):
        cur_rows = by_currency[cur]
        cur_total = sum(r["amount"] for r in cur_rows)
        lines.append(f"\n💱 <b>{h(cur)}</b>")
        for row in cur_rows:
            lines.append(fmt_tx(row))
        lines.append(f"  ── Subtotal: <b>{h(fmt_amount(cur_total, cur))}</b> ({len(cur_rows)} tx)")

    lines.append(f"\n💳 <b>{len(rows)} transactions total</b>")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=build_back_kb(),
    )


# ─────────────────────────────────────────────────────────────
#  /month
# ─────────────────────────────────────────────────────────────

async def cmd_month(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = _get_user(update)
    await _month_for_message(update.message, user_id)


# ─────────────────────────────────────────────────────────────
#  /budget
# ─────────────────────────────────────────────────────────────

async def cmd_budget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = _get_user(update)
    currency = _get_currency(user_id)
    args = ctx.args

    # /budget Food 500  →  set category budget
    if args and len(args) >= 2:
        try:
            limit = float(args[-1])
            category = " ".join(args[:-1]).title()
            db.set_budget(user_id, category, limit)
            await update.message.reply_text(
                f"✅ Budget set: <b>{h(category)}</b> → {h(fmt_amount(limit, currency))}/month",
                parse_mode="HTML",
            )
            return
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid format. Use: <code>/budget CategoryName 500</code>",
                parse_mode="HTML",
            )
            return

    # /budget 3000  →  set global monthly budget
    if args and len(args) == 1:
        try:
            limit = float(args[0])
            db.set_monthly_budget(user_id, limit)
            await update.message.reply_text(
                f"✅ Monthly budget set to {h(fmt_amount(limit, currency))}",
                parse_mode="HTML",
            )
            return
        except ValueError:
            pass

    # /budget  →  show overview
    budgets = db.get_budgets(user_id)
    cats = db.get_category_totals(user_id)
    spent = {r["category"]: r["total"] for r in cats}
    global_budget = db.get_monthly_budget(user_id)

    lines = [f"💰 <b>Budget Overview</b>\n"]
    lines.append(f"🌍 Global monthly budget: {h(fmt_amount(global_budget, currency))}\n")

    if budgets:
        lines.append("<b>Category limits:</b>")
        for b in budgets:
            cat = b["category"]
            limit = b["monthly_limit"]
            used = spent.get(cat, 0)
            pct = used / limit * 100 if limit else 0
            icon = "🟢" if pct < 75 else ("🟡" if pct < 100 else "🔴")
            lines.append(
                f"  {icon} <b>{h(cat)}</b>\n"
                f"     {h(fmt_amount(used, currency))} / {h(fmt_amount(limit, currency))} ({pct:.0f}%)"
            )
    else:
        lines.append("<i>No category budgets set.</i>")
        lines.append("\nSet one with: <code>/budget Food 500</code>")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=build_back_kb(),
    )


# ─────────────────────────────────────────────────────────────
#  /dashboard
# ─────────────────────────────────────────────────────────────

async def cmd_dashboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = _get_user(update)
    await _dashboard_for_message(update.message, user_id)


# ─────────────────────────────────────────────────────────────
#  INLINE BUTTON CALLBACKS
# ─────────────────────────────────────────────────────────────

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = _get_user(update)
    msg = query.message

    if query.data == "dashboard":
        await _dashboard_for_message(msg, user_id)
    elif query.data == "month":
        await _month_for_message(msg, user_id)


# ─────────────────────────────────────────────────────────────
#  SHARED LOGIC
# ─────────────────────────────────────────────────────────────

async def _dashboard_for_message(msg, user_id: int):
    currency = _get_currency(user_id)
    status = await msg.reply_text("📊 Generating your dashboard…")
    try:
        cats = db.get_category_totals(user_id)
        daily = db.get_daily_totals_this_month(user_id)
        trend = db.get_monthly_trend(user_id, 6)
        budget = db.get_monthly_budget(user_id)

        cats_by_cur = db.get_category_totals_by_currency(user_id)
        daily_by_cur = db.get_daily_totals_by_currency(user_id)
        trend_by_cur = db.get_monthly_trend_by_currency(user_id, 6)

        buf = generate_dashboard(
            category_totals=cats,
            daily_totals=daily,
            monthly_trend=trend,
            monthly_budget=budget,
            currency=currency,
            category_totals_by_currency=cats_by_cur,
            daily_totals_by_currency=daily_by_cur,
            monthly_trend_by_currency=trend_by_cur,
        )

        await msg.reply_photo(
            photo=buf,
            caption=(
                f"📊 <b>Spending Dashboard — {datetime.now().strftime('%B %Y')}</b>\n"
                f"Tap to expand for full view."
            ),
            parse_mode="HTML",
        )
        await status.delete()
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        await status.edit_text("❌ Could not generate dashboard. Check logs.")


async def _month_for_message(msg, user_id: int):
    currency = _get_currency(user_id)
    now = datetime.now()
    rows = db.get_month_transactions(user_id)
    cats = db.get_category_totals(user_id)
    bdgt = db.get_monthly_budget(user_id)

    total = sum(r["total"] for r in cats)
    remain = bdgt - total
    pct = total / bdgt * 100 if bdgt else 0

    header = (
        f"📅 <b>{now.strftime('%B %Y')} Summary</b>\n\n"
        f"💳 Spent:      {h(fmt_amount(total, currency))}\n"
        f"🎯 Budget:     {h(fmt_amount(bdgt, currency))}\n"
        f"✅ Remaining:  {h(fmt_amount(remain, currency))}\n"
        f"📊 Used:       {pct:.1f}%\n"
    )

    filled = int(pct / 5)
    bar = "█" * min(filled, 20) + "░" * max(20 - filled, 0)
    header += f"<code>[{bar}]</code>\n\n"

    currency_cats = db.get_category_totals_by_currency(user_id)
    if currency_cats:
        grouped = defaultdict(list)
        for r in currency_cats:
            grouped[r["currency"]].append(r)

        for cur in sorted(grouped.keys()):
            header += f"\n💱 <b>{h(cur)}</b>\n"
            cur_total = 0
            for r in grouped[cur]:
                header += f"  • <i>{h(r['category'])}</i>: {h(fmt_amount(r['total'], cur))} ({r['count']} tx)\n"
                cur_total += r["total"]
            header += f"  ── Subtotal: <b>{h(fmt_amount(cur_total, cur))}</b>\n"
    else:
        header += "<b>By Category:</b>\n"
        for r in cats:
            header += f"  • <i>{h(r['category'])}</i>: {h(fmt_amount(r['total'], currency))} ({r['count']} tx)\n"

    header += f"\n<i>{len(rows)} transactions total</i>"

    await msg.reply_text(
        header,
        parse_mode="HTML",
        reply_markup=build_back_kb(),
    )


# ─────────────────────────────────────────────────────────────
#  PUSH NOTIFICATION (called by scheduler for a specific user)
# ─────────────────────────────────────────────────────────────

async def notify_transaction(app: Application, telegram_chat_id: int, tx: dict):
    """Send a notification when a new transaction is found."""
    icon_map = {
        "Food & Dining": "🍔", "Groceries": "🛒", "Transport": "🚗",
        "Shopping": "🛍️", "Entertainment": "🎬", "Health": "💊",
        "Utilities": "💡", "Subscriptions": "📱", "Travel": "✈️",
        "Uncategorized": "💳",
    }
    icon = icon_map.get(tx.get("category", ""), "💳")
    cur = tx.get("currency", "$")

    text = (
        f"{icon} <b>New Transaction Detected</b>\n\n"
        f"🏪 <b>{h(tx['merchant'])}</b>\n"
        f"💰 {h(fmt_amount(tx['amount'], cur))}\n"
        f"💱 {h(cur)}\n"
        f"🗂️ {h(tx['category'])}\n"
        f"📅 {tx['date']}\n"
        f"🏦 Parsed from: {h(tx.get('bank', 'Gmail'))}"
    )

    for attempt in range(3):
        try:
            await app.bot.send_message(
                chat_id=telegram_chat_id,
                text=text,
                parse_mode="HTML",
            )
            return
        except (TimedOut, NetworkError) as e:
            logger.warning(f"Notification attempt {attempt + 1}/3 failed: {e}")
            if attempt < 2:
                await asyncio.sleep(3 * (attempt + 1))
    logger.error(f"Failed to send notification for {tx.get('merchant', '?')} after 3 attempts")


# ─────────────────────────────────────────────────────────────
#  UNKNOWN COMMAND
# ─────────────────────────────────────────────────────────────

async def unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Unknown command. Use /help to see available commands."
    )


# ─────────────────────────────────────────────────────────────
#  APP FACTORY
# ─────────────────────────────────────────────────────────────

def build_app() -> Application:
    app = (
        Application.builder()
        .token(TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(15)
        .build()
    )

    app.add_handler(CommandHandler("start",           cmd_start))
    app.add_handler(CommandHandler("help",            cmd_help))
    app.add_handler(CommandHandler("today",           cmd_today))
    app.add_handler(CommandHandler("month",           cmd_month))
    app.add_handler(CommandHandler("budget",          cmd_budget))
    app.add_handler(CommandHandler("dashboard",       cmd_dashboard))
    app.add_handler(CommandHandler("connectgmail",    cmd_connectgmail))
    app.add_handler(CommandHandler("disconnectgmail", cmd_disconnectgmail))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    return app
