# Kalshi High-Probability Notifier

A lean, notification-first bot that scans Kalshi for ultra high-probability YES contracts (≥90¢ by default), highlights the ones closing soon with solid liquidity, and forwards the best ideas to Telegram so you can manually sweep the remaining contracts.

![Trading Bot Flowchart](KalshiDeepTradingBot.png)

## ⚠️ Financial Disclaimer

**IMPORTANT: This software is provided for educational and research purposes only. Trading prediction markets involves significant financial risk.**

- **No Financial Advice**: This bot does not provide financial advice. Interpret the output as raw market data only.
- **Risk of Loss**: Even “high probability” markets can settle against you. Only trade with capital you can afford to lose.
- **No Liability**: Contributors are not liable for any trading losses or damages.
- **Use at Your Own Risk**: By using this software you acknowledge all associated risks.
- **No Warranty**: Provided “as is” with no guarantees of performance or profitability.

## How It Works

1. **Fetch Top Events** – Pulls the most active Kalshi events by 24 h volume.
2. **Grab Markets & Odds** – Collects the top markets per event plus live bid/ask snapshots.
3. **Apply Filters** – Keeps only markets where:
   - YES bid ≥ `MIN_YES_PRICE_CENTS` (default 90¢)
   - Bid/ask spread ≥ `MIN_SPREAD_CENTS`
   - Closes within `MAX_HOURS_TO_CLOSE`
   - Event or market 24 h volume ≥ `MIN_VOLUME_24H`
4. **Summarize ROI** – Calculates the implied return in cents and % (e.g., 95¢ price → 5¢ / 5.3%).
5. **Notify** – Renders a Rich console table for all matches and sends the top N to Telegram.

There is **no AI, research, or auto-trading** — just Kalshi data filtered for “almost done” markets.

## Features

- 🔍 **Configurable Filters** – Tune price, expiration window, spread, and volume thresholds via `.env`.
- 📊 **Rich Console Table** – Quickly scan qualified markets with ROI, spread, and time-to-close.
- 📱 **Telegram Alerts** – Push the top few opportunities to any chat or channel.
- 🛡️ **Dry-Run Only** – `DISABLE_TRADING=true` by default; no Kalshi orders are ever placed.
- ⏱️ **Automation Ready** – GitHub Actions workflow runs hourly for always-on monitoring.

## Quick Start

1. **Install uv**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Install Dependencies**
   ```bash
   uv sync
   ```

3. **Configure Environment**
   ```bash
   cp env_template.txt .env
   # Fill in Kalshi + Telegram values
   ```

4. **Run the Bot**
   ```bash
   uv run trading_bot.py --max-expiration-hours 24
   ```

   The flag overrides `MAX_HOURS_TO_CLOSE` for that run (optional).

### Required Credentials

- **Kalshi API Key + Private Key** – [Get from your Kalshi profile](https://docs.kalshi.com/getting_started/api_keys). Demo credentials are separate from production.
- **Telegram Bot Token & Chat ID** (optional but recommended) – Create a bot with [@BotFather](https://t.me/botfather) and get your chat ID via [@userinfobot](https://t.me/userinfobot).

## Configuration

All settings live in `.env` (see `env_template.txt`):

```env
KALSHI_API_KEY=...
KALSHI_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
KALSHI_USE_DEMO=true

MAX_EVENTS_TO_ANALYZE=50
MAX_MARKETS_PER_EVENT=10
MAX_HOURS_TO_CLOSE=24
MIN_YES_PRICE_CENTS=90
MIN_SPREAD_CENTS=1
MIN_VOLUME_24H=1000

MAX_NOTIFICATIONS_PER_RUN=5
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
DISABLE_TRADING=true
```

Tweak the thresholds to match your comfort level (e.g., set `MIN_YES_PRICE_CENTS=95` and `MAX_HOURS_TO_CLOSE=12` for extra conservatism).

## Telegram Notifications

Once `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set, the bot sends the top `MAX_NOTIFICATIONS_PER_RUN` entries, e.g.:

```
🎯 CONGRESS-23-TAX-CUT
Budget vote passes?

Ticker: CONGRESS-23-TAX-CUT-YES
Yes bid/ask: 95¢ / 96¢ (spread 1¢)
Expected return: 5¢ (5.3%)
Closes in: 3.2h
24h volume: 18,250
```

No orders are submitted; the message is purely informational so you can place trades manually.

## GitHub Actions Automation

`.github/workflows/bot-scheduler.yml` runs every hour (`cron: 0 * * * *`) or on-demand. Configure these repo secrets:

- `KALSHI_API_KEY`
- `KALSHI_PRIVATE_KEY`
- `KALSHI_USE_DEMO`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

The workflow installs dependencies via `uv sync` and executes:

```bash
uv run trading_bot.py --max-expiration-hours 24
```

It forces `DISABLE_TRADING=true` and reuses the filter env values, keeping runs under a minute and within Actions’ free tier limits.

## Project Structure

```
├── trading_bot.py          # Main notifier workflow
├── kalshi_client.py        # Lightweight Kalshi API client
├── config.py               # Env parsing & validation
├── env_template.txt        # Sample .env
├── pyproject.toml / uv.lock# Dependencies (uv)
└── README.md               # This file
```

Legacy AI modules remain in the repo for reference but are no longer used.

## Validation & Troubleshooting

1. Run locally with demo credentials: `uv run trading_bot.py --max-expiration-hours 24`.
2. Ensure the console table lists qualifying markets (or explains why none passed).
3. Confirm Telegram deliveries (if configured).
4. Review GitHub Actions logs for scheduled runs.

If you see no matches, try relaxing filters (e.g., lower `MIN_YES_PRICE_CENTS` or increase `MAX_HOURS_TO_CLOSE`) and re-run.

## License

Educational use only. No warranty. Use at your own risk.
