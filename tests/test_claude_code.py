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


def _rate_limit_line(ts, text):
    return {
        "type": "assistant",
        "timestamp": _iso(ts),
        "error": "rate_limit",
        "apiErrorStatus": 429,
        "isApiErrorMessage": True,
        "message": {
            "content": [
                {"type": "text", "text": text}
            ]
        },
    }


def _tool_output_marker_line(reset_epoch):
    """A contaminated transcript line mentioning the marker in tool output."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "content": f"Claude Code usage limit reached|{reset_epoch}",
                }
            ],
        },
    }


def _usage_line(ts, *, input_tokens=0, cache_creation=0, cache_read=0, output_tokens=0):
    return {
        "type": "assistant",
        "timestamp": _iso(ts),
        "message": {
            "usage": {
                "input_tokens": input_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
                "output_tokens": output_tokens,
            }
        },
    }


def test_no_projects_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    st = ClaudeCodeProvider("claude", {}).read_state()
    assert st.status == Status.UNKNOWN


def test_activity_without_marker_is_unknown(tmp_path, monkeypatch):
    """The core fix: heavy recent activity but NO limit marker -> UNKNOWN.
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
    assert st.status == Status.UNKNOWN
    assert st.reset_at is None


def test_local_usage_windows_sum_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    now = datetime.now(timezone.utc)
    _write_jsonl(
        tmp_path / "projects" / "proj" / "s.jsonl",
        [
            _usage_line(now - timedelta(hours=1), input_tokens=100, output_tokens=50),
            _usage_line(now - timedelta(hours=6), cache_read=25, output_tokens=25),
            _usage_line(now - timedelta(days=8), input_tokens=999),
        ],
    )
    st = ClaudeCodeProvider("claude", {}).read_state()
    assert st.status == Status.UNKNOWN
    assert [(w.name, w.tokens_used) for w in st.usage_windows] == [
        ("current", 150),
        ("weekly", 200),
    ]


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


def test_rate_limit_message_reset_time_is_exhausted(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    base = datetime.now(timezone.utc)
    ba = timezone(timedelta(hours=-3))
    reset_local = (base.astimezone(ba) + timedelta(hours=2)).replace(
        second=0, microsecond=0
    )
    hour = reset_local.hour % 12 or 12
    suffix = "am" if reset_local.hour < 12 else "pm"
    _write_jsonl(
        tmp_path / "projects" / "proj" / "s.jsonl",
        [
            _rate_limit_line(
                base,
                f"You've hit your session limit · resets {hour}:{reset_local.minute:02d}"
                f"{suffix} (America/Buenos_Aires)",
            )
        ],
    )
    st = ClaudeCodeProvider("claude", {}).read_state()
    assert st.status == Status.EXHAUSTED
    assert st.reset_at == reset_local.astimezone(timezone.utc)


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


def test_tool_output_marker_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    now = datetime.now(timezone.utc)
    epoch = int((now + timedelta(hours=2)).timestamp())
    _write_jsonl(
        tmp_path / "projects" / "proj" / "s.jsonl",
        [_tool_output_marker_line(epoch)],
    )
    st = ClaudeCodeProvider("claude", {}).read_state()
    assert st.status == Status.UNKNOWN
    assert st.detail == "no usage-limit marker"
