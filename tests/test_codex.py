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


def _write_named_rollout(home, name, lines):
    d = home / "sessions" / "2026" / "05" / "30"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
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
    assert [(w.name, w.pct_used) for w in st.usage_windows] == [
        ("current", 0.4),
        ("weekly", 0.1),
    ]


def test_stale_window_already_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    _write_rollout(tmp_path, [_token_count(_iso(past), primary_pct=100, primary_resets=3600)])
    st = CodexProvider("codex", {}).read_state()
    assert st.status == Status.AVAILABLE  # reset_at (past + 1h) is already behind us
    assert st.pct_used == 0.0


def test_uses_newest_snapshot_by_timestamp_not_file_mtime(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    now = datetime.now(timezone.utc)
    old_ts = now - timedelta(hours=2)
    new_ts = now
    stale = _write_named_rollout(
        tmp_path,
        "rollout-stale.jsonl",
        [_token_count(_iso(old_ts), primary_pct=83, primary_resets=60)],
    )
    fresh = _write_named_rollout(
        tmp_path,
        "rollout-fresh.jsonl",
        [_token_count(_iso(new_ts), primary_pct=4, primary_resets=3600)],
    )
    # A running process can keep appending unrelated lines to an older rollout.
    # The provider should use the newest token_count timestamp, not file mtime.
    stale.touch()
    fresh.touch()
    stale.touch()
    st = CodexProvider("codex", {}).read_state()
    assert st.status == Status.AVAILABLE
    assert abs((st.pct_used or 0) - 0.04) < 1e-6
    assert st.detail == "current window 4% used"


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


def test_secondary_window_can_exhaust(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    now = datetime.now(timezone.utc)
    _write_rollout(
        tmp_path,
        [_token_count(_iso(now), primary_pct=20, primary_resets=600,
                      secondary_pct=99, secondary_resets=600000)],
    )
    st = CodexProvider("codex", {}).read_state()
    assert st.status == Status.EXHAUSTED
    assert st.detail == "weekly 99% used"
    assert [(w.name, w.pct_used) for w in st.usage_windows] == [
        ("current", 0.2),
        ("weekly", 0.99),
    ]


def test_secondary_exhaustion_survives_primary_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    now = datetime.now(timezone.utc)
    _write_rollout(
        tmp_path,
        [_token_count_resets_at(
            _iso(now),
            primary_pct=100,
            primary_reset_at=now - timedelta(minutes=1),
            secondary_pct=99,
            secondary_reset_at=now + timedelta(days=2),
        )],
    )
    st = CodexProvider("codex", {}).read_state()
    assert st.status == Status.EXHAUSTED
    assert st.detail == "weekly 99% used"


def _raw_token_count(ts, rate_limits):
    return {
        "timestamp": ts,
        "type": "event_msg",
        "payload": {"type": "token_count", "rate_limits": rate_limits},
    }


def test_expired_current_window_refills_and_drops_stale_pct(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    now = datetime.now(timezone.utc)
    _write_rollout(
        tmp_path,
        [_token_count_resets_at(
            _iso(now),
            primary_pct=100,
            primary_reset_at=now - timedelta(minutes=1),
            secondary_pct=99,
            secondary_reset_at=now + timedelta(days=2),
        )],
    )
    st = CodexProvider("codex", {}).read_state()
    by_name = {w.name: w for w in st.usage_windows}
    # current refilled: no stale 100%, no countdown
    assert by_name["current"].status == Status.AVAILABLE
    assert by_name["current"].pct_used == 0.0
    assert by_name["current"].reset_at is None
    assert by_name["current"].assumed is True
    # weekly still blocked
    assert by_name["weekly"].status == Status.EXHAUSTED
    assert st.status == Status.EXHAUSTED


def test_stale_snapshot_no_weekly_avoids_false_full_battery(tmp_path, monkeypatch):
    # The reported bug: an old snapshot with no weekly window shows 100% free.
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    old = datetime.now(timezone.utc) - timedelta(hours=6)
    _write_rollout(
        tmp_path,
        [_raw_token_count(_iso(old), {
            "primary": {"used_percent": 50, "window_minutes": 300, "resets_in_seconds": 300 * 60},
            "secondary": None,
        })],
    )
    st = CodexProvider("codex", {}).read_state()
    assert st.status == Status.AVAILABLE
    # Honest: percentage is unknown, not a confident 100% free.
    assert st.pct_used is None
    assert "stale snapshot" in (st.detail or "")


def test_reached_type_forces_exhausted_below_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    now = datetime.now(timezone.utc)
    _write_rollout(
        tmp_path,
        [_raw_token_count(_iso(now), {
            "primary": {"used_percent": 80, "window_minutes": 300,
                        "resets_at": int((now + timedelta(hours=1)).timestamp())},
            "secondary": {"used_percent": 20, "window_minutes": 10080,
                          "resets_at": int((now + timedelta(days=2)).timestamp())},
            "rate_limit_reached_type": "primary",
        })],
    )
    st = CodexProvider("codex", {}).read_state()
    assert st.status == Status.EXHAUSTED
    assert "current" in (st.detail or "")


def test_plan_type_appended_to_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    now = datetime.now(timezone.utc)
    _write_rollout(
        tmp_path,
        [_raw_token_count(_iso(now), {
            "primary": {"used_percent": 20, "window_minutes": 300,
                        "resets_at": int((now + timedelta(hours=1)).timestamp())},
            "secondary": {"used_percent": 99, "window_minutes": 10080,
                          "resets_at": int((now + timedelta(days=2)).timestamp())},
            "plan_type": "plus",
        })],
    )
    st = CodexProvider("codex", {}).read_state()
    assert st.status == Status.EXHAUSTED
    assert (st.detail or "").endswith(" · plus")


def test_secondary_without_reset_is_still_shown(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    now = datetime.now(timezone.utc)
    _write_rollout(
        tmp_path,
        [_raw_token_count(_iso(now), {
            "primary": {"used_percent": 20, "window_minutes": 300,
                        "resets_at": int((now + timedelta(hours=1)).timestamp())},
            "secondary": {"used_percent": 40, "window_minutes": 10080},
        })],
    )
    st = CodexProvider("codex", {}).read_state()
    by_name = {w.name: w for w in st.usage_windows}
    assert "weekly" in by_name
    assert by_name["weekly"].reset_at is None
    assert abs((by_name["weekly"].pct_used or 0) - 0.4) < 1e-6
