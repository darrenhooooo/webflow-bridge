#!/usr/bin/env python3
"""Webflow Bridge for Firefox -- v1.4 self-heal smoke (ISOLATED stack).

Proves, end to end and without touching Darren's Firefox, the three v1.4
failure-handling behaviours plus the new wait_for action on the Firefox
backend:

  1. wait_for  -- appear (element injected after the call), gone (element
     removed), hidden (display:none), networkIdleMs (slow request, wait for
     silence) and the timeout wording;
  2. failure screenshots -- a failed browser action returns
     error_details.screenshot (real PNG on disk >1000 bytes), can be turned
     off with args.captureOnError=false, and parameter-validation failures
     never take one;
  3. transient retry -- in-process unit tests on the shared selfheal core
     plus one real integration case (the daemon is asked for evaluate while
     Firefox is still down, then Firefox starts and a later retry succeeds);
  4. legacy compatibility -- the retry/screenshot fields only appear when
     asked for, so pre-v1.4 requests keep their exact old shape.

Isolation (hard requirement): a throwaway profile under a temp dir, BiDi on
:9122 and the daemon on :10097 (never 9222/10086/10087/2008x/8901), the
daemon forced non-interactive with --allow-no-auth. Every process started
here is killed before exit and both ports are re-checked free.

Usage:  python3 ff/daemon/ff_selfheal_smoke.py
Prints PASS/FAIL per check; exits non-zero when anything fails.
"""
from __future__ import annotations

import functools
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import selfheal as sh                                            # noqa: E402

BIDI_PORT = 9122
HTTP_PORT = 10097
BASE = f"http://127.0.0.1:{HTTP_PORT}"
FF_CANDIDATES = [
    "/Applications/Firefox.app/Contents/MacOS/firefox",
    shutil.which("firefox") or "",
]

TEST_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>ff-selfheal-page</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 2em; background: #eef; }
  #hide-me { background: #0a6; color: #fff; padding: 1em; }
  .filler { height: 12em; background: linear-gradient(#fff, #99f); }
</style></head>
<body>
<h1>ff self-heal test page</h1>
<div id="doomed">doomed element</div>
<div id="hide-me">hide me</div>
<div class="filler">filler block for a &gt;1 KB screenshot</div>
<div id="out">out</div>
<script>
(function () {
  window.__armLate = function () {
    setTimeout(function () {
      var d = document.createElement('div');
      d.id = 'late';
      d.textContent = 'late arrived';
      document.body.appendChild(d);
    }, 700);
  };
  window.__killDoomed = function () {
    setTimeout(function () {
      var e = document.getElementById('doomed');
      if (e) e.remove();
    }, 700);
  };
  window.__hideMe = function () {
    setTimeout(function () {
      document.getElementById('hide-me').style.display = 'none';
    }, 700);
  };
  window.__slow = function () {
    fetch('/slow?ts=' + Date.now()).then(function (r) { return r.text(); })
      .then(function (t) { document.getElementById('out').textContent = t; });
  };
})();
</script>
</body></html>
"""

failures = []


def step(n, name, ok, note=""):
    print(f"STEP {n}  {name}")
    print(f"  -> {'PASS' if ok else 'FAIL'}" + (f"  {note}" if note else ""))
    if not ok:
        failures.append(f"{name}: {note}")
    return ok


record = {"n": 0}


def check(name, ok, note=""):
    record["n"] += 1
    return step(record["n"], name, ok, note)


# ---------------------------------------------------------------------------
# tiny infra
# ---------------------------------------------------------------------------

def find_firefox() -> str:
    for c in FF_CANDIDATES:
        if c and os.path.isfile(c):
            return c
    raise SystemExit("[ff-selfheal] FATAL: Firefox binary not found")


def port_open(port: int) -> bool:
    s = socket.socket()
    s.settimeout(0.4)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def wait_port(port: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(port):
            return True
        time.sleep(0.25)
    return False


def post(action, args, timeout=180):
    body = json.dumps({"action": action, "args": args}).encode("utf-8")
    req = urllib.request.Request(BASE + "/command", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"http": resp.status,
                    "body": json.loads(resp.read().decode("utf-8"))}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = {"raw": raw}
        return {"http": exc.code, "body": parsed}
    except urllib.error.URLError as exc:
        return {"http": 0, "body": {"error": f"cannot reach daemon: {exc.reason}"}}


def call(action, args):
    r = post(action, args)
    body = r.get("body") or {}
    if r.get("http") != 200 or body.get("status") != "ok":
        raise AssertionError(
            f"{action} failed: http={r.get('http')} "
            f"body={json.dumps(body, ensure_ascii=False)[:300]}")
    return body.get("data", {}).get("value")


class Stack:
    """Throwaway Firefox + ff daemon, both on private ports."""

    def __init__(self, tmp):
        self.tmp = tmp
        self.profile = os.path.join(tmp, "profile")
        self.captures = os.path.join(tmp, "captures")
        self.daemon = None
        self.firefox = None
        self._logs = []

    def _log(self, name):
        fh = open(os.path.join(self.tmp, name), "wb")
        self._logs.append(fh)
        return fh

    def start_daemon(self):
        env = dict(os.environ)
        env["WBF_CAPTURE_DIR"] = self.captures
        env.pop("WBF_FF_BIDI_URL", None)
        self.daemon = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "ff_bridge.py"),
             "--ff-port", str(BIDI_PORT), "--http-port", str(HTTP_PORT),
             "--allow-no-auth"],
            cwd=REPO, env=env, stdout=self._log("daemon.log"),
            stderr=subprocess.STDOUT)
        if not wait_port(HTTP_PORT, 15):
            raise SystemExit("[ff-selfheal] FATAL: daemon HTTP never came up")

    def start_firefox(self):
        os.makedirs(self.profile, exist_ok=True)
        self.firefox = subprocess.Popen(
            [find_firefox(), "-no-remote", "-profile", self.profile,
             "--remote-debugging-port", str(BIDI_PORT),
             "-remote-allow-system-access", "-headless"],
            stdout=self._log("firefox.log"), stderr=subprocess.STDOUT)
        if not wait_port(BIDI_PORT, 40):
            raise SystemExit("[ff-selfheal] FATAL: Firefox BiDi never came up")

    def stop(self):
        for proc in (self.daemon, self.firefox):
            if proc is None or proc.poll() is not None:
                continue
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=8)
        # belt and braces: any leftover child bound to OUR temp profile only
        subprocess.run(["pkill", "-f", self.profile],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for fh in self._logs:
            try:
                fh.close()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# in-process retry unit tests (no browser)
# ---------------------------------------------------------------------------

def unit_retry_checks():
    def fake_seq(action, error, fail_times, attempts):
        state = {"n": 0}

        def fake(payload):
            state["n"] += 1
            if state["n"] <= fail_times:
                return 200, {"status": "error", "error": error}
            return 200, {"status": "ok", "data": {"value": state["n"]}}

        spec = sh.RetrySpec(True, attempts, 0)
        st, body, retries, log = sh.execute_with_retry(
            fake, {"action": action}, spec)
        return st, body, retries, log, state["n"]

    st, body, retries, log, calls = fake_seq(
        "evaluate", "firefox not connected", 1, 2)
    check("retry unit: failure once then success -> retries=1, 2 calls",
          st == 200 and body.get("status") == "ok" and retries == 1
          and calls == 2 and len(log) == 1 and log[0]["delivered"] is True,
          f"retries={retries} calls={calls} log={log}")

    st, body, retries, log, calls = fake_seq(
        "click", "CDP click did not respond within 30s", 5, 3)
    check("retry unit: delivered side-effect click is NOT retried",
          retries == 0 and calls == 1
          and not sh.classify_retry(
              "click", "CDP click did not respond within 30s", True),
          f"retries={retries} calls={calls}")

    st, body, retries, log, calls = fake_seq(
        "click", "cannot attach debugger to tab 5", 1, 3)
    check("retry unit: pre-delivery side-effect failure IS retried",
          retries == 1 and calls == 2, f"retries={retries} calls={calls}")

    st, body, retries, log, calls = fake_seq(
        "evaluate", "connection closed", 99, sh.RETRY_MAX_ATTEMPTS)
    check(f"retry unit: attempts cap ({sh.RETRY_MAX_ATTEMPTS}) enforced",
          retries == sh.RETRY_MAX_ATTEMPTS
          and calls == sh.RETRY_MAX_ATTEMPTS + 1,
          f"retries={retries} calls={calls}")

    spec, err = sh.parse_retry_spec({"retry": {"attempts": 2}})
    bad = sh.parse_retry_spec({"retry": {"attempts": 9}})[1]
    check("retry unit: parse defaults + bounds",
          err is None and spec.attempts == 2 and bad is not None,
          f"spec={spec} bad_err={bad!r}")


# ---------------------------------------------------------------------------
# live checks
# ---------------------------------------------------------------------------

def live_checks(page_url):
    r = None

    # ---- 1. wait_for appear (element injected after the call) -----------
    try:
        call("navigate", {"url": page_url})
        call("evaluate", {"code": "window.__armLate()"})
        t0 = time.time()
        v = call("wait_for", {"selector": "#late", "timeoutMs": 6000,
                              "intervalMs": 100})
        elapsed = int((time.time() - t0) * 1000)
        ok = (isinstance(v, dict) and v.get("found") is True
              and v.get("matched") == "appear"
              and isinstance(v.get("elapsedMs"), int))
        check("wait_for appear: dynamic element found",
              ok and elapsed >= 400,
              f"value={json.dumps(v)} wallMs={elapsed} (needs >=400 to prove "
              f"real polling)")
    except AssertionError as exc:
        check("wait_for appear: dynamic element found", False, str(exc))

    # ---- 2. wait_for gone ----------------------------------------------
    try:
        call("navigate", {"url": page_url})
        call("evaluate", {"code": "window.__killDoomed()"})
        v = call("wait_for", {"selector": "#doomed", "until": "gone",
                              "timeoutMs": 6000, "intervalMs": 100})
        ok = (isinstance(v, dict) and v.get("found") is True
              and v.get("matched") == "gone")
        check("wait_for gone: removed element detected", ok,
              f"value={json.dumps(v)}")
    except AssertionError as exc:
        check("wait_for gone: removed element detected", False, str(exc))

    # ---- 3. wait_for hidden (display:none) -----------------------------
    try:
        call("navigate", {"url": page_url})
        call("evaluate", {"code": "window.__hideMe()"})
        v = call("wait_for", {"selector": "#hide-me", "until": "hidden",
                              "timeoutMs": 6000, "intervalMs": 100})
        ok = (isinstance(v, dict) and v.get("found") is True
              and v.get("matched") == "hidden")
        check("wait_for hidden: display:none detected", ok,
              f"value={json.dumps(v)}")
    except AssertionError as exc:
        check("wait_for hidden: display:none detected", False, str(exc))

    # ---- 4. wait_for networkIdleMs -------------------------------------
    try:
        call("navigate", {"url": page_url})
        call("evaluate", {"code": "window.__slow()"})
        v = call("wait_for", {"selector": "#out", "timeoutMs": 8000,
                              "intervalMs": 100, "networkIdleMs": 1000})
        idle = (v or {}).get("lastNetworkActivityMs")
        ok = (isinstance(v, dict) and v.get("found") is True
              and isinstance(idle, int) and idle >= 1000)
        check("wait_for networkIdleMs: waits for the slow request to settle",
              ok, f"value={json.dumps(v)}")
    except AssertionError as exc:
        check("wait_for networkIdleMs: waits for the slow request to settle",
              False, str(exc))

    # ---- 5. wait_for timeout wording -----------------------------------
    try:
        r = post("wait_for", {"selector": "#never-exists",
                              "timeoutMs": 900, "intervalMs": 100})
        body = r.get("body") or {}
        text = str(body.get("error") or "")
        ok = (r.get("http") == 200 and body.get("status") == "error"
              and "wait_for timed out after 900ms" in text
              and "condition not met" in text
              and "until=appear" in text and "selector=#never-exists" in text)
        check("wait_for timeout: Chrome-shaped error text", ok, f"error={text!r}")
    except Exception as exc:                                    # noqa: BLE001
        check("wait_for timeout: Chrome-shaped error text", False, repr(exc))

    # ---- 6. wait_for validation failures take NO screenshot -------------
    try:
        r = post("wait_for", {"text": "anything", "until": "gone"})
        body = r.get("body") or {}
        details = body.get("error_details") or {}
        ok = (body.get("status") == "error" and "requires 'args.selector'"
              in str(body.get("error") or "") and "screenshot" not in details)
        check("wait_for until=gone without selector: rejected, no screenshot",
              ok, f"body={json.dumps(body)[:200]}")
    except Exception as exc:                                    # noqa: BLE001
        check("wait_for until=gone without selector: rejected, no screenshot",
              False, repr(exc))

    # ---- 7. failure screenshot on a browser-action failure -------------
    try:
        call("navigate", {"url": page_url})
        r = post("click", {"selector": "#no-such-element-selfheal"})
        body = r.get("body") or {}
        details = body.get("error_details") or {}
        path = details.get("screenshot")
        ok = (body.get("status") == "error" and isinstance(path, str)
              and os.path.isabs(path) and os.path.isfile(path))
        magic = size = None
        if ok:
            with open(path, "rb") as fh:
                raw = fh.read()
            magic, size = raw[:8], len(raw)
            ok = magic == b"\x89PNG\r\n\x1a\n" and size > 1000
        check("failure screenshot: error_details.screenshot is a real PNG >1KB",
              ok, f"path={path} magic={magic!r} size={size} "
                  f"body={json.dumps(body)[:160]}")
    except Exception as exc:                                    # noqa: BLE001
        check("failure screenshot: error_details.screenshot is a real PNG >1KB",
              False, repr(exc))

    # ---- 8. captureOnError:false disables the screenshot ----------------
    try:
        r = post("click", {"selector": "#no-such-element-selfheal",
                           "captureOnError": False})
        body = r.get("body") or {}
        ok = (body.get("status") == "error"
              and "error_details" not in body
              and "screenshot" not in json.dumps(body))
        check("captureOnError:false -> no screenshot, no error_details",
              ok, f"body={json.dumps(body)[:200]}")
    except Exception as exc:                                    # noqa: BLE001
        check("captureOnError:false -> no screenshot, no error_details",
              False, repr(exc))

    # ---- 9. parameter-validation failure takes NO screenshot ------------
    try:
        r = post("click", {})
        body = r.get("body") or {}
        details = body.get("error_details") or {}
        ok = (body.get("status") == "error"
              and "'args.selector'" in str(body.get("error") or "")
              and "screenshot" not in details)
        check("parameter-validation failure -> no screenshot", ok,
              f"body={json.dumps(body)[:200]}")
    except Exception as exc:                                    # noqa: BLE001
        check("parameter-validation failure -> no screenshot", False, repr(exc))

    # ---- 10. legacy request shape unchanged ----------------------------
    try:
        r = post("evaluate", {"code": "1+1"})
        body = r.get("body") or {}
        value = (body.get("data") or {}).get("value")
        ok = (body.get("status") == "ok" and value == 2
              and "retries" not in (body.get("data") or {}))
        check("legacy evaluate: unchanged 200 shape, no retries field",
              ok, f"body={json.dumps(body)[:200]}")
    except Exception as exc:                                    # noqa: BLE001
        check("legacy evaluate: unchanged 200 shape, no retries field",
              False, repr(exc))


def retry_integration_check(launcher):
    """Real transient failure: daemon asked for evaluate while Firefox is
    still down (503 'firefox not connected' = transient), Firefox starts, a
    later retry succeeds and the reply reports retries>=1."""
    r = post("evaluate", {"code": "document.title",
                          "retry": {"attempts": 5, "backoffMs": 3000}})
    body = r.get("body") or {}
    value = (body.get("data") or {}).get("value")
    retries = (body.get("data") or {}).get("retries")
    ok = (body.get("status") == "ok" and isinstance(retries, int)
          and retries >= 1)
    check("retry integration: 503 while Firefox down, retried into success",
          ok, f"http={r.get('http')} value={value!r} retries={retries} "
              f"body={json.dumps(body)[:200]}")


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):                                           # noqa: N802
        if self.path.startswith("/slow"):
            time.sleep(1.2)
            payload = b"slow-ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        return super().do_GET()

    def log_message(self, fmt, *args):                          # noqa: A003
        pass


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="wbf-ff-selfheal-")
    stack = Stack(tmp)
    httpd = None
    try:
        ff_version = subprocess.run(
            [find_firefox(), "--version"], capture_output=True,
            text=True).stdout.strip()
        print(f"[ff-selfheal] temp profile : {stack.profile}")
        print(f"[ff-selfheal] BiDi port    : {BIDI_PORT}  "
              f"daemon HTTP port: {HTTP_PORT}")
        print(f"[ff-selfheal] Firefox      : {ff_version}")
        print()

        with open(os.path.join(tmp, "selfheal_page.html"), "w",
                  encoding="utf-8") as fh:
            fh.write(TEST_PAGE)
        handler = functools.partial(Handler, directory=tmp)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        page_url = f"http://127.0.0.1:{httpd.server_address[1]}/selfheal_page.html"

        # ---- retry unit tests first (no browser needed) ----------------
        unit_retry_checks()
        print()

        # ---- daemon FIRST (Firefox down), then the retry integration ----
        stack.start_daemon()

        def launch_later():
            time.sleep(1.5)
            stack.start_firefox()

        t = threading.Thread(target=launch_later, daemon=True)
        t.start()
        retry_integration_check(t)
        t.join(timeout=45)
        print()

        live_checks(page_url)
        return 0
    finally:
        if httpd is not None:
            httpd.shutdown()
        stack.stop()
        print()
        print(f"[ff-selfheal] cleanup: BiDi {BIDI_PORT} open="
              f"{port_open(BIDI_PORT)}  HTTP {HTTP_PORT} open="
              f"{port_open(HTTP_PORT)}")
        shutil.rmtree(tmp, ignore_errors=True)
        if failures:
            print("[ff-selfheal] FAILED:")
            for f in failures:
                print("  - " + f)
        else:
            print("[ff-selfheal] PASSED: all self-heal steps ok")


if __name__ == "__main__":
    code = main()
    sys.exit(1 if failures else (code or 0))
