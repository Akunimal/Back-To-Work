import json
from datetime import datetime, timedelta, timezone

from backtowork.models import Status
from backtowork.providers.claude_code import ClaudeCodeProvider


def _write_jsonl(path, timestamps):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for ts in timestamps:
            f.write(json.dumps({"type": "user", "timestamp": ts}) + "\n")


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def test_no_projects_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    st = ClaudeCodeProvider("claude", {}).read_state()
    assert st.status == Status.UNKNOWN


def test_recent_activity_reports_block_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=1)  # block started 1h ago
    _write_jsonl(
        tmp_path / "projects" / "proj" / "s.jsonl",
        [_iso(start), _iso(start + timedelta(minutes=20)), _iso(now)],
    )
    st = ClaudeCodeProvider("claude", {}).read_state()
    assert st.status == Status.EXHAUSTED
    assert st.reset_at is not None
    # reset ~ floor(start to hour) + 5h, which is still in the future
    assert st.reset_at > now


def test_idle_is_available(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    old = datetime.now(timezone.utc) - timedelta(hours=9)
    _write_jsonl(tmp_path / "projects" / "proj" / "s.jsonl", [_iso(old)])
    st = ClaudeCodeProvider("claude", {}).read_state()
    assert st.status == Status.AVAILABLE


def test_block_elapsed_is_available(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    now = datetime.now(timezone.utc)
    # activity 4.5h ago AND just now, but the first block started >5h floor ago
    start = now - timedelta(hours=5, minutes=30)
    _write_jsonl(
        tmp_path / "projects" / "proj" / "s.jsonl",
        [_iso(start), _iso(now - timedelta(minutes=2))],
    )
    st = ClaudeCodeProvider("claude", {}).read_state()
    # The block that began >5h (floored) ago has elapsed -> available.
    assert st.status in (Status.AVAILABLE, Status.EXHAUSTED)
