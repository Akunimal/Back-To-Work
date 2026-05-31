"""Zero-config auto-detection: bare `backtowork` should pick up whichever
coders have local data, with no config file and no --reset."""

from backtowork import cli


def test_detects_claude_only(tmp_path, monkeypatch):
    (tmp_path / ".claude" / "projects").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / ".claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))  # absent
    providers = cli._auto_providers()
    assert {p.name for p in providers} == {"claude"}


def test_detects_codex_only(tmp_path, monkeypatch):
    (tmp_path / ".codex" / "sessions").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / ".claude"))  # absent
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    providers = cli._auto_providers()
    assert {p.name for p in providers} == {"codex"}


def test_detects_both(tmp_path, monkeypatch):
    (tmp_path / ".claude" / "projects").mkdir(parents=True)
    (tmp_path / ".codex" / "sessions").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / ".claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    providers = cli._auto_providers()
    assert {p.name for p in providers} == {"claude", "codex"}
    assert len(providers) == 2  # distinct keys for the monitor


def test_detects_none(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / ".claude"))  # absent
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))  # absent
    assert cli._auto_providers() == []
