import json
from pathlib import Path

import pytest

from cc_poke.config import Config, ConfigError, load_config


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_load_minimal_config(tmp_path):
    p = _write(tmp_path, {"ntfy_topic": "my-secret-topic"})
    cfg = load_config(path=p)
    assert isinstance(cfg, Config)
    assert cfg.ntfy_topic == "my-secret-topic"
    assert cfg.ntfy_server == "https://ntfy.sh"  # default
    assert cfg.adapter == "ntfy"  # default


def test_server_trailing_slash_stripped(tmp_path):
    p = _write(tmp_path, {"ntfy_topic": "t", "ntfy_server": "https://push.example.com/"})
    cfg = load_config(path=p)
    assert cfg.ntfy_server == "https://push.example.com"


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(path=tmp_path / "nope.json")


def test_missing_topic_raises(tmp_path):
    p = _write(tmp_path, {"ntfy_server": "https://ntfy.sh"})
    with pytest.raises(ConfigError):
        load_config(path=p)


def test_path_from_env(tmp_path):
    p = _write(tmp_path, {"ntfy_topic": "envtopic"})
    cfg = load_config(env={"CC_POKE_CONFIG": str(p)})
    assert cfg.ntfy_topic == "envtopic"


def test_path_arg_beats_env(tmp_path):
    p1 = _write(tmp_path, {"ntfy_topic": "from-arg"})
    sub = tmp_path / "other"
    sub.mkdir()
    p2 = sub / "config.json"
    p2.write_text(json.dumps({"ntfy_topic": "from-env"}), encoding="utf-8")
    cfg = load_config(path=p1, env={"CC_POKE_CONFIG": str(p2)})
    assert cfg.ntfy_topic == "from-arg"


def test_whitespace_topic_raises(tmp_path):
    p = _write(tmp_path, {"ntfy_topic": "   "})
    with pytest.raises(ConfigError):
        load_config(path=p)


def test_phase2_fields_default(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"ntfy_topic": "t"}', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.daemon_url == "http://127.0.0.1:8787"
    assert cfg.public_base_url == ""
    assert cfg.webhook_secret == ""
    assert cfg.allowlist == ()
    assert cfg.wait_seconds == 300.0


def test_phase2_fields_parsed(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({
        "ntfy_topic": "t",
        "daemon_url": "http://127.0.0.1:9999/",
        "public_base_url": "https://poke.test/",
        "webhook_secret": "sek",
        "allowlist": ["^git status$", "^ls"],
        "wait_seconds": 120,
    }), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.daemon_url == "http://127.0.0.1:9999"
    assert cfg.public_base_url == "https://poke.test"
    assert cfg.webhook_secret == "sek"
    assert cfg.allowlist == ("^git status$", "^ls")
    assert cfg.wait_seconds == 120.0


def test_allowlist_must_be_list(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"ntfy_topic": "t", "allowlist": "nope"}', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


def test_bark_fields_default(tmp_path):
    p = _write(tmp_path, {"ntfy_topic": "t"})
    cfg = load_config(path=p)
    assert cfg.bark_server == "https://api.day.app"
    assert cfg.bark_device_key == ""


def test_bark_fields_parsed(tmp_path):
    p = _write(tmp_path, {
        "adapter": "bark",
        "bark_server": "https://api.day.app/",
        "bark_device_key": "KEY123",
    })
    cfg = load_config(path=p)
    assert cfg.adapter == "bark"
    assert cfg.bark_server == "https://api.day.app"  # trailing slash stripped
    assert cfg.bark_device_key == "KEY123"


def test_bark_adapter_does_not_require_ntfy_topic(tmp_path):
    p = _write(tmp_path, {"adapter": "bark", "bark_device_key": "KEY123"})
    cfg = load_config(path=p)  # must not raise
    assert cfg.adapter == "bark"


def test_bark_adapter_requires_device_key(tmp_path):
    p = _write(tmp_path, {"adapter": "bark"})
    with pytest.raises(ConfigError):
        load_config(path=p)


def test_bypass_defaults_false(tmp_path):
    p = _write(tmp_path, {"ntfy_topic": "t"})
    cfg = load_config(path=p)
    assert cfg.bypass is False


def test_bypass_parsed_true(tmp_path):
    p = _write(tmp_path, {"ntfy_topic": "t", "bypass": True})
    cfg = load_config(path=p)
    assert cfg.bypass is True


def test_stop_quiet_seconds_default(tmp_path):
    p = _write(tmp_path, {"ntfy_topic": "t"})
    cfg = load_config(path=p)
    assert cfg.stop_quiet_seconds == 300.0


def test_stop_quiet_seconds_parsed(tmp_path):
    p = _write(tmp_path, {"ntfy_topic": "t", "stop_quiet_seconds": 120})
    cfg = load_config(path=p)
    assert cfg.stop_quiet_seconds == 120.0
