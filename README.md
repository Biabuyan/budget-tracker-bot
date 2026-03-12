# Budget Tracker Telegram Bot

A **multi-user** Telegram bot that automatically imports bank email receipts via the **Gmail API** (OAuth 2.0), categorises transactions, tracks budgets across multiple currencies, and delivers a **visual spending dashboard** — all inside Telegram. Designed to deploy on **Railway** with PostgreSQL.

---

## Features

| Feature                    | Details                                                                                                                                     |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **Multi-User**             | Each Telegram user gets their own account, budgets, and transactions                                                                        |
| **Gmail OAuth**            | Users connect their own Gmail via `/connectgmail` — no shared passwords                                                                     |
| **Auto Email Import**      | Polls Gmail API at a configurable interval for bank receipt emails                                                                          |
| **Smart Categorisation**   | Auto-tags merchants into categories: Food & Dining, Groceries, Transport, Shopping, Entertainment, Health, Utilities, Subscriptions, Travel |
| **Multi-Currency Support** | Detects currency from email (e.g. SGD, DKK, USD) and groups transactions by currency                                                        |
| **Visual Dashboard**       | Generates a 4-panel PNG dashboard: KPI cards, category pie chart, daily bar chart, monthly trend                                            |
| **Real-time Alerts**       | Instant Telegram notification with retry logic for every new transaction                                                                    |
| **Budget Limits**          | Set per-category or global monthly budgets; see % used with colour-coded indicators                                                         |
| **Duplicate Protection**   | `UNIQUE(user_id, source_message_id)` constraint prevents duplicate imports                                                                  |
| **Encrypted Tokens**       | Gmail OAuth tokens are encrypted at rest with Fernet                                                                                        |

---

## Project Structure

```
budget-tracker-bot/
├── main.py              ← Entry point: bot + web server + Gmail scheduler
├── requirements.txt     ← Python dependencies
├── .env                 ← Your credentials (not committed — see .env.example)
├── .env.example         ← Template for environment variables
├── .gitignore
├── logs/
│   └── bot.log          ← Runtime logs (auto-created)
└── src/
    ├── bot.py           ← Telegram command handlers (multi-user)
    ├── database.py      ← PostgreSQL/SQLAlchemy models & queries
    ├── dashboard.py     ← Matplotlib chart generator
    ├── email_parser.py  ← Bank email regex parsing
    ├── encryption.py    ← Fernet encrypt/decrypt for OAuth tokens
    ├── gmail_client.py  ← Gmail API client (replaces IMAP)
    └── web.py           ← FastAPI server: health check + OAuth routes
```

---

## Quick Start

### 1. Clone & Install

```bash
git clone <your-repo-url>
cd budget-tracker-bot
pip install -r requirements.txt
```

**Python 3.10+** is required.

### 2. Create a PostgreSQL Database

If deploying on Railway:

1. Open Railway dashboard → **New** → **Add Database** → **PostgreSQL**
2. Copy the `DATABASE_URL` connection string

For local dev, you can use any PostgreSQL instance.

### 3. Set Up Google OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project (or select existing)
3. **APIs & Services** → **Library** → Enable **Gmail API**
4. **APIs & Services** → **Credentials** → **Create Credentials** → **OAuth Client ID**
   - Application type: **Web application**
   - Authorized redirect URI: `https://YOUR_RAILWAY_APP/auth/google/callback`
5. Copy the **Client ID** and **Client Secret**

### 4. Generate Encryption Key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 5. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your values:

| Variable               | Required | Description                                          |
| ---------------------- | -------- | ---------------------------------------------------- |
| `TELEGRAM_BOT_TOKEN`   | Yes      | Token from [@BotFather](https://t.me/BotFather)      |
| `DATABASE_URL`         | Yes      | PostgreSQL connection string                         |
| `GOOGLE_CLIENT_ID`     | Yes      | From Google Cloud Console                            |
| `GOOGLE_CLIENT_SECRET` | Yes      | From Google Cloud Console                            |
| `GOOGLE_REDIRECT_URI`  | Yes      | `https://YOUR_APP/auth/google/callback`              |
| `APP_BASE_URL`         | Yes      | Public URL of your app (e.g. Railway domain)         |
| `ENCRYPTION_KEY`       | Yes      | Fernet key for token encryption                      |
| `EMAIL_CHECK_INTERVAL` | No       | Minutes between Gmail checks (default: `5`)          |
| `PORT`                 | No       | Web server port (default: `8080`, Railway sets this) |

### 6. Run

```bash
python main.py
```

On startup the bot will:

1. Create all PostgreSQL tables
2. Start the Telegram bot (long-polling)
3. Start the FastAPI web server (port 8080)
4. Start the Gmail polling scheduler (every 5 min)

---

## Bot Commands

| Command            | Description                                             |
| ------------------ | ------------------------------------------------------- |
| `/start`           | Register & welcome message                              |
| `/help`            | Full command reference                                  |
| `/connectgmail`    | Link your Gmail for automatic email import              |
| `/disconnectgmail` | Unlink Gmail                                            |
| `/today`           | Today's transactions, grouped by currency               |
| `/month`           | Monthly summary with category breakdown per currency    |
| `/budget`          | View all budgets and usage with colour-coded indicators |
| `/budget Food 500` | Set the Food category limit to 500/month                |
| `/budget 3000`     | Set the global monthly budget to 3000                   |
| `/dashboard`       | Generate and send a visual spending dashboard image     |

---

## How It Works

1. **User Registration** — `/start` creates a user row in PostgreSQL.

2. **Gmail Connection** — `/connectgmail` sends the user to a Google OAuth consent page. The callback stores encrypted refresh/access tokens in `gmail_connections`.

3. **Email Polling** — APScheduler runs every N minutes. For each user with a Gmail connection, it refreshes the access token, fetches new emails via the Gmail API, and parses them.

4. **Parsing** — Email bodies are matched against bank regex patterns (`BANK_PATTERNS` in `email_parser.py`). The first successful match extracts amount, merchant, currency, and date.

5. **Categorisation** — Merchants are auto-tagged via keyword matching in `CATEGORY_RULES`.

6. **Duplicate Protection** — `UNIQUE(user_id, source_message_id)` prevents the same email from being imported twice.

7. **Notification** — Each new transaction triggers a Telegram message to the user.

8. **Dashboard** — Charts are generated per-user by matplotlib and sent as PNG.

---

## Deploy to Railway

1. Push your code to GitHub
2. Open [Railway](https://railway.app) → **New Project** → **Deploy from GitHub Repo**
3. Add a **PostgreSQL** database (Railway auto-sets `DATABASE_URL`)
4. Add environment variables in the Railway dashboard:
   - `TELEGRAM_BOT_TOKEN`
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `GOOGLE_REDIRECT_URI` → `https://YOUR_RAILWAY_DOMAIN/auth/google/callback`
   - `APP_BASE_URL` → `https://YOUR_RAILWAY_DOMAIN`
   - `ENCRYPTION_KEY`
5. Deploy — Railway will install dependencies and run `python main.py`

### Railway Procfile (optional)

```
web: python main.py
```

---

## Database Schema

```sql
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    telegram_user_id BIGINT UNIQUE NOT NULL,
    telegram_username TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE user_settings (
    user_id BIGINT PRIMARY KEY,
    monthly_budget NUMERIC,
    base_currency TEXT,
    timezone TEXT
);

CREATE TABLE gmail_connections (
    user_id BIGINT PRIMARY KEY,
    google_email TEXT,
    refresh_token_encrypted TEXT,
    access_token_encrypted TEXT,
    token_expiry TIMESTAMPTZ
);

CREATE TABLE transactions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    source_message_id TEXT,
    merchant TEXT,
    amount NUMERIC,
    currency TEXT DEFAULT '$',
    category TEXT DEFAULT 'Uncategorized',
    transaction_date DATE,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, source_message_id)
);

CREATE TABLE budgets (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    category TEXT NOT NULL,
    monthly_limit NUMERIC NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, category)
);
```

---

## Test Flow

```
/start                → register
/connectgmail         → authorize Gmail
(authorize in browser)
(wait for auto-import or send a test bank email)
/today                → see today's transactions
/month                → see monthly summary
/budget Food 500      → set a budget
/budget               → view budgets
/dashboard            → visual dashboard
/disconnectgmail      → unlink Gmail
```
