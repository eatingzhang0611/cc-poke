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
