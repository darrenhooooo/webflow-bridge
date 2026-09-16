#!/usr/bin/env python3
"""End-to-end acceptance test for the Phase 0.1/0.2 installer (macOS).

Runs the real install/uninstall scripts against an ISOLATED temp HOME and a
non-production launchd label on throwaway ports. It never touches the real
`~/.webflow_bridge` or the production `com.yctech.wb.daemon` agent (their
state is snapshotted before and checked after).

    python3.11 tools/installer_test.py

Exit code 0 == all assertions passed. Assertions:
  ⓪ the frozen binary runs with `env -i` (no Python, no PATH)
  ① install  -> binary + plist present, launchd loaded, /status alive
  ② reinstall -> idempotent, still exactly one agent, still alive
  ③ uninstall -> stopped, plist + files gone, only empty dirs remain
"""
from __future__ import annotations

import hashlib
import json
import os
import pwd
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEST_ROOT = Path("/tmp/wb-install-test")
TMP_HOME = TEST_ROOT / "home"
APP_DIR = TMP_HOME / "Library/Application Support/WebflowBridge"
LABEL = "com.yctech.wb.daemon.installtest"       # never the production label
PROD_LABEL = "com.yctech.wb.daemon"
REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
REAL_TOKEN_DIR = REAL_HOME / ".webflow_bridge"

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)
    return ok


def run(cmd, env=None, check_rc=True):
    p = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if check_rc and p.returncode != 0:
        raise RuntimeError(f"{cmd} failed rc={p.returncode}\n{p.stdout}\n{p.stderr}")
    return p


def script_env(**extra) -> dict:
    env = os.environ.copy()
    env.update({
        "HOME": str(TMP_HOME),
        "WBF_LABEL": LABEL,
        "WBF_HTTP_PORT": str(HTTP_PORT),
        "WBF_WS_PORT": str(WS_PORT),
        "WBF_APP_DIR": str(APP_DIR),
        "WBF_BINARY": str(BINARY),
    })
    env.update(extra)
    return env


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def port_listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def launchd_print(label: str):
    return subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                          capture_output=True, text=True)


def launchd_pid(label: str) -> int | None:
    p = launchd_print(label)
    if p.returncode != 0:
        return None
    for line in p.stdout.splitlines():
        line = line.strip()
        if line.startswith("pid = "):
            return int(line.split("=")[1])
    return None


def http_get(port: int, path: str, token: str | None = None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=2) as r:
        return r.status, r.read().decode()


def daemon_alive(port: int) -> bool:
    try:
        _, cfg = http_get(port, "/config")
        tok = json.loads(cfg).get("token", "")
        if not tok:
            return False
        status, body = http_get(port, "/status", tok)
        return status == 200 and json.loads(body).get("status") == "ok"
    except Exception:                                        # noqa: BLE001
        return False


def wait_alive(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if daemon_alive(port):
            return True
        time.sleep(0.5)
    return False


def hash_dir(path: Path) -> dict:
    out = {}
    if path.is_dir():
        for f in sorted(path.rglob("*")):
            if f.is_file():
                out[str(f.relative_to(path))] = hashlib.sha256(
                    f.read_bytes()).hexdigest()[:16]
    return out


def find_residue(home: Path) -> tuple[list[str], list[str]]:
    files, dirs = [], []
    for root, dnames, fnames in os.walk(home):
        for f in fnames:
            files.append(str(Path(root, f).relative_to(home)))
        for d in dnames:
            dirs.append(str(Path(root, d).relative_to(home)))
    return sorted(files), sorted(dirs)


def build_if_needed() -> Path:
    cands = sorted(REPO.glob("dist/webflow-bridge-daemon-*-macos"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if cands:
        return cands[0]
    print("[setup] no dist binary — building ...")
    run([sys.executable, str(REPO / "tools/build_standalone.py")])
    return build_if_needed()


def standalone_no_python(binary: Path, ports: tuple[int, int]) -> None:
    """⓪ Run the frozen binary with a wiped environment: no Python, no PATH."""
    http_port, ws_port = ports
    home = TEST_ROOT / "env-i-home"
    home.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [str(binary), "--http-port", str(http_port), "--ws-port", str(ws_port)],
        env={"HOME": str(home)},                       # env -i equivalent
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    try:
        alive = wait_alive(http_port, timeout=15)
        check("⓪ frozen binary runs with `env -i` (no Python/PATH)", alive,
              f"port {http_port}")
        # Prove no interpreter was involved: the process is the binary itself.
        ps = run(["ps", "-o", "command=", "-p", str(proc.pid)]).stdout.strip()
        check("⓪ process is the binary, not a script/interpreter",
              str(binary) in ps, ps[:80])
    finally:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)


def main() -> int:
    global BINARY, HTTP_PORT, WS_PORT

    print("=" * 72)
    print("Webflow Bridge installer acceptance test")
    print(f"  temp HOME : {TMP_HOME}")
    print(f"  label     : {LABEL} (production label '{PROD_LABEL}' untouched)")
    print("=" * 72)

    if LABEL == PROD_LABEL:
        print("REFUSING to run: test label equals the production label")
        return 2

    BINARY = build_if_needed()
    HTTP_PORT, WS_PORT = free_port(), free_port()
    print(f"  binary    : {BINARY}")
    print(f"  test ports: HTTP {HTTP_PORT}, WS {WS_PORT}\n")

    # Snapshot the real user environment (isolation proof).
    real_token_before = hash_dir(REAL_TOKEN_DIR)
    real_prod_pid_before = launchd_pid(PROD_LABEL)

    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)
    TMP_HOME.mkdir(parents=True)
    chmod = run(["chmod", "+x", str(REPO / "tools/install_macos.sh"),
                 str(REPO / "tools/uninstall_macos.sh")])
    del chmod

    install = str(REPO / "tools/install_macos.sh")
    uninstall = str(REPO / "tools/uninstall_macos.sh")

    try:
        standalone_no_python(BINARY, (HTTP_PORT, WS_PORT))

        # ---- ① install -------------------------------------------------
        print("\n① install")
        p = run(["bash", install], env=script_env())
        print("  install stdout:", p.stdout.strip().replace("\n", "\n    "))
        bin_dst = APP_DIR / "webflow-bridge-daemon"
        plist = TMP_HOME / "Library/LaunchAgents" / f"{LABEL}.plist"
        check("binary installed + executable",
              bin_dst.is_file() and os.access(bin_dst, os.X_OK), str(bin_dst))
        check("launchd plist written", plist.is_file(), str(plist))
        check("launchd agent loaded (state=running)",
              launchd_pid(LABEL) is not None,
              f"pid={launchd_pid(LABEL)}")
        check("daemon answers GET /status", wait_alive(HTTP_PORT),
              f"http://127.0.0.1:{HTTP_PORT}/status")

        # ---- ② idempotent reinstall ------------------------------------
        print("\n② reinstall (idempotency)")
        p2 = run(["bash", install], env=script_env())
        print("  reinstall stdout:", p2.stdout.strip().replace("\n", "\n    "))
        plists = list((TMP_HOME / "Library/LaunchAgents").glob(f"{LABEL}*.plist"))
        check("reinstall exit 0", p2.returncode == 0)
        check("exactly one plist for label", len(plists) == 1,
              f"{len(plists)} file(s)")
        check("still one running agent", launchd_pid(LABEL) is not None,
              f"pid={launchd_pid(LABEL)}")
        check("still alive after reinstall", wait_alive(HTTP_PORT))

        # ---- ③ uninstall -----------------------------------------------
        print("\n③ uninstall")
        p3 = run(["bash", uninstall], env=script_env())
        print("  uninstall stdout:", p3.stdout.strip().replace("\n", "\n    "))
        time.sleep(1)
        check("launchd agent gone", launchd_pid(LABEL) is None)
        check("plist removed", not plist.exists())
        check("install dir removed", not APP_DIR.exists())
        check("port stopped listening", not port_listening(HTTP_PORT))
        check("token dir KEPT by default",
              (TMP_HOME / ".webflow_bridge/token").is_file())

        # --purge is the explicit opt-in that deletes token/audit
        run(["bash", uninstall, "--purge"], env=script_env())
        check("--purge removes token dir",
              not (TMP_HOME / ".webflow_bridge").exists())

        # ---- residual check --------------------------------------------
        print("\n④ residual check (find under temp HOME)")
        files, dirs = find_residue(TMP_HOME)
        for f in files:
            print(f"    file: {f}")
        for d in dirs:
            print(f"    dir : {d}/")
        check("no residual files under temp HOME", not files,
              f"{len(files)} file(s)" if files else "0 files")
        print(f"    (only {len(dirs)} empty macOS scaffold dir(s) remain)")

        # ---- isolation proof -------------------------------------------
        print("\n⑤ real-environment isolation")
        check("real ~/.webflow_bridge unchanged",
              hash_dir(REAL_TOKEN_DIR) == real_token_before)
        prod_pid_after = launchd_pid(PROD_LABEL)
        check("production launchd agent untouched",
              prod_pid_after == real_prod_pid_before,
              f"pid {real_prod_pid_before} -> {prod_pid_after}")
    finally:
        subprocess.run(["bash", uninstall], env=script_env(),
                       capture_output=True, text=True)
        subprocess.run(["bash", uninstall, "--purge"], env=script_env(),
                       capture_output=True, text=True)
        if not os.environ.get("WBF_KEEP_TEST"):
            shutil.rmtree(TEST_ROOT, ignore_errors=True)

    print("\n" + "=" * 72)
    if FAILURES:
        print(f"RESULT: FAIL ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("RESULT: PASS (all assertions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
