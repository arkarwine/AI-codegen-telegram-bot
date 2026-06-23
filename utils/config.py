"""Environment-based configuration for both services."""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def configure_logging(service_name: str) -> None:
    """Configure concise stdout logging for systemd and terminal runs."""

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format=f"%(asctime)s %(levelname)s {service_name}: %(message)s",
    )


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated process settings loaded from environment variables."""

    database_path: Path
    builder_bot_token: str | None
    telegram_api_id: int
    telegram_api_hash: str
    gemini_api_key: str | None
    runtime_poll_interval_seconds: float
    owner_telegram_id: int | None

    @classmethod
    def from_env(cls) -> "Settings":
        api_id = _parse_int(os.getenv("TELEGRAM_API_ID"), "TELEGRAM_API_ID")
        poll_interval = _parse_float(
            os.getenv("RUNTIME_POLL_INTERVAL_SECONDS", "5"),
            "RUNTIME_POLL_INTERVAL_SECONDS",
        )
        return cls(
            database_path=Path(os.getenv("DATABASE_PATH", "./botbuilder.sqlite3")),
            builder_bot_token=os.getenv("BUILDER_BOT_TOKEN"),
            telegram_api_id=api_id,
            telegram_api_hash=os.getenv("TELEGRAM_API_HASH", ""),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            runtime_poll_interval_seconds=poll_interval,
            owner_telegram_id=_parse_optional_int(os.getenv("OWNER_TELEGRAM_ID"), "OWNER_TELEGRAM_ID"),
        )

    def validate_for_builder(self) -> None:
        errors = self._common_errors()
        if not self.builder_bot_token:
            errors.append("BUILDER_BOT_TOKEN is required")
        if not self.gemini_api_key:
            errors.append("GEMINI_API_KEY is required")
        _raise_if_errors(errors)

    def validate_for_runtime(self) -> None:
        errors = self._common_errors()
        if self.runtime_poll_interval_seconds <= 0:
            errors.append("RUNTIME_POLL_INTERVAL_SECONDS must be greater than 0")
        _raise_if_errors(errors)

    def _common_errors(self) -> list[str]:
        errors: list[str] = []
        if self.telegram_api_id <= 0:
            errors.append("TELEGRAM_API_ID must be a positive integer")
        if not self.telegram_api_hash:
            errors.append("TELEGRAM_API_HASH is required")
        if not str(self.database_path):
            errors.append("DATABASE_PATH is required")
        return errors


def require(value: str | None, name: str) -> str:
    """Return an environment value or raise a startup-friendly error."""

    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _parse_int(value: str | None, name: str) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _parse_optional_int(value: str | None, name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _parse_float(value: str | None, name: str) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc


def _raise_if_errors(errors: list[str]) -> None:
    if errors:
        joined = "\n- ".join(errors)
        raise RuntimeError(f"Invalid environment configuration:\n- {joined}")
