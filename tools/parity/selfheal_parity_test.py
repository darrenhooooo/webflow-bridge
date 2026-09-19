#!/usr/bin/env python3
"""Self-heal parity test: Chrome/Edge daemon vs Firefox selfheal core.

One case table is fed to BOTH implementations and every observable is
asserted identical:

  * daemon/webflow_bridge.py          (Chrome/Edge, the shipped v1.4 logic)
  * ff/daemon/selfheal.py             (Firefox port)

Covered: transient/non-transient error text x read-only/side-effecting
action x delivered/not-delivered x attempt bounds (>=20 classifier rows),
parse_retry_spec defaults+bounds+error text, the seeded backoff sequence,
execute_with_retry (retries / attempt log / cap) and the capture path/env
rules.  Any mismatch prints a diff line and exits non-zero.

Usage:  python3 tools/parity/selfheal_parity_test.py
"""
from __future__ import annotations

import os
import random
import re
import sys
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "daemon"))
sys.path.insert(0, os.path.join(REPO, "ff", "daemon"))

import webflow_bridge as chrome                                  # noqa: E402
import selfheal as ff                                            # noqa: E402

DIFFS = []
COUNT = 0


def diff(label: str, a, b) -> None:
    DIFFS.append(f"{label}: chrome={a!r} ff={b!r}")


def eq(label: str, a, b) -> None:
    global COUNT
    COUNT += 1
    # namedtuples from two modules are different classes but equal by value
    if isinstance(a, tuple) and isinstance(b, tuple) \
            and hasattr(a, "_fields") and hasattr(b, "_fields"):
        a, b = tuple(a), tuple(b)
    if a != b or type(a) is not type(b):
        diff(label, a, b)


def check(label: str, cond: bool, detail: str = "") -> None:
    global COUNT
    COUNT += 1
    if not cond:
        DIFFS.append(f"{label}: FAIL {detail}")


# ---------------------------------------------------------------------------
# 1. classifier table (>=20 rows): action x error x delivered
# ---------------------------------------------------------------------------
TRANSIENT = [
    "CDP evaluate did not respond within 30s",
    "Extension wb disconnected",
    "extension not connected",
    "no tab with id 42",
    "cannot attach debugger to tab 5",
    "another debugger is already attached",
    "debugger is not attached",
    "no session with given id",
    "connection closed",
    "firefox not connected",
    "please reconnect",
    "target detached",
]
NON_TRANSIENT = [
    "no element matches selector #nope",
    "javascript error: TypeError: x is undefined",
    "unknown action: frobnicate",
    "file not found: /tmp/x",
    "",
    "wait_for timed out after 10000ms: condition not met",
    "value is not a string",
    "timed out waiting for the page",   # note: no exact marker
]
ACTIONS = ["evaluate", "wait_for", "snapshot", "click", "fill", "type_text",
           "navigate", "surface_unknown_action"]

CASES = []
for err in TRANSIENT:
    for action in ("evaluate", "click"):
        for delivered in (True, False):
            CASES.append((action, err, delivered))
for err in NON_TRANSIENT:
    for action in ("evaluate", "click", "unknown"):
        for delivered in (True, False):
            CASES.append((action, err, delivered))
CASES.append(("evaluate", "connected", True))          # bare non-marker
CASES.append(("tab_close", "disconnected", False))     # side-effect-ish

for action, err, delivered in CASES:
    eq(f"classify_retry({action!r}, {err[:32]!r}, {delivered})",
       chrome.classify_retry(action, err, delivered),
       ff.classify_retry(action, err, delivered))
    eq(f"is_transient_error({err[:32]!r})",
       chrome.is_transient_error(err), ff.is_transient_error(err))
    eq(f"command_reached_page({err[:32]!r})",
       chrome.command_reached_page(err), ff.command_reached_page(err))


# ---------------------------------------------------------------------------
# 2. parse_retry_spec: defaults, bounds and error strings
# ---------------------------------------------------------------------------
PARSE_CASES = [
    None, {}, {"retry": None},
    {"retry": {"attempts": 0}}, {"retry": {"attempts": 2}},
    {"retry": {"attempts": 5}}, {"retry": {"attempts": 6}},
    {"retry": {"attempts": -1}}, {"retry": {"attempts": True}},
    {"retry": {"attempts": 1.5}}, {"retry": {"attempts": "2"}},
    {"retry": {"backoffMs": 0}}, {"retry": {"backoffMs": 5000}},
    {"retry": {"backoffMs": 5001}}, {"retry": {"backoffMs": -1}},
    {"retry": {"backoffMs": False}},
    {"retry": {"attempts": 3, "backoffMs": 250}},
    {"retry": "nope"}, {"retry": 7}, {"retry": []},
]
for args in PARSE_CASES:
    a_spec, a_err = chrome.parse_retry_spec(args)
    b_spec, b_err = ff.parse_retry_spec(args)
    eq(f"parse_retry_spec({args!r}) spec", a_spec, b_spec)
    eq(f"parse_retry_spec({args!r}) err", a_err, b_err)
    if a_spec is not None:
        eq(f"parse_retry_spec({args!r}) given", a_spec.given, b_spec.given)
    if a_err is not None:
        check(f"parse_retry_spec({args!r}) err is str",
              isinstance(a_err, str) and isinstance(b_err, str), repr(a_err))


# ---------------------------------------------------------------------------
# 3. seeded backoff sequence (jitter consumes the shared RNG identically)
# ---------------------------------------------------------------------------
for base in (0, 1, 400, 1000, 3333, 5000, 9999):
    for attempt in range(1, 7):
        random.seed(1000 + base + attempt)
        a = chrome.retry_delay_seconds(base, attempt)
        random.seed(1000 + base + attempt)
        b = ff.retry_delay_seconds(base, attempt)
        eq(f"retry_delay_seconds({base}, {attempt})", a, b)
# mixed sequence, one shared RNG stream reset
for base in (400, 1200):
    random.seed(7)
    a_seq = [chrome.retry_delay_seconds(base, i) for i in range(1, 7)]
    random.seed(7)
    b_seq = [ff.retry_delay_seconds(base, i) for i in range(1, 7)]
    eq(f"backoff sequence base={base}", a_seq, b_seq)


# ---------------------------------------------------------------------------
# 4. execute_with_retry: fake dispatch (no RNG by using backoffMs=0)
# ---------------------------------------------------------------------------
def run_wrapper(mod, action, error, fail_times, attempts, backoff=0):
    state = {"n": 0}

    def fake(payload):
        state["n"] += 1
        if state["n"] <= fail_times:
            return 200, {"status": "error", "error": error}
        return 200, {"status": "ok", "data": {"value": state["n"]}}

    spec = mod.RetrySpec(True, attempts, backoff)
    status, body, retries, log = mod.execute_with_retry(
        fake, {"action": action}, spec)
    return status, body.get("status"), body.get("data"), retries, log, state["n"]


WRAP_CASES = [
    ("evaluate", "CDP evaluate did not respond within 30s", 1, 2),
    ("evaluate", "Extension wb disconnected", 2, 5),
    ("evaluate", "no element matches selector", 5, 3),
    ("click", "cannot attach debugger to tab 5", 1, 3),   # pre-delivery -> retry
    ("click", "CDP click did not respond within 30s", 5, 3),  # delivered -> stop
    ("click", "no tab with id 42", 1, 3),                 # pre-delivery marker
    ("navigate", "connection closed", 5, 5),
    ("mystery", "Extension wb disconnected", 5, 4),       # unknown -> no retry
    ("evaluate", "Extension wb disconnected", 0, 3),      # first try ok
]
for action, error, fail_times, attempts in WRAP_CASES:
    a = run_wrapper(chrome, action, error, fail_times, attempts)
    b = run_wrapper(ff, action, error, fail_times, attempts)
    eq(f"execute_with_retry({action!r}, {error[:24]!r}, fail={fail_times}, "
       f"att={attempts})", a, b)


# ---------------------------------------------------------------------------
# 5. capture path / env rules
# ---------------------------------------------------------------------------
FIXED_NOW = datetime(2025, 1, 2, 3, 4, 5)
a_path = chrome.capture_path("click", root="/tmp/wb_cap", now=FIXED_NOW)
b_path = ff.capture_path("click", root="/tmp/wb_cap", now=FIXED_NOW)
SHAPE = re.compile(r"^/tmp/wb_cap/2025-01-02/030405-click-[0-9a-f]{4}\.png$")
check("chrome capture_path shape", bool(SHAPE.match(a_path)), a_path)
check("ff capture_path shape", bool(SHAPE.match(b_path)), b_path)
eq("capture_path dir prefix", os.path.dirname(a_path), os.path.dirname(b_path))
for action in (None, "a/b c", "", "wait_for"):
    a_p = chrome.capture_path(action, root="/tmp/r", now=FIXED_NOW)
    b_p = ff.capture_path(action, root="/tmp/r", now=FIXED_NOW)
    eq(f"capture_path({action!r}) dir",
       os.path.dirname(a_p), os.path.dirname(b_p))
    eq(f"capture_path({action!r}) name shape",
       re.sub(r"[0-9a-f]{4}\.png$", "X.png", os.path.basename(a_p)),
       re.sub(r"[0-9a-f]{4}\.png$", "X.png", os.path.basename(b_p)))

CAPTURE_ENV_CASES = [
    ({}, {}),
    ({"WBF_CAPTURE_ON_ERROR": "0"}, {}),
    ({"WBF_CAPTURE_ON_ERROR": "false"}, {"captureOnError": False}),
    ({"WBF_CAPTURE_ON_ERROR": "OFF"}, {}),
    ({"WBF_CAPTURE_ON_ERROR": "no"}, {}),
    ({"WBF_CAPTURE_ON_ERROR": "1"}, {"captureOnError": False}),
    ({"WBF_CAPTURE_ON_ERROR": ""}, {"captureOnError": True}),
]
for env, args in CAPTURE_ENV_CASES:
    old_env = {k: os.environ.get(k) for k in env}
    old_cap = os.environ.get("WBF_CAPTURE_DIR")
    try:
        for k, v in env.items():
            os.environ[k] = v
        eq(f"capture_enabled({env}, {args})",
           chrome.capture_enabled(args), ff.capture_enabled(args))
        os.environ["WBF_CAPTURE_DIR"] = "/tmp/wb_env_root"
        eq(f"capture_root({env})",
           chrome.capture_root(), ff.capture_root())
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if old_cap is None:
            os.environ.pop("WBF_CAPTURE_DIR", None)
        else:
            os.environ["WBF_CAPTURE_DIR"] = old_cap
eq("default capture_root", chrome.capture_root(), ff.capture_root())
eq("BROWSER_ACTIONS", chrome.BROWSER_ACTIONS, ff.BROWSER_ACTIONS)
eq("NO_SIDE_EFFECT_ACTIONS", chrome.NO_SIDE_EFFECT_ACTIONS,
   ff.NO_SIDE_EFFECT_ACTIONS)
eq("SIDE_EFFECT_ACTIONS", chrome.SIDE_EFFECT_ACTIONS, ff.SIDE_EFFECT_ACTIONS)
eq("TRANSIENT_ERROR_MARKERS", chrome.TRANSIENT_ERROR_MARKERS,
   ff.TRANSIENT_ERROR_MARKERS)
eq("NOT_DELIVERED_MARKERS", chrome.NOT_DELIVERED_MARKERS,
   ff.NOT_DELIVERED_MARKERS)
eq("retry constants",
   (chrome.RETRY_MAX_ATTEMPTS, chrome.RETRY_DEFAULT_ATTEMPTS,
    chrome.RETRY_DEFAULT_BACKOFF_MS, chrome.RETRY_MAX_BACKOFF_MS,
    chrome.RETRY_JITTER_FRACTION),
   (ff.RETRY_MAX_ATTEMPTS, ff.RETRY_DEFAULT_ATTEMPTS,
    ff.RETRY_DEFAULT_BACKOFF_MS, ff.RETRY_MAX_BACKOFF_MS,
    ff.RETRY_JITTER_FRACTION))


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
print(f"[selfheal-parity] classifier rows : {len(CASES)}")
print(f"[selfheal-parity] parse rows      : {len(PARSE_CASES)}")
print(f"[selfheal-parity] wrapper rows    : {len(WRAP_CASES)}")
print(f"[selfheal-parity] assertions      : {COUNT}")
if DIFFS:
    print(f"[selfheal-parity] FAILED: {len(DIFFS)} difference(s)")
    for line in DIFFS:
        print("  DIFF " + line)
    sys.exit(1)
print("[selfheal-parity] PASSED: chrome and ff self-heal are identical")
sys.exit(0)
