"""
bot.py — Budget Tracker Telegram Bot
Commands: /start /help /today /month /budget /dashboard
"""

import os
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TimedOut, NetworkError
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

load_dotenv()
import database as db
from dashboard import generate_dashboard

# Ensure logs directory exists regardless of working directory
_log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(_log_dir, exist_ok=True)
_log_file = os.path.join(_log_dir, "bot.log")

import sys as _sys
# Force UTF-8 output on Windows (cp1252 can't encode emoji)
_utf8_stream = open(_sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1, closefd=False)
_stream_handler = logging.StreamHandler(_utf8_stream)
_stream_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        _stream_handler,
        logging.FileHandler(_log_file, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID  = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
CURRENCY = os.getenv("CURRENCY_SYMBOL", "$")


# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

def h(text: str) -> str:
    """Escape HTML special chars so arbitrary strings are safe in HTML messages."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_amount(amount: float, currency: str = None) -> str:
    sym = currency if currency else CURRENCY
    return f"{sym}{amount:,.2f}"


def fmt_tx(row) -> str:
    cur = row['currency'] if 'currency' in row.keys() else CURRENCY
    return (
        f"  • <b>{h(row['merchant'])}</b> — {h(fmt_amount(row['amount'], cur))}\n"
        f"    <i>{h(row['category'])}</i> | {row['date']}"
    )


def build_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📊 Dashboard", callback_data="dashboard"),
        InlineKeyboardButton("📅 This Month", callback_data="month"),
    ]])


# ─────────────────────────────────────────────────────────────
#  /start
# ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 <b>Welcome to Budget Tracker Bot!</b>\n\n"
        "I automatically import your bank email receipts and help you "
        "track spending. Here's what I can do:\n\n"
        "📌 /today — Today's transactions\n"
        "📅 /month — This month's summary\n"
        "💰 /budget — View or set category budgets\n"
        "📊 /dashboard — Full visual spending dashboard\n"
        "❓ /help — Show this help\n\n"
        "<i>Email receipts are checked every few minutes automatically.</i>"
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
        "  ↳ Set: <code>/budget Food 500</code> (sets Food limit to $500)\n"
        "/dashboard — Send spending dashboard image\n\n"
        "<b>How it works:</b>\n"
        "1. Your bank sends email receipts\n"
        "2. This bot polls your inbox every 5 min\n"
        "3. Transactions are parsed &amp; categorised automatically\n"
        "4. You get a notification here for each new transaction\n\n"
        "<b>Tip:</b> Set budgets with <code>/budget Category Amount</code>\n"
        "e.g. <code>/budget Groceries 400</code>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ─────────────────────────────────────────────────────────────
#  /today
# ─────────────────────────────────────────────────────────────

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = db.get_today_transactions()
    today = datetime.now().strftime("%A, %d %b %Y")

    if not rows:
        await update.message.reply_text(
            f"📭 <b>No transactions yet today</b>\n<i>{today}</i>",
            parse_mode="HTML"
        )
        return

    # Group transactions by currency
    from collections import defaultdict
    by_currency = defaultdict(list)
    for row in rows:
        cur = row['currency'] if 'currency' in row.keys() else CURRENCY
        by_currency[cur].append(row)

    lines = [f"📋 <b>Today's Transactions</b>\n<i>{today}</i>\n"]

    for cur in sorted(by_currency.keys()):
        cur_rows = by_currency[cur]
        cur_total = sum(r["amount"] for r in cur_rows)
        lines.append(f"\n💱 <b>{h(cur)}</b>")
        for row in cur_rows:
            lines.append(fmt_tx(row))
        lines.append(f"  ── Subtotal: <b>{h(fmt_amount(cur_total, cur))}</b> ({len(cur_rows)} tx)")

    total_count = len(rows)
    lines.append(f"\n💳 <b>{total_count} transactions total</b>")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=build_back_kb()
    )


# ─────────────────────────────────────────────────────────────
#  /month
# ─────────────────────────────────────────────────────────────

async def cmd_month(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _month_for_message(update.message)


# ─────────────────────────────────────────────────────────────
#  /budget
# ─────────────────────────────────────────────────────────────

async def cmd_budget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args

    if args and len(args) >= 2:
        try:
            limit = float(args[-1])
            category = " ".join(args[:-1]).title()
            db.set_budget(category, limit)
            await update.message.reply_text(
                f"✅ Budget set: <b>{h(category)}</b> → {h(fmt_amount(limit))}/month",
                parse_mode="HTML"
            )
            return
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid format. Use: <code>/budget CategoryName 500</code>",
                parse_mode="HTML"
            )
            return

    if args and len(args) == 1:
        try:
            limit = float(args[0])
            db.set_setting("monthly_budget", str(limit))
            await update.message.reply_text(
                f"✅ Monthly budget set to {h(fmt_amount(limit))}",
                parse_mode="HTML"
            )
            return
        except ValueError:
            pass

    budgets = db.get_budgets()
    cats    = db.get_category_totals()
    spent   = {r["category"]: r["total"] for r in cats}
    global_budget = float(db.get_setting("monthly_budget") or 3000)

    lines = [f"💰 <b>Budget Overview</b>\n"]
    lines.append(f"🌍 Global monthly budget: {h(fmt_amount(global_budget))}\n")

    if budgets:
        lines.append("<b>Category limits:</b>")
        for b in budgets:
            cat   = b["category"]
            limit = b["monthly_limit"]
            used  = spent.get(cat, 0)
            pct   = used / limit * 100 if limit else 0
            icon  = "🟢" if pct < 75 else ("🟡" if pct < 100 else "🔴")
            lines.append(
                f"  {icon} <b>{h(cat)}</b>\n"
                f"     {h(fmt_amount(used))} / {h(fmt_amount(limit))} ({pct:.0f}%)"
            )
    else:
        lines.append("<i>No category budgets set.</i>")
        lines.append("\nSet one with: <code>/budget Food 500</code>")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=build_back_kb()
    )


# ─────────────────────────────────────────────────────────────
#  /dashboard
# ─────────────────────────────────────────────────────────────

async def cmd_dashboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _dashboard_for_message(update.message)


# ─────────────────────────────────────────────────────────────
#  INLINE BUTTON CALLBACKS
# ─────────────────────────────────────────────────────────────

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Build a lightweight wrapper so handlers can use msg.reply_text / reply_photo
    msg = query.message

    if query.data == "dashboard":
        await _dashboard_for_message(msg)
    elif query.data == "month":
        await _month_for_message(msg)


async def _dashboard_for_message(msg):
    """Dashboard logic reusable from both /dashboard command and inline button."""
    status = await msg.reply_text("📊 Generating your dashboard…")
    try:
        cats   = db.get_category_totals()
        daily  = db.get_daily_totals_this_month()
        trend  = db.get_monthly_trend(6)
        budget = float(db.get_setting("monthly_budget") or 3000)

        # Currency-aware data
        cats_by_cur  = db.get_category_totals_by_currency()
        daily_by_cur = db.get_daily_totals_by_currency()
        trend_by_cur = db.get_monthly_trend_by_currency(6)

        buf = generate_dashboard(
            category_totals=[dict(r) for r in cats],
            daily_totals   =[dict(r) for r in daily],
            monthly_trend  =[dict(r) for r in trend],
            monthly_budget  =budget,
            currency        =CURRENCY,
            category_totals_by_currency=[dict(r) for r in cats_by_cur],
            daily_totals_by_currency   =[dict(r) for r in daily_by_cur],
            monthly_trend_by_currency  =[dict(r) for r in trend_by_cur],
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


async def _month_for_message(msg):
    """Month summary logic reusable from both /month command and inline button."""
    now   = datetime.now()
    rows  = db.get_month_transactions()
    cats  = db.get_category_totals()
    bdgt  = float(db.get_setting("monthly_budget") or 3000)

    total   = sum(r["total"] for r in cats)
    remain  = bdgt - total
    pct     = total / bdgt * 100 if bdgt else 0

    header = (
        f"📅 <b>{now.strftime('%B %Y')} Summary</b>\n\n"
        f"💳 Spent:      {h(fmt_amount(total))}\n"
        f"🎯 Budget:     {h(fmt_amount(bdgt))}\n"
        f"✅ Remaining:  {h(fmt_amount(remain))}\n"
        f"📊 Used:       {pct:.1f}%\n"
    )

    filled = int(pct / 5)
    bar    = "█" * filled + "░" * (20 - filled)
    header += f"<code>[{bar}]</code>\n\n"

    currency_cats = db.get_category_totals_by_currency()
    if currency_cats:
        from collections import defaultdict
        grouped = defaultdict(list)
        for r in currency_cats:
            grouped[r['currency']].append(r)

        for cur in sorted(grouped.keys()):
            header += f"\n💱 <b>{h(cur)}</b>\n"
            cur_total = 0
            for r in grouped[cur]:
                header += f"  • <i>{h(r['category'])}</i>: {h(fmt_amount(r['total'], cur))} ({r['count']} tx)\n"
                cur_total += r['total']
            header += f"  ── Subtotal: <b>{h(fmt_amount(cur_total, cur))}</b>\n"
    else:
        header += "<b>By Category:</b>\n"
        for r in cats:
            header += f"  • <i>{h(r['category'])}</i>: {h(fmt_amount(r['total']))} ({r['count']} tx)\n"

    header += f"\n<i>{len(rows)} transactions total</i>"

    await msg.reply_text(
        header,
        parse_mode="HTML",
        reply_markup=build_back_kb()
    )


# ─────────────────────────────────────────────────────────────
#  PUSH NOTIFICATION (called by scheduler)
# ─────────────────────────────────────────────────────────────

async def notify_transaction(app: Application, tx: dict):
    """Send a notification when a new transaction is found from email."""
    icon_map = {
        "Food & Dining": "🍔", "Groceries": "🛒", "Transport": "🚗",
        "Shopping": "🛍️", "Entertainment": "🎬", "Health": "💊",
        "Utilities": "💡", "Subscriptions": "📱", "Travel": "✈️",
        "Uncategorized": "💳",
    }
    icon = icon_map.get(tx.get("category", ""), "💳")
    cur = tx.get('currency', CURRENCY)

    text = (
        f"{icon} <b>New Transaction Detected</b>\n\n"
        f"🏪 <b>{h(tx['merchant'])}</b>\n"
        f"💰 {h(fmt_amount(tx['amount'], cur))}\n"
        f"💱 {h(cur)}\n"
        f"🗂️ {h(tx['category'])}\n"
        f"📅 {tx['date']}\n"
        f"🏦 Parsed from: {h(tx.get('bank', 'Email'))}"
    )

    for attempt in range(3):
        try:
            await app.bot.send_message(
                chat_id=CHAT_ID,
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

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("today",     cmd_today))
    app.add_handler(CommandHandler("month",     cmd_month))
    app.add_handler(CommandHandler("budget",    cmd_budget))
    app.add_handler(CommandHandler("dashboard", cmd_dashboard))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    return app