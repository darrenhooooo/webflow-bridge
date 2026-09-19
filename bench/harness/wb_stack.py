"""Side A plumbing: an isolated Webflow Bridge stack.

Starts, all throwaway and isolated from whatever the machine already runs:

  * a daemon that imports the real ``daemon/webflow_bridge.py`` on ports
    20086/20087 with our own WBF_TOKEN_FILE under /tmp (the user's
    ``~/.webflow_bridge/token`` is never read or written);
  * a temp-dir COPY of ``extension/`` whose port constants are rewritten to
    that daemon (the repo is never modified);
  * a Chrome with a /tmp --user-data-dir + --remote-debugging-port=20088 and
    ``--enable-unsafe-extension-debugging``, into which the patched copy is
    loaded through the browser-level CDP ``Extensions.loadUnpacked``.

Read-only driver: it uses the repo's public POST /command surface only.
"""
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (WB_CDP_PORT, WB_DAEMON_DIR, WB_EXT_DIR, WB_HTTP,
                    WB_HTTP_PORT, WB_TOKEN, WB_WS_PORT, url)

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _chrome():
    for cand in (os.environ.get("WB_CHROME"), CHROME_PATH):
        if cand and os.path.exists(cand):
            return cand
    found = shutil.which("chromium") or shutil.which("google-chrome")
    if found:
        return found
    raise RuntimeError("no Chrome/Chromium binary found")


def _http_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


class BrowserCdp:
    """Minimal browser-level CDP client (one request/response at a time)."""

    def __init__(self, ws_url):
        import websocket                      # websocket-client
        self.ws = websocket.create_connection(ws_url, timeout=20,
                                              suppress_origin=True)
        self.ids = itertools.count(1)

    def call(self, method, params=None):
        rid = next(self.ids)
        self.ws.send(json.dumps({"id": rid, "method": method,
                                 "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == rid:
                return msg

    def close(self):
        try:
            self.ws.close()
        except Exception:                     # noqa: BLE001
            pass


class WbStack:
    def __init__(self, work_tmp):
        self.work_tmp = work_tmp
        self.procs = []
        self.tmp_dirs = []
        self.cdp = None
        self.probe_value = None

    # -- commands -----------------------------------------------------------
    def cmd(self, action, args=None, timeout=60):
        body = json.dumps({"action": action, "args": args or {},
                           "session": "default"}).encode()
        req = urllib.request.Request(
            f"{WB_HTTP}/command", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {WB_TOKEN}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode())
            except Exception:                 # noqa: BLE001
                return {"status": "error", "error": f"HTTP {e.code}"}

    def status(self):
        req = urllib.request.Request(
            f"{WB_HTTP}/status",
            headers={"Authorization": f"Bearer {WB_TOKEN}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())

    # -- lifecycle ----------------------------------------------------------
    def _patch_extension(self):
        dst = tempfile.mkdtemp(prefix="wb_bench_ext_", dir=self.work_tmp)
        self.tmp_dirs.append(dst)
        # WB_EXT_SRC lets a caller point the stack at an ALREADY-BUILT
        # extension tree (e.g. a zip extracted under /tmp) instead of the
        # repo's extension/. Default stays WB_EXT_DIR, so every existing
        # caller is unaffected.
        src = os.environ.get("WB_EXT_SRC") or WB_EXT_DIR
        print(f"wb_stack: copying extension from {src}")
        shutil.copytree(src, dst, dirs_exist_ok=True)
        path = os.path.join(dst, "background.js")
        with open(path, "r", encoding="utf-8", newline="") as fh:
            txt = fh.read()
        old_ws, old_http = "ws://127.0.0.1:10087", "http://127.0.0.1:10086"
        txt = txt.replace(old_ws, f"ws://127.0.0.1:{WB_WS_PORT}")
        txt = txt.replace(old_http, f"http://127.0.0.1:{WB_HTTP_PORT}")
        if (old_ws in txt or old_http in txt
                or f"127.0.0.1:{WB_HTTP_PORT}" not in txt):
            raise RuntimeError("could not rewrite extension port constants; "
                               "refusing to run against the real daemon")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(txt)
        return dst

    def _start_daemon(self):
        token_file = os.path.join(self.work_tmp, "token")
        audit = os.path.join(self.work_tmp, "wb_audit.jsonl")
        py = sys.executable
        code = (
            "import sys; sys.path.insert(0, %r); import webflow_bridge as wb; "
            "wb.HTTP_PORT = %d; wb.WS_PORT = %d; "
            "sys.argv = ['webflow_bridge', '--audit', %r]; wb.main()"
            % (WB_DAEMON_DIR, WB_HTTP_PORT, WB_WS_PORT, audit)
        )
        env = dict(os.environ, WBF_TOKEN=WB_TOKEN, WBF_TOKEN_FILE=token_file,
                   PYTHONDONTWRITEBYTECODE="1")
        env.pop("http_proxy", None)
        env.pop("https_proxy", None)
        env.pop("HTTP_PROXY", None)
        env.pop("HTTPS_PROXY", None)
        proc = subprocess.Popen([py, "-c", code], cwd=WB_DAEMON_DIR, env=env,
                                stdout=open(os.path.join(self.work_tmp,
                                                         "daemon.log"), "wb"),
                                stderr=subprocess.STDOUT)
        self.procs.append(proc)
        for _ in range(80):
            if proc.poll() is not None:
                raise RuntimeError("isolated daemon exited during startup")
            try:
                self.status()
                return
            except Exception:                 # noqa: BLE001
                time.sleep(0.25)
        raise RuntimeError("isolated daemon did not start")

    def _start_chrome(self, ext_dir):
        profile = tempfile.mkdtemp(prefix="wb_bench_profile_", dir=self.work_tmp)
        self.tmp_dirs.append(profile)
        args = [_chrome(), f"--remote-debugging-port={WB_CDP_PORT}",
                f"--user-data-dir={profile}", "--no-first-run",
                "--no-default-browser-check",
                "--enable-unsafe-extension-debugging",
                "--disable-features=Translate,AcceptCHFrame",
                "--window-size=1280,900", "--window-position=0,0",
                "about:blank"]
        if os.environ.get("WB_HEADED") != "1":
            args.insert(1, "--headless=new")
        self.procs.append(subprocess.Popen(
            args, stdout=open(os.path.join(self.work_tmp, "chrome.log"), "wb"),
            stderr=subprocess.STDOUT))
        version = None
        for _ in range(120):
            try:
                version = _http_json(f"http://127.0.0.1:{WB_CDP_PORT}/json/version")
                break
            except Exception:                 # noqa: BLE001
                time.sleep(0.25)
        if version is None:
            raise RuntimeError("Chrome did not expose the DevTools endpoint")
        self.cdp = BrowserCdp(version["webSocketDebuggerUrl"])
        loaded = self.cdp.call("Extensions.loadUnpacked", {"path": ext_dir})
        if "error" in loaded:
            raise RuntimeError(f"Extensions.loadUnpacked failed: {loaded}")
        self.extension_id = loaded["result"].get("id")
        return self.extension_id

    def _wait_connected(self, timeout=40):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                data = self.status().get("data", {})
                if data.get("extension_connected"):
                    return time.time() - t0
            except Exception:                 # noqa: BLE001
                pass
            time.sleep(0.25)
        return None

    def start(self):
        self.ext_dir = self._patch_extension()
        self._start_daemon()
        self.extension_id = self._start_chrome(self.ext_dir)
        waited = self._wait_connected()
        if waited is None:
            raise RuntimeError("extension never connected to the isolated daemon")
        # Warm up on a normal http(s) page so `probe` exercises its real
        # injection paths instead of the about:blank permission wall.
        self.cmd("navigate", {"url": url("hello.html")}, timeout=30)
        time.sleep(0.5)
        resp = self.cmd("probe", {}, timeout=60)
        self.probe_value = resp
        self.connected_after_s = waited
        return resp

    def stop(self):
        for proc in self.procs:
            try:
                proc.terminate()
            except Exception:                 # noqa: BLE001
                pass
        for proc in self.procs:
            try:
                proc.wait(timeout=10)
            except Exception:                 # noqa: BLE001
                try:
                    proc.kill()
                except Exception:             # noqa: BLE001
                    pass
        self.procs = []
        if self.cdp:
            self.cdp.close()
            self.cdp = None
        for d in self.tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)
        self.tmp_dirs = []
