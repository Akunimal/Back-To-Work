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
class UsageWindow:
    """Usage for one quota window."""

    name: str
    pct_used: float | None = None         # 0.0 .. 1.0, if known
    tokens_used: int | None = None        # local token total, if known
    reset_at: datetime | None = None
    detail: str | None = None
    status: Status | None = None          # per-window status (row coloring); None = inherit
    assumed: bool = False                 # pct is inferred from a stale snapshot, not confirmed


@dataclass(frozen=True)
class QuotaState:
    """A point-in-time reading of a coder's quota."""

    status: Status
    reset_at: datetime | None = None      # when the quota is expected to refill
    pct_used: float | None = None         # 0.0 .. 1.0, if the provider knows it
    detail: str | None = None             # free-form note for the UI (errors, hints)
    usage_windows: tuple[UsageWindow, ...] = ()


@dataclass(frozen=True)
class RefillEvent:
    """Emitted on an EXHAUSTED -> AVAILABLE transition."""

    provider: str
    at: datetime
    previous: Status
