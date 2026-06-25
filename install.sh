#!/usr/bin/env bash
#
# cc-poke installer — idempotent. Safe to re-run.
#
#   ./install.sh
#
# Sets up a virtualenv + the package, writes a config template with a freshly
# generated webhook secret, and installs the (user) systemd unit for the
# approval daemon. It does NOT start the daemon or touch your Claude Code
# settings — those steps are printed at the end so you stay in control.
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$REPO_DIR/.venv"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
CONFIG_DIR="$CONFIG_HOME/cc-poke"
CONFIG_FILE="$CONFIG_DIR/config.json"
UNIT_DIR="$CONFIG_HOME/systemd/user"
UNIT_FILE="$UNIT_DIR/cc-poke-daemon.service"

c_info='\033[36m'; c_ok='\033[32m'; c_warn='\033[33m'; c_err='\033[31m'; c_off='\033[0m'
info() { printf "${c_info}[cc-poke]${c_off} %s\n" "$*"; }
ok()   { printf "${c_ok}[cc-poke]${c_off} %s\n" "$*"; }
warn() { printf "${c_warn}[cc-poke] WARN:${c_off} %s\n" "$*" >&2; }
die()  { printf "${c_err}[cc-poke] ERROR:${c_off} %s\n" "$*" >&2; exit 1; }

# 1) Python >= 3.10 -----------------------------------------------------------
command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH"
PYVER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)' \
  || die "need Python >= 3.10 (found $PYVER)"
ok "python $PYVER"

# 2) virtualenv + package -----------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
  info "creating virtualenv at $VENV"
  python3 -m venv "$VENV" 2>/dev/null \
    || die "venv creation failed — on Debian/Ubuntu run: sudo apt install python3-venv"
fi
info "installing cc-poke into the venv"
"$VENV/bin/python" -m pip install -q --upgrade pip >/dev/null
"$VENV/bin/python" -m pip install -q -e "$REPO_DIR"
ok "package installed (cc-poke-notify / cc-poke-daemon / cc-poke-approve)"

# 3) config (generate a real webhook secret; keep other fields as placeholders)
mkdir -p "$CONFIG_DIR"
if [ -f "$CONFIG_FILE" ]; then
  info "config already exists at $CONFIG_FILE (left unchanged)"
else
  "$VENV/bin/python" - "$REPO_DIR/config.example.json" "$CONFIG_FILE" <<'PY'
import json, secrets, sys
src, dst = sys.argv[1], sys.argv[2]
cfg = json.load(open(src))
cfg["webhook_secret"] = secrets.token_urlsafe(24)
json.dump(cfg, open(dst, "w"), ensure_ascii=False, indent=2)
PY
  ok "wrote $CONFIG_FILE (webhook_secret generated)"
fi

# 4) systemd user unit (path-substituted; not started) ------------------------
if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  mkdir -p "$UNIT_DIR"
  sed "s#/path/to/cc-poke#$REPO_DIR#g" "$REPO_DIR/deploy/cc-poke-daemon.service" > "$UNIT_FILE"
  systemctl --user daemon-reload
  ok "installed user unit $UNIT_FILE (not started yet)"
  loginctl enable-linger "$USER" >/dev/null 2>&1 \
    && ok "lingering enabled (daemon will survive logout)" \
    || warn "could not enable linger — daemon won't run while you're logged out (run: loginctl enable-linger $USER)"
else
  warn "no systemd user session — skipped daemon unit (notify-only still works)"
fi

# 5) next steps ---------------------------------------------------------------
cat <<EOF

$(ok "core install done.")

Next steps
──────────
1. Edit your config:  $CONFIG_FILE
     • ntfy_topic       — a long random string (acts as a password)
     • public_base_url  — only for the approval daemon (Phase 2); your HTTPS
                          reverse-proxy address. Leave as-is if you only want
                          notifications.

2. Notifications only (Phase 1) — merge hooks/notification-settings.example.json
   into your Claude Code settings.json, using this absolute command path:
       $VENV/bin/cc-poke-notify

3. Remote approve (Phase 2) — additionally:
     a. Reverse-proxy ONLY /webhook and /d to 127.0.0.1:8787 over HTTPS
        (keep /requests private). See README "反代 / reverse proxy".
     b. Start the daemon:
            systemctl --user enable --now cc-poke-daemon
     c. Merge hooks/pretooluse-settings.example.json into settings.json, using:
            $VENV/bin/cc-poke-approve

Verify notifications:
    echo '{"message":"hello from cc-poke","cwd":"/tmp"}' | $VENV/bin/cc-poke-notify
EOF
