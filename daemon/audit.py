"""Audit event stream v0 — append-only JSONL with a sha256 hash chain.

Implementing Phase 0.6 audit event stream v0 (internal roadmap §5; that doc is
kept out of the repo). Pure stdlib.

Privacy red lines (see §5):
  * Raw action params and page content NEVER enter the audit file. Params are
    reduced to a sha256 fingerprint (`params_hash`) plus a tiny whitelist of
    non-sensitive scalar fields (`params_meta`, e.g. cdp `method`).
  * URLs are reduced to domain + path; the query string is dropped (default)
    or hashed — never stored verbatim.
  * `evaluate` code, `fill`/`type_text` values, uploaded file paths and page
    content are therefore never written.

Storage / retention (§5):
  * one event per line, local append-only JSONL;
  * default `~/.webflow_bridge/audit/audit-YYYYMMDD.jsonl`;
  * rotate at 10 MiB per file, keep the latest 5 files;
  * rotation does NOT break the chain: the first event of a new file carries
    `prev_hash` = the last event's `hash` of the previous file (kept in memory
    and re-read from the tail on startup, so a crash/reboot still chains);
  * `verify()` re-hashes every event and checks every `prev_hash` link,
    returning the first mismatch (index / file / line / reason).

Fail-open: a write failure must never affect action execution — `record()`
swallows and logs OSError. Enterprise deployments may flip this to fail-closed
(see the comment in `record`).
"""
from __future__ import annotations

import glob
import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

log = logging.getLogger("webflow_bridge.audit")

DEFAULT_DIR = os.path.join(os.path.expanduser("~"), ".webflow_bridge", "audit")
DEFAULT_MAX_BYTES = 10 * 1024 * 1024     # §5: single file <= 10 MiB
DEFAULT_KEEP = 5                         # §5: keep the latest 5 files
PARAM_WHITELIST = ("method",)            # non-sensitive scalars stored verbatim
JSONL_SUFFIX = ".jsonl"


def canonical(obj) -> str:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8 safe."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def event_hash(event: dict) -> str:
    """sha256 over the deterministic JSON of `event` (must not contain hash)."""
    return hashlib.sha256(canonical(event).encode("utf-8")).hexdigest()


def sanitize_url(url, hash_query: bool = False):
    """(domain, url) reduced to domain + path. Query dropped (default) or
    hashed. Returns (None, None) for a non-string/empty url."""
    if not isinstance(url, str) or not url:
        return None, None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None, None
    domain = parts.netloc or None
    clean = (parts.netloc or "") + (parts.path or "")
    if hash_query and parts.query:
        clean += "?" + hashlib.sha256(parts.query.encode("utf-8")).hexdigest()[:16]
    return domain, (clean or None)


def hash_error(message) -> str:
    """Correlation-safe error code: sha256 prefix, never the raw message
    (error text can embed file paths / page content)."""
    return "e:" + hashlib.sha256(str(message).encode("utf-8")).hexdigest()[:12]


def param_fingerprint(args):
    """(params_hash, params_meta|None) — full params hashed, never stored."""
    if not isinstance(args, dict) or not args:
        return None, None
    try:
        ph = hashlib.sha256(canonical(args).encode("utf-8")).hexdigest()
    except (TypeError, ValueError):
        ph = None
    meta = {k: args[k] for k in PARAM_WHITELIST
            if k in args and isinstance(args[k], (str, int, float, bool))}
    return ph, (meta or None)


def _arg_url(args):
    if isinstance(args, dict):
        url = args.get("url")
        if isinstance(url, str) and url:
            return url
    return None


class AuditLog:
    """Append-only hash-chained JSONL writer. Thread-safe, fail-open."""

    def __init__(self, path: str | None = None, max_bytes: int = DEFAULT_MAX_BYTES,
                 keep: int = DEFAULT_KEEP, enabled: bool = True,
                 skip_actions=()):
        self.enabled = bool(enabled)
        self.max_bytes = max_bytes
        self.keep = keep
        self.skip_actions = frozenset(skip_actions or ())
        self._base = path            # explicit override, or None for dated default
        self._dir = os.path.dirname(os.path.abspath(path)) if path else DEFAULT_DIR
        self._prefix = os.path.basename(path)[:-len(JSONL_SUFFIX)] \
            if path and path.endswith(JSONL_SUFFIX) else "audit-"
        self._lock = threading.Lock()
        self._last_hash = ""         # chain tail ("" = genesis)
        self._path = None
        self._fh = None
        if self.enabled:
            try:
                os.makedirs(self._dir, exist_ok=True)
                self._last_hash = self._tail_hash()
            except OSError as exc:
                log.warning("audit init failed (fail-open): %s", exc)
                self.enabled = False

    # -- files -----------------------------------------------------------
    def _target_path(self) -> str:
        if self._base:
            return self._base
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        return os.path.join(self._dir, f"audit-{day}{JSONL_SUFFIX}")

    def files(self):
        """Audit files in chronological order (lexicographic on the names)."""
        return sorted(glob.glob(os.path.join(self._dir, self._prefix + "*" + JSONL_SUFFIX)))

    def _tail_hash(self) -> str:
        """Last valid event hash across existing files (chain survives restart)."""
        for path in reversed(self.files()):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    lines = [ln for ln in (l.strip() for l in fh) if ln]
            except OSError:
                continue
            for line in reversed(lines):
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue                 # torn tail line after a crash
                if isinstance(ev, dict) and ev.get("hash"):
                    return ev["hash"]
        return ""

    # -- writing ---------------------------------------------------------
    def _ensure_current(self) -> None:
        want = self._target_path()
        if self._fh is not None and self._path == want:
            return
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        self._path = want
        self._fh = open(want, "a", encoding="utf-8")

    def _rotate(self) -> None:
        self._fh.close()
        self._fh = None
        stem = self._path[:-len(JSONL_SUFFIX)]
        pat = re.compile(re.escape(self._prefix) + r"\.(\d+)" + re.escape(JSONL_SUFFIX) + "$")
        seq = 0
        for path in self.files():
            m = pat.match(os.path.basename(path))
            if m:
                seq = max(seq, int(m.group(1)))
        os.replace(self._path, f"{stem}.{seq + 1:06d}{JSONL_SUFFIX}")
        self._path = self._target_path()
        self._fh = open(self._path, "a", encoding="utf-8")
        self._prune()

    def _prune(self) -> None:
        files = self.files()
        for path in files[:max(0, len(files) - self.keep)]:
            if os.path.abspath(path) == os.path.abspath(self._path):
                continue
            try:
                os.remove(path)
            except OSError:
                pass

    def record(self, action: str, *, actor=None, session_id: str = "default",
               args=None, status: str = "ok", error_code=None,
               duration_ms: float = 0.0, policy_decision: str = "allow",
               target_url=None, retries: int = 0):
        """Append one event. Returns the event dict, or None when disabled /
        skipped / on write failure. Never raises.

        Fail-open (v0): audit write failure must not affect action execution.
        Enterprise deployments can switch to fail-closed by letting the OSError
        propagate instead of logging it."""
        if not self.enabled or action in self.skip_actions:
            return None
        with self._lock:
            try:
                self._ensure_current()
                if os.path.getsize(self._path) >= self.max_bytes:
                    self._rotate()
                domain, url = sanitize_url(
                    target_url if target_url is not None else _arg_url(args))
                params_hash, params_meta = param_fingerprint(args)
                event = {
                    "event_id": uuid.uuid4().hex,
                    "ts": int(time.time() * 1000),
                    "actor": actor or None,
                    "session_id": session_id,
                    "action": action,
                    "target": {"domain": domain, "url": url},
                    "params_hash": params_hash,
                    "result": {"status": status, "error_code": error_code},
                    "duration_ms": round(float(duration_ms), 3),
                    "policy_decision": policy_decision,
                    "retries": int(retries or 0),
                    "prev_hash": self._last_hash,
                }
                if params_meta:
                    event["params_meta"] = params_meta
                event["hash"] = event_hash(event)
                self._fh.write(json.dumps(event, ensure_ascii=False,
                                          sort_keys=True) + "\n")
                self._fh.flush()
                self._last_hash = event["hash"]
                return event
            except Exception as exc:              # noqa: BLE001 (fail-open)
                log.warning("audit write failed (fail-open): %s", exc)
                return None

    # -- verification ----------------------------------------------------
    def verify(self, anchor: str | None = None):
        return verify(self.files(), anchor=anchor)


def verify(paths, anchor: str | None = None):
    """Re-hash every event and check every prev_hash link, in file order.

    Returns {"ok", "checked", "files", "error"}; on failure `error` is
    {"index" (1-based), "file", "line", "reason"}. A single torn trailing
    line (crash mid-write) is tolerated; any other bad line fails. Pass
    `anchor=""` to also require the first event's prev_hash (skipped by
    default so a pruned window can still be verified)."""
    paths = list(paths)
    prev = None
    index = 0
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = [ln.strip() for ln in fh]
        except OSError as exc:
            return {"ok": False, "checked": index, "files": paths,
                    "error": {"index": index + 1, "file": path, "line": 0,
                              "reason": f"cannot read: {exc}"}}
        lines = [ln for ln in raw if ln]
        for pos, line in enumerate(lines, 1):
            try:
                ev = json.loads(line)
            except ValueError:
                if pos == len(lines):            # torn tail after a crash
                    break
                return {"ok": False, "checked": index, "files": paths,
                        "error": {"index": index + 1, "file": path, "line": pos,
                                  "reason": "invalid json"}}
            index += 1
            stored = ev.get("hash")
            body = {k: v for k, v in ev.items() if k != "hash"}
            if stored != event_hash(body):
                return {"ok": False, "checked": index, "files": paths,
                        "error": {"index": index, "file": path, "line": pos,
                                  "reason": "hash mismatch"}}
            if prev is None:
                if anchor is not None and ev.get("prev_hash") != anchor:
                    return {"ok": False, "checked": index, "files": paths,
                            "error": {"index": index, "file": path, "line": pos,
                                      "reason": "prev_hash != anchor"}}
            elif ev.get("prev_hash") != prev:
                return {"ok": False, "checked": index, "files": paths,
                        "error": {"index": index, "file": path, "line": pos,
                                  "reason": "prev_hash mismatch"}}
            prev = stored
    return {"ok": True, "checked": index, "files": paths, "error": None}
