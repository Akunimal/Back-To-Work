from backtowork.models import Status
from backtowork.providers.manual import ManualProvider


def test_exhausted_then_available():
    p = ManualProvider("claude", {"reset_at": "1h"})
    st = p.read_state()
    assert st.status == Status.EXHAUSTED
    assert st.reset_at is not None


def test_past_reset_is_available():
    p = ManualProvider("claude", {"reset_at": "2000-01-01T00:00:00Z"})
    assert p.read_state().status == Status.AVAILABLE


def test_missing_reset_is_unknown():
    p = ManualProvider("claude", {})
    st = p.read_state()
    assert st.status == Status.UNKNOWN
    assert "reset_at" in (st.detail or "")


def test_bad_reset_is_unknown():
    p = ManualProvider("claude", {"reset_at": "whenever"})
    assert p.read_state().status == Status.UNKNOWN
