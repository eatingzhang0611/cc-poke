"""Stop hook entry point: notify the phone that Claude has finished a turn."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from .adapters import make_adapter
from .config import ConfigError, load_config

_LOG_PATH = Path.home() / ".cache" / "cc-poke" / "stopper.log"
_LAST_STOP_PATH = Path.home() / ".cache" / "cc-poke" / "last_stop.ts"

_TITLE = "cc-poke: Claude 已完成"
_BODY = "等待你的回复"


def _log(msg: str) -> None:
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _shorten_cwd(cwd: str) -> str:
    home = str(Path.home())
    return "~" + cwd[len(home):] if cwd.startswith(home) else cwd


def _in_quiet_period(quiet_seconds: float) -> bool:
    try:
        ts = float(_LAST_STOP_PATH.read_text(encoding="utf-8").strip())
        return (time.time() - ts) < quiet_seconds
    except Exception:
        return False


def _record_push() -> None:
    try:
        _LAST_STOP_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LAST_STOP_PATH.write_text(str(time.time()), encoding="utf-8")
    except Exception:
        pass


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

    # Prevent infinite loop: Stop hook itself triggering another Stop
    if payload.get("stop_hook_active"):
        return 0

    try:
        config = load_config()
    except ConfigError as e:
        _log(f"config error: {e}")
        return 0

    if config.bypass:
        return 0

    if _in_quiet_period(config.stop_quiet_seconds):
        return 0

    cwd = str(payload.get("cwd", "")).strip()
    body = f"{_BODY}\n({_shorten_cwd(cwd)})" if cwd else _BODY

    try:
        adapter = make_adapter(config)
        adapter.send(_TITLE, body)
        _record_push()
    except Exception as e:  # noqa: BLE001 — never block Claude
        _log(f"stopper error: {e!r}")
    return 0
