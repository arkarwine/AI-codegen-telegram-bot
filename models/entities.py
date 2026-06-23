"""Typed domain models used by the builder and runtime."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class User:
    id: int
    telegram_id: int
    username: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class BotRecord:
    id: int
    owner_id: int
    name: str
    username: str | None
    token: str
    enabled: bool
    schema_json: str
    created_at: str
    updated_at: str
    last_error: str | None
    last_started_at: str | None
    last_failed_at: str | None


@dataclass(frozen=True, slots=True)
class SessionRecord:
    id: int
    bot_id: int
    user_id: int
    current_flow: str | None
    current_step: int
    session_data_json: str


@dataclass(frozen=True, slots=True)
class AnalyticsEvent:
    id: int
    bot_id: int
    event_type: str
    timestamp: str
