"""Notification hook entry point: read the hook payload and push it to the phone."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .adapters import make_adapter
from .adapters.base import PushAdapter
from .config import ConfigError, load_config

_TITLE = "cc-poke: Claude needs you"
_DEFAULT_BODY = "Claude is waiting for you"
_LOG_PATH = Path.home() / ".cache" / "cc-poke" / "notifier.log"


def _log(msg: str) -> None:
    """Best-effort local log. Never raises."""
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def build_message(payload: dict) -> tuple[str, str]:
    message = payload.get("message") or _DEFAULT_BODY
    cwd = payload.get("cwd")
    body = f"{message}\n({cwd})" if cwd else message
    return _TITLE, body


def run(payload: dict, adapter: PushAdapter) -> bool:
    title, body = build_message(payload)
    return adapter.send(title, body)


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    try:
        config = load_config()
    except ConfigError as e:
        _log(f"config error: {e}")
        return 0

    try:
        adapter = make_adapter(config)
        if not run(payload, adapter):
            _log("push failed (adapter returned False)")
    except Exception as e:  # noqa: BLE001 — never block Claude
        _log(f"notifier error: {e!r}")
    return 0
