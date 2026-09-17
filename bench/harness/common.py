"""Shared constants + tiny helpers for the wb-bench harness.

Everything the harness writes lives under WB_BENCH (repo root of this
directory). Temporary browser profiles live under /tmp (never the user's
real profiles / user-data-dirs).
"""
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # bench/
SITE_DIR = os.path.join(ROOT, "site")
FIXTURES = os.path.join(ROOT, "fixtures")
LOGS = os.path.join(ROOT, "logs")
OUT = os.path.join(ROOT, "out")
ENVS = os.path.join(ROOT, "envs")
BU_VENV_PY = os.path.join(ENVS, ".venv-bu", "bin", "python")
UV_PYTHON_INSTALL_DIR = os.path.join(ENVS, "uv-python")

# --- Webflow Bridge repo (read-only; never modified) -----------------------
# Defaults to the repo this bench/ directory lives in; override with WB_REPO.
WB_REPO = os.environ.get("WB_REPO", os.path.dirname(ROOT))
WB_DAEMON_DIR = os.path.join(WB_REPO, "daemon")
WB_EXT_DIR = os.path.join(WB_REPO, "extension")

# --- ports -----------------------------------------------------------------
SITE_PORT = 8901
WB_HTTP_PORT = 20086
WB_WS_PORT = 20087
WB_CDP_PORT = 20088          # isolated Chrome for side A; never 9222/10086/10087/10096

SITE_BASE = f"http://127.0.0.1:{SITE_PORT}"
WB_HTTP = f"http://127.0.0.1:{WB_HTTP_PORT}"
WB_TOKEN = "wb-bench-isolated-token"     # ours; the user's ~/.webflow_bridge/token is untouched

TASK_TIMEOUT = 120.0         # seconds, per task, both sides

RESULTS_JSONL = os.path.join(LOGS, "results.jsonl")
CONNECTION_JSONL = os.path.join(LOGS, "connection.jsonl")


def url(page: str) -> str:
    return f"{SITE_BASE}/{page}"


def append_jsonl(path: str, record: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def truncate(text, limit: int = 300) -> str:
    """error field cap (red-line: real error text, truncated to 300 chars)."""
    if text is None:
        return ""
    s = str(text)
    return s if len(s) <= limit else s[:limit]


def now() -> float:
    return time.time()
