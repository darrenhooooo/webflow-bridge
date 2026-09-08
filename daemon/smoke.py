#!/usr/bin/env python3
"""
Webflow Bridge smoke test.

Sends a few real commands through the full pipeline:

    daemon (:10086)  ->  WS (:10087)  ->  extension  ->  active tab page

Prerequisites:
  1. daemon running:       uv run --python 3.11 daemon/webflow_bridge.py
  2. extension loaded:     chrome://extensions -> Developer mode -> Load unpacked
                           -> extension/   (Webflow Bridge)
  3. Chrome open on a real http(s) page in the ACTIVE tab (not chrome://,
     not a new-tab page — content scripts cannot run there).

Usage:
    uv run --python 3.11 daemon/smoke.py
    uv run --python 3.11 daemon/smoke.py --navigate=https://example.com

Prints PASS/FAIL per check and exits non-zero when anything fails.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

ENDPOINT = "http://127.0.0.1:10086/command"

# The daemon requires the shared bearer token (P0): it is read from
# $WBF_TOKEN or ~/.webflow_bridge/token (same defaults as the daemon). When
# the daemon runs with --allow-no-auth no header is needed/sent.
TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".webflow_bridge", "token")


def _auth_headers() -> dict:
    token = os.environ.get("WBF_TOKEN")
    if not token:
        path = os.environ.get("WBF_TOKEN_FILE") or TOKEN_FILE
        try:
            with open(path, "r", encoding="utf-8") as fh:
                token = fh.read().strip()
        except OSError:
            token = ""
    return {"Authorization": f"Bearer {token}"} if token else {}


# ---------------- tiny HTTP client (mirrors the publish scripts) ----------

def post(payload: dict):
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **_auth_headers()},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=140) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"raw": raw}
    except urllib.error.URLError as exc:
        return None, {"error": f"cannot reach daemon: {exc.reason}"}


def evaluate(code: str):
    return post({"action": "evaluate", "args": {"code": code}, "session": "default"})


def navigate(url: str):
    return post({"action": "navigate", "args": {"url": url}, "session": "default"})


def cdp(method: str, params=None):
    args = {"method": method}
    if params is not None:
        args["params"] = params
    return post({"action": "cdp", "args": args, "session": "default"})


def tabs_list():
    return post({"action": "tabs_list", "args": {}, "session": "default"})


# ---------------- verdict helpers -----------------------------------------

def _not_connected(status, body) -> bool:
    return status == 503 or (isinstance(body, dict) and "extension not connected"
                             in str(body.get("error", "")))


def expect_ok_value(code: str, want):
    status, body = evaluate(code)
    if status is None:
        return False, f"daemon unreachable: {body.get('error')} — start it with 'uv run --python 3.11 daemon/webflow_bridge.py'"
    if _not_connected(status, body):
        return False, "extension not connected — load extension/ in Chrome and keep an http(s) page active"
    if isinstance(body, dict) and "Receiving end does not exist" in str(body.get("error", "")):
        return False, "no content script on the active tab — open a normal http(s) page"
    if status != 200 or body.get("status") != "ok":
        return False, f"expected ok, got status={status} body={body}"
    got = body.get("data", {}).get("value")
    if got != want:
        return False, f"expected value {want!r}, got {got!r}"
    return True, ""


def expect_ok_object(code: str):
    status, body = evaluate(code)
    if status is None:
        return False, f"daemon unreachable: {body.get('error')}"
    if _not_connected(status, body):
        return False, "extension not connected — load extension/ in Chrome and keep an http(s) page active"
    if status != 200 or body.get("status") != "ok":
        return False, f"expected ok, got status={status} body={body}"
    got = body.get("data", {}).get("value")
    if not isinstance(got, dict):
        return False, f"expected an object result, got {got!r}"
    url = got.get("url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False, f"expected page url http(s), got {url!r}"
    return True, ""


def expect_error_reported(code: str, needle: str):
    status, body = evaluate(code)
    if status is None:
        return False, f"daemon unreachable: {body.get('error')}"
    if _not_connected(status, body):
        return False, "extension not connected — load extension/ in Chrome and keep an http(s) page active"
    if status != 200 or body.get("status") != "error":
        return False, f"expected status=error, got status={status} body={body}"
    if needle not in str(body.get("error", "")):
        return False, f"error text missing {needle!r}: {body.get('error')!r}"
    return True, ""


def expect_cdp_title():
    """cdp Runtime.evaluate passthrough: document.title must be a string.

    CDP returns {result: {type, value}}; the string title is nested at
    data.value.result.value. May be empty on exotic pages — any string is OK.
    """
    status, body = cdp("Runtime.evaluate",
                       {"expression": "document.title", "returnByValue": True})
    if status is None:
        return False, f"daemon unreachable: {body.get('error')}"
    if _not_connected(status, body):
        return False, "extension not connected — load extension/ in Chrome and keep an http(s) page active"
    if status != 200 or body.get("status") != "ok":
        return False, f"expected ok, got status={status} body={body}"
    got = body.get("data", {}).get("value")
    result = got.get("result") if isinstance(got, dict) else None
    value = result.get("value") if isinstance(result, dict) else None
    if not isinstance(value, str):
        return False, f"expected data.value.result.value to be a string title, got {got!r}"
    return True, ""


def expect_tabs_list():
    """tabs_list must return a non-empty list whose items carry numeric ids."""
    status, body = tabs_list()
    if status is None:
        return False, f"daemon unreachable: {body.get('error')}"
    if _not_connected(status, body):
        return False, "extension not connected — load extension/ in Chrome and keep an http(s) page active"
    if status != 200 or body.get("status") != "ok":
        return False, f"expected ok, got status={status} body={body}"
    value = body.get("data", {}).get("value")
    if not isinstance(value, list) or not value:
        return False, f"expected a non-empty tab list, got {value!r}"
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            return False, f"expected a numeric id per tab item, got {item!r}"
    return True, ""


# ---------------- main -----------------------------------------------------

def main(argv) -> int:
    print("Webflow Bridge smoke test")
    print(f"  endpoint : POST {ENDPOINT}")
    print("  preconditions: daemon running, 'Webflow Bridge' extension loaded,")
    print("                 Chrome active tab on a real http(s) page")
    print()

    cases = [
        ("evaluate: basic arithmetic -> 2",
         lambda: expect_ok_value("(() => 1 + 1)()", 2)),
        ("evaluate: document.title is a string",
         lambda: _title_check()),
        ("evaluate: structured object result (url/title)",
         lambda: expect_ok_object("(() => ({ url: location.href, title: document.title }))()")),
        ("evaluate: thrown error is reported as status=error",
         lambda: expect_error_reported("(() => { throw new Error('webflow-smoke-error'); })()",
                                       "webflow-smoke-error")),
        ("cdp: Runtime.evaluate passthrough returns document.title",
         lambda: expect_cdp_title()),
        ("tabs_list returns at least one tab",
         lambda: expect_tabs_list()),
    ]

    failures = 0
    for name, fn in cases:
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001 - a case must never kill the run
            ok, detail = False, f"unexpected exception: {exc!r}"
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok and detail:
            print(f"        {detail}")
        failures += 0 if ok else 1

    # Optional live-navigation check (off by default: it reloads the tab).
    nav_url = None
    for arg in argv[1:]:
        if arg.startswith("--navigate="):
            nav_url = arg.split("=", 1)[1]
    if nav_url:
        ok, detail = _navigate_check(nav_url)
        print(f"[{'PASS' if ok else 'FAIL'}] navigate: tab -> {nav_url}")
        if not ok and detail:
            print(f"        {detail}")
        failures += 0 if ok else 1

    total = len(cases) + (1 if nav_url else 0)
    print()
    print(f"summary: {total - failures}/{total} passed")
    if failures:
        print("HINT: make sure the daemon is running, the extension is loaded,")
        print("      and the active tab is a normal website.")
    return 1 if failures else 0


def _title_check():
    """document.title must be a string (may be empty on exotic pages)."""
    status, body = evaluate("(() => document.title)()")
    if status is None:
        return False, f"daemon unreachable: {body.get('error')}"
    if _not_connected(status, body):
        return False, "extension not connected — load extension/ in Chrome and keep an http(s) page active"
    if isinstance(body, dict) and "Receiving end does not exist" in str(body.get("error", "")):
        return False, "no content script on the active tab — open a normal http(s) page"
    if status != 200 or body.get("status") != "ok":
        return False, f"expected ok, got status={status} body={body}"
    got = body.get("data", {}).get("value")
    if not isinstance(got, str):
        return False, f"expected a string title, got {got!r}"
    return True, ""


def _navigate_check(url: str):
    status, body = navigate(url)
    if status is None:
        return False, f"daemon unreachable: {body.get('error')}"
    if _not_connected(status, body):
        return False, "extension not connected — load extension/ in Chrome and keep an http(s) page active"
    if status != 200 or body.get("status") != "ok":
        return False, f"expected ok, got status={status} body={body}"
    return True, ""


if __name__ == "__main__":
    sys.exit(main(sys.argv))
