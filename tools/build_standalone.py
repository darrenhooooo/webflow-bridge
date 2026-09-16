#!/usr/bin/env python3
"""Build the single-file Webflow Bridge daemon (Phase 0.2).

The daemon is stdlib-only, so PyInstaller can freeze it into one self-contained
executable with no Python on the target machine. This script never adds a
runtime dependency to the daemon itself: PyInstaller is a *build-time* tool
(invoked via `uv tool run` when not installed) and nothing it needs ships in
the daemon's import graph.

Usage:
    python3 tools/build_standalone.py [--version 1.3.0] [--python PATH]

Output (repo `dist/`):
    macOS/Linux : webflow-bridge-daemon-<version>-macos
    Windows     : webflow-bridge-daemon-<version>-windows.exe

Cross-compiling is NOT supported by PyInstaller: each OS must build its own
binary (see docs/INSTALL.md).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DAEMON = REPO / "daemon" / "webflow_bridge.py"
DIST = REPO / "dist"
BUILD = REPO / "build" / "pyinstaller"


def product_version(explicit: str | None) -> str:
    if explicit:
        return explicit
    manifest = REPO / "extension" / "manifest.json"
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))["version"]
    except (OSError, KeyError, ValueError):
        return "0.0.0"


def platform_tag() -> tuple[str, str]:
    """(tag, extension) for the host PyInstaller runs on."""
    if sys.platform.startswith("darwin"):
        return "macos", ""
    if os.name == "nt":
        return "windows", ".exe"
    return "linux", ""


def pyinstaller_cmd(python: str | None, args: list[str]) -> list[str]:
    """PyInstaller as [python -m PyInstaller] if importable, else the `uv`
    tool runner. Never installs into the daemon's environment."""
    probe = [python or sys.executable, "-c", "import PyInstaller"]
    if subprocess.run(probe, capture_output=True).returncode == 0:
        return [python or sys.executable, "-m", "PyInstaller", *args]
    if shutil.which("pyinstaller"):
        return ["pyinstaller", *args]
    if shutil.which("uv"):
        return ["uv", "tool", "run", "pyinstaller", *args]
    raise SystemExit(
        "PyInstaller not found. Install it (pip install pyinstaller) or `uv` "
        "(https://astral.sh/uv), then re-run.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", help="override the product version")
    ap.add_argument("--python", help="interpreter to run PyInstaller with "
                                    "(default: the one running this script)")
    opts = ap.parse_args()

    if not DAEMON.is_file():
        raise SystemExit(f"daemon not found: {DAEMON}")

    tag, ext = platform_tag()
    name = f"webflow-bridge-daemon-{product_version(opts.version)}-{tag}"
    DIST.mkdir(parents=True, exist_ok=True)
    out = DIST / f"{name}{ext}"
    if out.exists():
        out.unlink()

    cmd = pyinstaller_cmd(opts.python, [
        "--onefile",
        "--noconfirm",
        "--clean",
        "--console",
        "--name", name,
        "--distpath", str(DIST),
        "--workpath", str(BUILD),
        "--specpath", str(BUILD),
        "--paths", str(DAEMON.parent),
        "--hidden-import", "audit",       # sibling module, imported guardedly
        str(DAEMON),
    ])
    print("[build] " + " ".join(cmd), flush=True)
    rc = subprocess.run(cmd, cwd=REPO).returncode
    if rc != 0 or not out.is_file():
        raise SystemExit(f"PyInstaller failed (rc={rc}); expected {out}")

    size_mb = out.stat().st_size / (1024 * 1024)
    kind = subprocess.run(["file", str(out)], capture_output=True,
                          text=True).stdout.strip()
    print(f"[ok] {out}")
    print(f"[ok] {size_mb:.1f} MB")
    print(f"[ok] {kind}")
    if size_mb > 60:
        print("[warn] over the 60 MB Phase-0.2 budget", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
