#!/usr/bin/env python3
"""Webflow Bridge for Firefox -- P3 actions smoke (ISOLATED stack).

Proves, end to end and without touching Darren's Firefox, the five actions
that were still missing on the Firefox backend:

  1. fill_form  -- input/textarea/select in one pass; a bad selector is
     reported per field ({selector,error}) without aborting the others;
  2. submit     -- requestSubmit really changes the page state (read back
     the DOM), and a missing selector is an explicit error;
  3. drop       -- a real local file lands on the drop-zone (DataTransfer +
     DragEvent inside script.evaluate); bad selector / unreadable path are
     explicit errors, never a timeout or a 500;
  4. list_downloads -- after a real attachment download the record is listed
     (Chrome shape {downloads,count}); the list is CURRENT-SESSION only;
  5. resize_page -- setViewport really changes innerWidth, clear:true
     restores it, bad dimensions are rejected.

Isolation (hard requirement): a throwaway profile under a temp dir, BiDi on
:9122 and the daemon on :10097 (never 9222/10086/10087/2008x/8901), the
daemon forced non-interactive with --allow-no-auth. Every process started
here is killed before exit and both ports are re-checked free.

Usage:  python3 ff/daemon/ff_actions_smoke.py
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

BIDI_PORT = 9122
HTTP_PORT = 10097
BASE = f"http://127.0.0.1:{HTTP_PORT}"
FF_CANDIDATES = [
    "/Applications/Firefox.app/Contents/MacOS/firefox",
    shutil.which("firefox") or "",
]

TEST_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>ff-actions-page</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 2em; }
  #dropzone { border: 2px dashed #999; padding: 2em; min-height: 3em;
              margin: 1em 0; }
</style></head>
<body>
<h1>ff actions test page</h1>
<form id="f1">
  <input id="name" type="text" size="30">
  <input id="email" type="email" size="30">
  <select id="role">
    <option value="alpha">Alpha</option>
    <option value="beta">Beta</option>
  </select>
  <textarea id="bio" rows="3" cols="30"></textarea>
  <button id="go" type="submit">go</button>
</form>
<div id="submitlog">(no submit)</div>

<div id="dropzone">drop here</div>
<div id="droplog">(no drop)</div>

<a id="dl" href="/dl">download</a>
<script>
(function () {
  document.getElementById('f1').addEventListener('submit', function (e) {
    e.preventDefault();
    document.getElementById('submitlog').textContent =
      'submitted:' + document.getElementById('name').value;
  });
  var z = document.getElementById('dropzone');
  ['dragenter', 'dragover', 'drop', 'dragleave'].forEach(function (t) {
    z.addEventListener(t, function (e) { e.preventDefault(); });
  });
  z.addEventListener('drop', function (e) {
    var fs = (e.dataTransfer && e.dataTransfer.files) || [];
    var names = [];
    for (var i = 0; i < fs.length; i += 1) {
      names.push(fs[i].name + ':' + fs[i].size);
    }
    document.getElementById('droplog').textContent = 'dropped:' + names.join(',');
  });
})();
</script>
</body></html>
"""

failures = []
record = {"n": 0}


def step(n, name, ok, note=""):
    print(f"STEP {n}  {name}")
    print(f"  -> {'PASS' if ok else 'FAIL'}" + (f"  {note}" if note else ""))
    if not ok:
        failures.append(f"{name}: {note}")
    return ok


def check(name, ok, note=""):
    record["n"] += 1
    return step(record["n"], name, ok, note)


def find_firefox() -> str:
    for c in FF_CANDIDATES:
        if c and os.path.isfile(c):
            return c
    raise SystemExit("[ff-actions] FATAL: Firefox binary not found")


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


def ev_obj(code: str):
    """evaluate a JSON.stringify(...) expression into a python object."""
    raw = call("evaluate", {"code": "JSON.stringify(" + code + ")"})
    if not isinstance(raw, str):
        raise AssertionError(f"evaluate did not return a string: {raw!r}")
    return json.loads(raw)


class Stack:
    """Throwaway Firefox + ff daemon, both on private ports."""

    def __init__(self, tmp):
        self.tmp = tmp
        self.profile = os.path.join(tmp, "profile")
        self.downloads = os.path.join(tmp, "downloads")
        self.daemon = None
        self.firefox = None
        self._logs = []

    def _log(self, name):
        fh = open(os.path.join(self.tmp, name), "wb")
        self._logs.append(fh)
        return fh

    def start_daemon(self):
        env = dict(os.environ)
        env.pop("WBF_FF_BIDI_URL", None)
        self.daemon = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "ff_bridge.py"),
             "--ff-port", str(BIDI_PORT), "--http-port", str(HTTP_PORT),
             "--allow-no-auth", "--no-auto-dialog"],
            cwd=REPO, env=env, stdout=self._log("daemon.log"),
            stderr=subprocess.STDOUT)
        if not wait_port(HTTP_PORT, 15):
            raise SystemExit("[ff-actions] FATAL: daemon HTTP never came up")

    def start_firefox(self):
        os.makedirs(self.profile, exist_ok=True)
        os.makedirs(self.downloads, exist_ok=True)
        with open(os.path.join(self.profile, "user.js"), "w",
                  encoding="utf-8") as fh:
            fh.write(
                'user_pref("browser.download.folderList", 2);\n'
                f'user_pref("browser.download.dir", '
                f'{json.dumps(self.downloads)});\n'
                'user_pref("browser.download.useDownloadDir", true);\n'
                'user_pref("browser.download.alwaysOpenPanel", false);\n'
                'user_pref("browser.helperApps.neverAsk.saveToDisk", '
                '"text/plain,application/octet-stream");\n'
                'user_pref("browser.shell.checkDefaultBrowser", false);\n')
        self.firefox = subprocess.Popen(
            [find_firefox(), "-no-remote", "-profile", self.profile,
             "--remote-debugging-port", str(BIDI_PORT),
             "-remote-allow-system-access", "-headless"],
            stdout=self._log("firefox.log"), stderr=subprocess.STDOUT)
        if not wait_port(BIDI_PORT, 40):
            raise SystemExit("[ff-actions] FATAL: Firefox BiDi never came up")

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
        subprocess.run(["pkill", "-f", self.profile],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for fh in self._logs:
            try:
                fh.close()
            except OSError:
                pass


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):                                           # noqa: N802
        if self.path.startswith("/dl"):
            payload = b"ff-actions-download-body"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header(
                "Content-Disposition",
                'attachment; filename="ff-actions-dl.txt"')
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        return super().do_GET()

    def log_message(self, fmt, *args):                          # noqa: A003
        pass


def live_checks(page_url, drop_file):
    # ---- 1. fill_form: input + select + textarea in one pass -----------
    try:
        fields = [
            {"selector": "#name", "value": "Ada"},
            {"selector": "#role", "value": "beta"},
            {"selector": "#bio", "value": "hello ff"},
        ]
        v = call("fill_form", {"fields": fields})
        got = ev_obj("({n:document.getElementById('name').value,"
                     "r:document.getElementById('role').value,"
                     "b:document.getElementById('bio').value})")
        want = {"n": "Ada", "r": "beta", "b": "hello ff"}
        ok = (isinstance(v, dict) and v.get("success") is True
              and len(v.get("filled") or []) == 3
              and not v.get("errors") and got == want)
        check("fill_form: input/select/textarea filled in one pass",
              ok, f"value={json.dumps(v, ensure_ascii=False)} got={got}")
    except Exception as exc:                                    # noqa: BLE001
        check("fill_form: input/select/textarea filled in one pass", False,
              repr(exc))

    # ---- 2. fill_form: a bad selector is named, good fields still fill --
    try:
        v = call("fill_form", {"fields": [
            {"selector": "#name", "value": "Grace"},
            {"selector": "#no-such-field", "value": "x"},
        ]})
        errs = v.get("errors") or []
        hit = [e for e in errs if e.get("selector") == "#no-such-field"]
        name = ev_obj("({n:document.getElementById('name').value})")
        ok = (isinstance(v, dict) and v.get("success") is True
              and v.get("filled") == ["#name"] and len(errs) == 1
              and hit and "element not found" in str(hit[0].get("error"))
              and name == {"n": "Grace"})
        check("fill_form: missing selector named in errors, others filled",
              ok, f"value={json.dumps(v, ensure_ascii=False)}")
    except Exception as exc:                                    # noqa: BLE001
        check("fill_form: missing selector named in errors, others filled",
              False, repr(exc))

    # ---- 3. submit: requestSubmit really changes the page state ---------
    try:
        v = call("submit", {"selector": "#f1"})
        time.sleep(0.3)
        log = call("evaluate",
                   {"code": "document.getElementById('submitlog').textContent"})
        ok = (isinstance(v, dict) and v.get("success") is True
              and v.get("tag") == "form" and v.get("mode") == "requestSubmit"
              and log == "submitted:Grace")
        check("submit: requestSubmit fires the handler (DOM read back)",
              ok, f"value={json.dumps(v)} submitlog={log!r}")
    except Exception as exc:                                    # noqa: BLE001
        check("submit: requestSubmit fires the handler (DOM read back)", False,
              repr(exc))

    # ---- 4. submit: missing selector -> explicit error ------------------
    try:
        r = post("submit", {"selector": "#no-such-form"})
        body = r.get("body") or {}
        err = str(body.get("error") or "")
        ok = (r.get("http") == 200 and body.get("status") == "error"
              and "element not found" in err
              and "#no-such-form" in err)
        check("submit: missing selector -> explicit 'element not found'",
              ok, f"error={err!r}")
    except Exception as exc:                                    # noqa: BLE001
        check("submit: missing selector -> explicit 'element not found'",
              False, repr(exc))

    # ---- 5. drop: a real local file lands on the drop-zone --------------
    try:
        v = call("drop", {"selector": "#dropzone", "file": drop_file})
        time.sleep(0.3)
        log = call("evaluate",
                   {"code": "document.getElementById('droplog').textContent"})
        want = "dropped:" + os.path.basename(drop_file) + ":16"
        ok = (isinstance(v, dict) and v.get("success") is True
              and v.get("dropped") == 1 and log == want)
        check("drop: DataTransfer file received by the drop-zone",
              ok, f"value={json.dumps(v)} droplog={log!r} want={want!r}")
    except Exception as exc:                                    # noqa: BLE001
        check("drop: DataTransfer file received by the drop-zone", False,
              repr(exc))

    # ---- 6. drop: bad selector -> explicit error (not timeout/500) ------
    try:
        r = post("drop", {"selector": "#no-such-zone", "file": drop_file})
        body = r.get("body") or {}
        err = str(body.get("error") or "")
        ok = (r.get("http") == 200 and body.get("status") == "error"
              and "element not found" in err and "#no-such-zone" in err)
        check("drop: bad selector -> explicit 'element not found'",
              ok, f"error={err!r}")
    except Exception as exc:                                    # noqa: BLE001
        check("drop: bad selector -> explicit 'element not found'",
              False, repr(exc))

    # ---- 7. drop: unreadable local path -> explicit error ---------------
    try:
        r = post("drop", {"selector": "#dropzone",
                          "file": os.path.join(os.path.dirname(drop_file),
                                               "does-not-exist.bin")})
        body = r.get("body") or {}
        err = str(body.get("error") or "")
        ok = (r.get("http") == 200 and body.get("status") == "error"
              and "cannot read drop file" in err)
        check("drop: unreadable path -> explicit 'cannot read drop file'",
              ok, f"error={err!r}")
    except Exception as exc:                                    # noqa: BLE001
        check("drop: unreadable path -> explicit 'cannot read drop file'",
              False, repr(exc))

    # ---- 8. list_downloads: trigger a real download, then list it -------
    try:
        before = call("list_downloads", {})
        call("click", {"selector": "#dl"})
        hit = None
        deadline = time.time() + 8
        while time.time() < deadline and hit is None:
            v = call("list_downloads", {})
            for d in v.get("downloads") or []:
                if d.get("suggestedFilename") == "ff-actions-dl.txt":
                    hit = d
            time.sleep(0.3)
        saved = os.path.join(os.path.dirname(drop_file),
                             "downloads", "ff-actions-dl.txt")
        ok = (isinstance(before.get("count"), int)
              and before["count"] == 0
              and hit is not None and hit.get("state") == "completed"
              and hit.get("url", "").endswith("/dl")
              and isinstance(hit.get("guid"), str) and hit["guid"]
              and os.path.isfile(saved))
        check("list_downloads: real attachment listed (session-scoped)",
              ok, f"before={before.get('count')} "
                  f"hit={json.dumps(hit, ensure_ascii=False)} saved={saved}")
    except Exception as exc:                                    # noqa: BLE001
        check("list_downloads: real attachment listed (session-scoped)",
              False, repr(exc))

    # ---- 9. list_downloads: limit validation ----------------------------
    try:
        r = post("list_downloads", {"limit": 0})
        body = r.get("body") or {}
        err = str(body.get("error") or "")
        ok = (body.get("status") == "error"
              and "'args.limit' must be a positive integer" in err)
        check("list_downloads: limit=0 rejected", ok, f"error={err!r}")
    except Exception as exc:                                    # noqa: BLE001
        check("list_downloads: limit=0 rejected", False, repr(exc))

    # ---- 10. resize_page: innerWidth really changes ---------------------
    try:
        before = call("evaluate", {"code": "window.innerWidth"})
        v = call("resize_page", {"width": 900, "height": 700})
        time.sleep(0.4)
        after = call("evaluate", {"code": "window.innerWidth"})
        ok = (isinstance(v, dict) and v.get("success") is True
              and v.get("width") == 900 and v.get("height") == 700
              and after == 900 and before != 900)
        check("resize_page: innerWidth becomes 900", ok,
              f"value={json.dumps(v)} innerWidth {before} -> {after}")
    except Exception as exc:                                    # noqa: BLE001
        check("resize_page: innerWidth becomes 900", False, repr(exc))

    # ---- 11. resize_page clear:true restores the viewport ---------------
    try:
        v = call("resize_page", {"clear": True})
        time.sleep(0.4)
        restored = call("evaluate", {"code": "window.innerWidth"})
        ok = (isinstance(v, dict) and v.get("success") is True
              and v.get("cleared") is True and restored != 900)
        check("resize_page: clear:true restores the viewport", ok,
              f"value={json.dumps(v)} innerWidth={restored}")
    except Exception as exc:                                    # noqa: BLE001
        check("resize_page: clear:true restores the viewport", False, repr(exc))

    # ---- 12. resize_page: missing dimensions rejected -------------------
    try:
        r = post("resize_page", {})
        body = r.get("body") or {}
        err = str(body.get("error") or "")
        ok = (body.get("status") == "error"
              and "'args.width'/'args.height' (positive integers) are required"
              in err)
        check("resize_page: missing width/height rejected", ok,
              f"error={err!r}")
    except Exception as exc:                                    # noqa: BLE001
        check("resize_page: missing width/height rejected", False, repr(exc))


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="wbf-ff-actions-")
    stack = Stack(tmp)
    httpd = None
    try:
        ff_version = subprocess.run(
            [find_firefox(), "--version"], capture_output=True,
            text=True).stdout.strip()
        print(f"[ff-actions] temp profile : {stack.profile}")
        print(f"[ff-actions] BiDi port    : {BIDI_PORT}  "
              f"daemon HTTP port: {HTTP_PORT}")
        print(f"[ff-actions] Firefox      : {ff_version}")
        print()

        with open(os.path.join(tmp, "actions_page.html"), "w",
                  encoding="utf-8") as fh:
            fh.write(TEST_PAGE)
        drop_file = os.path.join(tmp, "drop_me.txt")
        with open(drop_file, "wb") as fh:
            fh.write(b"0123456789abcdef")           # exactly 16 bytes
        handler = functools.partial(Handler, directory=tmp)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        page_url = f"http://127.0.0.1:{httpd.server_address[1]}/actions_page.html"

        stack.start_daemon()
        stack.start_firefox()
        time.sleep(1.0)
        call("navigate", {"url": page_url})
        time.sleep(0.5)

        live_checks(page_url, drop_file)
        return 0
    finally:
        if httpd is not None:
            httpd.shutdown()
        stack.stop()
        print()
        print(f"[ff-actions] cleanup: BiDi {BIDI_PORT} open="
              f"{port_open(BIDI_PORT)}  HTTP {HTTP_PORT} open="
              f"{port_open(HTTP_PORT)}")
        shutil.rmtree(tmp, ignore_errors=True)
        if failures:
            print("[ff-actions] FAILED:")
            for f in failures:
                print("  - " + f)
        else:
            print("[ff-actions] PASSED: all action steps ok")


if __name__ == "__main__":
    code = main()
    sys.exit(1 if failures else (code or 0))
