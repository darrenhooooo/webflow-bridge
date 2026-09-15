#!/usr/bin/env python3
"""Cross-tab dialog-scope regression for Webflow Bridge (self-contained).

End-to-end guard for the v1.2.2 fix that made native-dialog blocking
tab-scoped: a dialog on tab A must never leak onto tab B. The whole run is
throwaway and isolated from whatever Webflow Bridge is installed on the
machine:

  * the dialog range is the repo's own ``tools/blocking_range.py`` on a free
    loopback port;
  * an isolated daemon imports ``daemon/webflow_bridge.py``, overrides
    ``HTTP_PORT`` / ``WS_PORT`` to free ports and runs ``main()``;
  * a temporary ``--user-data-dir`` Chrome loads a patched COPY of
    ``extension/`` (its port constants rewritten to the isolated daemon) via
    the CDP ``Extensions.loadUnpacked`` command.

Nothing here imports or reads another test harness, an environment-specific
task file or a hard-coded temporary directory, so a clean checkout can run it
directly. The only third-party dependency is ``websocket-client`` (used for the
browser-level Chrome DevTools connection).

Run from anywhere (the repo root is derived from this file's location):

    uv run --with websocket-client --python 3.11 python tools/dialog_scope_regression.py

A copy of this file placed outside a checkout can be pointed at one with the
``WBF_REPO`` environment variable (a clean checkout needs no override).

Exit status is 0 when every check passes and non-zero otherwise, so it can be
wired into CI or used as a one-shot manual regression. Every process, port and
temporary directory the run created is torn down on the way out; the machine's
real daemon is left untouched.
"""
from __future__ import annotations

import itertools
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

try:
    import websocket  # websocket-client: browser-level Chrome DevTools socket
except ImportError:  # pragma: no cover - dependency guard
    sys.stderr.write(
        "websocket-client is required for the Chrome DevTools connection.\n"
        "Run this file with:\n"
        "  uv run --with websocket-client --python 3.11 python "
        "tools/dialog_scope_regression.py\n"
    )
    sys.exit(2)

# --- locations (derived from this file, never hard-coded) ------------------
# WBF_REPO lets a copy of this file run against a checkout from elsewhere;
# a clean checkout needs no override.
REPO = (os.environ.get("WBF_REPO")
        or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXT_SRC = os.path.join(REPO, "extension")
RANGE_SCRIPT = os.path.join(REPO, "tools", "blocking_range.py")
DAEMON_DIR = os.path.join(REPO, "daemon")

TOKEN = "test-token-dialog-scope"
HEADLESS = os.environ.get("WB_HEADLESS", "1") == "1"

# Isolated ports, allocated at runtime so they can never collide with the
# user's daemon (:10086/:10087) or a parallel run.
HTTP_PORT = 0
WS_PORT = 0
RANGE_PORT = 0
DEBUG_PORT = 0

RESULTS: "list[tuple[str, bool | None, str]]" = []
PROCS: "list[subprocess.Popen]" = []
TEMP_DIRS: "list[str]" = []
RUN_TMP = ""


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------
def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}", flush=True)


def info(name: str, detail: str) -> None:
    RESULTS.append((name, None, detail))
    print(f"[INFO] {name}: {detail}", flush=True)


# ---------------------------------------------------------------------------
# isolated HTTP / CDP plumbing
# ---------------------------------------------------------------------------
def cmd(action: str, args=None, timeout: int = 60, session: str = "default"):
    body = json.dumps({"action": action, "args": args or {},
                       "session": session}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/command", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {TOKEN}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        data = json.loads(e.read().decode())
        data["_http"] = e.code
    data["_elapsed"] = time.time() - t0
    return data


def status():
    req = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/status",
        headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())


def http_json(url: str, timeout: int = 5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


class BrowserCdp:
    """Minimal browser-level CDP client (one request/response at a time)."""

    def __init__(self, ws_url: str) -> None:
        self.ws = websocket.create_connection(ws_url, timeout=20,
                                              suppress_origin=True)
        self.ids = itertools.count(1)

    def call(self, method: str, params=None):
        rid = next(self.ids)
        self.ws.send(json.dumps({"id": rid, "method": method,
                                 "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == rid:
                return msg

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# environment setup
# ---------------------------------------------------------------------------
def _free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def allocate_ports() -> None:
    global HTTP_PORT, WS_PORT, RANGE_PORT, DEBUG_PORT
    seen: set = set()
    while len(seen) < 4:
        seen.add(_free_port())
    HTTP_PORT, WS_PORT, RANGE_PORT, DEBUG_PORT = sorted(seen)


def find_chrome():
    candidates = []
    for var in ("CHROME_PATH", "WB_CHROME"):
        if os.environ.get(var):
            candidates.append(os.environ[var])
    candidates += [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for name in ("google-chrome", "google-chrome-stable", "chrome",
                 "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for cand in candidates:
        if cand and os.path.exists(cand):
            return cand
    return None


def build_patched_extension() -> str:
    dst = tempfile.mkdtemp(prefix="wbf_scope_ext_")
    TEMP_DIRS.append(dst)
    shutil.copytree(EXT_SRC, dst, dirs_exist_ok=True)
    path = os.path.join(dst, "background.js")
    with open(path, "r", encoding="utf-8", newline="") as f:
        txt = f.read()
    old_ws = "ws://127.0.0.1:10087"
    old_http = "http://127.0.0.1:10086"
    txt = txt.replace(old_ws, f"ws://127.0.0.1:{WS_PORT}")
    txt = txt.replace(old_http, f"http://127.0.0.1:{HTTP_PORT}")
    # Safety net: if those constants ever move, a silently unpatched copy would
    # point the test extension at the user's real daemon. Refuse to run.
    if old_ws in txt or old_http in txt or f"127.0.0.1:{HTTP_PORT}" not in txt:
        raise RuntimeError(
            "could not rewrite the extension port constants in background.js; "
            "aborting so a test build can never reach the real daemon")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(txt)
    return dst


def start_range():
    proc = subprocess.Popen(
        [sys.executable, RANGE_SCRIPT, "--port", str(RANGE_PORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    PROCS.append(proc)
    for _ in range(60):
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{RANGE_PORT}/plain", timeout=1).read()
            return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    raise RuntimeError("blocking_range.py did not start")


def start_daemon():
    code = (
        "import sys; sys.path.insert(0, %r); "
        "import webflow_bridge as wb; "
        "wb.HTTP_PORT = %d; wb.WS_PORT = %d; "
        "sys.argv = ['webflow_bridge']; wb.main()"
        % (DAEMON_DIR, HTTP_PORT, WS_PORT)
    )
    env = dict(os.environ,
               WBF_TOKEN=TOKEN,
               WBF_TOKEN_FILE=os.path.join(RUN_TMP, "token"),
               WBF_STALE_AFTER="20")
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=REPO, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    PROCS.append(proc)
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError("isolated daemon exited during startup")
        try:
            status()
            return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    raise RuntimeError("isolated daemon did not start")


def start_chrome(chrome_path: str, ext_dir: str):
    profile = tempfile.mkdtemp(prefix="wbf_scope_prof_")
    TEMP_DIRS.append(profile)
    args = [chrome_path, f"--remote-debugging-port={DEBUG_PORT}",
            f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check",
            "--enable-unsafe-extension-debugging",
            "--disable-features=Translate,AcceptCHFrame",
            "--window-size=900,700", "--window-position=0,0", "about:blank"]
    if HEADLESS:
        args.insert(1, "--headless=new")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    PROCS.append(proc)
    version = None
    for _ in range(100):
        try:
            version = http_json(f"http://127.0.0.1:{DEBUG_PORT}/json/version")
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    if version is None:
        raise RuntimeError("Chrome did not expose the DevTools endpoint")
    cdp = BrowserCdp(version["webSocketDebuggerUrl"])
    loaded = cdp.call("Extensions.loadUnpacked", {"path": ext_dir})
    if "error" in loaded:
        raise RuntimeError(f"Extensions.loadUnpacked failed: {loaded}")
    info("extension loaded", f"id={loaded['result']['id']}")
    return cdp


def wait_connected(timeout: int = 30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            data = status().get("data", {})
            if data.get("extension_connected"):
                return time.time() - t0
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.25)
    return None


# ---------------------------------------------------------------------------
# scenario helpers
# ---------------------------------------------------------------------------
def active_tab():
    tabs = cmd("tabs_list")["data"]["value"]
    return [t for t in tabs if t.get("active")][0]


def tab_by_url(fragment: str):
    for tab in cmd("tabs_list")["data"]["value"]:
        if fragment in (tab.get("url") or ""):
            return tab
    return None


def snapshot(label: str):
    """Run the tab-B action battery, returning everything compared later."""
    out = {}
    probe = cmd("probe", {}, timeout=60)
    value = (probe.get("data") or {}).get("value", {}) or {}
    paths = value.get("paths", {})
    out["probe_status"] = probe.get("status")
    out["probe_elapsed"] = probe["_elapsed"]
    out["probe_paths_n"] = len(paths)
    out["probe_allok"] = bool(paths) and all(v.get("ok") for v in paths.values())
    out["probe_skipped"] = sorted(
        k for k, v in paths.items()
        if str(v.get("error", "")).startswith("skipped:"))
    out["probe_bad"] = {k: (v.get("error") or "")[:70] for k, v in paths.items()
                        if not v.get("ok")}
    out["probe_dialog"] = value.get("dialog", {})
    ev = cmd("evaluate", {"code": "location.pathname"})
    out["eval_status"] = ev.get("status")
    out["eval_value"] = (ev.get("data") or {}).get("value")
    out["eval_error"] = (ev.get("error") or "")[:160]
    out["eval_elapsed"] = ev["_elapsed"]
    ck = cmd("click", {"selector": "h1"}, timeout=40)
    out["click_status"] = ck.get("status")
    out["click_error"] = (ck.get("error") or "")[:160]
    out["click_elapsed"] = ck["_elapsed"]
    sh = cmd("screenshot", {}, timeout=60)
    out["shot_status"] = sh.get("status")
    out["shot_error"] = (sh.get("error") or "")[:160]
    out["shot_elapsed"] = sh["_elapsed"]
    printable = {k: v for k, v in out.items() if k != "probe_dialog"}
    info("snapshot " + label, json.dumps(printable, ensure_ascii=False))
    print("        probe.dialog =",
          json.dumps(out["probe_dialog"], ensure_ascii=False), flush=True)
    return out


def compare(base: dict, with_dialog: dict):
    keys = ["probe_status", "probe_paths_n", "probe_allok", "probe_skipped",
            "probe_bad", "eval_status", "eval_value", "click_status",
            "shot_status"]
    diffs = []
    for key in keys:
        if base.get(key) != with_dialog.get(key):
            diffs.append("%s: base=%r withA=%r"
                         % (key, base.get(key), with_dialog.get(key)))
    return diffs


# ---------------------------------------------------------------------------
# teardown
# ---------------------------------------------------------------------------
def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            proc.terminate()
    except Exception:  # noqa: BLE001
        pass


def cleanup() -> None:
    try:
        for proc in reversed(PROCS):
            _kill_tree(proc)
        time.sleep(0.8)
        for proc in reversed(PROCS):
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
    finally:
        for path in TEMP_DIRS:
            shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def run() -> bool:
    global RUN_TMP
    RUN_TMP = tempfile.mkdtemp(prefix="wbf_scope_run_")
    TEMP_DIRS.append(RUN_TMP)
    allocate_ports()
    info("isolated ports",
         f"daemon HTTP={HTTP_PORT} WS={WS_PORT} range={RANGE_PORT} "
         f"CDP={DEBUG_PORT}")
    chrome_path = find_chrome()
    if chrome_path is None:
        print("Chrome/Chromium not found; set CHROME_PATH to its binary.",
              flush=True)
        return False

    cdp = None
    try:
        ext_dir = build_patched_extension()
        start_range()
        start_daemon()
        cdp = start_chrome(chrome_path, ext_dir)
        connected = wait_connected()
        check("S0 extension connects to the isolated daemon",
              connected is not None,
              f"{connected:.1f}s" if connected else "never connected")
        if connected is None:
            return False

        range_url = f"http://127.0.0.1:{RANGE_PORT}"

        # --- open A (/dialogs) and B (/plain); B ends active ---------------
        cmd("tabs_open", {"url": range_url + "/dialogs"})
        time.sleep(0.6)
        cmd("tabs_open", {"url": range_url + "/plain"})
        time.sleep(0.8)
        tab_a = tab_by_url("/dialogs")
        tab_b = tab_by_url("/plain")
        check("S1 tabs A(/dialogs) + B(/plain) open, B active",
              bool(tab_a and tab_b and tab_a["id"] != tab_b["id"] and tab_b["active"]),
              f"A={tab_a and tab_a['id']} B={tab_b and tab_b['id']} "
              f"active={(active_tab() or {}).get('id')}")
        if not (tab_a and tab_b):
            return False
        aid, bid = tab_a["id"], tab_b["id"]

        # --- baseline on B with no dialog anywhere -------------------------
        baseline = snapshot("BASELINE-B (no dialog)")

        # --- open a manual dialog on A -------------------------------------
        r = cmd("set_dialog_policy", {"policy": "manual"})
        check("S2 set_dialog_policy manual", r.get("status") == "ok",
              json.dumps(r.get("data"))[:80])
        cmd("tabs_activate", {"tabId": aid})
        time.sleep(0.5)
        cmd("navigate", {"url": range_url + "/dialogs"})
        time.sleep(0.5)
        cmd("click", {"selector": "#al"})
        time.sleep(0.9)

        a_ev = cmd("evaluate", {"code": "1 + 1"})
        check("S3 tab A blocked: evaluate fast-fails with a dialog hint",
              a_ev.get("status") == "error"
              and "dialog" in str(a_ev.get("error", "")).lower()
              and a_ev["_elapsed"] < 3,
              f"{a_ev['_elapsed']:.3f}s err={(a_ev.get('error') or '')[:90]}")
        a_probe = cmd("probe", {}, timeout=30)
        a_value = (a_probe.get("data") or {}).get("value", {}) or {}
        a_paths = a_value.get("paths", {})
        a_skipped = [k for k, v in a_paths.items()
                     if str(v.get("error", "")).startswith("skipped:")]
        check("S4 tab A probe fast-returns with its paths skipped",
              a_probe.get("status") == "ok" and a_probe["_elapsed"] < 3
              and len(a_skipped) == 4,
              f"{a_probe['_elapsed']:.3f}s skipped={len(a_skipped)} "
              f"blocking={(a_value.get('dialog') or {}).get('blocking')}")

        # --- assertion 1: B is unaffected while A is blocked ---------------
        cmd("tabs_activate", {"tabId": bid})
        time.sleep(0.6)
        check("S5 back on tab B", (active_tab() or {}).get("id") == bid,
              f"active={(active_tab() or {}).get('id')}")
        with_dialog = snapshot("WITH-A-DIALOG-B")
        diffs = compare(baseline, with_dialog)
        check("P1 (assert 1) B evaluate/probe/click/screenshot identical "
              "with/without A's dialog",
              not diffs, "diffs=" + json.dumps(diffs, ensure_ascii=False)[:400])

        # --- assertion 2: B's probe does not claim A's dialog --------------
        b_dialog = with_dialog["probe_dialog"]
        pending = b_dialog.get("pending") or {}
        check("P2 (assert 2) B probe.dialog: blocking=false, pending.tabId=A",
              b_dialog.get("blocking") is False
              and pending.get("tabId") == aid,
              json.dumps(b_dialog, ensure_ascii=False)[:240])

        # --- assertion 4: resolve A's dialog while B stays active ----------
        hd_cross = cmd("handle_dialog",
                       {"accept": True, "timeoutMs": 5000, "tabId": aid},
                       timeout=30)
        check("S6a (assert 4) handle_dialog(tabId=A) resolves A while B is active",
              hd_cross.get("status") == "ok"
              and ((hd_cross.get("data", {}).get("value", {}) or {}).get("success")),
              json.dumps(hd_cross.get("data"))[:160]
              + " err=" + str(hd_cross.get("error"))[:80])
        b_ev = cmd("evaluate", {"code": "location.pathname"})
        check("S6b B still works after resolving A's dialog",
              b_ev.get("status") == "ok"
              and b_ev.get("data", {}).get("value") == "/plain",
              f"{b_ev['_elapsed']:.3f}s")

        # --- assertion 3: a fresh dialog on A, B detour, then back to A ----
        cmd("tabs_activate", {"tabId": aid})
        time.sleep(0.4)
        cmd("navigate", {"url": range_url + "/dialogs"})
        time.sleep(0.4)
        cmd("click", {"selector": "#al"})
        time.sleep(0.9)
        cmd("tabs_activate", {"tabId": bid})
        time.sleep(0.5)
        cmd("tabs_activate", {"tabId": aid})
        time.sleep(0.6)
        a_ev2 = cmd("evaluate", {"code": "1 + 1"})
        check("S7 (assert 3) back on A via the B detour: evaluate still "
              "fast-fails with a dialog hint",
              a_ev2.get("status") == "error"
              and "dialog" in str(a_ev2.get("error", "")).lower()
              and a_ev2["_elapsed"] < 3,
              f"{a_ev2['_elapsed']:.3f}s err={(a_ev2.get('error') or '')[:90]}")

        # --- assertion 5: resolve and recover, A and B ---------------------
        hd = cmd("handle_dialog", {"accept": True, "timeoutMs": 5000}, timeout=30)
        check("S8 (assert 5) A's dialog resolves after the detour",
              hd.get("status") == "ok"
              and ((hd.get("data", {}).get("value", {}) or {}).get("success")),
              json.dumps(hd.get("data"))[:180]
              + " err=" + str(hd.get("error"))[:80])
        a_ev3 = cmd("evaluate", {"code": "1 + 1"})
        check("S9 (assert 5) A recovers after handle_dialog",
              a_ev3.get("status") == "ok"
              and a_ev3.get("data", {}).get("value") == 2,
              f"{a_ev3['_elapsed']:.3f}s value="
              f"{a_ev3.get('data', {}).get('value')}")
        cmd("tabs_activate", {"tabId": bid})
        time.sleep(0.4)
        b_ev2 = cmd("evaluate", {"code": "location.pathname"})
        check("S10 (assert 5) B recovers too",
              b_ev2.get("status") == "ok"
              and b_ev2.get("data", {}).get("value") == "/plain",
              f"{b_ev2['_elapsed']:.3f}s")

        # --- assertion 6: auto-accept regression for all four kinds --------
        cmd("set_dialog_policy", {"policy": "auto-accept"})
        cmd("tabs_activate", {"tabId": bid})
        for kind, selector in (("alert", "#al"), ("confirm", "#cf"),
                               ("prompt", "#pr")):
            cmd("navigate", {"url": range_url + "/dialogs"})
            time.sleep(0.4)
            cmd("click", {"selector": selector})
            time.sleep(0.5)
            res = cmd("evaluate", {"code": "1 + 1"})
            check(f"S11 (assert 6) auto-accept {kind}: evaluate fast",
                  res.get("status") == "ok"
                  and res.get("data", {}).get("value") == 2
                  and res["_elapsed"] < 2.5,
                  f"{res['_elapsed']:.3f}s value="
                  f"{res.get('data', {}).get('value')}")
        cmd("navigate", {"url": range_url + "/beforeunload"})
        time.sleep(0.4)
        cmd("navigate", {"url": range_url + "/plain"}, timeout=40)
        time.sleep(0.3)
        res = cmd("evaluate", {"code": "location.pathname"})
        check("S12 (assert 6) auto-accept beforeunload: evaluate fast",
              res.get("status") == "ok"
              and res.get("data", {}).get("value") == "/plain"
              and res["_elapsed"] < 2.5,
              f"{res['_elapsed']:.3f}s value="
              f"{res.get('data', {}).get('value')}")

        # --- normal-page regression (no dialog) ----------------------------
        cmd("navigate", {"url": range_url + "/big"})
        time.sleep(0.5)
        res = cmd("evaluate", {"code": "document.title"})
        check("S13 normal navigate + evaluate", res.get("status") == "ok"
              and res.get("data", {}).get("value") == "big",
              f"{res['_elapsed']:.3f}s")
        res = cmd("screenshot", {}, timeout=60)
        check("S14 normal screenshot", res.get("status") == "ok",
              f"{res['_elapsed']:.3f}s")
        res = cmd("save_as_pdf", {}, timeout=90)
        check("S15 normal save_as_pdf", res.get("status") == "ok",
              f"{res['_elapsed']:.3f}s")
        probe = cmd("probe", {}, timeout=60)
        paths = (probe.get("data") or {}).get("value", {}).get("paths", {})
        check("S16 probe with no dialog: every path ok",
              bool(paths) and all(v.get("ok") for v in paths.values()),
              f"allok={all(v.get('ok') for v in paths.values())} n={len(paths)}")
    finally:
        if cdp is not None:
            cdp.close()

    graded = [ok for _, ok, _ in RESULTS if ok is not None]
    return bool(graded) and all(graded)


if __name__ == "__main__":
    ok = False
    try:
        ok = run()
    except Exception as exc:  # noqa: BLE001
        print(f"EXC: {type(exc).__name__}: {exc}", flush=True)
        ok = False
    finally:
        cleanup()
        print("\n==== SUMMARY ====")
        for name, passed, _ in RESULTS:
            print(f"{'INFO' if passed is None else ('PASS' if passed else 'FAIL')}  {name}")
        graded = [p for _, p, _ in RESULTS if p is not None]
        print(f"TOTAL {sum(1 for p in graded if p)}/{len(graded)}")
    sys.exit(0 if ok else 1)
