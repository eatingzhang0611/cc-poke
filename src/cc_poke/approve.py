"""PreToolUse hook client: ask the phone to approve/deny a tool call.

NEVER blocks Claude: on config error, daemon error, or timeout it exits 0
with NO permissionDecision, so Claude Code falls back to its terminal popup.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

from .config import ConfigError, load_config

_LOG_PATH = Path.home() / ".cache" / "cc-poke" / "approve.log"


def _log(msg: str) -> None:
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def is_allowlisted(tool_name: str, tool_input: dict, patterns) -> bool:
    if tool_name != "Bash":
        return False
    command = str(tool_input.get("command", ""))
    for pat in patterns:
        try:
            if re.search(pat, command):
                return True
        except re.error:
            continue
    return False


def build_summary(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Bash":
        return str(tool_input.get("command", ""))[:300]
    return f"{tool_name}: {json.dumps(tool_input, ensure_ascii=False)}"[:300]


def emit_decision(decision: str, reason: str) -> None:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(out))


def _default_poster(url: str, data: bytes, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return int(resp.status), resp.read()


def request_decision(config, tool_name, tool_input, cwd: str = "", *, poster=_default_poster) -> str | None:
    summary = build_summary(tool_name, tool_input)
    payload = json.dumps({"tool_name": tool_name, "summary": summary, "cwd": cwd}).encode("utf-8")
    url = f"{config.daemon_url}/requests"
    status, body = poster(url, payload, config.wait_seconds + 15.0)
    if not (200 <= status < 300):
        return None
    try:
        decision = json.loads(body).get("decision")
    except Exception:
        return None
    return decision if decision in ("allow", "deny") else None


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
    tool_name = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    cwd = str(payload.get("cwd", ""))

    try:
        config = load_config()
    except ConfigError as e:
        _log(f"config error: {e}")
        return 0  # no decision -> terminal popup

    if config.bypass:
        emit_decision("allow", "cc-poke bypass")
        return 0

    if is_allowlisted(tool_name, tool_input, config.allowlist):
        emit_decision("allow", "cc-poke allowlist")
        return 0

    try:
        decision = request_decision(config, tool_name, tool_input, cwd)
    except Exception as e:  # noqa: BLE001 — never block Claude
        _log(f"approve error: {e!r}")
        return 0  # no decision -> terminal popup

    if decision in ("allow", "deny"):
        emit_decision(decision, "cc-poke remote")
    # else: timeout -> no decision -> terminal popup
    return 0
