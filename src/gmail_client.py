"""
gmail_client.py — Gmail API client (replaces IMAP)

Uses OAuth2 refresh tokens stored per-user to fetch new bank emails
via the Gmail API (googleapis.com/auth/gmail.readonly).
"""

import os
import re
import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from src.encryption import encrypt, decrypt
from src.email_parser import parse_transaction_from_text

logger = logging.getLogger(__name__)

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


# ── Token refresh ─────────────────────────────────────────────

async def refresh_access_token(refresh_token_enc: str) -> dict:
    """
    Exchange a refresh token for a new access token.
    Returns {"access_token": ..., "expires_in": ...} or raises.
    """
    refresh_token = decrypt(refresh_token_enc)
    async with httpx.AsyncClient() as client:
        resp = await client.post(TOKEN_URL, data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
        resp.raise_for_status()
        data = resp.json()
        return {
            "access_token": data["access_token"],
            "expires_in": data.get("expires_in", 3600),
        }


# ── Fetch messages ────────────────────────────────────────────

async def fetch_new_messages(access_token: str,
                             query: str = "is:unread",
                             max_results: int = 20) -> list[dict]:
    """
    Fetch messages matching a Gmail search query.
    Returns list of {"id": ..., "body_text": ...} dicts.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    messages = []

    async with httpx.AsyncClient() as client:
        # List message IDs
        resp = await client.get(
            f"{GMAIL_API}/messages",
            headers=headers,
            params={"q": query, "maxResults": max_results},
        )
        resp.raise_for_status()
        data = resp.json()
        msg_items = data.get("messages", [])

        for item in msg_items:
            msg_id = item["id"]
            # Get full message
            resp2 = await client.get(
                f"{GMAIL_API}/messages/{msg_id}",
                headers=headers,
                params={"format": "full"},
            )
            resp2.raise_for_status()
            msg_data = resp2.json()

            body_text = _extract_body(msg_data)
            messages.append({
                "id": msg_id,
                "body_text": body_text,
            })

    return messages


def _extract_body(msg_data: dict) -> str:
    """Extract plain-text body from a Gmail API message resource."""
    payload = msg_data.get("payload", {})
    parts = payload.get("parts", [])

    # Try to find text/plain part
    for part in parts:
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode(errors="replace")
        # Nested multipart
        for sub in part.get("parts", []):
            if sub.get("mimeType") == "text/plain":
                data = sub.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode(errors="replace")

    # Fallback: text/html → strip tags
    for part in parts:
        if part.get("mimeType") == "text/html":
            data = part.get("body", {}).get("data", "")
            if data:
                html = base64.urlsafe_b64decode(data).decode(errors="replace")
                from bs4 import BeautifulSoup
                return BeautifulSoup(html, "lxml").get_text(separator=" ")

    # Single-part message (no parts array)
    body_data = payload.get("body", {}).get("data", "")
    if body_data:
        raw = base64.urlsafe_b64decode(body_data).decode(errors="replace")
        if payload.get("mimeType", "") == "text/html":
            from bs4 import BeautifulSoup
            return BeautifulSoup(raw, "lxml").get_text(separator=" ")
        return raw

    return ""


# ── High-level: fetch + parse transactions ────────────────────

async def fetch_transactions_for_user(
    access_token: str,
    bank_sender: str = "",
) -> list[dict]:
    """
    Fetch recent bank emails and parse transactions.
    Returns list of parsed transaction dicts with 'source_message_id'.
    """
    # Build Gmail search query
    query_parts = ["is:unread"]
    if bank_sender:
        query_parts.append(f"from:{bank_sender}")
    query = " ".join(query_parts)

    messages = await fetch_new_messages(access_token, query=query)
    transactions = []

    for msg in messages:
        parsed = parse_transaction_from_text(msg["body_text"])
        if parsed:
            parsed["source_message_id"] = msg["id"]
            transactions.append(parsed)
        else:
            logger.debug(f"Could not parse Gmail message {msg['id']}")

    return transactions
