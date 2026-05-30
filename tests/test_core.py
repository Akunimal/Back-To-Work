from datetime import datetime, timedelta, timezone

from backtowork.core import Monitor
from backtowork.models import QuotaState, RefillEvent, Status
from backtowork.providers.base import Provider


class ScriptedProvider(Provider):
    """Yields a predefined sequence of states, one per poll."""

    def __init__(self, name, states):
        super().__init__(name, {})
        self._states = list(states)
        self._i = 0

    def read_state(self):
        st = self._states[min(self._i, len(self._states) - 1)]
        self._i += 1
        return st


def test_refill_event_fires_on_transition():
    p = ScriptedProvider(
        "claude",
        [
            QuotaState(Status.EXHAUSTED),
            QuotaState(Status.EXHAUSTED),
            QuotaState(Status.AVAILABLE),
        ],
    )
    mon = Monitor([p])
    events: list[RefillEvent] = []

    ticks = {"n": 0}

    def on_tick(_states):
        ticks["n"] += 1
        if ticks["n"] >= 3:
            mon.stop()

    mon.run(on_tick=on_tick, on_refill=events.append)
    assert len(events) == 1
    assert events[0].provider == "claude"
    assert events[0].previous == Status.EXHAUSTED


def test_next_sleep_idle_when_available():
    mon = Monitor([], idle_interval=60, fast_interval=10)
    states = {"x": QuotaState(Status.AVAILABLE)}
    assert mon._next_sleep(states) == 60


def test_next_sleep_fast_when_exhausted_no_reset():
    mon = Monitor([], idle_interval=60, fast_interval=10)
    states = {"x": QuotaState(Status.EXHAUSTED)}
    assert mon._next_sleep(states) == 10


def test_next_sleep_waits_until_before_reset():
    mon = Monitor([], idle_interval=60, fast_interval=10, wake_margin=5)
    reset = datetime.now(timezone.utc) + timedelta(seconds=100)
    states = {"x": QuotaState(Status.EXHAUSTED, reset_at=reset)}
    sleep = mon._next_sleep(states)
    assert 80 <= sleep <= 95  # ~ (100 - wake_margin)
