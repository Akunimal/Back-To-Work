import json
from datetime import datetime, timedelta, timezone

from backtowork.models import Status
from backtowork.providers.claude_code import ClaudeCodeProvider


def _write_jsonl(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _marker_line(reset_epoch):
    """A transcript line carrying the real Claude Code usage-limit marker."""
    return {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": f"Claude Code usage limit reached|{reset_epoch}"}
            ]
        },
    }


def test_no_projects_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    st = ClaudeCodeProvider("claude", {}).read_state()
    assert st.status == Status.UNKNOWN


def test_activity_without_marker_is_available(tmp_path, monkeypatch):
    """The core fix: heavy recent activity but NO limit marker -> AVAILABLE.
    (The old block-estimate logic wrongly reported EXHAUSTED here.)"""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    now = datetime.now(timezone.utc)
    _write_jsonl(
        tmp_path / "projects" / "proj" / "s.jsonl",
        [
            {"type": "user", "timestamp": _iso(now - timedelta(minutes=30))},
            {"type": "assistant", "timestamp": _iso(now - timedelta(minutes=20))},
            {"type": "user", "timestamp": _iso(now)},
        ],
    )
    st = ClaudeCodeProvider("claude", {}).read_state()
    assert st.status == Status.AVAILABLE
    assert st.reset_at is None


def test_future_marker_is_exhausted_with_exact_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    now = datetime.now(timezone.utc)
    reset = now + timedelta(hours=2)
    epoch = int(reset.timestamp())
    _write_jsonl(tmp_path / "projects" / "proj" / "s.jsonl", [_marker_line(epoch)])
    st = ClaudeCodeProvider("claude", {}).read_state()
    assert st.status == Status.EXHAUSTED
    assert st.reset_at is not None
    assert abs((st.reset_at - reset).total_seconds()) < 2  # exact, not estimate


def test_past_marker_is_available(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    now = datetime.now(timezone.utc)
    epoch = int((now - timedelta(minutes=10)).timestamp())
    _write_jsonl(tmp_path / "projects" / "proj" / "s.jsonl", [_marker_line(epoch)])
    st = ClaudeCodeProvider("claude", {}).read_state()
    assert st.status == Status.AVAILABLE


def test_millisecond_epoch_supported(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    now = datetime.now(timezone.utc)
    reset = now + timedelta(hours=1)
    epoch_ms = int(reset.timestamp() * 1000)
    _write_jsonl(tmp_path / "projects" / "proj" / "s.jsonl", [_marker_line(epoch_ms)])
    st = ClaudeCodeProvider("claude", {}).read_state()
    assert st.status == Status.EXHAUSTED
    assert abs((st.reset_at - reset).total_seconds()) < 2
