#!/usr/bin/env bash
#
# cc-poke uninstaller.
#
#   ./uninstall.sh            # stop+remove the daemon unit, keep venv & config
#   ./uninstall.sh --purge    # also delete the venv and the config directory
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$REPO_DIR/.venv"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
CONFIG_DIR="$CONFIG_HOME/cc-poke"
UNIT_FILE="$CONFIG_HOME/systemd/user/cc-poke-daemon.service"

PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

c_info='\033[36m'; c_ok='\033[32m'; c_off='\033[0m'
info() { printf "${c_info}[cc-poke]${c_off} %s\n" "$*"; }
ok()   { printf "${c_ok}[cc-poke]${c_off} %s\n" "$*"; }

# 1) daemon -------------------------------------------------------------------
if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  systemctl --user disable --now cc-poke-daemon >/dev/null 2>&1 || true
  if [ -f "$UNIT_FILE" ]; then
    rm -f "$UNIT_FILE"
    systemctl --user daemon-reload || true
    ok "removed daemon unit"
  fi
fi

# 2) optional purge -----------------------------------------------------------
if [ "$PURGE" -eq 1 ]; then
  rm -rf "$VENV" && ok "removed venv $VENV"
  rm -rf "$CONFIG_DIR" && ok "removed config $CONFIG_DIR"
else
  info "kept venv ($VENV) and config ($CONFIG_DIR) — re-run with --purge to remove"
fi

cat <<EOF

$(ok "uninstall done.")
Don't forget to remove the cc-poke hook entries (Notification / PreToolUse)
from your Claude Code settings.json — this script does not edit that file.
EOF
