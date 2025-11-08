"""
Kalshi high-probability notifier that surfaces nearly certain YES markets.
"""
import argparse
import asyncio
import html
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from config import load_config
from kalshi_client import KalshiClient


class SimpleTradingBot:
    """Notification-first bot that looks for high-confidence YES markets."""

    def __init__(self, max_close_ts: Optional[int] = None):
        self.config = load_config()
        self.console = Console()
        self.kalshi_client: Optional[KalshiClient] = None
        self.max_close_ts = max_close_ts

        # Default to config-specified window if CLI override absent
        if self.max_close_ts is None and self.config.max_hours_to_close:
            self.max_close_ts = int(time.time()) + int(self.config.max_hours_to_close * 3600)

        # Telegram (optional)
        self.telegram_bot: Optional[Bot] = None
        if self.config.telegram_bot_token and self.config.telegram_chat_id:
            try:
                self.telegram_bot = Bot(token=self.config.telegram_bot_token)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error(f"Failed to initialize Telegram bot: {exc}")

    async def initialize(self):
        """Initialize the Kalshi client and authenticate."""
        self.console.print("[bold blue]Initializing high-probability notifier...[/bold blue]")
        self.kalshi_client = KalshiClient(
            self.config.kalshi,
            self.config.max_hours_to_close,
            self.config.max_markets_per_event,
            max_close_ts=self.max_close_ts,
        )

        await self.kalshi_client.login()
        self.console.print("[green]✓ Kalshi API connected[/green]")

        env_color = "green" if self.config.kalshi.use_demo else "yellow"
        env_name = "DEMO" if self.config.kalshi.use_demo else "PRODUCTION"
        self.console.print(f"[{env_color}]Environment: {env_name}[/{env_color}]")
        self.console.print(f"[blue]Max events: {self.config.max_events_to_analyze}[/blue]")
        self.console.print(f"[blue]Max markets per event: {self.config.max_markets_per_event}[/blue]")
        self.console.print(
            f"[blue]Filters → YES ≥ {self.config.min_yes_price_cents}¢, spread ≥ {self.config.min_spread_cents}¢, "
            f"volume ≥ {self.config.min_volume_24h}, closes ≤ {self.config.max_hours_to_close}h[/blue]"
        )
        if self.telegram_bot:
            self.console.print("[blue]Telegram notifications: Enabled[/blue]")
        else:
            self.console.print("[yellow]Telegram notifications: Disabled (set TELEGRAM_* env vars to enable)[/yellow]")

    async def get_top_events(self) -> List[Dict[str, Any]]:
        """Get top events sorted by 24-hour volume."""
        self.console.print("[bold]Step 1: Fetching top events...[/bold]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True,
        ) as progress:
            task = progress.add_task("Fetching events...", total=None)
            try:
                fetch_limit = self.config.max_events_to_analyze * 3
                events = await self.kalshi_client.get_events(limit=fetch_limit)
                progress.update(task, completed=fetch_limit)
                self.console.print(f"[green]✓ Retrieved {len(events)} events[/green]")
                return events
            except Exception as exc:
                progress.update(task, completed=fetch_limit)
                self.console.print(f"[red]Error fetching events: {exc}[/red]")
                return []

    async def get_markets_for_events(
        self, events: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Convert event payloads into the structure expected downstream."""
        self.console.print(f"\n[bold]Step 2: Processing markets for {len(events)} events...[/bold]")
        event_markets: Dict[str, Dict[str, Any]] = {}

        for event in events:
            event_ticker = event.get("event_ticker")
            if not event_ticker:
                continue

            markets = event.get("markets", [])
            top_markets = []
            for market in markets[: self.config.max_markets_per_event]:
                top_markets.append(
                    {
                        "ticker": market.get("ticker", ""),
                        "title": market.get("title", ""),
                        "subtitle": market.get("subtitle", ""),
                        "volume": market.get("volume", 0),
                        "volume_24h": market.get("volume_24h", 0),
                        "close_time": market.get("close_time", ""),
                    }
                )

            if top_markets:
                event_markets[event_ticker] = {"event": event, "markets": top_markets}

        self.console.print(
            f"[green]✓ Prepared {sum(len(data['markets']) for data in event_markets.values())} markets "
            f"across {len(event_markets)} events[/green]"
        )
        return event_markets

    async def get_market_odds(self, event_markets: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Fetch current order book snapshots for all markets."""
        self.console.print(f"\n[bold]Step 3: Fetching current market odds...[/bold]")
        tickers: List[str] = []
        for data in event_markets.values():
            for market in data["markets"]:
                ticker = market.get("ticker")
                if ticker:
                    tickers.append(ticker)

        market_odds: Dict[str, Dict[str, Any]] = {}
        batch_size = 20
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
        ) as progress:
            task = progress.add_task("Pulling odds...", total=len(tickers))
            for i in range(0, len(tickers), batch_size):
                batch = tickers[i : i + batch_size]
                tasks = [self.kalshi_client.get_market_with_odds(t) for t in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for ticker, result in zip(batch, results):
                    if isinstance(result, Exception) or not result:
                        self.console.print(f"[red]✗ Failed to load odds for {ticker}[/red]")
                    else:
                        market_odds[ticker] = result
                    progress.update(task, advance=1)
                await asyncio.sleep(0.2)

        self.console.print(f"[green]✓ Loaded odds for {len(market_odds)} markets[/green]")
        return market_odds

    def filter_high_probability_markets(
        self,
        event_markets: Dict[str, Dict[str, Any]],
        market_odds: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Apply high-confidence filters (price, spread, expiration, volume)."""
        if not event_markets:
            return []

        now_ts = int(time.time())
        max_close_ts = self.max_close_ts or (now_ts + int(self.config.max_hours_to_close * 3600))
        results: List[Dict[str, Any]] = []
        total_markets = sum(len(data["markets"]) for data in event_markets.values())
        rejects = {
            "no_odds": 0,
            "price": 0,
            "spread": 0,
            "expiration": 0,
            "volume": 0,
        }

        for event_ticker, data in event_markets.items():
            event = data["event"]
            event_volume = event.get("volume_24h", 0)
            event_slug = self._event_slug(event_ticker)
            for market in data["markets"]:
                ticker = market.get("ticker")
                if not ticker:
                    continue

                odds = market_odds.get(ticker)
                if not odds:
                    rejects["no_odds"] += 1
                    continue

                yes_bid = odds.get("yes_bid")
                yes_ask = odds.get("yes_ask")
                if yes_bid is None or yes_ask is None:
                    continue
                if yes_bid < self.config.min_yes_price_cents:
                    rejects["price"] += 1
                    continue

                spread = yes_ask - yes_bid
                if spread < self.config.min_spread_cents:
                    rejects["spread"] += 1
                    continue

                close_ts = self._parse_kalshi_timestamp(odds.get("close_time") or market.get("close_time"))
                if close_ts is None or close_ts <= now_ts:
                    rejects["expiration"] += 1
                    continue
                if max_close_ts and close_ts > max_close_ts:
                    rejects["expiration"] += 1
                    continue

                hours_to_close = self._hours_until(close_ts)
                market_volume = max(
                    market.get("volume_24h", 0),
                    market.get("volume", 0),
                    odds.get("volume", 0),
                )
                if max(event_volume, market_volume) < self.config.min_volume_24h:
                    rejects["volume"] += 1
                    continue

                roi_cents = max(0, 100 - yes_bid)
                roi_pct = (roi_cents / yes_bid * 100) if yes_bid else 0
                ticker_base = ticker.rsplit("-", 1)[0].lower()
                market_subtitle = market.get("subtitle") or market.get("yes_sub_title") or ""

                results.append(
                    {
                        "ticker": ticker,
                        "ticker_base": ticker_base,
                        "event_ticker": event_ticker,
                        "event_slug": event_slug,
                        "event_title": event.get("title", "N/A"),
                        "market_title": market.get("title", "N/A"),
                        "market_subtitle": market_subtitle,
                        "yes_bid": yes_bid,
                        "yes_ask": yes_ask,
                        "spread": spread,
                        "hours_to_close": hours_to_close,
                        "close_ts": close_ts,
                        "event_volume_24h": event_volume,
                        "market_volume": market_volume,
                        "roi_cents": roi_cents,
                        "roi_pct": roi_pct,
                    }
                )

        results.sort(
            key=lambda item: (
                -item["roi_pct"],
                item["hours_to_close"] if item["hours_to_close"] is not None else float("inf"),
            )
        )

        kept = len(results)
        self.console.print(
            f"[blue]Filter summary: kept {kept}/{total_markets} markets "
            f"(price rejects: {rejects['price']}, spread: {rejects['spread']}, "
            f"expiration: {rejects['expiration']}, volume: {rejects['volume']}, odds: {rejects['no_odds']})[/blue]"
        )

        return results

    def render_console_table(self, markets: List[Dict[str, Any]]):
        """Display qualifying markets in a Rich table."""
        if not markets:
            self.console.print("[yellow]No markets met the high-probability criteria.[/yellow]")
            return

        table = Table(title="High-Probability YES Markets", show_lines=True)
        table.add_column("Ticker", style="cyan")
        table.add_column("Event", style="green")
        table.add_column("Market", style="white")
        table.add_column("Outcome", style="magenta")
        table.add_column("Yes Bid", justify="right")
        table.add_column("Yes Ask", justify="right")
        table.add_column("Spread", justify="right")
        table.add_column("ROI", justify="right")
        table.add_column("Closes In", justify="right")
        table.add_column("24h Volume", justify="right")

        for market in markets:
            subtitle = market.get("market_subtitle") or "—"
            subtitle_disp = subtitle[:30] + ("…" if len(subtitle) > 30 else "")
            table.add_row(
                market["ticker"],
                market["event_title"][:35] + ("…" if len(market["event_title"]) > 35 else ""),
                market["market_title"][:40] + ("…" if len(market["market_title"]) > 40 else ""),
                subtitle_disp,
                f"{market['yes_bid']}¢",
                f"{market['yes_ask']}¢",
                f"{market['spread']}¢",
                f"{market['roi_cents']}¢ ({market['roi_pct']:.1f}%)",
                self._format_hours(market["hours_to_close"]),
                f"{max(market['event_volume_24h'], market['market_volume']):,}",
            )

        self.console.print()
        self.console.print(table)

    async def send_telegram_notifications(self, markets: List[Dict[str, Any]]):
        """Send the top N markets to Telegram."""
        if not self.telegram_bot or not self.config.telegram_chat_id:
            return
        if not markets:
            self.console.print("[yellow]Telegram skipped: no qualifying markets this run.[/yellow]")
            return

        top_n = min(len(markets), self.config.max_notifications_per_run)
        self.console.print(f"[blue]Sending {top_n} Telegram notification(s)...[/blue]")
        seen_pairs = set()
        sent = 0
        for market in markets:
            key = (market.get("event_ticker"), market.get("market_subtitle") or market["ticker"])
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            message = self._format_market_message(market)
            try:
                await self.telegram_bot.send_message(
                    chat_id=self.config.telegram_chat_id,
                    text=message,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                self.console.print(f"[green]✓ Telegram alert sent for {market['ticker']}[/green]")
                sent += 1
                if sent >= top_n:
                    break
            except TelegramError as exc:
                logger.error(f"Telegram error for {market['ticker']}: {exc}")
                self.console.print(f"[red]✗ Telegram failed for {market['ticker']}[/red]")

    async def _safe_telegram_message(self, text: str):
        if not self.telegram_bot:
            return
        try:
            await self.telegram_bot.send_message(
                chat_id=self.config.telegram_chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
            )
        except TelegramError as exc:  # pragma: no cover
            logger.error(f"Telegram error: {exc}")

    def _format_market_message(self, market: Dict[str, Any]) -> str:
        """Build a concise Telegram message for a market."""
        market_url = self._build_market_url(
            market["ticker"],
            market.get("event_ticker"),
            market.get("market_subtitle") or market["market_title"],
            market.get("ticker_base"),
        )
        title_link = f'<a href="{market_url}">{html.escape(market["event_title"])}</a>'
        outcome = market.get("market_subtitle") or market["market_title"]
        outcome_line = html.escape(outcome)
        return (
            f"🎯 {title_link}\n"
            f"{outcome_line}\n\n"
            f"Ticker: <code>{market['ticker']}</code>\n"
            f"Yes bid/ask: {market['yes_bid']}¢ / {market['yes_ask']}¢ (spread {market['spread']}¢)\n"
            f"Expected return: {market['roi_cents']}¢ ({market['roi_pct']:.1f}%)\n"
            f"Closes in: {self._format_hours(market['hours_to_close'])}\n"
            f"24h volume: {max(market['event_volume_24h'], market['market_volume']):,}"
        )

    def _format_hours(self, hours: Optional[float]) -> str:
        if hours is None:
            return "unknown"
        if hours <= 0:
            return "closed"
        if hours >= 24:
            return f"{hours/24:.1f}d"
        return f"{hours:.1f}h"

    @staticmethod
    def _hours_until(close_ts: Optional[int]) -> Optional[float]:
        if close_ts is None:
            return None
        return (close_ts - time.time()) / 3600

    @staticmethod
    def _parse_kalshi_timestamp(ts: Optional[str]) -> Optional[int]:
        if not ts:
            return None
        try:
            if ts.endswith("Z"):
                ts = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            return None

    @staticmethod
    def _event_slug(event_ticker: Optional[str]) -> str:
        if not event_ticker:
            return "market"
        slug = event_ticker.lower()
        match = re.search(r"-(\d{2}[a-z]{3}\d{2})$", slug)
        if match:
            slug = slug[: match.start()]
        return slug

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "market"

    def _build_market_url(
        self,
        ticker: str,
        event_ticker: Optional[str],
        market_subtitle: str,
        ticker_base: Optional[str],
    ) -> str:
        base = (ticker_base or ticker).lower()
        event_slug = self._event_slug(event_ticker or ticker)
        outcome_slug = self._slugify(market_subtitle or ticker)
        return f"https://kalshi.com/markets/{event_slug}/{outcome_slug}/{base}"

    async def run(self):
        """Main execution pipeline."""
        try:
            await self.initialize()
            events = await self.get_top_events()
            if not events:
                self.console.print("[red]No events returned. Exiting.[/red]")
                return

            event_markets = await self.get_markets_for_events(events)
            if not event_markets:
                self.console.print("[red]No markets to process. Exiting.[/red]")
                return

            # Keep only the top N events by 24h volume after loading markets
            if len(event_markets) > self.config.max_events_to_analyze:
                sorted_events = sorted(
                    event_markets.items(),
                    key=lambda item: item[1]["event"].get("volume_24h", 0),
                    reverse=True,
                )
                event_markets = dict(sorted_events[: self.config.max_events_to_analyze])

            market_odds = await self.get_market_odds(event_markets)
            if not market_odds:
                self.console.print("[red]Unable to load market odds. Exiting.[/red]")
                return

            qualifying_markets = self.filter_high_probability_markets(event_markets, market_odds)
            self.render_console_table(qualifying_markets)
            await self.send_telegram_notifications(qualifying_markets)

            self.console.print("\n[bold green]Run complete.[/bold green]")
        finally:
            if self.kalshi_client:
                await self.kalshi_client.close()


async def main(max_expiration_hours: Optional[int] = None):
    """Entry point for async execution."""
    max_close_ts = None
    if max_expiration_hours is not None:
        max_close_ts = int(time.time()) + max(1, max_expiration_hours) * 3600
    bot = SimpleTradingBot(max_close_ts=max_close_ts)
    await bot.run()


def cli():
    """Command-line interface entry point."""
    parser = argparse.ArgumentParser(
        description="Kalshi high-probability notifier (dry-run only)",
    )
    parser.add_argument(
        "--max-expiration-hours",
        type=int,
        default=None,
        help="Override MAX_HOURS_TO_CLOSE for this run.",
    )

    args = parser.parse_args()

    try:
        asyncio.run(main(max_expiration_hours=args.max_expiration_hours))
    except Exception as exc:  # pragma: no cover - CLI safety
        console = Console()
        console.print(f"[red]Error: {exc}[/red]")
        console.print("[yellow]Please verify your .env configuration.[/yellow]")


if __name__ == "__main__":
    cli()
