"""Core domain models. No provider- or UI-specific logic lives here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Status(str, Enum):
    AVAILABLE = "available"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class QuotaState:
    """A point-in-time reading of a coder's quota."""

    status: Status
    reset_at: datetime | None = None      # when the quota is expected to refill
    pct_used: float | None = None         # 0.0 .. 1.0, if the provider knows it
    detail: str | None = None             # free-form note for the UI (errors, hints)


@dataclass(frozen=True)
class RefillEvent:
    """Emitted on an EXHAUSTED -> AVAILABLE transition."""

    provider: str
    at: datetime
    previous: Status
