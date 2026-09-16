#!/usr/bin/env bash
# macOS uninstall for the Webflow Bridge daemon (Phase 0.1).
#
#   ./tools/uninstall_macos.sh [--purge]
#
# Stops the launchd agent, removes the plist and the installed files. The
# token/audit directory (~/.webflow_bridge) is KEPT by default; --purge also
# deletes it. Idempotent: safe on a machine that was never installed.
#
# Overridable for isolated tests: WBF_LABEL, WBF_APP_DIR.
set -euo pipefail

LABEL="${WBF_LABEL:-com.yctech.wb.daemon}"
APP_DIR="${WBF_APP_DIR:-$HOME/Library/Application Support/WebflowBridge}"
LOG_DIR="$HOME/Library/Logs/WebflowBridge"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

PURGE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --purge) PURGE=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

echo "[uninstall] label=$LABEL"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
rm -rf "$APP_DIR" "$LOG_DIR"

if [ "$PURGE" = 1 ]; then
  rm -rf "$HOME/.webflow_bridge"
  echo "[ok] purged $HOME/.webflow_bridge (token + audit)"
else
  echo "[keep] $HOME/.webflow_bridge (token + audit) — use --purge to delete"
fi
echo "[ok] uninstalled"
