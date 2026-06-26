"""cc-poke-setup: interactive configuration wizard."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

_BIN_DIR = Path(sys.executable).parent
_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
_CONFIG_FILE = _CONFIG_HOME / "cc-poke" / "config.json"
_UNIT_DIR = _CONFIG_HOME / "systemd" / "user"
_CC_SETTINGS_DEFAULT = Path.home() / ".claude" / "settings.json"

_G = "\033[32m"; _C = "\033[36m"; _Y = "\033[33m"; _R = "\033[0m"


def _ok(msg: str) -> None:   print(f"{_G}[cc-poke]{_R} {msg}")
def _info(msg: str) -> None: print(f"{_C}[cc-poke]{_R} {msg}")
def _warn(msg: str) -> None: print(f"{_Y}[cc-poke] WARN:{_R} {msg}", file=sys.stderr)


def _ask(prompt: str, default: str = "", required: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        val = input(f"  {prompt}{suffix}: ").strip()
        result = val or default
        if result or not required:
            return result
        print("  (required)")


# ── Step 1: config.json ───────────────────────────────────────────────────────

def _setup_config() -> dict:
    if _CONFIG_FILE.exists():
        _info(f"config found at {_CONFIG_FILE} — skipping (delete to reconfigure)")
        return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))

    adapter = _ask("adapter (ntfy/bark)", default="ntfy")
    cfg: dict = {"adapter": adapter, "webhook_secret": secrets.token_urlsafe(24)}

    if adapter == "ntfy":
        cfg["ntfy_server"] = _ask("ntfy server", default="https://ntfy.sh")
        cfg["ntfy_topic"] = _ask("ntfy topic", required=True)
    else:
        cfg["bark_server"] = _ask("bark server", default="https://api.day.app")
        cfg["bark_device_key"] = _ask("bark device key", required=True)

    cfg["public_base_url"] = _ask("public HTTPS URL for approval webhook (blank = notify-only)", default="")
    cfg["daemon_url"] = "http://127.0.0.1:8787"
    cfg["allowlist"] = [
        r"^(pwd|ls( [^;&|<>$()`\s]+)?)$",
        r"^(cat|head|tail|wc) [^;&|<>$()`\s]+$",
        r"^git (log|diff|status|show)( .*)?$",
        r"^which [^;&|<>$()`\s]+$",
    ]
    cfg["wait_seconds"] = 300
    cfg["stop_quiet_seconds"] = 300
    cfg["bypass"] = False

    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    _ok(f"wrote {_CONFIG_FILE}")
    return cfg


# ── Step 2: systemd ───────────────────────────────────────────────────────────

def _setup_systemd() -> None:
    try:
        r = subprocess.run(["systemctl", "--user", "show-environment"],
                           capture_output=True, timeout=5)
        if r.returncode != 0:
            raise RuntimeError
    except Exception:
        _warn("no systemd user session — skipping daemon unit")
        return

    unit = (
        "[Unit]\n"
        "Description=cc-poke approval daemon\n"
        "After=network.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={_BIN_DIR}/cc-poke-daemon\n"
        "Restart=on-failure\n"
        "RestartSec=2\n"
        "MemoryMax=128M\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )
    unit_file = _UNIT_DIR / "cc-poke-daemon.service"
    _UNIT_DIR.mkdir(parents=True, exist_ok=True)
    unit_file.write_text(unit, encoding="utf-8")

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, capture_output=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "cc-poke-daemon"],
                   check=True, capture_output=True)
    _ok(f"daemon enabled and started ({unit_file})")

    try:
        subprocess.run(["loginctl", "enable-linger", os.environ.get("USER", "")],
                       check=True, capture_output=True, timeout=5)
        _ok("lingering enabled (daemon survives logout)")
    except Exception:
        _warn("could not enable linger — run manually: loginctl enable-linger $USER")


# ── Step 3: Claude Code settings.json ────────────────────────────────────────

def _cmd_present(hooks_data: dict, marker: str) -> bool:
    for entries in hooks_data.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            for h in entry.get("hooks", []) if isinstance(entry, dict) else []:
                if marker in h.get("command", ""):
                    return True
    return False


def inject_cc_settings(cc_settings: Path, bin_dir: Path = _BIN_DIR) -> None:
    """Merge cc-poke hooks into CC settings.json (idempotent)."""
    data: dict = {}
    if cc_settings.exists():
        try:
            data = json.loads(cc_settings.read_text(encoding="utf-8"))
        except Exception:
            pass
    if not isinstance(data, dict):
        data = {}

    hooks = data.setdefault("hooks", {})
    notify_cmd  = str(bin_dir / "cc-poke-notify")
    approve_cmd = str(bin_dir / "cc-poke-approve")
    stop_cmd    = str(bin_dir / "cc-poke-stop")

    if not _cmd_present(hooks, "cc-poke-notify"):
        hooks.setdefault("Notification", []).append(
            {"hooks": [{"type": "command", "command": notify_cmd}]}
        )
    if not _cmd_present(hooks, "cc-poke-approve"):
        hooks.setdefault("PreToolUse", []).append(
            {"matcher": "Bash", "hooks": [{"type": "command", "command": approve_cmd, "timeout": 600}]}
        )
    if not _cmd_present(hooks, "cc-poke-stop"):
        hooks.setdefault("Stop", []).append(
            {"hooks": [{"type": "command", "command": stop_cmd}]}
        )

    cc_settings.parent.mkdir(parents=True, exist_ok=True)
    cc_settings.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _ok(f"hooks injected into {cc_settings}")


# ── Next steps printout ───────────────────────────────────────────────────────

def _print_next_steps(cfg: dict) -> None:
    base = cfg.get("public_base_url", "")
    print(f"\n{_G}══ cc-poke setup complete! ══{_R}\n")

    if base:
        print(f"""\
── Reverse proxy (Caddy example) ──────────────────────
Expose ONLY /webhook and /d (keep /requests private):

  @ccpoke path /ccpoke/webhook /ccpoke/d
  handle @ccpoke {{
    uri strip_prefix /ccpoke
    reverse_proxy 127.0.0.1:8787
  }}

Then: sudo systemctl reload caddy
""")
    else:
        print("  [!] No public_base_url — running in notify-only mode.\n"
              "      Edit ~/.config/cc-poke/config.json to enable approval.\n")

    print("""\
── Optional: bypass toggle (add to ~/.bashrc) ─────────
ccbypass() {
  local cfg="$HOME/.config/cc-poke/config.json"
  case "$1" in
    on)  python3 -c "import json,pathlib; p=pathlib.Path('$cfg'); d=json.loads(p.read_text()); d['bypass']=True; p.write_text(json.dumps(d,indent=2))" && echo "cc-poke bypass ON" ;;
    off) python3 -c "import json,pathlib; p=pathlib.Path('$cfg'); d=json.loads(p.read_text()); d['bypass']=False; p.write_text(json.dumps(d,indent=2))" && echo "cc-poke bypass OFF" ;;
    *)   echo "usage: ccbypass on|off" ;;
  esac
}

Effect:
  ccbypass on   — all commands silently approved, no phone push
  ccbypass off  — restore phone approval flow
  (takes effect immediately; no daemon restart needed)
""")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    print(f"{_C}cc-poke setup{_R}\n{'─' * 36}")
    try:
        print(f"\n── Step 1: config ({_CONFIG_FILE})")
        cfg = _setup_config()

        print("\n── Step 2: approval daemon (systemd)")
        _setup_systemd()

        print("\n── Step 3: Claude Code hooks")
        cc_path = _ask("settings.json path", default=str(_CC_SETTINGS_DEFAULT))
        inject_cc_settings(Path(cc_path).expanduser())

        _print_next_steps(cfg)
    except KeyboardInterrupt:
        print("\naborted")
        return 1
    return 0
