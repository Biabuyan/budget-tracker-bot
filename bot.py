"""
bot.py — Budget Tracker Telegram Bot
Commands: /start /help /today /month /budget /dashboard
"""

import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

load_dotenv()
import database as db
from dashboard import generate_dashboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("../logs/bot.log"),
    ],
)
logger = logging.getLogger(__name__)

TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID  = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
CURRENCY = os.getenv("CURRENCY_SYMBOL", "$")


# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

def fmt_amount(amount: float) -> str:
    return f"{CURRENCY}{amount:,.2f}"


def fmt_tx(row) -> str:
    return (
        f"  • *{row['merchant']}* — {fmt_amount(row['amount'])}\n"
        f"    _{row['category']}_ | {row['date']}"
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
        "👋 *Welcome to Budget Tracker Bot!*\n\n"
        "I automatically import your bank email receipts and help you "
        "track spending. Here's what I can do:\n\n"
        "📌 /today — Today's transactions\n"
        "📅 /month — This month's summary\n"
        "💰 /budget — View or set category budgets\n"
        "📊 /dashboard — Full visual spending dashboard\n"
        "❓ /help — Show this help\n\n"
        "_Email receipts are checked every few minutes automatically._"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────
#  /help
# ─────────────────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Budget Tracker Bot — Help*\n\n"
        "*Commands:*\n"
        "/today — Transactions recorded today\n"
        "/month — Monthly spending breakdown\n"
        "/budget — View/set budgets per category\n"
        "  ↳ Set: `/budget Food 500` (sets Food limit to $500)\n"
        "/dashboard — Send spending dashboard image\n\n"
        "*How it works:*\n"
        "1. Your bank sends email receipts\n"
        "2. This bot polls your inbox every 5 min\n"
        "3. Transactions are parsed & categorised automatically\n"
        "4. You get a notification here for each new transaction\n\n"
        "*Tip:* Set budgets with `/budget Category Amount`\n"
        "e.g. `/budget Groceries 400`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────
#  /today
# ─────────────────────────────────────────────────────────────

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = db.get_today_transactions()
    today = datetime.now().strftime("%A, %d %b %Y")

    if not rows:
        await update.message.reply_text(
            f"📭 *No transactions yet today*\n_{today}_",
            parse_mode="Markdown"
        )
        return

    total = sum(r["amount"] for r in rows)
    lines = [f"📋 *Today's Transactions*\n_{today}_\n"]
    for row in rows:
        lines.append(fmt_tx(row))
    lines.append(f"\n💳 *Total: {fmt_amount(total)}* ({len(rows)} transactions)")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=build_back_kb()
    )


# ─────────────────────────────────────────────────────────────
#  /month
# ─────────────────────────────────────────────────────────────

async def cmd_month(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    now   = datetime.now()
    rows  = db.get_month_transactions()
    cats  = db.get_category_totals()
    bdgt  = float(db.get_setting("monthly_budget") or 3000)

    total   = sum(r["total"] for r in cats)
    remain  = bdgt - total
    pct     = total / bdgt * 100 if bdgt else 0

    header = (
        f"📅 *{now.strftime('%B %Y')} Summary*\n\n"
        f"💳 Spent:      {fmt_amount(total)}\n"
        f"🎯 Budget:     {fmt_amount(bdgt)}\n"
        f"✅ Remaining:  {fmt_amount(remain)}\n"
        f"📊 Used:       {pct:.1f}%\n"
    )

    # Budget bar
    filled = int(pct / 5)
    bar    = "█" * filled + "░" * (20 - filled)
    header += f"`[{bar}]`\n\n"

    header += "*By Category:*\n"
    for r in cats:
        header += f"  • _{r['category']}_: {fmt_amount(r['total'])} ({r['count']} tx)\n"

    header += f"\n_{len(rows)} transactions total_"

    await update.message.reply_text(
        header,
        parse_mode="Markdown",
        reply_markup=build_back_kb()
    )


# ─────────────────────────────────────────────────────────────
#  /budget
# ─────────────────────────────────────────────────────────────

async def cmd_budget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args  # e.g. ["Food", "500"] from /budget Food 500

    # Set budget mode: /budget Category Amount
    if args and len(args) >= 2:
        try:
            limit = float(args[-1])
            category = " ".join(args[:-1]).title()
            db.set_budget(category, limit)
            await update.message.reply_text(
                f"✅ Budget set: *{category}* → {fmt_amount(limit)}/month",
                parse_mode="Markdown"
            )
            return
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid format. Use: `/budget CategoryName 500`",
                parse_mode="Markdown"
            )
            return

    # Set global budget: /budget 3000
    if args and len(args) == 1:
        try:
            limit = float(args[0])
            db.set_setting("monthly_budget", str(limit))
            await update.message.reply_text(
                f"✅ Monthly budget set to {fmt_amount(limit)}",
                parse_mode="Markdown"
            )
            return
        except ValueError:
            pass

    # View budgets
    budgets = db.get_budgets()
    cats    = db.get_category_totals()
    spent   = {r["category"]: r["total"] for r in cats}
    global_budget = float(db.get_setting("monthly_budget") or 3000)

    lines = [f"💰 *Budget Overview*\n"]
    lines.append(f"🌍 Global monthly budget: {fmt_amount(global_budget)}\n")

    if budgets:
        lines.append("*Category limits:*")
        for b in budgets:
            cat   = b["category"]
            limit = b["monthly_limit"]
            used  = spent.get(cat, 0)
            pct   = used / limit * 100 if limit else 0
            icon  = "🟢" if pct < 75 else ("🟡" if pct < 100 else "🔴")
            lines.append(
                f"  {icon} *{cat}*\n"
                f"     {fmt_amount(used)} / {fmt_amount(limit)} ({pct:.0f}%)"
            )
    else:
        lines.append("_No category budgets set._")
        lines.append("\nSet one with: `/budget Food 500`")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=build_back_kb()
    )


# ─────────────────────────────────────────────────────────────
#  /dashboard
# ─────────────────────────────────────────────────────────────

async def cmd_dashboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📊 Generating your dashboard…")

    try:
        cats   = db.get_category_totals()
        daily  = db.get_daily_totals_this_month()
        trend  = db.get_monthly_trend(6)
        budget = float(db.get_setting("monthly_budget") or 3000)

        buf = generate_dashboard(
            category_totals=[dict(r) for r in cats],
            daily_totals   =[dict(r) for r in daily],
            monthly_trend  =[dict(r) for r in trend],
            monthly_budget  =budget,
            currency        =CURRENCY,
        )

        await update.message.reply_photo(
            photo=buf,
            caption=(
                f"📊 *Spending Dashboard — {datetime.now().strftime('%B %Y')}*\n"
                f"Tap to expand for full view."
            ),
            parse_mode="Markdown",
        )
        await msg.delete()
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        await msg.edit_text("❌ Could not generate dashboard. Check logs.")


# ─────────────────────────────────────────────────────────────
#  INLINE BUTTON CALLBACKS
# ─────────────────────────────────────────────────────────────

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "dashboard":
        # Reuse dashboard logic
        ctx.args = []
        update.message = query.message
        await cmd_dashboard(update, ctx)
    elif query.data == "month":
        update.message = query.message
        await cmd_month(update, ctx)


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

    text = (
        f"{icon} *New Transaction Detected*\n\n"
        f"🏪 *{tx['merchant']}*\n"
        f"💰 {fmt_amount(tx['amount'])}\n"
        f"🗂️ {tx['category']}\n"
        f"📅 {tx['date']}\n"
        f"🏦 Parsed from: {tx.get('bank', 'Email')}"
    )

    await app.bot.send_message(
        chat_id=CHAT_ID,
        text=text,
        parse_mode="Markdown",
    )


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
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("today",     cmd_today))
    app.add_handler(CommandHandler("month",     cmd_month))
    app.add_handler(CommandHandler("budget",    cmd_budget))
    app.add_handler(CommandHandler("dashboard", cmd_dashboard))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    return app
