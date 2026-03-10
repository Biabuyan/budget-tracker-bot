# 💰 Budget Tracker Telegram Bot

A production-ready Telegram bot that **automatically imports bank email receipts**, categorises transactions, tracks budgets, and delivers a rich **visual spending dashboard** — all inside Telegram.

---

## ✨ Features

| Feature | Details |
|---|---|
| 📧 **Auto Email Import** | Polls your inbox via IMAP every 5 min for bank receipts |
| 🧠 **Smart Categorisation** | Auto-tags spending: Food, Groceries, Transport, Shopping… |
| 📊 **Visual Dashboard** | Pie chart, daily bar chart, monthly trend line — sent as image |
| 💳 **Real-time Alerts** | Instant Telegram notification for every new transaction |
| 🎯 **Budget Limits** | Set per-category budgets, see % used with visual bar |
| 🏦 **Multi-bank Support** | Patterns for Chase, BofA, Wells Fargo, Citi + generic |

---

## 🗂 Project Structure

```
budget-tracker-bot/
├── main.py              ← Entry point (bot + scheduler)
├── seed_demo.py         ← Populate with demo data for testing
├── requirements.txt
├── .env.example         ← Copy to .env and fill in your values
├── data/
│   └── budget.db        ← SQLite database (auto-created)
├── logs/
│   └── bot.log
└── src/
    ├── bot.py           ← All Telegram command handlers
    ├── database.py      ← SQLite queries
    ├── email_parser.py  ← IMAP client + bank email parsing
    └── dashboard.py     ← Matplotlib chart generator
```

---

## 🚀 Quick Start

### 1. Clone & Install

```bash
git clone <your-repo>
cd budget-tracker-bot
pip install -r requirements.txt
```

### 2. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env` and fill in:

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_CHAT_ID` | Your user ID (get from @userinfobot) |
| `EMAIL_ADDRESS` | Your email address |
| `EMAIL_PASSWORD` | Gmail App Password (not your main password) |
| `IMAP_SERVER` | `imap.gmail.com` for Gmail |
| `BANK_EMAIL_SENDER` | Your bank's sender e.g. `alerts@chase.com` |
| `DEFAULT_MONTHLY_BUDGET` | e.g. `3000` |
| `CURRENCY_SYMBOL` | `$`, `€`, `£`, etc. |

### 3. Gmail App Password Setup

> ⚠️ Gmail requires an **App Password**, not your main account password.

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Enable **2-Step Verification**
3. Go to **App Passwords** → Select app: Mail → Generate
4. Use the 16-character password as `EMAIL_PASSWORD`

### 4. Seed Demo Data (Optional)

```bash
python seed_demo.py
```

This fills the DB with 21 realistic transactions across 3 months so you can test the dashboard right away.

### 5. Run

```bash
python main.py
```

---

## 🤖 Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/help` | Command reference |
| `/today` | All transactions today |
| `/month` | Monthly summary with breakdown |
| `/budget` | View all budgets and usage |
| `/budget Food 500` | Set Food category limit to $500 |
| `/budget 3000` | Set global monthly budget |
| `/dashboard` | Generate & send visual dashboard |

---

## 🏦 Adding Your Bank's Email Pattern

Open `src/email_parser.py` and add an entry to `BANK_PATTERNS`:

```python
{
    "name": "My Bank",
    "amount":   r"\$(?P<amount>[\d,]+\.\d{2})",
    "merchant": r"at (?P<merchant>[A-Za-z0-9 ]+?)(?:\s*on|\n)",
    "date":     r"(?P<date>\d{2}/\d{2}/\d{4})",
},
```

**Tips:**
- Forward a real bank email to yourself
- Use [regex101.com](https://regex101.com) to build your patterns
- The named groups `amount`, `merchant`, `date` are required
- Add it **before** the Generic fallback entry

---

## 📊 Dashboard Preview

The `/dashboard` command generates a 4-panel image:

- **KPI Cards** — Spent, Remaining, Budget, % Used, Transaction Count
- **Category Pie Chart** — Where your money goes
- **Daily Bar Chart** — Spending per day this month
- **Monthly Trend** — 6-month line chart vs budget

---

## 🐳 Run with Docker (Optional)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["python", "main.py"]
```

```bash
docker build -t budget-bot .
docker run -d --env-file .env budget-bot
```

---

## 🔒 Security Notes

- Your `.env` file contains sensitive credentials — **never commit it to git**
- Add `.env` to your `.gitignore`
- Use Gmail App Passwords, not your main password
- The bot only responds to messages from `TELEGRAM_CHAT_ID` — only you can use it

---

## 📦 Dependencies

- `python-telegram-bot` — Telegram Bot API
- `apscheduler` — Email polling scheduler
- `matplotlib` + `pillow` — Dashboard image generation
- `beautifulsoup4` + `lxml` — HTML email parsing
- `python-dotenv` — Environment config
