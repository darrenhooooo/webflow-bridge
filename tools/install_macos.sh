#!/usr/bin/env bash
# One-command macOS install for the Webflow Bridge daemon (Phase 0.1).
#
#   ./tools/install_macos.sh [--binary PATH] [--purge]
#
# Copies the self-contained daemon into ~/Library/Application Support/
# WebflowBridge/, writes a launchd LaunchAgent and bootstraps it, then probes
# GET /status to prove the daemon is actually alive. No Python required.
#
# Idempotent: re-running stops+replaces the previous install and re-registers
# exactly one agent. Overridable for isolated tests (installer_test.py):
#   WBF_LABEL, WBF_HTTP_PORT, WBF_WS_PORT, WBF_BINARY, WBF_APP_DIR
set -euo pipefail

LABEL="${WBF_LABEL:-com.yctech.wb.daemon}"
HTTP_PORT="${WBF_HTTP_PORT:-10086}"
WS_PORT="${WBF_WS_PORT:-10087}"
APP_DIR="${WBF_APP_DIR:-$HOME/Library/Application Support/WebflowBridge}"
LOG_DIR="$HOME/Library/Logs/WebflowBridge"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

BINARY="${WBF_BINARY:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --binary) BINARY="${2:?--binary needs a path}"; shift 2 ;;
    --purge)  shift ;;                       # accepted (uninstall-side flag)
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$BINARY" ]; then
  BINARY="$(ls -t "$REPO"/dist/webflow-bridge-daemon-*-macos 2>/dev/null | head -1 || true)"
fi
[ -n "$BINARY" ] && [ -f "$BINARY" ] || {
  echo "FATAL: no daemon binary. Build one first:" >&2
  echo "  python3.11 tools/build_standalone.py" >&2
  exit 1
}
BINARY="$(cd "$(dirname "$BINARY")" && pwd)/$(basename "$BINARY")"

xml_escape() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

echo "[install] label=$LABEL ports=$HTTP_PORT/$WS_PORT"
echo "[install] binary=$BINARY"

mkdir -p "$APP_DIR" "$LOG_DIR" "$HOME/Library/LaunchAgents"

# Idempotent: remove any previous registration before replacing files.
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
rm -f "$PLIST"

install -m 0755 "$BINARY" "$APP_DIR/webflow-bridge-daemon"

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$(xml_escape "$LABEL")</string>
    <key>ProgramArguments</key>
    <array>
        <string>$(xml_escape "$APP_DIR")/webflow-bridge-daemon</string>
        <string>--http-port</string>
        <string>$HTTP_PORT</string>
        <string>--ws-port</string>
        <string>$WS_PORT</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>$(xml_escape "$APP_DIR")</string>
    <key>StandardOutPath</key>
    <string>$(xml_escape "$LOG_DIR")/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>$(xml_escape "$LOG_DIR")/daemon.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>$(xml_escape "$HOME")</string>
    </dict>
</dict>
</plist>
PLIST_EOF

# Retry: bootout above is synchronous but launchd can briefly still report the
# old label, which makes bootstrap fail with EIO on an immediate re-install.
ok=0
for _ in 1 2 3 4 5; do
  if launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null; then ok=1; break; fi
  sleep 1
done
[ "$ok" = 1 ] || { echo "FATAL: launchctl bootstrap failed for $PLIST" >&2; exit 1; }

# Self-check: the daemon is only "installed" once it answers /status.
probe() {
  local cfg tok
  cfg="$(curl -fsS --max-time 2 "http://127.0.0.1:$HTTP_PORT/config" 2>/dev/null)" || return 1
  tok="$(printf '%s' "$cfg" | sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
  [ -n "$tok" ] || return 1
  curl -fsS --max-time 2 -H "Authorization: Bearer $tok" \
    "http://127.0.0.1:$HTTP_PORT/status" >/dev/null 2>&1
}
for _ in $(seq 1 30); do
  if probe; then
    echo "[ok] daemon alive: http://127.0.0.1:$HTTP_PORT/status"
    echo "[ok] installed to $APP_DIR (auto-starts at login)"
    exit 0
  fi
  sleep 1
done

echo "FATAL: daemon did not answer /status on port $HTTP_PORT within 30s." >&2
echo "  launchd log: $LOG_DIR/daemon.err" >&2
tail -n 20 "$LOG_DIR/daemon.err" 2>/dev/null >&2 || true
exit 1
