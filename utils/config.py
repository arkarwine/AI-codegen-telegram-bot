"""Environment-based configuration for both services."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated process settings loaded from environment variables."""

    database_path: Path
    builder_bot_token: str | None
    telegram_api_id: int
    telegram_api_hash: str
    gemini_api_key: str | None
    runtime_poll_interval_seconds: float

    @classmethod
    def from_env(cls) -> "Settings":
        api_id = os.getenv("TELEGRAM_API_ID", "0")
        return cls(
            database_path=Path(os.getenv("DATABASE_PATH", "./botbuilder.sqlite3")),
            builder_bot_token=os.getenv("BUILDER_BOT_TOKEN"),
            telegram_api_id=int(api_id),
            telegram_api_hash=os.getenv("TELEGRAM_API_HASH", ""),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            runtime_poll_interval_seconds=float(os.getenv("RUNTIME_POLL_INTERVAL_SECONDS", "5")),
        )


def require(value: str | None, name: str) -> str:
    """Return an environment value or raise a startup-friendly error."""

    if not value:
        raise RuntimeError(f"{name} is required")
    return value
