#!/usr/bin/env bash
#
# Webflow Bridge — zero-SDK live demo (curl only, no bespoke client, no jq).
#
# Proves that the :10086 protocol is drivable by ANY generic HTTP tool:
#   1. tabs_open   https://example.com  -> capture the new tab id from JSON
#   2. sleep 4                          (let example.com settle)
#   3. evaluate    (() => document.title)()  -> expect "Example Domain"
#   4. sleep 1
#   5. tabs_close  <captured id>
#
# Prints PASS at every step, exits non-zero on the first mismatch.
# The flow opens + closes its OWN scratch tab and never touches other tabs.
#
# JSON parsing is python-free: the one value we must capture (the tab id from
# tabs_open) is extracted with sed. If sed comes up empty we fall back to
# python3 (or `uv run --python 3.11 python`) so the demo still works anywhere.
set -u

BASE=http://127.0.0.1:10086/command
CT='Content-Type: application/json'
fail=0

# Daemon shared bearer token (P0): $WBF_TOKEN or ~/.webflow_bridge/token.
# When the daemon runs with --allow-no-auth the header is simply omitted.
TOKEN="${WBF_TOKEN:-}"
if [ -z "$TOKEN" ]; then
  TOKEN=$(cat "$HOME/.webflow_bridge/token" 2>/dev/null | tr -d '[:space:]' || true)
fi
if [ -n "$TOKEN" ]; then
  AUTH="Authorization: Bearer $TOKEN"
else
  AUTH=''
fi

json_get_id() {
  # input:  JSON body on stdin (single line)
  # output: the first "id": <number> found, else nothing
  sed -nE 's/.*"id"[[:space:]]*:[[:space:]]*([0-9]+).*/\1/p' | head -n1
}

extract_tab_id() {
  # Try pure-bash/sed first; fall back to python if the id is not numeric.
  local raw="$1" id
  id=$(printf '%s' "$raw" | json_get_id)
  case "$id" in
    ''|*[!0-9]*) id='' ;;
  esac
  if [ -z "$id" ]; then
    if command -v uv >/dev/null 2>&1; then
      id=$(printf '%s' "$raw" | uv run --python 3.11 python -c \
        'import json,sys; print(json.load(sys.stdin)["data"]["value"]["id"])' 2>/dev/null)
    elif command -v python3 >/dev/null 2>&1; then
      id=$(printf '%s' "$raw" | python3 -c \
        'import json,sys; print(json.load(sys.stdin)["data"]["value"]["id"])' 2>/dev/null)
    fi
    case "$id" in
      ''|*[!0-9]*) id='' ;;
    esac
  fi
  printf '%s' "$id"
}

post() { # post <payload> -> body on stdout
  if [ -n "$AUTH" ]; then
    curl -sS -m 60 -X POST "$BASE" -H "$CT" -H "$AUTH" -d "$1"
  else
    curl -sS -m 60 -X POST "$BASE" -H "$CT" -d "$1"
  fi
}

echo "== [1/5] tabs_open https://example.com (own scratch tab)"
OPEN=$(post '{"action":"tabs_open","args":{"url":"https://example.com"},"session":"default"}')
echo "   response: $OPEN"
TAB_ID=$(extract_tab_id "$OPEN")
if [ -n "$TAB_ID" ]; then
  echo "   PASS tabs_open -> captured new tab id: $TAB_ID"
else
  echo "   FAIL tabs_open -> no numeric \"id\" in response"
  echo "   raw: $OPEN"
  fail=1
fi

echo "== [2/5] sleep 4 (wait for example.com to load)"
sleep 4
echo "   PASS sleep 4"

echo "== [3/5] evaluate (() => document.title)() on the active tab"
TITLE=$(post '{"action":"evaluate","args":{"code":"(() => document.title)()"},"session":"default"}')
echo "   response: $TITLE"
if printf '%s' "$TITLE" | grep -q 'Example Domain'; then
  echo "   PASS evaluate -> title is \"Example Domain\""
else
  echo "   FAIL evaluate -> expected \"Example Domain\" in response"
  echo "   raw: $TITLE"
  fail=1
fi

echo "== [4/5] sleep 1"
sleep 1
echo "   PASS sleep 1"

echo "== [5/5] tabs_close the scratch tab (id $TAB_ID)"
if [ -n "$TAB_ID" ]; then
  CLOSE=$(post "{\"action\":\"tabs_close\",\"args\":{\"tabId\":$TAB_ID},\"session\":\"default\"}")
  echo "   response: $CLOSE"
  if printf '%s' "$CLOSE" | grep -q '"closed"'; then
    echo "   PASS tabs_close -> closed tab $TAB_ID"
  else
    echo "   FAIL tabs_close -> expected {\"closed\": ...}"
    echo "   raw: $CLOSE"
    fail=1
  fi
else
  echo "   SKIP tabs_close (no tab id to close)"
  fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo
  echo "ALL PASS — Webflow Bridge driven end-to-end by plain curl, zero SDK."
  exit 0
fi
echo
echo "FLOW FAILED — see FAIL lines above."
exit 1
