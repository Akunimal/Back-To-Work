"""The core. Owns the polling loop, the per-provider state machine, and the
adaptive sleep schedule. Knows nothing about the UI or how you get notified —
it just calls back with ticks and refill events.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timezone

from .models import QuotaState, RefillEvent, Status
from .providers.base import Provider

OnTick = Callable[[dict[str, QuotaState]], None]
OnRefill = Callable[[RefillEvent], None]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Monitor:
    def __init__(
        self,
        providers: list[Provider],
        idle_interval: float = 60.0,   # poll cadence while credit is available
        fast_interval: float = 10.0,   # poll cadence right around a known reset
        wake_margin: float = 5.0,      # wake this many secs before a reset
    ) -> None:
        self.providers = providers
        self.idle_interval = idle_interval
        self.fast_interval = fast_interval
        self.wake_margin = wake_margin
        self._last: dict[str, Status] = {p.name: Status.UNKNOWN for p in providers}
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def poll_once(self) -> dict[str, QuotaState]:
        states: dict[str, QuotaState] = {}
        for p in self.providers:
            try:
                states[p.name] = p.read_state()
            except Exception as exc:  # providers shouldn't raise, but be safe
                states[p.name] = QuotaState(Status.UNKNOWN, detail=f"crash: {exc}")
        return states

    def run(self, on_tick: OnTick, on_refill: OnRefill) -> None:
        while not self._stop.is_set():
            states = self.poll_once()

            for name, st in states.items():
                prev = self._last[name]
                if prev == Status.EXHAUSTED and st.status == Status.AVAILABLE:
                    on_refill(RefillEvent(provider=name, at=_now(), previous=prev))
                self._last[name] = st.status

            on_tick(states)
            self._stop.wait(self._next_sleep(states))

    def _next_sleep(self, states: dict[str, QuotaState]) -> float:
        exhausted = [s for s in states.values() if s.status == Status.EXHAUSTED]
        if not exhausted:
            return self.idle_interval

        resets = [s.reset_at for s in exhausted if s.reset_at is not None]
        if not resets:
            # Exhausted but no reset hint -> check at the fast cadence.
            return self.fast_interval

        seconds_to_reset = (min(resets) - _now()).total_seconds()
        if seconds_to_reset <= self.wake_margin:
            return self.fast_interval
        # Sleep until just before the soonest reset, then start fast-polling.
        return max(self.fast_interval, seconds_to_reset - self.wake_margin)
