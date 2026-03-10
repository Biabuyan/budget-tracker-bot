"""
email_parser.py — IMAP email reader + bank transaction parser

Supports pattern-based parsing for common bank email formats.
Add your bank's pattern in BANK_PATTERNS below.
"""

import imaplib
import email
import re
import os
import logging
from datetime import datetime
from email.header import decode_header
from typing import Optional
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
#  CATEGORY KEYWORDS  (merchant name → category)
# ──────────────────────────────────────────────────────────────
CATEGORY_RULES = {
    "Food & Dining":    ["restaurant", "cafe", "coffee", "pizza", "burger", "sushi",
                         "mcdonald", "starbucks", "subway", "grubhub", "doordash",
                         "ubereats", "chipotle", "dunkin", "bakery", "diner"],
    "Groceries":        ["walmart", "target", "kroger", "safeway", "whole foods",
                         "trader joe", "aldi", "publix", "costco", "supermarket", "grocery"],
    "Transport":        ["uber", "lyft", "taxi", "parking", "gas", "shell", "bp",
                         "chevron", "transit", "metro", "train", "airline", "delta",
                         "united", "american airlines", "southwest"],
    "Shopping":         ["amazon", "ebay", "etsy", "zara", "h&m", "nike", "apple",
                         "best buy", "ikea", "shop", "store", "mall"],
    "Entertainment":    ["netflix", "spotify", "hulu", "disney", "cinema", "movie",
                         "theatre", "concert", "steam", "xbox", "playstation", "game"],
    "Health":           ["pharmacy", "cvs", "walgreens", "doctor", "hospital",
                         "clinic", "dental", "gym", "fitness", "health"],
    "Utilities":        ["electric", "water", "gas bill", "internet", "comcast",
                         "verizon", "at&t", "t-mobile", "phone", "utility"],
    "Subscriptions":    ["subscription", "membership", "annual", "monthly plan"],
    "Travel":           ["hotel", "airbnb", "booking", "expedia", "marriott", "hilton"],
}


# ──────────────────────────────────────────────────────────────
#  BANK EMAIL PATTERNS
#  Add your bank's regex pattern here.
#  Each entry: (amount_pattern, merchant_pattern, date_pattern)
#  Use named groups: (?P<amount>...) (?P<merchant>...) (?P<date>...)
# ──────────────────────────────────────────────────────────────
BANK_PATTERNS = [
    # ── Trust Bank Singapore ──────────────────────────────────
    # Matches: "You've spent DKK 175.95 using Trust Link card at Wolt Denmark DK on 10 Mar 2026 21:35SGT"
    {
        "name": "Trust Bank SG",
        "amount":   r"You(?:'|&#39;|&rsquo;|‘|’|ve) ?(?:ve )?spent\s+(?P<currency>[A-Z]{3})\s+(?P<amount>[\d,]+\.?\d*)",
        "merchant": r"card at\s+(?P<merchant>.+?)\s+on\s+\d{1,2}\s+\w+\s+\d{4}",
        "date":     r"on\s+(?P<date>\d{1,2}\s+\w+\s+\d{4})",
    },
    # ── Chase Bank ────────────────────────────────────────────
    {
        "name": "Chase",
        "currency_default": "USD",
        "amount": r"(?:Amount|charged|purchase of)[:\s]*\$(?P<amount>[\d,]+\.?\d*)",
        "merchant": r"(?:at|merchant|from)[:\s]+(?P<merchant>[A-Za-z0-9 &',\.\-]+?)(?:\s*on|\s*for|\n|\r|\.)",
        "date": r"(?:on|date)[:\s]+(?P<date>\w+ \d{1,2},?\s*\d{4}|\d{1,2}/\d{1,2}/\d{2,4})",
    },
    # ── Bank of America ───────────────────────────────────────
    {
        "name": "Bank of America",
        "currency_default": "USD",
        "amount": r"\$(?P<amount>[\d,]+\.\d{2})\s*(?:was charged|charge|transaction)",
        "merchant": r"(?:at|Merchant)[:\s]+(?P<merchant>[A-Za-z0-9 &',\.\-]+?)(?:\n|\r|\.|on\s)",
        "date": r"(?:on|Date)[:\s]*(?P<date>\d{2}/\d{2}/\d{4}|\w+ \d{1,2},?\s*\d{4})",
    },
    # ── Wells Fargo ───────────────────────────────────────────
    {
        "name": "Wells Fargo",
        "currency_default": "USD",
        "amount": r"(?:debit|charge|purchase)[^$]*\$(?P<amount>[\d,]+\.?\d*)",
        "merchant": r"(?:at|to)[:\s]+(?P<merchant>[A-Za-z0-9 &',\.\-]+?)(?:\s*\.|\s*on|\n)",
        "date": r"(?P<date>\d{2}/\d{2}/\d{4})",
    },
    # ── Citi ──────────────────────────────────────────────────
    {
        "name": "Citi",
        "currency_default": "USD",
        "amount": r"(?:Amount|USD)[:\s]*\$?(?P<amount>[\d,]+\.\d{2})",
        "merchant": r"(?:Merchant|Description)[:\s]+(?P<merchant>[A-Za-z0-9 &',\.\-\*]+?)(?:\n|\r|\s{2,})",
        "date": r"(?:Date)[:\s]+(?P<date>\d{2}/\d{2}/\d{4}|\w+\.?\s+\d{1,2},?\s+\d{4})",
    },
    # ── Generic fallback ──────────────────────────────────────
    {
        "name": "Generic",
        "currency_default": "USD",
        "amount": r"\$(?P<amount>[\d,]+\.\d{2})",
        "merchant": r"(?:at|from|merchant)[:\s]+(?P<merchant>[A-Za-z0-9 &',\.\-]+?)(?:\s*[\.\n\r])",
        "date": r"(?P<date>\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\w+ \d{1,2},?\s*\d{4})",
    },
]


# ──────────────────────────────────────────────────────────────

def categorise(merchant: str) -> str:
    m = merchant.lower()
    for category, keywords in CATEGORY_RULES.items():
        if any(kw in m for kw in keywords):
            return category
    return "Uncategorized"


def parse_amount(raw: str) -> Optional[float]:
    try:
        return float(raw.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def parse_date(raw: str) -> Optional[str]:
    """Normalise various date strings to YYYY-MM-DD."""
    if not raw:
        return datetime.now().strftime("%Y-%m-%d")
    raw = raw.strip().rstrip(",")
    formats = [
        "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y",
        "%B %d %Y", "%B %d, %Y", "%b %d %Y", "%b %d, %Y",
        "%b. %d, %Y", "%b. %d %Y",
        "%d %b %Y", "%d %B %Y",   # Trust Bank: "10 Mar 2026"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return datetime.now().strftime("%Y-%m-%d")


def extract_text_from_email(msg) -> str:
    """Extract plain text from an email message (handles multipart)."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body += payload.decode(errors="replace")
            elif ct == "text/html" and not body:
                payload = part.get_payload(decode=True)
                if payload:
                    soup = BeautifulSoup(payload.decode(errors="replace"), "lxml")
                    body += soup.get_text(separator=" ")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            ct = msg.get_content_type()
            if ct == "text/html":
                soup = BeautifulSoup(payload.decode(errors="replace"), "lxml")
                body = soup.get_text(separator=" ")
            else:
                body = payload.decode(errors="replace")
    return body


def parse_transaction_from_text(text: str) -> Optional[dict]:
    """Try each bank pattern and return first successful parse."""
    for pattern in BANK_PATTERNS:
        amount_match  = re.search(pattern["amount"],   text, re.IGNORECASE)
        merchant_match = re.search(pattern["merchant"], text, re.IGNORECASE)
        date_match    = re.search(pattern["date"],     text, re.IGNORECASE)

        if amount_match:
            amount = parse_amount(amount_match.group("amount"))
            if not amount or amount <= 0:
                continue

            # Extract currency: from named group or pattern default
            try:
                currency = amount_match.group("currency")
            except IndexError:
                currency = pattern.get("currency_default", "USD")

            merchant = (merchant_match.group("merchant").strip()
                        if merchant_match else "Unknown Merchant")
            date_str = parse_date(date_match.group("date") if date_match else None)
            category = categorise(merchant)

            return {
                "amount":      amount,
                "currency":    currency,
                "merchant":    merchant,
                "category":    category,
                "date":        date_str,
                "description": text[:300],
                "bank":        pattern["name"],
            }
    return None


# ──────────────────────────────────────────────────────────────
#  IMAP CLIENT
# ──────────────────────────────────────────────────────────────

class EmailClient:
    def __init__(self, host: str, port: int, user: str, password: str,
                 sender_filter: str):
        self.host   = host
        self.port   = port
        self.user   = user
        self.password = password
        self.sender_filter = sender_filter

    def fetch_new_transactions(self, processed_uids: set) -> list[dict]:
        """Connect via IMAP, fetch all emails from bank sender, return parsed transactions."""
        results = []
        try:
            mail = imaplib.IMAP4_SSL(self.host, self.port)
            mail.login(self.user, self.password)
            mail.select("INBOX")

            # Search ALL emails from the bank sender (duplicates blocked by DB unique constraint)
            _, data = mail.search(None, f'FROM "{self.sender_filter}"')
            uids = data[0].split()

            logger.info(f"Found {len(uids)} emails from {self.sender_filter}")

            for uid in uids:
                uid_str = uid.decode()
                if uid_str in processed_uids:
                    continue  # already handled this session

                _, msg_data = mail.fetch(uid, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                text = extract_text_from_email(msg)

                parsed = parse_transaction_from_text(text)
                if parsed:
                    parsed["email_uid"] = uid_str
                    results.append(parsed)
                    logger.info(f"Parsed: {parsed['merchant']} {parsed.get('currency', '$')}{parsed['amount']}")
                else:
                    logger.debug(f"Could not parse email UID {uid_str}")

            mail.logout()
        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP error: {e}")
        except Exception as e:
            logger.error(f"Email fetch error: {e}")

        return results