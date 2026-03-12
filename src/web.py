"""
web.py — FastAPI web server for health checks and Google OAuth callback.

Routes:
  GET  /health                  → health check
  GET  /auth/google/start       → redirect user to Google OAuth consent
  GET  /auth/google/callback    → exchange code for tokens, store in DB
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
import httpx

import src.database as db
from src.encryption import encrypt

logger = logging.getLogger(__name__)

app = FastAPI(title="Budget Tracker Bot")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "")

SCOPES = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


# ── Health ────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── OAuth: Start ──────────────────────────────────────────────

@app.get("/auth/google/start")
def auth_google_start(telegram_user_id: int):
    """
    Redirect user to Google consent screen.
    The telegram_user_id is passed as the OAuth state parameter so the
    callback knows which user initiated the flow.
    """
    if not GOOGLE_CLIENT_ID or not GOOGLE_REDIRECT_URI:
        raise HTTPException(500, "Google OAuth is not configured")

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": str(telegram_user_id),
    }
    url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url)


# ── OAuth: Callback ───────────────────────────────────────────

@app.get("/auth/google/callback")
async def auth_google_callback(code: str = "", state: str = "", error: str = ""):
    """
    Google redirects here after consent.
    Exchange the auth code for tokens and store them encrypted.
    """
    if error:
        return HTMLResponse(
            f"<h2>Authorization failed</h2><p>{error}</p>"
            "<p>You can close this window and try again with /connectgmail.</p>",
            status_code=400,
        )

    if not code or not state:
        raise HTTPException(400, "Missing code or state parameter")

    try:
        telegram_user_id = int(state)
    except ValueError:
        raise HTTPException(400, "Invalid state parameter")

    # Look up internal user
    user_id = db.get_user_id(telegram_user_id)
    if not user_id:
        return HTMLResponse(
            "<h2>User not found</h2>"
            "<p>Please send /start to the bot first, then try /connectgmail again.</p>",
            status_code=404,
        )

    # Exchange auth code for tokens
    async with httpx.AsyncClient() as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": GOOGLE_REDIRECT_URI,
        })
        if resp.status_code != 200:
            logger.error(f"Token exchange failed: {resp.text}")
            return HTMLResponse(
                "<h2>Token exchange failed</h2><p>Please try again.</p>",
                status_code=502,
            )
        token_data = resp.json()

    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 3600)

    if not refresh_token:
        return HTMLResponse(
            "<h2>Missing refresh token</h2>"
            "<p>Google did not return a refresh token. "
            "Try revoking access at "
            "<a href='https://myaccount.google.com/permissions'>Google Account Permissions</a> "
            "and re-authorizing.</p>",
            status_code=400,
        )

    # Fetch user's email address
    google_email = ""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code == 200:
                google_email = resp.json().get("email", "")
    except Exception as e:
        logger.warning(f"Could not fetch Google email: {e}")

    # Encrypt & store
    token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    db.save_gmail_connection(
        user_id=user_id,
        google_email=google_email,
        refresh_token_enc=encrypt(refresh_token),
        access_token_enc=encrypt(access_token),
        token_expiry=token_expiry,
    )

    logger.info(f"Gmail connected for user {user_id} ({google_email})")

    return HTMLResponse(
        f"<h2>Gmail Connected!</h2>"
        f"<p>Account: <b>{google_email or '(unknown)'}</b></p>"
        f"<p>Your bank emails will now be imported automatically.</p>"
        f"<p>You can close this window and return to Telegram.</p>",
    )
