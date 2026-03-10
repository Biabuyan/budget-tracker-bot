"""
main.py — Entry point: runs the Telegram bot + email polling scheduler
"""

import os
import sys
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import src.database as db
from src.email_parser import EmailClient
from src.bot import build_app, notify_transaction

os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)

# ── Fix Windows console Unicode (emoji) encoding ──────────────
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
#  EMAIL CHECK JOB (runs every N minutes via scheduler)
# ─────────────────────────────────────────────────────────────

_processed_uids: set = set()


async def check_emails(app, client: EmailClient):
    """Poll inbox, parse new transactions, push Telegram notifications."""
    logger.info("Processing emails...")

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
            currency    = tx.get("currency", "$"),
        )
        if row_id:
            _processed_uids.add(uid)
            logger.info(f"Saved tx #{row_id}: {tx['merchant']} {tx.get('currency', '$')}{tx['amount']}")
            try:
                await notify_transaction(app, tx)
            except Exception as e:
                logger.error(f"Failed to notify for tx #{row_id}: {e}")
        else:
            logger.info(f"Skipped duplicate: {uid}")

    logger.info("Processing emails done")


# ─────────────────────────────────────────────────────────────
#  STARTUP
# ─────────────────────────────────────────────────────────────

async def main():
    db.init_db()

    app = build_app()
    await app.initialize()
    await app.start()

    email_client = EmailClient(
        host          = os.getenv("IMAP_SERVER",       "imap.gmail.com"),
        port          = int(os.getenv("IMAP_PORT",     "993")),
        user          = os.getenv("EMAIL_ADDRESS",     ""),
        password      = os.getenv("EMAIL_PASSWORD",    ""),
        sender_filter = os.getenv("BANK_EMAIL_SENDER", ""),
    )

    interval_min = int(os.getenv("EMAIL_CHECK_INTERVAL", "5"))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_emails,
        "interval",
        minutes       = interval_min,
        args          = [app, email_client],
        id            = "email_check",
        max_instances = 1,
        next_run_time = datetime.now(),   # ← run immediately on startup
    )
    scheduler.start()
    logger.info(f"Email check scheduled every {interval_min} min")

    logger.info("Bot is running. Press Ctrl+C to stop.")
    await app.updater.start_polling(drop_pending_updates=True)

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