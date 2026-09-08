#!/usr/bin/env python3
"""Webflow Bridge for Firefox -- P0 end-to-end smoke test.

Connects to the ff daemon's HTTP endpoint (:10096 by default) and drives a
real Firefox (opened by ff/ff-launch.bat, BiDi on :9222):

  1. evaluate "1+1"            -> 2
  2. navigate https://example.com   (wait complete)
  3. evaluate "document.title" -> "Example Domain"
  4. tabs_list                 -> non-empty list with id/url

Requires an external Firefox already running in BiDi mode (ff-launch.bat).
Reads the shared token from ~/.webflow_bridge_ff/token (or WBF_FF_TOKEN /
--token); pass --no-auth when the daemon runs with --allow-no-auth.

Exit code 0 when every step passes, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_TOKEN_PATH = os.path.join(
    os.path.expanduser("~"), ".webflow_bridge_ff", "token")

STEPS = [
    ("evaluate 1+1", "evaluate", {"code": "1 + 1"}, "2"),
    ("navigate example.com", "navigate", {"url": "https://example.com"}, None),
    ("evaluate document.title", "evaluate",
     {"code": "document.title"}, "Example Domain"),
]


def read_token(path: str) -> str:
    env = os.environ.get("WBF_FF_TOKEN")
    if env:
        return env.strip()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            tok = fh.read().strip()
            if tok:
                return tok
    except FileNotFoundError:
        pass
    return ""


def post(base: str, token: str, action: str, args: dict) -> dict:
    body = json.dumps({"action": action, "args": args}).encode("utf-8")
    req = urllib.request.Request(
        base + "/command", data=body,
        headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=150) as resp:
            return {"http": resp.status, "body": json.loads(resp.read().decode("utf-8"))}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = {"raw": raw}
        return {"http": exc.code, "body": parsed}
    except urllib.error.URLError as exc:
        return {"http": 0, "body": {"error": f"cannot reach daemon: {exc.reason}"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:10096",
                        help="ff daemon base URL (default http://127.0.0.1:10096)")
    parser.add_argument("--token", default="",
                        help="bearer token (default: ~/.webflow_bridge_ff/token)")
    parser.add_argument("--no-auth", action="store_true",
                        help="daemon runs with --allow-no-auth; send no header")
    opts = parser.parse_args()

    token = "" if opts.no_auth else (opts.token or read_token(DEFAULT_TOKEN_PATH))
    base = opts.base.rstrip("/")
    print(f"[ff-smoke] daemon {base}  token={'<env/file>' if token else 'none'}")
    print()

    failures = []

    # Step: evaluate 1+1 -> 2
    print("STEP 1/4  evaluate 1+1")
    r = post(base, token, "evaluate", {"code": "1 + 1"})
    value = (r.get("body") or {}).get("data", {}).get("value") \
        if r.get("http") == 200 else None
    ok = r.get("http") == 200 and value == 2
    print(f"  -> http={r.get('http')} value={value!r}")
    if not ok:
        failures.append(f"evaluate 1+1: expected 2, got {r!r}")

    # Step: navigate example.com
    print("STEP 2/4  navigate https://example.com")
    r = post(base, token, "navigate", {"url": "https://example.com"})
    body = r.get("body") or {}
    ok = r.get("http") == 200 and body.get("status") == "ok"
    print(f"  -> http={r.get('http')} body={json.dumps(body, ensure_ascii=False)[:200]}")
    if not ok:
        failures.append(f"navigate example.com failed: {r!r}")

    # Step: evaluate document.title
    print("STEP 3/4  evaluate document.title")
    r = post(base, token, "evaluate", {"code": "document.title"})
    value = (r.get("body") or {}).get("data", {}).get("value") \
        if r.get("http") == 200 else None
    ok = r.get("http") == 200 and value == "Example Domain"
    print(f"  -> http={r.get('http')} value={value!r}")
    if not ok:
        failures.append(f"evaluate document.title: expected 'Example Domain', got {r!r}")

    # Step: tabs_list non-empty
    print("STEP 4/4  tabs_list")
    r = post(base, token, "tabs_list", {})
    value = (r.get("body") or {}).get("data", {}).get("value") \
        if r.get("http") == 200 else None
    ok = (r.get("http") == 200 and isinstance(value, list) and len(value) > 0
          and all(isinstance(t, dict) and t.get("id") for t in value))
    print(f"  -> http={r.get('http')} tabs={value!r}")
    if not ok:
        failures.append(f"tabs_list: expected non-empty list with ids, got {r!r}")

    print()
    if failures:
        print("[ff-smoke] FAILED:")
        for f in failures:
            print("  - " + f)
        return 1
    print("[ff-smoke] PASSED: all 4 steps ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
