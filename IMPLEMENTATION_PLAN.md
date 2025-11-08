# AI-Free High-Probability Bot Plan

## Objectives
- Remove all Octagon/OpenAI dependencies and operate purely on Kalshi market data.
- Surface “near-certain” YES markets (≥90¢ by default) that close soon and have basic liquidity so they can be manually swept for quick, low-risk returns.
- Present every qualifying market in a Rich console table and mirror the top N entries to Telegram; keep trading disabled.
- Maintain the hourly GitHub Actions workflow with the leaner runtime and configuration.

## Key Design Decisions
1. **AI-Free Pipeline** – Delete research/decision stages; only Kalshi APIs determine results.
2. **Configurable High-Probability Filters** – Require `MIN_YES_PRICE_CENTS`, `MAX_HOURS_TO_CLOSE`, `MIN_SPREAD_CENTS`, plus `MIN_VOLUME_24H` to avoid thin markets.
3. **ROI Snapshot** – Show implied return (100 - yes_price) in cents and hours-to-close for instant triage.
4. **Notification-Only Default** – Leave `DISABLE_TRADING=true`; no automated orders.
5. **Top-N Alerts** – Limit Telegram blasts to the best few markets while still displaying all matches in the console table.

## Workstream Breakdown

### 1. Dependency & Config Cleanup
- **Files**: `pyproject.toml`, `uv.lock`, `config.py`, `env_template.txt`
- Remove Octagon/OpenAI dependencies and config classes.
- Add env vars:
  - `MIN_YES_PRICE_CENTS` (default 90)
  - `MAX_HOURS_TO_CLOSE` (default 24)
  - `MIN_SPREAD_CENTS` (default 1)
  - `MIN_VOLUME_24H` (default 1000)
  - `MAX_NOTIFICATIONS_PER_RUN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DISABLE_TRADING`
- Ensure CLI `--max-expiration-hours` falls back to `MAX_HOURS_TO_CLOSE`.

### 2. Trading Bot Refactor
- **File**: `trading_bot.py`
- Strip imports and methods tied to Octagon/OpenAI, including research, probability extraction, betting decisions, hedging, Kelly sizing, etc., keeping only the event/market fetching, filtering, and notification logic.
- Implement `filter_high_probability_markets()` applying:
  - YES bid ≥ `MIN_YES_PRICE_CENTS`
  - closes within `MAX_HOURS_TO_CLOSE`
  - spread ≥ `MIN_SPREAD_CENTS`
  - event or market volume ≥ `MIN_VOLUME_24H`
- Compute ROI (`100 - yes_bid` cents and percentage).
- Render a Rich table sorted by ROI (or soonest close when ROI ties) showing ticker, event title, YES bid/ask, spread, volume, hours to close, ROI.
- Telegram notifications:
  - Take the console results, limit to `MAX_NOTIFICATIONS_PER_RUN`.
  - Send formatted Markdown/HTML messages with the same fields plus a link to the market if easily derivable.
- Remove `place_bets()` calls (or keep stub logging that trading is disabled).

### 3. Documentation
- **File**: `README.md`
- Update “How It Works”, configuration tables, and setup instructions to describe the new high-probability filter workflow and the absence of AI dependencies.
- Document the new env vars and provide a sample console table + Telegram message snapshot.

### 4. Automation
- **File**: `.github/workflows/bot-scheduler.yml`
- Remove Octagon/OpenAI secrets/envs; keep only Kalshi + Telegram + filter thresholds.
- Maintain hourly cron, `uv sync`, and `uv run trading_bot.py --max-expiration-hours 24`.

### 5. Validation & Presentation
- Manual test: run `uv run trading_bot.py --max-expiration-hours 24` and confirm the console table lists qualifying markets; Telegram messages should match the top rows.
- CI test: rely on workflow logs + Telegram delivery confirmation; runtime should stay under a minute thanks to removed AI calls.
