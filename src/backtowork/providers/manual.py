"""Manual provider — zero-config, zero-guessing.

You tell it when the quota comes back; it reports EXHAUSTED until then, AVAILABLE
after. Powers `backtowork watch --reset 3h` and the `[[provider]] kind = "manual"`
config block.

    [[provider]]
    kind = "manual"
    name = "claude"
    reset_at = "3h"          # relative, or an ISO time like 2026-05-30T18:00:00Z
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..durations import resolve_reset
from ..models import QuotaState, Status
from .base import Provider, register


@register("manual")
class ManualProvider(Provider):
    def __init__(self, name: str, options: dict) -> None:
        super().__init__(name, options)
        self._reset_at: datetime | None = None
        self._error: str | None = None
        raw = options.get("reset_at")
        if raw is None:
            self._error = "manual provider needs 'reset_at' (e.g. '3h' or an ISO time)"
        else:
            try:
                self._reset_at = resolve_reset(str(raw))
            except ValueError as exc:
                self._error = str(exc)

    def read_state(self) -> QuotaState:
        if self._error:
            return QuotaState(Status.UNKNOWN, detail=self._error)
        assert self._reset_at is not None
        now = datetime.now(timezone.utc)
        if now >= self._reset_at:
            return QuotaState(Status.AVAILABLE)
        return QuotaState(Status.EXHAUSTED, reset_at=self._reset_at, detail="waiting")
