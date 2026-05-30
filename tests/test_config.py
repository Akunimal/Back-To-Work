from backtowork.config import find_config, load_providers
from backtowork.models import Status


def test_load_providers(tmp_path):
    cfg = tmp_path / "backtowork.toml"
    cfg.write_text(
        """
[settings]
idle_interval = 30
play_sound = false

[[provider]]
kind = "manual"
name = "claude"
reset_at = "2000-01-01T00:00:00Z"
""",
        encoding="utf-8",
    )
    providers, settings = load_providers(cfg)
    assert len(providers) == 1
    assert providers[0].name == "claude"
    assert settings["idle_interval"] == 30
    assert settings["play_sound"] is False
    assert providers[0].read_state().status == Status.AVAILABLE


def test_find_config_explicit(tmp_path):
    cfg = tmp_path / "x.toml"
    cfg.write_text("[settings]\n", encoding="utf-8")
    assert find_config(str(cfg)) == cfg


def test_find_config_env(tmp_path, monkeypatch):
    cfg = tmp_path / "env.toml"
    cfg.write_text("[settings]\n", encoding="utf-8")
    monkeypatch.setenv("BACKTOWORK_CONFIG", str(cfg))
    assert find_config() == cfg
