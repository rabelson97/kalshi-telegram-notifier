"""
Configuration management for the high-probability Kalshi notifier.
"""
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field, validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class KalshiConfig(BaseModel):
    """Kalshi API configuration."""

    api_key: str = Field(..., description="Kalshi API key")
    private_key: str = Field(..., description="Kalshi private key (PEM format)")
    use_demo: bool = Field(default=True, description="Use demo environment")

    @property
    def base_url(self) -> str:
        """Return the base URL for the selected environment."""
        return "https://demo-api.kalshi.co" if self.use_demo else "https://api.elections.kalshi.com"

    @validator("private_key")
    def validate_private_key(cls, value: str) -> str:
        """Ensure the private key is provided and formatted correctly."""
        if not value or value == "your_kalshi_private_key_here":
            raise ValueError("KALSHI_PRIVATE_KEY is required. Please set it in your .env file.")

        # Allow pointing to a file path for the private key
        if not value.startswith("-----BEGIN") and (Path(value).exists() or value.endswith(".pem")):
            try:
                value = Path(value).read_text()
            except Exception as exc:  # pragma: no cover - just defensive logging
                raise ValueError(f"Could not read private key file '{value}': {exc}") from exc

        stripped = value.strip()
        if not (stripped.startswith("-----BEGIN") and stripped.endswith("-----")):
            raise ValueError(
                "Private key must be in PEM format starting with '-----BEGIN' and ending with '-----'. "
                "Include \\n for line breaks if the key is on a single line."
            )

        return value


def _clean(value: str) -> str:
    """Remove inline comments and trim whitespace from env values."""
    return value.split("#")[0].strip()


class BotConfig(BaseSettings):
    """Main configuration for the notifier."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="allow")

    kalshi: KalshiConfig = Field(..., description="Kalshi configuration")

    # Analysis limits
    dry_run: bool = Field(default=True, description="Always run in dry-run mode (no orders placed)")
    max_events_to_analyze: int = Field(default=600, description="Number of top events to fetch by volume")
    max_markets_per_event: int = Field(default=10, description="Top markets per event to evaluate")

    # Filtering thresholds
    max_hours_to_close: float = Field(default=24.0, description="Only analyze markets closing within N hours")
    min_yes_price_cents: int = Field(default=90, description="Minimum YES bid price in cents")
    min_spread_cents: int = Field(default=1, description="Minimum bid/ask spread in cents")
    max_yes_ask_cents: int = Field(default=98, description="Maximum YES ask price (in cents) to ensure contracts can be purchased immediately")
    min_volume_24h: int = Field(default=1000, description="Minimum 24h volume (event or market) to consider")

    # Notifications
    telegram_bot_token: Optional[str] = Field(default=None, description="Telegram bot token")
    telegram_chat_id: Optional[str] = Field(default=None, description="Telegram chat/channel ID")
    max_notifications_per_run: int = Field(default=5, description="Number of markets to push to Telegram")
    disable_trading: bool = Field(default=True, description="Always disable automated trading")

    def __init__(self, **data):
        private_key = os.getenv("KALSHI_PRIVATE_KEY", "")
        private_key_file = os.getenv("KALSHI_PRIVATE_KEY_FILE", "")
        if private_key_file and not private_key:
            private_key = private_key_file

        kalshi_config = KalshiConfig(
            api_key=os.getenv("KALSHI_API_KEY", ""),
            private_key=private_key,
            use_demo=os.getenv("KALSHI_USE_DEMO", "true").lower() == "true",
        )

        data.update(
            {
                "kalshi": kalshi_config,
                "max_events_to_analyze": int(_clean(os.getenv("MAX_EVENTS_TO_ANALYZE", "600"))),
                "max_markets_per_event": int(_clean(os.getenv("MAX_MARKETS_PER_EVENT", "10"))),
                "max_hours_to_close": float(_clean(os.getenv("MAX_HOURS_TO_CLOSE", "24.0"))),
                "min_yes_price_cents": int(_clean(os.getenv("MIN_YES_PRICE_CENTS", "97"))),
                "min_spread_cents": int(_clean(os.getenv("MIN_SPREAD_CENTS", "1"))),
                "max_yes_ask_cents": int(_clean(os.getenv("MAX_YES_ASK_CENTS", "99"))),
                "min_volume_24h": int(_clean(os.getenv("MIN_VOLUME_24H", "1000"))),
                "telegram_bot_token": (_clean(os.getenv("TELEGRAM_BOT_TOKEN", "")) or None),
                "telegram_chat_id": (_clean(os.getenv("TELEGRAM_CHAT_ID", "")) or None),
                "max_notifications_per_run": int(_clean(os.getenv("MAX_NOTIFICATIONS_PER_RUN", "5"))),
                "disable_trading": _clean(os.getenv("DISABLE_TRADING", "true")).lower() == "true",
            }
        )

        super().__init__(**data)


def load_config() -> BotConfig:
    """Load and validate configuration."""
    return BotConfig()
