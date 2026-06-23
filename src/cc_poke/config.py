"""Load and validate cc-poke configuration from a JSON file."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "cc-poke" / "config.json"


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    ntfy_server: str
    ntfy_topic: str
    adapter: str = "ntfy"
    daemon_url: str = "http://127.0.0.1:8787"
    public_base_url: str = ""
    webhook_secret: str = ""
    allowlist: tuple[str, ...] = ()
    wait_seconds: float = 300.0


def load_config(
    path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Config:
    env = os.environ if env is None else env
    resolved = path or env.get("CC_POKE_CONFIG") or DEFAULT_CONFIG_PATH
    p = Path(resolved).expanduser()
    if not p.exists():
        raise ConfigError(
            f"cc-poke config not found at {p}. "
            f'Create it, e.g. {{"ntfy_topic": "your-topic"}}'
        )
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"cc-poke config at {p} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"cc-poke config at {p} must be a JSON object")
    topic = data.get("ntfy_topic")
    if topic is None:
        raise ConfigError(f'cc-poke config at {p} is missing required "ntfy_topic"')
    if not str(topic).strip():
        raise ConfigError(f'cc-poke config at {p} has an empty "ntfy_topic"')
    server = str(data.get("ntfy_server", "https://ntfy.sh")).rstrip("/")
    adapter = str(data.get("adapter", "ntfy"))
    daemon_url = str(data.get("daemon_url", "http://127.0.0.1:8787")).rstrip("/")
    public_base_url = str(data.get("public_base_url", "")).rstrip("/")
    webhook_secret = str(data.get("webhook_secret", ""))
    raw_allow = data.get("allowlist", [])
    if not isinstance(raw_allow, list):
        raise ConfigError(f'cc-poke config at {p} has "allowlist" that is not a list')
    allowlist = tuple(str(x) for x in raw_allow)
    try:
        wait_seconds = float(data.get("wait_seconds", 300.0))
    except (TypeError, ValueError) as e:
        raise ConfigError(f'cc-poke config at {p} has invalid "wait_seconds": {e}') from e
    return Config(
        ntfy_server=server,
        ntfy_topic=str(topic),
        adapter=adapter,
        daemon_url=daemon_url,
        public_base_url=public_base_url,
        webhook_secret=webhook_secret,
        allowlist=allowlist,
        wait_seconds=wait_seconds,
    )
