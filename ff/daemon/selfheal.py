#!/usr/bin/env python3
"""Failure-handling core for the Firefox edition -- v1.4 parity.

Pure, stdlib-only port of the Chrome/Edge self-heal layer in
daemon/webflow_bridge.py (failure screenshots, opt-in transient retry).
Field names, defaults, bounds and error strings are kept BYTE-FOR-BYTE
identical to the Chrome side so a script never has to change code when it
switches browsers -- tools/parity/selfheal_parity_test.py proves that.

Nothing here touches BiDi: ff_bridge.py wires these helpers around its own
dispatch.  Everything is import-safe (no side effects).
"""
from __future__ import annotations

import os
import random
import secrets
import time
from collections import namedtuple
from datetime import datetime

# Actions that reach the page/browser and can be screenshotted on failure.
# A parameter-validation failure never reaches the browser action, so it is
# never captured (see ff_bridge.Bridge._capture_failure_screenshot).
BROWSER_ACTIONS = frozenset({
    "evaluate", "navigate", "cdp", "find_tab", "snapshot", "click", "fill",
    "screenshot", "upload", "save_as_pdf", "mouse_click", "send_key",
    "type_text", "submit", "fill_form", "wait_for", "handle_dialog",
    "handle_file_chooser", "drop", "resize_page", "list_network_requests",
    "get_network_request", "list_console_messages", "tabs_list", "tabs_close",
    "tabs_close_all_but", "tabs_activate", "tabs_open", "probe",
    "list_downloads",
})

# Read-only actions: safe to re-run by construction, so a transient failure
# may be retried automatically.
NO_SIDE_EFFECT_ACTIONS = frozenset({
    "evaluate", "snapshot", "screenshot", "save_as_pdf", "probe", "find_tab",
    "tabs_list", "list_downloads", "list_network_requests",
    "get_network_request", "list_console_messages", "wait_for",
})
# Actions with a page/browser side effect: retried ONLY when the failure
# happened before the command was delivered to the page.
SIDE_EFFECT_ACTIONS = frozenset({
    "click", "fill", "type_text", "submit", "fill_form", "upload", "drop",
    "mouse_click", "send_key", "navigate",
})

RETRY_MAX_ATTEMPTS = 5            # extra attempts on top of the first try
RETRY_DEFAULT_ATTEMPTS = 2        # when a retry object is given without attempts
RETRY_DEFAULT_BACKOFF_MS = 400
RETRY_MAX_BACKOFF_MS = 5000
RETRY_JITTER_FRACTION = 0.25      # +/- 25% jitter on every backoff step

# Error substrings identifying a transient transport/debugger failure
# (case-insensitive, documented in docs/HTTP_API.md).
TRANSIENT_ERROR_MARKERS = (
    "did not respond within",
    "debugger",
    "no tab with id",
    "disconnected",
    "not connected",
    "connection closed",
    "reconnect",
    "detached",
    "cannot attach",
)
# Error substrings that PROVE the command never reached the page. Only then
# may a side-effecting action be retried. Deliberately NARROW: bare words like
# "disconnected"/"detached" can appear in page-exception text, and retrying a
# delivered click is worse than not retrying at all.
NOT_DELIVERED_MARKERS = (
    "extension not connected",       # daemon 503: the WS slot is empty
    "no tab with id",                # the tab was resolved before any action
    "cannot attach",                 # debugger attach refused
    "another debugger",              # attach blocked by DevTools / other client
    "debugger is not attached",      # CDP session gone before sendCommand
    "no session with given id",
)

CAPTURE_ON_ERROR_ENV = "WBF_CAPTURE_ON_ERROR"   # "0"/"false"/"off" disables
CAPTURE_DIR_ENV = "WBF_CAPTURE_DIR"             # overrides the captures root
# Same default tree as the Chrome edition: ~/.webflow_bridge/captures/<date>/.
DEFAULT_TOKEN_DIR = os.path.join(os.path.expanduser("~"), ".webflow_bridge")

# args.retry as parsed: given=False means the caller did not opt into retry.
RetrySpec = namedtuple("RetrySpec", "given attempts backoff_ms")


def parse_retry_spec(args):
    """args.retry -> (RetrySpec, None) or (None, error_message).

    Absent/None `retry` means no retry (a legacy request keeps the exact old
    behaviour). `attempts` is the number of EXTRA tries (0..5) and defaults to
    2 when the retry object omits it; `backoffMs` is the base delay
    (0..5000, default 400)."""
    spec = args.get("retry") if isinstance(args, dict) else None
    if spec is None:
        return RetrySpec(False, 0, RETRY_DEFAULT_BACKOFF_MS), None
    if not isinstance(spec, dict):
        return None, ("'args.retry' must be an object like "
                      '{"attempts": 2, "backoffMs": 400}')
    attempts = spec.get("attempts", RETRY_DEFAULT_ATTEMPTS)
    if not isinstance(attempts, int) or isinstance(attempts, bool) \
            or not 0 <= attempts <= RETRY_MAX_ATTEMPTS:
        return None, (f"'args.retry.attempts' must be an integer 0-"
                      f"{RETRY_MAX_ATTEMPTS} when provided")
    backoff = spec.get("backoffMs", RETRY_DEFAULT_BACKOFF_MS)
    if not isinstance(backoff, int) or isinstance(backoff, bool) \
            or not 0 <= backoff <= RETRY_MAX_BACKOFF_MS:
        return None, (f"'args.retry.backoffMs' must be an integer 0-"
                      f"{RETRY_MAX_BACKOFF_MS} when provided")
    return RetrySpec(True, attempts, backoff), None


def is_transient_error(error_text) -> bool:
    """True when the text names a retryable transport/debugger failure."""
    low = (error_text or "").lower()
    return any(marker in low for marker in TRANSIENT_ERROR_MARKERS)


def command_reached_page(error_text) -> bool:
    """False only when the error text PROVES the command never reached the
    page (so nothing can have executed). Conservative by design: an unknown
    failure counts as reached."""
    low = (error_text or "").lower()
    return not any(marker in low for marker in NOT_DELIVERED_MARKERS)


def classify_retry(action, error_text, delivered_to_page) -> bool:
    """Pure retry classifier: may this failed (action, error) be retried?

    * unknown / non-browser actions -> never;
    * transient transport/debugger errors -> retryable for no-side-effect
      actions, and for side-effecting actions ONLY when the command had not
      been delivered to the page (a click that already ran must not run
      twice)."""
    if action not in NO_SIDE_EFFECT_ACTIONS \
            and action not in SIDE_EFFECT_ACTIONS:
        return False
    if not is_transient_error(error_text):
        return False
    if action in SIDE_EFFECT_ACTIONS and delivered_to_page:
        return False
    return True


def retry_delay_seconds(base_ms, attempt) -> float:
    """Exponential backoff (base * 2^(attempt-1)) with +/-25% jitter, capped
    at RETRY_MAX_BACKOFF_MS. `attempt` is 1-based."""
    base = min(base_ms * (2 ** max(0, attempt - 1)), RETRY_MAX_BACKOFF_MS)
    jitter = base * RETRY_JITTER_FRACTION * (random.random() * 2.0 - 1.0)
    return max(0.0, (base + jitter) / 1000.0)


def error_text_of(body) -> str:
    """Best-effort error string out of a response body ('' when absent)."""
    if isinstance(body, dict):
        return str(body.get("error") or body.get("status") or "")
    return str(body or "")


def execute_with_retry(dispatch_fn, payload, spec):
    """Run dispatch_fn(payload) under `spec` -> (status, body, retries, log).

    Pure wrapper around a dispatch callable so the policy is unit-testable
    with a fake dispatch. `retries` counts attempts actually re-run; `log` is
    one {attempt, error, delivered} entry per re-run."""
    action = payload.get("action") if isinstance(payload, dict) else None
    attempts_log = []
    retries = 0
    status, body = 200, {"status": "error", "error": "internal error"}
    for i in range(spec.attempts + 1):
        status, body = dispatch_fn(payload)
        if status == 200 and isinstance(body, dict) \
                and body.get("status") == "ok":
            return status, body, retries, attempts_log
        if i >= spec.attempts:
            break
        err = error_text_of(body)
        delivered = command_reached_page(err)
        if not classify_retry(action, err, delivered):
            break
        attempts_log.append({"attempt": i + 1, "error": err,
                             "delivered": delivered})
        retries += 1
        delay = retry_delay_seconds(spec.backoff_ms, i + 1)
        if delay > 0:
            time.sleep(delay)
    return status, body, retries, attempts_log


def capture_enabled(args) -> bool:
    """WBF_CAPTURE_ON_ERROR=0 (global) or args.captureOnError=false (single
    request) turns the failure screenshot off; default ON."""
    raw = os.environ.get(CAPTURE_ON_ERROR_ENV, "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if isinstance(args, dict) and args.get("captureOnError") is False:
        return False
    return True


def capture_root() -> str:
    """Root of the captures tree: WBF_CAPTURE_DIR or ~/.webflow_bridge/captures."""
    return os.environ.get(CAPTURE_DIR_ENV) or os.path.join(DEFAULT_TOKEN_DIR,
                                                           "captures")


def capture_path(action, root=None, now=None) -> str:
    """<root>/<YYYY-MM-DD>/<HHMMSS>-<action>-<4 hex>.png (pure, testable)."""
    stamp = now if now is not None else datetime.now()
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "_"
                    for ch in str(action or "action")) or "action"
    return os.path.join(root or capture_root(), stamp.strftime("%Y-%m-%d"),
                        "%s-%s-%s.png" % (stamp.strftime("%H%M%S"), safe,
                                          secrets.token_hex(2)))
