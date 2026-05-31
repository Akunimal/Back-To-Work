import json
from datetime import datetime, timedelta, timezone

from backtowork.models import Status
from backtowork.providers.codex import CodexProvider


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _write_rollout(home, lines):
    d = home / "sessions" / "2026" / "05" / "30"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "rollout-2026-05-30T12-00-00-abc.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return p


def _token_count(ts, *, primary_pct, primary_resets, secondary_pct=10, secondary_resets=600000):
    return {
        "timestamp": ts,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "rate_limits": {
                "primary": {
                    "used_percent": primary_pct,
                    "window_minutes": 300,
                    "resets_in_seconds": primary_resets,
                },
                "secondary": {
                    "used_percent": secondary_pct,
                    "window_minutes": 10080,
                    "resets_in_seconds": secondary_resets,
                },
            },
        },
    }


def _token_count_resets_at(ts, *, primary_pct, primary_reset_at, secondary_pct=10, secondary_reset_at=None):
    if secondary_reset_at is None:
        secondary_reset_at = primary_reset_at + timedelta(seconds=600000)
    return {
        "timestamp": ts,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "rate_limits": {
                "primary": {
                    "used_percent": primary_pct,
                    "window_minutes": 300,
                    "resets_at": int(primary_reset_at.timestamp()),
                },
                "secondary": {
                    "used_percent": secondary_pct,
                    "window_minutes": 10080,
                    "resets_at": int(secondary_reset_at.timestamp()),
                },
            },
        },
    }


def test_no_home_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "nope"))
    assert CodexProvider("codex", {}).read_state().status == Status.UNKNOWN


def test_null_rate_limits_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    now = datetime.now(timezone.utc)
    _write_rollout(
        tmp_path,
        [{"timestamp": _iso(now), "type": "event_msg",
          "payload": {"type": "token_count", "rate_limits": None}}],
    )
    assert CodexProvider("codex", {}).read_state().status == Status.UNKNOWN


def test_exhausted_with_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    now = datetime.now(timezone.utc)
    _write_rollout(
        tmp_path,
        [{"timestamp": _iso(now), "type": "session_meta", "payload": {}},
         _token_count(_iso(now), primary_pct=100, primary_resets=3600)],
    )
    st = CodexProvider("codex", {}).read_state()
    assert st.status == Status.EXHAUSTED
    assert st.reset_at is not None and st.reset_at > now
    assert st.pct_used == 1.0


def test_exhausted_with_resets_at_epoch(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    now = datetime.now(timezone.utc)
    reset_at = now + timedelta(hours=1)
    _write_rollout(
        tmp_path,
        [{"timestamp": _iso(now), "type": "session_meta", "payload": {}},
         _token_count_resets_at(_iso(now), primary_pct=100, primary_reset_at=reset_at)],
    )
    st = CodexProvider("codex", {}).read_state()
    assert st.status == Status.EXHAUSTED
    assert st.reset_at is not None
    assert abs((st.reset_at - reset_at).total_seconds()) < 1
    assert st.pct_used == 1.0


def test_under_threshold_is_available(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    now = datetime.now(timezone.utc)
    _write_rollout(tmp_path, [_token_count(_iso(now), primary_pct=40, primary_resets=3600)])
    st = CodexProvider("codex", {}).read_state()
    assert st.status == Status.AVAILABLE
    assert abs((st.pct_used or 0) - 0.4) < 1e-6


def test_stale_window_already_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    _write_rollout(tmp_path, [_token_count(_iso(past), primary_pct=100, primary_resets=3600)])
    st = CodexProvider("codex", {}).read_state()
    assert st.status == Status.AVAILABLE  # reset_at (past + 1h) is already behind us


def test_prefers_primary_window(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    now = datetime.now(timezone.utc)
    _write_rollout(
        tmp_path,
        [_token_count(_iso(now), primary_pct=100, primary_resets=600,
                      secondary_pct=10, secondary_resets=600000)],
    )
    st = CodexProvider("codex", {}).read_state()
    assert st.status == Status.EXHAUSTED
    assert st.reset_at is not None
    assert (st.reset_at - now) < timedelta(minutes=11)
