# Budget Tracker Telegram Bot

A Telegram bot that **automatically imports bank email receipts** via IMAP, categorises transactions, tracks budgets across multiple currencies, and delivers a **visual spending dashboard** — all inside Telegram.

---

## Features

| Feature                    | Details                                                                                                                                     |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **Auto Email Import**      | Polls your inbox via IMAP at a configurable interval for bank receipt emails                                                                |
| **Smart Categorisation**   | Auto-tags merchants into categories: Food & Dining, Groceries, Transport, Shopping, Entertainment, Health, Utilities, Subscriptions, Travel |
| **Multi-Currency Support** | Detects currency from email (e.g. SGD, DKK, USD) and groups transactions by currency                                                        |
| **Visual Dashboard**       | Generates a 4-panel PNG dashboard: KPI cards, category pie chart, daily bar chart, monthly trend                                            |
| **Real-time Alerts**       | Instant Telegram notification with retry logic for every new transaction                                                                    |
| **Budget Limits**          | Set per-category or global monthly budgets; see % used with colour-coded indicators                                                         |
| **Multi-Bank Patterns**    | Built-in regex patterns for Trust Bank SG, Chase, Bank of America, Wells Fargo, Citi, plus a generic fallback                               |

---

## Project Structure

```
budget-tracker-bot/
├── main.py              ← Entry point: bot + email polling scheduler
├── requirements.txt     ← Python dependencies
├── .env                 ← Your credentials (not committed — see .env.example)
├── .env.example         ← Template for environment variables
├── .gitignore
├── data/
│   └── budget.db        ← SQLite database (auto-created on first run)
├── logs/
│   └── bot.log          ← Runtime logs (auto-created)
└── src/
    ├── bot.py           ← Telegram command handlers & notification logic
    ├── database.py      ← SQLite schema, queries & migrations
    ├── email_parser.py  ← IMAP client + bank email regex parsing
    └── dashboard.py     ← Matplotlib chart generator
```

---

## Quick Start

### 1. Clone & Install

```bash
git clone <your-repo-url>
cd budget-tracker-bot
pip install -r requirements.txt
```

**Python 3.10+** is required. Dependencies:

| Package                     | Purpose                      |
| --------------------------- | ---------------------------- |
| `python-telegram-bot==20.7` | Telegram Bot API (async)     |
| `apscheduler==3.10.4`       | Email polling scheduler      |
| `matplotlib==3.8.2`         | Dashboard chart generation   |
| `pillow==10.2.0`            | Image support for matplotlib |
| `beautifulsoup4==4.12.3`    | HTML email body parsing      |
| `lxml==5.1.0`               | HTML parser backend          |
| `python-dotenv==1.0.0`      | `.env` file loading          |
| `aiofiles==23.2.1`          | Async file I/O               |

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your values:

| Variable                 | Required | Description                                                               | Example               |
| ------------------------ | -------- | ------------------------------------------------------------------------- | --------------------- |
| `TELEGRAM_BOT_TOKEN`     | Yes      | Token from [@BotFather](https://t.me/BotFather)                           | `123456:ABC-DEF...`   |
| `TELEGRAM_CHAT_ID`       | Yes      | Your Telegram user ID (get from [@userinfobot](https://t.me/userinfobot)) | `123456789`           |
| `EMAIL_ADDRESS`          | Yes      | Email address to poll for bank receipts                                   | `you@gmail.com`       |
| `EMAIL_PASSWORD`         | Yes      | App password (**not** your main password — see below)                     | `abcd efgh ijkl mnop` |
| `IMAP_SERVER`            | Yes      | Your email provider's IMAP server                                         | `imap.gmail.com`      |
| `IMAP_PORT`              | No       | IMAP port (default: `993`)                                                | `993`                 |
| `BANK_EMAIL_SENDER`      | Yes      | Sender address your bank uses for receipts                                | `alerts@chase.com`    |
| `EMAIL_CHECK_INTERVAL`   | No       | Minutes between email checks (default: `5`)                               | `5`                   |
| `DEFAULT_MONTHLY_BUDGET` | No       | Default monthly budget (default: `3000`)                                  | `3000`                |
| `CURRENCY_SYMBOL`        | No       | Fallback currency symbol (default: `$`)                                   | `$`                   |

### 3. Email Provider Setup

#### Gmail

Gmail requires an **App Password**, not your main account password.

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Enable **2-Step Verification** if not already enabled
3. Navigate to **App Passwords** → Select app: **Mail** → Generate
4. Copy the 16-character password and use it as `EMAIL_PASSWORD` in your `.env`

#### Outlook / Hotmail

1. Use `imap-mail.outlook.com` as `IMAP_SERVER`
2. You may need to enable IMAP access in Outlook settings
3. Use an App Password if 2FA is enabled

#### Other Providers

Set `IMAP_SERVER` and `IMAP_PORT` to your provider's IMAP settings. Most providers use port `993` with SSL.

### 4. Run

```bash
python main.py
```

On startup the bot will:

1. Initialise the SQLite database (`data/budget.db`)
2. Start listening for Telegram commands
3. Immediately check emails, then repeat every `EMAIL_CHECK_INTERVAL` minutes
4. Send you a Telegram notification for each new transaction found

---

## Bot Commands

| Command            | Description                                             |
| ------------------ | ------------------------------------------------------- |
| `/start`           | Welcome message with command overview                   |
| `/help`            | Detailed command reference                              |
| `/today`           | Today's transactions, grouped by currency               |
| `/month`           | Monthly summary with category breakdown per currency    |
| `/budget`          | View all budgets and usage with colour-coded indicators |
| `/budget Food 500` | Set the Food category limit to 500/month                |
| `/budget 3000`     | Set the global monthly budget to 3000                   |
| `/dashboard`       | Generate and send a visual spending dashboard image     |

Inline buttons for **Dashboard** and **This Month** appear below transaction messages for quick navigation.

---

## Adding a Custom Bank Pattern

Edit `src/email_parser.py` and add an entry to the `BANK_PATTERNS` list **before** the Generic fallback:

```python
{
    "name": "My Bank",
    "currency_default": "USD",                                          # fallback currency
    "amount":   r"(?:charged|spent)\s*\$(?P<amount>[\d,]+\.\d{2})",    # must have (?P<amount>...)
    "merchant": r"at\s+(?P<merchant>[A-Za-z0-9 &',.\-]+?)(?:\s*on|\n)", # must have (?P<merchant>...)
    "date":     r"on\s+(?P<date>\d{2}/\d{2}/\d{4})",                   # must have (?P<date>...)
},
```

**Tips:**

- Forward a real bank email to yourself and inspect the text
- Use [regex101.com](https://regex101.com) to build and test your patterns
- Named groups `amount`, `merchant`, and `date` are required
- To capture currency from the email text (e.g. `SGD`, `EUR`), add a `(?P<currency>[A-Z]{3})` group to the amount pattern instead of using `currency_default`

### Supported Date Formats

The parser auto-detects these date formats:
`MM/DD/YYYY`, `MM/DD/YY`, `MM-DD-YYYY`, `Month DD YYYY`, `Month DD, YYYY`, `DD Mon YYYY`

---

## Dashboard

The `/dashboard` command generates a 4-panel dark-themed image:

| Panel                  | Content                                                                                    |
| ---------------------- | ------------------------------------------------------------------------------------------ |
| **KPI Cards**          | Total Spent (per currency if multi-currency), Remaining, Budget, % Used, Transaction Count |
| **Category Pie Chart** | Spending breakdown by category (and currency when applicable)                              |
| **Daily Bar Chart**    | Spending per day this month (stacked by currency if multi-currency)                        |
| **Monthly Trend**      | 6-month line chart with one line per currency                                              |

---

## How It Works

1. **Email Polling** — `main.py` uses APScheduler to run an IMAP check every N minutes. It searches for emails from your configured `BANK_EMAIL_SENDER`.

2. **Parsing** — Each email body is extracted (HTML emails are converted to text via BeautifulSoup). The text is matched against `BANK_PATTERNS` in order until a pattern successfully extracts an amount, merchant, and date.

3. **Categorisation** — The merchant name is matched against keyword lists in `CATEGORY_RULES` to auto-assign a category (Food & Dining, Groceries, etc.). Unmatched merchants are labelled "Uncategorized".

4. **Storage** — Transactions are stored in SQLite with a `UNIQUE` constraint on `email_uid` to prevent duplicates across restarts.

5. **Notification** — Each new transaction triggers a Telegram message with merchant, amount, currency, category, and date. Notifications retry up to 3 times on timeout.

6. **Dashboard** — Charts are generated by matplotlib and sent as a PNG image via the Telegram Bot API.

---

## Docker (Optional)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "main.py"]
```

```bash
docker build -t budget-bot .
docker run -d --env-file .env --name budget-bot budget-bot
```

---

## Security Notes

- **Never commit `.env`** — it contains your bot token, email credentials, and chat ID. It is already in `.gitignore`.
- Use **App Passwords** for Gmail/Outlook, never your main account password.
- The bot only sends notifications to the `TELEGRAM_CHAT_ID` configured in `.env`.
- The SQLite database and log files are stored locally in `data/` and `logs/`.

---

## License

MIT
