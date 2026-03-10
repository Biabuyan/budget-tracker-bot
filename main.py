"""
main.py — Entry point: runs the Telegram bot + email polling scheduler
"""

import os
import asyncio
import logging
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import database as db
from email_parser import EmailClient
from bot import build_app, notify_transaction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/bot.log"),
    ],
)
logger = logging.getLogger(__name__)

os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)


# ─────────────────────────────────────────────────────────────
#  EMAIL CHECK JOB (runs every N minutes via scheduler)
# ─────────────────────────────────────────────────────────────

# In-memory set of already-processed email UIDs.
# On restart, SQLite unique constraint prevents duplicates anyway.
_processed_uids: set = set()


async def check_emails(app, client: EmailClient):
    """Poll inbox, parse new transactions, push Telegram notifications."""
    logger.info("🔍 Checking email for new bank transactions…")

    new_txs = client.fetch_new_transactions(_processed_uids)

    for tx in new_txs:
        uid = tx.get("email_uid")
        row_id = db.add_transaction(
            date_str    = tx["date"],
            amount      = tx["amount"],
            merchant    = tx["merchant"],
            category    = tx["category"],
            description = tx.get("description", ""),
            email_uid   = uid,
        )
        if row_id:
            _processed_uids.add(uid)
            logger.info(f"💾 Saved tx #{row_id}: {tx['merchant']} ${tx['amount']}")
            await notify_transaction(app, tx)
        else:
            logger.info(f"⏭️  Skipped duplicate: {uid}")


# ─────────────────────────────────────────────────────────────
#  STARTUP
# ─────────────────────────────────────────────────────────────

async def main():
    # Initialise DB
    db.init_db()

    # Build bot application
    app = build_app()
    await app.initialize()
    await app.start()

    # Email client
    email_client = EmailClient(
        host          = os.getenv("IMAP_SERVER",       "imap.gmail.com"),
        port          = int(os.getenv("IMAP_PORT",     "993")),
        user          = os.getenv("EMAIL_ADDRESS",     ""),
        password      = os.getenv("EMAIL_PASSWORD",    ""),
        sender_filter = os.getenv("BANK_EMAIL_SENDER", ""),
    )

    interval_min = int(os.getenv("EMAIL_CHECK_INTERVAL", "5"))

    # Scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_emails,
        "interval",
        minutes   = interval_min,
        args      = [app, email_client],
        id        = "email_check",
        max_instances=1,
    )
    scheduler.start()
    logger.info(f"⏰ Email check scheduled every {interval_min} min")

    # Start polling Telegram
    logger.info("🤖 Bot is running. Press Ctrl+C to stop.")
    await app.updater.start_polling(drop_pending_updates=True)

    # Run until interrupted
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        scheduler.shutdown()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        logger.info("Bot stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
