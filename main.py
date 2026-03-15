"""
main.py — Entry point: Telegram bot + FastAPI web server + Gmail polling scheduler

Runs three things concurrently:
  1. Telegram bot (long-polling via python-telegram-bot)
  2. FastAPI web server (uvicorn, for OAuth callbacks & health checks)
  3. APScheduler job that polls Gmail API for every connected user
"""

import os
import sys
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import src.database as db
from src.bot import build_app, notify_transaction
from src.gmail_client import refresh_access_token, fetch_transactions_for_user
from src.encryption import encrypt, decrypt

# ── Fix Windows console Unicode (emoji) encoding ──────────────
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

os.makedirs("logs", exist_ok=True)

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
#  GMAIL CHECK JOB  (multi-user, runs every N minutes)
# ─────────────────────────────────────────────────────────────

async def check_gmail_all_users(telegram_app):
    """For every user with a Gmail connection, refresh token → fetch → parse → save → notify."""
    connections = db.get_all_gmail_connections()
    if not connections:
        logger.info("No Gmail connections to check.")
        return

    logger.info(f"Checking Gmail for {len(connections)} user(s)...")

    for conn in connections:
        user_id = conn["user_id"]
        try:
            # Refresh access token if expired (or nearly expired)
            token_expiry = conn.get("token_expiry")
            access_token_enc = conn["access_token_encrypted"]

            needs_refresh = True
            if token_expiry and token_expiry > datetime.now(timezone.utc) + timedelta(minutes=2):
                needs_refresh = False

            if needs_refresh:
                result = await refresh_access_token(conn["refresh_token_encrypted"])
                access_token = result["access_token"]
                new_expiry = datetime.now(timezone.utc) + timedelta(seconds=result["expires_in"])
                access_token_enc = encrypt(access_token)
                db.update_gmail_tokens(user_id, access_token_enc, new_expiry)
                logger.info(f"Refreshed token for user {user_id}")
            else:
                access_token = decrypt(access_token_enc)

            # Fetch new messages (look back 2x the poll interval to avoid gaps)
            interval_min = int(os.getenv("EMAIL_CHECK_INTERVAL", "5"))
            days_back = max(1, round((interval_min * 2) / 1440) + 1)
            transactions = await fetch_transactions_for_user(access_token, days_back=days_back)

            for tx in transactions:
                row_id = db.add_transaction(
                    user_id=user_id,
                    date_str=tx["date"],
                    amount=tx["amount"],
                    merchant=tx["merchant"],
                    category=tx["category"],
                    description=tx.get("description", ""),
                    source_message_id=tx.get("source_message_id"),
                    currency=tx.get("currency", "$"),
                )
                if row_id:
                    logger.info(f"User {user_id}: saved tx #{row_id}: {tx['merchant']} {tx.get('currency', '$')}{tx['amount']}")
                    # Send Telegram notification
                    tg_user_id = db.get_telegram_user_id_for(user_id)
                    if tg_user_id:
                        try:
                            await notify_transaction(telegram_app, tg_user_id, tx)
                        except Exception as e:
                            logger.error(f"Failed to notify user {user_id}: {e}")
                else:
                    logger.debug(f"User {user_id}: skipped duplicate {tx.get('source_message_id')}")

            # Stamp the last successful check time for this user
            db.update_last_gmail_check(user_id, datetime.now(timezone.utc))

        except Exception as e:
            logger.error(f"Gmail check failed for user {user_id}: {e}")

    logger.info("Gmail check done.")


# ─────────────────────────────────────────────────────────────
#  STARTUP
# ─────────────────────────────────────────────────────────────

async def run_bot(telegram_app):
    """Initialise and run the Telegram bot with long-polling."""
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram bot is running.")


async def run_web_server():
    """Run the FastAPI/uvicorn web server."""
    import uvicorn
    from src.web import app as fastapi_app

    port = int(os.getenv("PORT", "8080"))
    config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    logger.info(f"FastAPI server starting on port {port}")
    await server.serve()


async def run_scheduler(telegram_app):
    """Run periodic Gmail check using APScheduler."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    interval_min = int(os.getenv("EMAIL_CHECK_INTERVAL", "5"))
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_gmail_all_users,
        "interval",
        minutes=interval_min,
        args=[telegram_app],
        id="gmail_check",
        max_instances=1,
        next_run_time=datetime.now() + timedelta(seconds=10),  # first run 10s after start
    )
    scheduler.start()
    logger.info(f"Gmail check scheduled every {interval_min} min")

    try:
        await asyncio.Event().wait()  # keep running forever
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


async def main():
    db.init_db()

    telegram_app = build_app()

    # Run bot polling, web server, and scheduler concurrently
    await run_bot(telegram_app)

    try:
        await asyncio.gather(
            run_web_server(),
            run_scheduler(telegram_app),
        )
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()
        logger.info("Bot stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
