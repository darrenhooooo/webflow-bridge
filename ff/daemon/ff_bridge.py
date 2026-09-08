#!/usr/bin/env python3
"""Webflow Bridge for Firefox -- independent P0 daemon.

A stdlib-only local bridge that drives a real, already-running Firefox
through WebDriver BiDi (no extension involved):

  * HTTP : POST http://127.0.0.1:10096/command   (same contract as the
           Chrome edition -- scripts only change the port)
           -> 200 {"status":"ok","data":{...}}
           -> 200 {"status":"error","error":"..."}
           -> 503 {"error":"firefox not connected"}   (no live BiDi session)
  * BiDi : outbound WebSocket client -> ws://127.0.0.1:9222/session
           (the Firefox remote agent; one session at a time, session.new on
           connect, reconnect with exponential backoff when it drops)

This file is the Firefox variant of daemon/webflow_bridge.py.  It does NOT
import that module: HTTP protocol shape, token auth and RFC 6455 framing are
re-implemented here (independently, as the plan requires) with the Firefox
semantics baked in:

  - single resident BiDi session; every action first refreshes the top-level
    context list with browsingContext.getTree
  - actions: evaluate / navigate / tabs_list / tabs_open / tabs_close /
    tabs_close_all_but / tabs_activate / find_tab / probe
  - cdp is NOT supported on this backend and answers an explicit error
  - unknown actions answer {"status":"error","error":"unknown action: <x>"}

Auth: enabled by default.  The daemon owns a random token persisted at
~/.webflow_bridge_ff/token (0600).  Every HTTP POST must carry
"Authorization: Bearer <token>"; GET /config answers {"token": ...} to a
local companion/companion extension.  --allow-no-auth disables the check for
local migration.  (Origin protection of the BiDi channel itself is provided
by the Firefox remote agent: any WS handshake that carries an Origin header
is rejected with 400 -- verified on Firefox 155 -- so no extra BiDi Origin
guard is needed here.)

Local audit: every action is info-logged (action + caller address + a
detail that never contains evaluate code or fill values); --audit PATH
additionally appends JSONL {ts, action, who, detail}.

The WebSocket client is a minimal hand-rolled RFC 6455 client (stdlib only).
Client frames are masked per the RFC; Firefox (server) frames are unmasked.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import itertools
import json
import logging
import os
import random
import secrets
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTTP_HOST = "127.0.0.1"
HTTP_PORT = 10096
FF_HOST = "127.0.0.1"
FF_PORT = 9222

# Origins a browser page may POST from (same CSRF posture as the Chrome
# daemon, scoped to this daemon's own port).  Native scripts/curl send no
# Origin header and are unaffected once they authenticate.  Beyond the two
# exact localhost values below, any moz-extension://<uuid> origin is also
# accepted via origin_allowed(): the Firefox companion's popup fetches this
# daemon and Firefox ALWAYS stamps extension-page requests with a
# moz-extension://<uuid> Origin header (the UUID changes on every temporary
# load, so it cannot be enumerated exactly -- hence prefix matching).
ALLOWED_ORIGINS = {"http://127.0.0.1:10096", "http://localhost:10096"}


def origin_allowed(origin: str) -> bool:
    """True when an Origin header may POST to /command.

    Exact match on ALLOWED_ORIGINS, else any moz-extension:// source.
    Security rationale: only a real Firefox extension page can emit a
    moz-extension:// Origin header -- web content cannot forge it -- and
    bearer auth (check_auth) already runs BEFORE this guard in do_POST, so
    a malicious page without the token is still stopped with 401.  Letting
    the moz-extension prefix through therefore costs nothing in CSRF terms.
    """
    if origin in ALLOWED_ORIGINS:
        return True
    return origin.startswith("moz-extension://")

EVAL_TIMEOUT = 120          # seconds an HTTP caller waits for Firefox
QUICK_TIMEOUT = 8           # internal per-tab probes (title / visibility)
CONNECT_TIMEOUT = 3         # TCP connect timeout per attempt
HANDSHAKE_TIMEOUT = 10      # session.new reply timeout
MAX_FRAME = 64 << 20        # sanity cap for a single WS message (64 MiB)
BACKOFF_MAX = 10.0          # reconnect backoff ceiling (seconds)
GETTREE_RETRY_SECS = 0.3    # wait before re-reading a transiently empty tree
GETTREE_MAX_RETRIES = 3     # extra getTree attempts before trusting the tree
CLOSE_GRACE_SECS = 0.8      # grace after the WS close frame so Firefox frees
                            # its single session slot (else zombie session)

# ---------------------------------------------------------------------------
# P2: event collectors + snapshot/dialog/humanize state (Chrome-parity
# behaviour; see docs/HTTP_API.md and extension/background.js for the
# contract).  Event subscription was verified live on Firefox 155.0.1:
# network.requestCompleted / loadingFinished / dataReceived are NOT
# implemented (session.subscribe answers 'invalid argument'), so only the
# classes below are subscribed.  requestCompleted/loadingFinished have no
# replacement: responseCompleted already carries status/mimeType/size
# (response.bytesReceived) on this backend.
# ---------------------------------------------------------------------------
EVENT_CAP = 300            # ring cap for the network/console collectors
HUMANIZE = False           # --humanize: human-like pacing for input actions
P2_NET_EVENTS = ["network.beforeRequestSent", "network.responseStarted",
                 "network.responseCompleted", "network.fetchError"]
P2_LOG_EVENTS = ["log.entryAdded"]
P2_PROMPT_EVENTS = ["browsingContext.userPromptOpened",
                    "browsingContext.userPromptClosed"]
DIALOG_WAIT_MS = 2000      # handle_dialog: default wait for a dialog
DIALOG_WAIT_MAX = 15000    # handle_dialog: timeoutMs ceiling (Chrome parity)
SNAPSHOT_MAX_DEFAULT = 400
SNAPSHOT_MAX_CAP = 5000
HERE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_GEN_PATH = os.path.join(HERE, "ff_snapshot_gen.js")

# ---------------------------------------------------------------------------
# Shared-secret auth (default ON).  Mirrors the Chrome daemon's mechanism in
# ~/.webflow_bridge_ff/ (a different token space so both editions coexist).
# ---------------------------------------------------------------------------
DEFAULT_TOKEN_DIR = os.path.join(os.path.expanduser("~"), ".webflow_bridge_ff")
DEFAULT_TOKEN_PATH = os.path.join(DEFAULT_TOKEN_DIR, "token")

AUTH_TOKEN = None           # set by load_auth_token(); None == auth disabled
AUTH_REQUIRED = True        # --allow-no-auth flips to False
AUDIT_PATH = None           # optional JSONL audit file (--audit)

log = logging.getLogger("webflow-bridge-ff")


def load_auth_token(path: str | None = None) -> str | None:
    """Load (or create) the shared token file.  Returns None when disabled."""
    if not AUTH_REQUIRED:
        return None
    token_path = path or os.environ.get("WBF_FF_TOKEN_FILE") or DEFAULT_TOKEN_PATH
    env_token = os.environ.get("WBF_FF_TOKEN")
    if env_token:
        return env_token
    try:
        with open(token_path, "r", encoding="utf-8") as fh:
            tok = fh.read().strip()
            if tok:
                return tok
    except FileNotFoundError:
        pass
    tok = secrets.token_hex(32)
    try:
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(tok + "\n")
    except OSError:
        log.warning("cannot persist auth token at %s", token_path)
    return tok


def check_auth(auth_header: str | None) -> bool:
    """True when the request authenticates (token matches or auth disabled)."""
    if AUTH_TOKEN is None:
        return True
    if not auth_header:
        return False
    scheme, _, cred = auth_header.partition(" ")
    return scheme.lower() == "bearer" and secrets.compare_digest(
        cred.strip(), AUTH_TOKEN)


def audit(action: str, who: str, detail: str = "") -> None:
    """One audit line: always info-logged; --audit also appends JSONL."""
    entry = {"ts": time.time(), "action": action, "who": who, "detail": detail}
    log.info("audit action=%s who=%s%s", action, who,
             f" {detail}" if detail else "")
    if AUDIT_PATH:
        try:
            with open(AUDIT_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("audit write failed: %s", exc)


# ---------------------------------------------------------------------------
# minimal RFC 6455 framing helpers (this edition is a WS *client*, so
# outgoing frames are masked; Firefox's incoming frames are unmasked)
# ---------------------------------------------------------------------------

def _recv_exact(conn: socket.socket, n: int) -> bytes:
    """Read exactly n bytes (or raise ConnectionError on EOF)."""
    chunks = []
    got = 0
    while got < n:
        chunk = conn.recv(min(n - got, 65536))
        if not chunk:
            raise ConnectionError("socket closed")
        chunks.append(chunk)
        got += len(chunk)
    return b"".join(chunks)


def _read_frame(conn: socket.socket):
    """Read one RFC 6455 frame -> (opcode, fin, payload).  Unmasks if masked."""
    hdr = _recv_exact(conn, 2)
    fin = bool(hdr[0] & 0x80)
    opcode = hdr[0] & 0x0F
    masked = bool(hdr[1] & 0x80)
    length = hdr[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", _recv_exact(conn, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _recv_exact(conn, 8))[0]
    if length > MAX_FRAME:
        raise RuntimeError(f"ws frame too large: {length}")
    mask = _recv_exact(conn, 4) if masked else None
    payload = _recv_exact(conn, length) if length else b""
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, fin, payload


def _build_client_frame(opcode: int, payload: bytes = b"") -> bytes:
    """Build a masked client->server frame (RFC 6455 clients must mask)."""
    mask = os.urandom(4)
    head = bytearray([0x80 | opcode])
    n = len(payload)
    if n < 126:
        head.append(0x80 | n)
    elif n < 65536:
        head.append(0x80 | 126)
        head += struct.pack(">H", n)
    else:
        head.append(0x80 | 127)
        head += struct.pack(">Q", n)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return bytes(head) + mask + masked


def _read_http_response_head(conn: socket.socket, limit: int = 1 << 16):
    """Read a raw HTTP response head up to CRLFCRLF -> (status_code, headers)."""
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = conn.recv(4096)
        if not chunk:
            raise ConnectionError("connection closed during WS handshake")
        buf += chunk
        if len(buf) > limit:
            raise RuntimeError("WS handshake response too large")
    head, _, _ = buf.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = 0
    if lines:
        parts = lines[0].split(" ", 2)
        if len(parts) >= 2 and parts[0].startswith("HTTP/"):
            try:
                status = int(parts[1])
            except ValueError:
                status = 0
    headers = {}
    for line in lines[1:]:
        k, sep, v = line.partition(":")
        if sep:
            headers[k.strip().lower()] = v.strip()
    return status, headers


# ---------------------------------------------------------------------------
# error types
# ---------------------------------------------------------------------------

class FfNotConnected(Exception):
    """Firefox / the BiDi session is not currently reachable (-> HTTP 503)."""


class FfActionError(Exception):
    """Action-level failure (validation or a BiDi error reply) -> HTTP 200
    with {"status":"error","error":...}."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code or ""
        self.message = message

    def __str__(self) -> str:
        if self.code and self.code not in self.message:
            return f"{self.code}: {self.message}"
        return self.message


# ---------------------------------------------------------------------------
# WebDriver BiDi client: one resident session on ws://127.0.0.1:<port>/session
# ---------------------------------------------------------------------------

def _ws_handshake(host: str, port: int) -> socket.socket:
    """RFC 6455 upgrade against the Firefox remote agent.

    Deliberately sends NO Origin header: Firefox rejects any WS handshake
    that carries an Origin (400) -- that is its built-in origin protection,
    and native clients must not send one.
    """
    sock = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
    sock.settimeout(CONNECT_TIMEOUT)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET /session HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    try:
        sock.sendall(request.encode("ascii"))
        status, _headers = _read_http_response_head(sock)
    except Exception:
        sock.close()
        raise
    if status != 101:
        sock.close()
        raise FfNotConnected(
            f"firefox remote agent refused the BiDi handshake (HTTP {status})")
    return sock


class FfBiDi:
    """Single resident BiDi session with lazy reconnect + exponential backoff.

    connect() runs the RFC 6455 handshake and session.new synchronously,
    then hands the socket to a reader thread that resolves in-flight command
    futures by id.  When the connection dies every pending future fails fast
    and the next command triggers a reconnect attempt (rate-limited by a
    backoff gate so a dead Firefox is not hammered).
    """

    def __init__(self, port: int = FF_PORT) -> None:
        self.host = FF_HOST
        self.port = port
        self._state_lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._pending: dict[str, concurrent.futures.Future] = {}
        self._ids = itertools.count(1)
        self._connected = False
        self._session = None        # {"sessionId": ..., "capabilities": {...}}
        self._stop = threading.Event()
        self._shutting = False      # graceful-close in progress
        self._attempt_lock = threading.Lock()
        self._backoff = 1.0
        self._next_try = 0.0
        # ---- P2 event state (written by _on_event on the reader
        # thread, read by the list_network_requests / handle_dialog etc.
        # action handlers on HTTP threads).  Buffers are reset on every
        # (re)connect -- the Chrome edition resets on every debugger
        # attach, and a fresh session cannot still show a dialog.
        self._ev_lock = threading.RLock()
        self.net_events = []       # [{requestId,url,method,type,status,
                                   #   mimeType,size,timestamp}] (ring)
        self.console_events = []   # [{type,text,timestamp}] (ring)
        self.pending_dialog = None # single-slot user-prompt state machine

    # -------- state accessors ---------------------------------------------

    def is_connected(self) -> bool:
        with self._state_lock:
            return self._connected

    def session_id(self):
        with self._state_lock:
            return (self._session or {}).get("sessionId")

    def browser_version(self):
        with self._state_lock:
            caps = (self._session or {}).get("capabilities") or {}
            return caps.get("browserVersion")

    def last_error(self) -> str:
        return getattr(self, "_last_error", "")

    # -------- lifecycle ----------------------------------------------------

    def _connect(self) -> None:
        """Handshake + session.new.  Caller holds _attempt_lock."""
        sock = _ws_handshake(self.host, self.port)
        sock.settimeout(HANDSHAKE_TIMEOUT)
        rid = next(self._ids)
        try:
            sock.sendall(_build_client_frame(
                0x1, json.dumps(
                    {"id": rid, "method": "session.new",
                     "params": {"capabilities": {
                         "alwaysMatch": {
                             "unhandledPromptBehavior": "ignore"}}}},
                ).encode("utf-8")))
        except OSError as exc:
            sock.close()
            raise FfNotConnected(f"firefox not connected: {exc}") from exc
        reply = None
        try:
            while True:
                opcode, _fin, payload = _read_frame(sock)
                if opcode == 0x8:                       # close
                    raise FfNotConnected("firefox closed the BiDi connection")
                if opcode == 0x9:                       # ping -> pong
                    sock.sendall(_build_client_frame(0xA, bytes(payload)))
                    continue
                if opcode not in (0x1,):
                    continue
                msg = json.loads(payload.decode("utf-8"))
                if isinstance(msg, dict) and msg.get("id") == rid:
                    reply = msg
                    break
        except (ConnectionError, OSError, ValueError) as exc:
            sock.close()
            raise FfNotConnected(f"firefox not connected: {exc}") from exc
        sock.settimeout(None)
        if not isinstance(reply, dict) or reply.get("type") == "error":
            sock.close()
            # BiDi error replies are FLAT: {"type":"error","id":N,
            # "error":"<code>","message":"...","stacktrace":"..."}
            raise FfActionError(
                str((reply or {}).get("error") or "session error"),
                str((reply or {}).get("message") or "session.new failed"))
        result = reply.get("result") or {}
        with self._state_lock:
            self._sock = sock
            self._session = {
                "sessionId": result.get("sessionId"),
                "capabilities": result.get("capabilities") or {},
            }
            self._connected = True
        self._reader = threading.Thread(target=self._reader_loop,
                                        name="ff-bidi-reader", daemon=True)
        self._reader.start()
        # P2: a fresh session starts with empty collectors and no pending
        # dialog, then subscribes the network/log/prompt event classes the
        # P2 actions consume (best-effort).
        self._reset_event_state()
        self._subscribe_events()
        log.info("biDi connected: session=%s firefox=%s",
                 result.get("sessionId"),
                 (result.get("capabilities") or {}).get("browserVersion"))

    def _mark_disconnected(self, reason: str) -> None:
        """Session gone: drop state, fail every in-flight request fast."""
        with self._state_lock:
            was = self._connected
            self._connected = False
            self._session = None
            sock, self._sock = self._sock, None
            pending, self._pending = self._pending, {}
            self._last_error = reason
        for fut in pending.values():
            if not fut.done():
                fut.set_result({"ok": False, "disconnected": True})
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if was and not self._shutting:
            log.warning("biDi connection lost: %s", reason)

    def _reader_loop(self) -> None:
        """Consume frames; resolve pending command futures by id."""
        while not self._stop.is_set():
            sock = self._sock
            if sock is None:
                return
            try:
                opcode, fin, payload = _read_frame(sock)
            except (ConnectionError, OSError):
                self._mark_disconnected("connection closed")
                return
            if opcode == 0x8:                           # close
                self._mark_disconnected("firefox closed the connection")
                return
            if opcode == 0x9:                           # ping -> pong
                try:
                    sock.sendall(_build_client_frame(0xA, bytes(payload)))
                except OSError:
                    pass
                continue
            if opcode == 0xA:                           # pong
                continue
            if opcode in (0x1, 0x2):
                data = bytes(payload)
                while not fin:
                    opcode, fin, payload = _read_frame(sock)
                    data += bytes(payload)
            elif opcode == 0x0:                         # continuation start
                continue
            else:
                log.warning("unsupported ws opcode %d; dropping", opcode)
                continue
            try:
                msg = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                log.warning("non-JSON biDi message dropped")
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "event":
                self._on_event(msg)
                continue
            rid = msg.get("id")
            if rid is None:
                continue
            with self._state_lock:
                fut = self._pending.pop(str(rid), None)
            if fut is not None and not fut.done():
                fut.set_result(msg)

    def ensure_connected(self) -> None:
        """Reconnect lazily when down; backoff-gated, attempt-lock serialized."""
        if self.is_connected():
            return
        if self._stop.is_set():
            raise FfNotConnected("firefox not connected (daemon shutting down)")
        now = time.monotonic()
        if now < self._next_try:
            raise FfNotConnected("firefox not connected")
        with self._attempt_lock:
            if self.is_connected():
                return
            if now < self._next_try:                    # another thread retried
                raise FfNotConnected("firefox not connected")
            try:
                self._connect()
                self._backoff = 1.0
                self._next_try = 0.0
            except FfActionError as exc:
                # session.new was refused (e.g. "Maximum number of active
                # sessions" while another BiDi client -- or a stale session
                # from a previous daemon on Firefox 155, which retains the
                # slot until restart -- holds it).  Backoff-gate it like
                # any other connect failure so we do not hammer Firefox
                # with one session.new per HTTP request.
                self._next_try = time.monotonic() + self._backoff
                self._backoff = min(self._backoff * 2, BACKOFF_MAX)
                if "Maximum number of active sessions" in str(exc):
                    log.error(
                        "Firefox's single BiDi session slot is held by "
                        "another client or a stale session (Firefox 155 "
                        "retains it until restart). Restart Firefox to "
                        "clear it; the daemon will reconnect automatically.")
                else:
                    log.warning("biDi session.new failed: %s", exc)
                raise
            except FfNotConnected as exc:
                self._next_try = time.monotonic() + self._backoff
                self._backoff = min(self._backoff * 2, BACKOFF_MAX)
                log.warning("biDi reconnect attempt failed: %s", exc)
                raise
            except Exception as exc:
                self._next_try = time.monotonic() + self._backoff
                self._backoff = min(self._backoff * 2, BACKOFF_MAX)
                log.warning("biDi reconnect attempt failed: %s", exc)
                raise FfNotConnected(f"firefox not connected: {exc}") from exc

    def command(self, method: str, params: dict | None = None,
                timeout: float = EVAL_TIMEOUT) -> dict:
        """Send one BiDi command and wait for its reply (raises on errors)."""
        rid = next(self._ids)
        fut = concurrent.futures.Future()
        with self._state_lock:
            if not self._connected or self._sock is None:
                raise FfNotConnected("firefox not connected")
            self._pending[str(rid)] = fut
        try:
            frame = _build_client_frame(
                0x1, json.dumps(
                    {"id": rid, "method": method, "params": params or {}},
                ).encode("utf-8"))
            with self._send_lock:
                self._sock.sendall(frame)
        except OSError as exc:
            with self._state_lock:
                self._pending.pop(str(rid), None)
            self._mark_disconnected(f"socket error: {exc}")
            raise FfNotConnected("firefox not connected") from exc
        try:
            resp = fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            with self._state_lock:
                self._pending.pop(str(rid), None)
            raise FfActionError("timeout", f"timeout: firefox did not reply to {method} within {timeout:.0f}s")
        if not isinstance(resp, dict):
            raise FfActionError("bad-reply", "malformed biDi reply")
        if resp.get("type") == "error":
            # Flat shape: {"type":"error","id":N,"error":"<code>",
            # "message":"...","stacktrace":"..."}
            raise FfActionError(
                str(resp.get("error") or "error"),
                str(resp.get("message") or "firefox reported an error"))
        return resp.get("result") or {}

    def close(self) -> None:
        # Best-effort clean RFC 6455 close handshake: send the close frame
        # and give the agent a moment to consume it.  NOTE (Firefox 155):
        # the remote agent keeps its SINGLE BiDi session slot registered
        # until the agent/Firefox restarts -- a clean close or an abrupt
        # drop both leave the slot occupied, so a freshly started daemon
        # against the same Firefox instance answers "Maximum number of
        # active sessions" until Firefox is restarted.  The graceful frame
        # is still correct hygiene for agents that DO free on close (older
        #/newer builds), it just cannot rescue 155's retained slot.
        with self._state_lock:
            self._shutting = True
            sock = self._sock
        if sock is not None:
            try:
                sock.sendall(_build_client_frame(0x8, b""))
            except OSError:
                pass
            time.sleep(CLOSE_GRACE_SECS)
        self._stop.set()
        self._mark_disconnected("daemon shutting down")

    # -------- P2: event ingestion (network / console / user prompts) ----

    def _reset_event_state(self) -> None:
        """Arm the per-session event buffers and the dialog slot.

        Mirrors the Chrome edition's 'reset on every (re)attach': the ring
        buffers always describe the CURRENT session from its attach point
        onward, and a fresh session cannot still be showing a dialog.
        """
        with self._ev_lock:
            self.net_events = []
            self.console_events = []
            self.pending_dialog = None

    def _subscribe_events(self) -> None:
        """Subscribe the event classes the P2 actions consume.

        Only the classes verified on Firefox 155.0.1 are attempted (see the
        P2 constants block).  A failed subscribe degrades the related list
        action, never the session.
        """
        for ev in (P2_NET_EVENTS + P2_LOG_EVENTS + P2_PROMPT_EVENTS):
            try:
                self.command("session.subscribe", {"events": [ev]},
                             timeout=QUICK_TIMEOUT)
            except Exception:  # noqa: BLE001
                log.warning("biDi subscribe %s failed: %s", ev,
                            self.last_error() or "unknown error")

    def _on_event(self, msg: dict) -> None:
        """Ingest one BiDi event message (reader thread).

        Shapes verified live on Firefox 155.0.1 -- see the P2 report:
          network.beforeRequestSent / responseStarted / responseCompleted /
          fetchError: params.request.request = requestId (uuid), .url,
          .method, .destination, .initiatorType; responseCompleted adds
          params.response {status, mimeType, bytesReceived, ...}.
          log.entryAdded: params {type: console|javascript, method, level,
          text, timestamp}.
          browsingContext.userPromptOpened/Closed: single-slot dialog
          machine (a page blocks on one dialog at a time).
        """
        method = msg.get("method")
        params = msg.get("params")
        if not isinstance(params, dict):
            return
        try:
            if method in ("network.beforeRequestSent",
                          "network.responseStarted",
                          "network.fetchError"):
                self._net_seen(params, create=True)
            elif method == "network.responseCompleted":
                self._net_seen(params, create=True, completed=True)
            elif method == "log.entryAdded":
                self._console_add(params)
            elif method == "browsingContext.userPromptOpened":
                dv = params.get("defaultValue")
                with self._ev_lock:
                    self.pending_dialog = {
                        "type": str(params.get("type") or "alert"),
                        "message": str(params.get("message") or ""),
                        "defaultValue": dv if isinstance(dv, str) else "",
                        "handler": str(params.get("handler") or ""),
                        "context": params.get("context"),
                        "openedAt": time.time(),
                    }
            elif method == "browsingContext.userPromptClosed":
                with self._ev_lock:
                    self.pending_dialog = None
        except Exception:  # noqa: BLE001
            log.warning("biDi event ingest failed for %s", method)

    def _net_seen(self, params: dict, create: bool = False,
                  completed: bool = False) -> None:
        """Fold one network.* event into the Chrome-shaped ring record.

        One logical request keeps ONE record across its beforeRequestSent /
        responseStarted / responseCompleted events (they share the BiDi
        request id).  Records are appended in event order, capped at
        EVENT_CAP, and the list actions serve them newest-first -- the
        Chrome collector contract.
        """
        req = params.get("request") or {}
        url = req.get("url")
        if not isinstance(url, str) or not (url.startswith("http://")
                                            or url.startswith("https://")):
            return                          # skip about:/data:/noise traffic
        rid = req.get("request")
        if not isinstance(rid, str) or not rid:
            return
        ts_ms = int(time.time() * 1000)
        with self._ev_lock:
            rec = next((e for e in self.net_events
                        if e.get("requestId") == rid), None)
            if rec is None:
                if not create:
                    return
                rec = {
                    "requestId": rid,
                    "url": url,
                    "method": str(req.get("method") or ""),
                    "type": _net_type(req.get("destination"),
                                      req.get("initiatorType")),
                    "status": None,
                    "mimeType": None,
                    "size": None,
                    "timestamp": ts_ms,
                }
                self.net_events.append(rec)
                if len(self.net_events) > EVENT_CAP:
                    del self.net_events[0:len(self.net_events) - EVENT_CAP]
            resp = params.get("response")
            if isinstance(resp, dict):
                status = resp.get("status")
                if isinstance(status, int) and not isinstance(status, bool):
                    rec["status"] = status
                mime = resp.get("mimeType")
                if isinstance(mime, str):
                    rec["mimeType"] = mime
                # Firefox has no loadingFinished event; responseCompleted
                # carries response.bytesReceived (wire bytes) which fills the
                # Chrome 'size' (encodedDataLength) slot as best as possible.
                br = resp.get("bytesReceived")
                if isinstance(br, (int, float)) and not isinstance(br, bool):
                    rec["size"] = int(br)

    def _console_add(self, params: dict) -> None:
        """Fold log.entryAdded into the console ring (Chrome-shaped).

        type: 'console' entries keep the console method (log/error/...;
        warn is normalised to Chrome's 'warning'); 'javascript' entries
        (uncaught exceptions) map to Chrome's 'exception'.
        """
        etype = params.get("type") or "console"
        method = params.get("method") or ""
        if etype == "javascript":
            ctype = "exception"
        elif method == "warn":
            ctype = "warning"
        else:
            ctype = method or "log"
        text = params.get("text")
        if not isinstance(text, str):
            text = ""
        if etype == "javascript":
            text = text[:500]           # Chrome exception text cap
        else:
            text = text[:2000]          # Chrome console text cap
        ts_ms = params.get("timestamp")
        if not isinstance(ts_ms, (int, float)) or isinstance(ts_ms, bool):
            ts_ms = time.time() * 1000
        with self._ev_lock:
            self.console_events.append({
                "type": ctype,
                "text": text,
                "timestamp": int(ts_ms),
            })
            if len(self.console_events) > EVENT_CAP:
                del self.console_events[0:len(self.console_events) - EVENT_CAP]


# ---------------------------------------------------------------------------
# RemoteValue -> JSON-safe value (Chrome-parity: plain JS data comes back
# plain; un-serialisable types stay as typed markers / passthrough)
# ---------------------------------------------------------------------------

def _unwrap_remote(rv):
    if not isinstance(rv, dict):
        return rv
    t = rv.get("type")
    if t == "null":
        return None
    if t == "undefined":
        return {"type": "undefined"}        # Chrome-edition marker
    if "value" not in rv:
        return {"type": t}
    v = rv.get("value")
    if t == "array":
        return [_unwrap_remote(x) for x in v] if isinstance(v, list) else v
    if t == "object":
        # Firefox serialises object values as [[key, RemoteValue], ...]
        # pairs; other backends may send a flat dict -- accept both.
        if isinstance(v, list):
            out = {}
            for pair in v:
                if (isinstance(pair, list) and len(pair) == 2):
                    out[str(pair[0])] = _unwrap_remote(pair[1])
                else:
                    out[str(len(out))] = _unwrap_remote(pair)
            return out
        if isinstance(v, dict):
            return {str(k): _unwrap_remote(x) for k, x in v.items()}
        return v
    return v


def _net_type(destination, initiator) -> str:
    """Best-effort Chrome ResourceType for a BiDi network record.

    Firefox's network events carry request.destination and
    request.initiatorType (no CDP-equivalent type enum).  The Chrome
    contract exposes types like Document/XHR/Fetch/Stylesheet/Image; we map
    the common Firefox values onto those names and fall back to a
    capitalised destination/initiator (fields Firefox genuinely has).
    """
    init = initiator if isinstance(initiator, str) else ""
    dest = destination if isinstance(destination, str) else ""
    v = init or dest or ""
    m = {
        "xmlhttprequest": "XHR",
        "document": "Document",
        "script": "Script",
        "style": "Stylesheet",
        "image": "Image",
        "img": "Image",
        "media": "Media",
        "font": "Font",
        "fetch": "Fetch",
        "navigation": "Document",
        "link": "Link",
        "websocket": "WebSocket",
    }
    if v in m:
        return m[v]
    return v[:1].upper() + v[1:] if v else ""


# ---------------------------------------------------------------------------
# P1 primitives -- BiDi building blocks shared by the P1 actions below.
# All JS snippets are built with json.dumps() so caller strings can never
# break out of the expression.  Behaviour notes verified live on Firefox
# 155.0.1 (see .pi_ff_p1_task.txt report section 1):
#   - node RemoteValues carry sharedId even under resultOwnership "none"
#   - pointer move origin must be the STRING "viewport" (the object form
#     {"type":"viewport"} is rejected with "invalid argument"); element
#     origins DO take the object form {"type":"element","element":{...}}
#   - performActions does not auto-scroll: an off-viewport target answers
#     "move target out of bounds", so every locate scrolls first
#   - setFiles needs a native Windows backslash path (a forward-slash path
#     fails with NS_ERROR_FILE_UNRECOGNIZED_PATH)
# ---------------------------------------------------------------------------

P1_KEY_MAP = {
    "Enter": "\uE007", "Tab": "\uE004", "Escape": "\uE00C",
    "Backspace": "\uE003", "Delete": "\uE017",
    "ArrowUp": "\uE013", "ArrowDown": "\uE015",
    "ArrowLeft": "\uE012", "ArrowRight": "\uE014",
    "Home": "\uE011", "End": "\uE010",
    "PageUp": "\uE00E", "PageDown": "\uE00F",
    "Space": " ",
}
P1_MOD_MAP = {"alt": "\uE00A", "ctrl": "\uE009",
              "meta": "\uE03D", "shift": "\uE008"}


def _p1_sel(args: dict) -> str:
    """Validate + return the selector argument.  Snapshot '@eN' refs pass
    through here untouched: the Bridge resolves them against the cached
    snapshot of the SAME context once the target context is known (P2)."""
    sel = args.get("selector")
    if not isinstance(sel, str) or not sel.strip():
        raise FfActionError("", "'args.selector' (CSS string) is required")
    return sel


def _p1_js(ff, ctx: str, code: str, timeout: float = EVAL_TIMEOUT) -> dict:
    """script.evaluate -> the raw success result; JS exceptions surface as
    the standard FfActionError the evaluate action uses."""
    res = ff.command("script.evaluate",
                     {"expression": code, "target": {"context": ctx},
                      "awaitPromise": True, "resultOwnership": "none"},
                     timeout=timeout)
    if res.get("type") == "exception":
        det = res.get("exceptionDetails") or {}
        exc = det.get("exception") or {}
        msg = (det.get("text") or exc.get("description")
               or exc.get("message") or "script evaluation threw")
        raise FfActionError("javascript error", msg)
    return res.get("result") or {}


def _p1_eval(ff, ctx: str, code: str):
    """Evaluate JS -> unwrapped value."""
    return _unwrap_remote(_p1_js(ff, ctx, code))


def _p1_eval_json(ff, ctx: str, expr: str):
    """Evaluate an expression returning an OBJECT -> python dict via a
    JSON.stringify round trip (Firefox serialises objects as key-value
    pairs otherwise)."""
    raw = _p1_eval(ff, ctx, "JSON.stringify(" + expr + ")")
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _p1_find_geo(ff, ctx: str, selector: str) -> dict:
    """Scroll the first match into view, read its center + tag + text."""
    expr = ("(()=>{const el=document.querySelector(%s);"
            "if(!el)return{found:false};"
            "el.scrollIntoView({block:'center'});"
            "const r=el.getBoundingClientRect();"
            "return{found:true,x:Math.round(r.x+r.width/2),"
            "y:Math.round(r.y+r.height/2),"
            "tag:(el.tagName||'').toLowerCase(),"
            "text:(el.innerText||el.textContent||'').trim().slice(0,500)};})()"
            % json.dumps(selector))
    out = _p1_eval_json(ff, ctx, expr) or {}
    return out


def _p1_find_shared(ff, ctx: str, selector: str):
    """Scroll the first match into view, return its BiDi sharedId (None
    when the element is missing)."""
    expr = ("(()=>{const el=document.querySelector(%s);"
            "if(!el)return null;"
            "el.scrollIntoView({block:'center'});return el;})()"
            % json.dumps(selector))
    rv = _p1_js(ff, ctx, expr)
    # _p1_js() already returns the RemoteValue: a node result is a
    # SharedReference carrying sharedId.
    if isinstance(rv, dict) and rv.get("type") == "node":
        return rv.get("sharedId")
    return None


def _p1_probe_el(ff, ctx: str, selector: str) -> dict:
    """Read tag/type/contenteditable-ness of the first match (no scroll)."""
    expr = ("(()=>{const el=document.querySelector(%s);"
            "if(!el)return{found:false};"
            "return{found:true,tag:(el.tagName||'').toLowerCase(),"
            "type:(el.type||'').toLowerCase(),"
            "isCE:el.isContentEditable===true};})()"
            % json.dumps(selector))
    out = _p1_eval_json(ff, ctx, expr) or {}
    return out


def _p1_pointer_click(ff, ctx: str, x, y) -> None:
    """Real left-button click at viewport CSS-pixel coordinates."""
    ff.command("input.performActions", {
        "context": ctx,
        "actions": [{
            "type": "pointer", "id": "mouse",
            "parameters": {"pointerType": "mouse"},
            "actions": [
                {"type": "pointerMove", "duration": 0, "x": int(x),
                 "y": int(y), "origin": "viewport"},
                {"type": "pointerDown", "button": 0},
                {"type": "pointerUp", "button": 0}]}]})


def _p1_key_seq(ff, ctx: str, values) -> None:
    """Type a sequence of single code points as real key down/up events."""
    acts = []
    for v in values:
        acts.append({"type": "keyDown", "value": v})
        acts.append({"type": "keyUp", "value": v})
    ff.command("input.performActions", {
        "context": ctx, "actions": [{"type": "key", "id": "kb",
                                     "actions": acts}]})


def _p1_chord(ff, ctx: str, mods, key) -> None:
    """One key (optional) with modifiers held: mods down, key down+up, mods
    up (mods are single-code-point WebDriver key values)."""
    acts = []
    for m in mods:
        acts.append({"type": "keyDown", "value": m})
    if key is not None:
        acts.append({"type": "keyDown", "value": key})
        acts.append({"type": "keyUp", "value": key})
    for m in reversed(mods):
        acts.append({"type": "keyUp", "value": m})
    ff.command("input.performActions", {
        "context": ctx, "actions": [{"type": "key", "id": "kb",
                                     "actions": acts}]})


def _p1_focused_kind(ff, ctx: str) -> str:
    """Classify the page's active element: 'ce' | 'textarea' | 'input' |
    'other' (drives how type_text renders newlines)."""
    out = _p1_eval_json(ff, ctx,
                        "(()=>{const el=document.activeElement;"
                        "if(!el)return{tag:''};"
                        "return{tag:(el.tagName||'').toLowerCase(),"
                        "isCE:el.isContentEditable===true,"
                        "type:(el.type||'').toLowerCase()};})()") or {}
    if out.get("isCE"):
        return "ce"
    if out.get("tag") == "textarea":
        return "textarea"
    if out.get("tag") == "input":
        return "input"
    return "other"


def _p1_type_text(ff, ctx: str, text: str, kind: str,
                  humanize: bool = False) -> None:
    """Type text as real key events into the CURRENTLY focused element.
    kind 'ce' renders newlines with the literal "\\n" key (Firefox inserts a
    <br>, the contenteditable newline), 'textarea' renders them with the
    Enter key \\uE007 (a real text newline); single-line inputs drop
    newlines.  Contenteditable typing was verified to need a real pointer
    click first (execCommand('insertText') answers false without it and
    CDP Input.insertText does not exist on this backend)."""
    nl = {"ce": "\n", "textarea": "\uE007"}.get(kind)
    seq = []
    for ch in text:
        if ch == "\r":
            continue
        if ch == "\n":
            if nl is None:
                continue
            seq.append(nl)
        else:
            seq.append(ch)
    if not seq:
        return
    if humanize:
        # P2 humanize pacing: send each code point as its own action chunk
        # with a random 30-120 ms gap (Chrome's per-insert jitter band).
        for v in seq:
            _p1_key_seq(ff, ctx, [v])
            time.sleep((30 + random.random() * 90) / 1000.0)
    else:
        _p1_key_seq(ff, ctx, seq)


def _p1_viewport_size(ff, ctx: str) -> tuple:
    out = _p1_eval_json(ff, ctx,
                        "(()=>({w:document.documentElement.clientWidth||0,"
                        "h:document.documentElement.clientHeight||0}))()") \
        or {}
    return out.get("w") or 0, out.get("h") or 0


def _img_size(raw: bytes):
    """(width, height) from a PNG/JPEG header with stdlib struct, or None."""
    try:
        if raw[:8] == b"\x89PNG\r\n\x1a\n" and len(raw) >= 24:
            import struct as _st
            return _st.unpack(">II", raw[16:24])
        if raw[:2] == b"\xff\xd8" and len(raw) > 16:
            import struct as _st
            i = 2
            while i + 9 < len(raw):
                if raw[i] != 0xFF:
                    i += 1
                    continue
                marker = raw[i + 1]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                if marker == 0xD9 or marker == 0xDA:
                    break
                seg = _st.unpack(">H", raw[i + 2:i + 4])[0]
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8,
                                                             0xCC):
                    h, w = _st.unpack(">HH", raw[i + 5:i + 9])
                    return w, h
                i += 2 + seg
    except Exception:                               # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------------------
# HTTP command dispatch
# ---------------------------------------------------------------------------

def _audit_detail(action: str, args: dict) -> str:
    """Audit detail at action/method/url level -- never code/value bodies."""
    parts = []
    method = args.get("method")
    if isinstance(method, str) and method:
        parts.append("method=" + method)
    url = args.get("url")
    if isinstance(url, str) and url:
        parts.append("url=" + url)
    sel = args.get("selector")
    if isinstance(sel, str) and sel:
        parts.append("selector=" + sel)
    if action == "cdp":
        return " ".join(parts)
    return " ".join(parts)


class Bridge:
    """Ties the HTTP /command endpoint to the single resident BiDi session."""

    def __init__(self, client: FfBiDi) -> None:
        self.ff = client
        # ---- P2 state --------------------------------------------------
        self.last_snapshot = None     # {context, byRef, byIndex} newest
        self._snap_lock = threading.Lock()
        self._gen_source: str | None = None   # ff_snapshot_gen.js cache
        self._humanize_tls = threading.local()   # per-request humanize flag

    # -------- context resolution ------------------------------------------

    @staticmethod
    def _tops(tree: dict) -> list:
        # Firefox marks top-level contexts with "parent": null (nested
        # contexts carry a parent id string); absent counts as top-level too.
        return [c for c in tree.get("contexts", [])
                if isinstance(c, dict) and not c.get("parent")]

    def _get_tree_retry(self) -> dict:
        """browsingContext.getTree with a short retry as a robust fallback.

        On some Firefox builds / moments (fresh session.new right after a
        reconnect, heavy window churn) getTree can transiently report no
        top-level contexts even though tabs exist; probe then answers
        non-empty while the very next action sees an empty list.  Wait
        300ms and re-read up to GETTREE_MAX_RETRIES times before trusting
        the tree.
        """
        tree: dict = {}
        for attempt in range(GETTREE_MAX_RETRIES + 1):
            tree = self.ff.command("browsingContext.getTree", {})
            if self._tops(tree) or attempt == GETTREE_MAX_RETRIES:
                if attempt:
                    log.warning(
                        "getTree stayed empty after %d retries; latest tree "
                        "reports %d context(s)",
                        attempt, len(tree.get("contexts") or []))
                return tree
            log.warning(
                "browsingContext.getTree returned no top-level contexts "
                "(attempt %d/%d); retrying in %.0f ms",
                attempt + 1, GETTREE_MAX_RETRIES + 1,
                GETTREE_RETRY_SECS * 1000)
            time.sleep(GETTREE_RETRY_SECS)
        return tree

    def _resolve_context(self, args: dict, tops: list) -> str:
        """args.context (string) wins; args.tabId accepts a context string or
        a positional index into the top-level context list; default = first
        top-level context."""
        ctx = args.get("context")
        if ctx is not None:
            if not isinstance(ctx, str) or not ctx:
                raise FfActionError(
                    "", "'args.context' must be a non-empty string when provided")
            return ctx
        tab = args.get("tabId")
        if tab is not None:
            if isinstance(tab, bool) or not isinstance(tab, (int, str)):
                raise FfActionError(
                    "", "'args.tabId' must be an integer, a context string, "
                    "or omitted")
            if isinstance(tab, str):
                if not tab:
                    raise FfActionError(
                        "", "'args.tabId' must be a non-empty string when provided")
                return tab
            if not 0 <= tab < len(tops):
                raise FfActionError(
                    "", f"'args.tabId' {tab} out of range: Firefox has "
                    f"{len(tops)} top-level contexts")
            return tops[tab]["context"]
        if not tops:
            raise FfActionError("", "no top-level browsing contexts")
        # No explicit context/tabId: default to the ACTIVE (visible)
        # top-level context, mirroring the Chrome edition's "default
        # active tab" semantics.  visibilityState is probed per
        # candidate; any failure degrades to tops[0] (P0 behaviour).
        for cand in tops:
            try:
                rv = _unwrap_remote((self.ff.command(
                    "script.evaluate",
                    {"expression":
                     "document.visibilityState === 'visible'",
                     "target": {"context": cand["context"]},
                     "awaitPromise": True,
                     "resultOwnership": "none"},
                    timeout=QUICK_TIMEOUT).get("result") or {}))
                if rv is True:
                    return cand["context"]
            except Exception:                       # noqa: BLE001
                continue
        return tops[0]["context"]

    # -------- P2 helpers ---------------------------------------------------

    def _snapshot_source(self) -> str:
        """The snapshot generator JS, read once from ff_snapshot_gen.js."""
        with self._snap_lock:
            if self._gen_source is None:
                try:
                    with open(SNAPSHOT_GEN_PATH, "r", encoding="utf-8") as fh:
                        self._gen_source = fh.read()
                except OSError as exc:
                    raise FfActionError(
                        "", f"cannot read snapshot generator: {exc}") from exc
            return self._gen_source

    def _resolve_selector(self, sel: str, ctx: str) -> str:
        """Resolve a snapshot '@eN' ref into its cached CSS path.

        Same-tab semantics as the Chrome edition's resolveElement: the ref
        must come from the LAST snapshot taken on the SAME context; a stale
        or missing snapshot / unknown ref is an explicit error that tells
        the caller to snapshot again.  Only '@e<digits>' refs are snapshot
        refs (Chrome /^@e\\d+$/); any other '@...' string stays a plain
        CSS selector and will simply not match -- same as Chrome.
        """
        if not (sel.startswith("@e") and sel[2:].isdigit()):
            return sel
        with self._snap_lock:
            snap = self.last_snapshot
        if not snap or snap.get("context") != ctx:
            raise FfActionError(
                "", "snapshot is stale/ref not found -- call snapshot again")
        path = (snap.get("byRef") or {}).get(sel)
        if not isinstance(path, str) or not path:
            raise FfActionError(
                "", f"snapshot ref not found: {sel} -- call snapshot again")
        return path

    def _h_on(self) -> bool:
        """True when this HTTP request asked for humanize pacing."""
        return bool(getattr(self._humanize_tls, "on", False))

    def _h_pre(self) -> None:
        """Humanize pre-delay before an input action (Chrome 200-900 ms)."""
        if self._h_on():
            time.sleep((200 + random.random() * 700) / 1000.0)

    def _wait_dialog(self, ctx: str, timeout_ms: int):
        """Wait up to timeout_ms for a user prompt opened on ctx."""
        deadline = time.time() + timeout_ms / 1000.0
        while True:
            with self.ff._ev_lock:
                dlg = self.ff.pending_dialog
            if dlg is not None and dlg.get("context") == ctx:
                return dict(dlg)
            if time.time() >= deadline:
                return None
            time.sleep(0.05)

    # -------- probe --------------------------------------------------------

    def _probe(self) -> dict:
        # A fresh daemon has no resident session yet.  Try a lazy connect so
        # the FIRST probe (typical for health checks / companion status)
        # answers connected:true + contexts instead of a misleading
        # connected:false forever.  Never raise: probe stays best-effort.
        try:
            self.ff.ensure_connected()
        except Exception:                               # noqa: BLE001
            pass
        connected = self.ff.is_connected()
        ctxs: list = []
        sid = self.ff.session_id() if connected else None
        version = self.ff.browser_version() if connected else None
        if connected:
            try:
                ctxs = [{"id": c.get("context"), "url": c.get("url", "") or ""}
                        for c in self._tops(self._get_tree_retry())]
            except Exception:                           # noqa: BLE001
                pass
        return {"connected": connected, "sessionId": sid,
                "contexts": ctxs, "firefox": version}

    # -------- dispatch -----------------------------------------------------

    def dispatch(self, payload, who: str = ""):
        """Handle one POST /command payload -> (http_status, response_dict)."""
        try:
            return self._dispatch(payload, who)
        except FfNotConnected:
            return 503, {"error": "firefox not connected"}
        except FfActionError as exc:
            return 200, {"status": "error", "error": str(exc)}
        except Exception as exc:                            # noqa: BLE001
            log.exception("dispatch failed")
            return 200, {"status": "error", "error": f"internal error: {exc}"}

    def _dispatch(self, payload, who: str) -> tuple:
        if not isinstance(payload, dict):
            raise FfActionError("", "body must be a JSON object")
        action = payload.get("action")
        args = payload.get("args") or {}
        if not isinstance(action, str) or not action:
            raise FfActionError("", "missing 'action'")
        if not isinstance(args, dict):
            raise FfActionError("", "'args' must be an object when provided")
        session = payload.get("session", "default")
        if session != "default":
            raise FfActionError(
                "", f"unsupported session {session!r}: only 'default' is served")
        # P2: per-request humanize decision -- daemon-wide --humanize, a
        # top-level "humanize": true, or args.humanize=true (Chrome daemon
        # semantics).  Input actions pace their real-input sequences when on.
        self._humanize_tls.on = bool(HUMANIZE) or payload.get("humanize") is True \
            or (isinstance(args, dict) and args.get("humanize") is True)
        audit(action, who, detail=_audit_detail(action, args))

        # --- actions that never need a live session -----------------------
        if action == "cdp":
            return 200, {"status": "error",
                         "error": "cdp not supported on firefox backend"}
        if action == "probe":
            return 200, {"status": "ok", "data": {"value": self._probe()}}
        if action not in {"evaluate", "navigate", "tabs_list", "tabs_open",
                          "tabs_close", "tabs_close_all_but", "tabs_activate",
                          "find_tab",
                          "click", "fill", "type_text", "send_key",
                          "mouse_click", "screenshot", "save_as_pdf",
                          "upload", "snapshot", "handle_dialog",
                          "handle_file_chooser", "list_network_requests",
                          "get_network_request", "list_console_messages"}:
            raise FfActionError("", f"unknown action: {action}")

        # --- every remaining action refreshes the context list first -------
        self.ff.ensure_connected()     # lazy reconnect when Firefox is up
        tree = self._get_tree_retry()
        tops = self._tops(tree)

        if action == "evaluate":
            code = args.get("code")
            if not isinstance(code, str) or not code.strip():
                raise FfActionError("", "'args.code' (string) is required")
            ctx = self._resolve_context(args, tops)
            res = self.ff.command(
                "script.evaluate",
                {"expression": code, "target": {"context": ctx},
                 "awaitPromise": True, "resultOwnership": "none"},
                timeout=EVAL_TIMEOUT)
            # Firefox's EvaluateResult is type "success" | "exception".
            # Exceptions carry exceptionDetails (text + Error.description)
            # and must surface as the standard error contract.
            if res.get("type") == "exception":
                det = res.get("exceptionDetails") or {}
                exc = det.get("exception") or {}
                msg = (det.get("text") or exc.get("description")
                       or exc.get("message") or "script evaluation threw")
                raise FfActionError("javascript error", msg)
            rv = (res.get("result") or {}) if isinstance(res, dict) else {}
            return 200, {"status": "ok",
                         "data": {"value": _unwrap_remote(rv)}}

        if action == "navigate":
            url = args.get("url")
            if not isinstance(url, str) or not url.strip():
                raise FfActionError("", "'args.url' (string) is required")
            ctx = self._resolve_context(args, tops)
            self.ff.command(
                "browsingContext.navigate",
                {"context": ctx, "url": url, "wait": "complete"},
                timeout=EVAL_TIMEOUT)
            return 200, {"status": "ok", "data": {}}       # Chrome parity

        if action == "tabs_list":
            entries = []
            for c in tops:
                cid = c.get("context")
                entry: dict = {"id": cid, "url": c.get("url", "") or ""}
                if c.get("title"):
                    entry["title"] = c["title"]
                # Best effort: title + active (visibilityState) in one
                # evaluate per tab.  Failures degrade gracefully.
                try:
                    rv = _unwrap_remote((
                        self.ff.command(
                            "script.evaluate",
                            {"expression": "(() => ({t: document.title, "
                             "v: document.visibilityState === 'visible'}))()",
                             "target": {"context": cid},
                             "awaitPromise": True,
                             "resultOwnership": "none"},
                            timeout=QUICK_TIMEOUT)
                        .get("result") or {}))
                    if isinstance(rv, dict):
                        if isinstance(rv.get("t"), str):
                            entry["title"] = rv["t"]
                        if rv.get("v") is True:
                            entry["active"] = True
                except Exception:                           # noqa: BLE001
                    pass
                entries.append(entry)
            return 200, {"status": "ok", "data": {"value": entries}}

        if action == "tabs_open":
            url = args.get("url")
            if not isinstance(url, str) or not url.strip():
                raise FfActionError("", "'args.url' (string) is required")
            # Firefox's browsingContext.create IGNORES the url param (it
            # echoes it back but opens about:blank) -- so create a bare tab
            # and navigate it explicitly, waiting for load so tabs_open has
            # the same "tab is really at url" semantics as the Chrome
            # edition and a following find_tab matches immediately.
            res = self.ff.command(
                "browsingContext.create", {"type": "tab"})
            cid = res.get("context")
            if not cid:
                raise FfActionError(
                    "", "browsingContext.create returned no context")
            nav = self.ff.command(
                "browsingContext.navigate",
                {"context": cid, "url": url, "wait": "complete"},
                timeout=EVAL_TIMEOUT)
            return 200, {"status": "ok", "data": {
                "value": {"id": cid,
                          "url": (nav or {}).get("url") or url}}}

        if action == "tabs_close":
            ctx = self._resolve_context(args, tops)
            self.ff.command("browsingContext.close", {"context": ctx})
            return 200, {"status": "ok", "data": {
                "value": {"closed": ctx}}}

        if action == "tabs_close_all_but":
            # Chrome parity (extension/background.js handleTabsCloseAllBut):
            # default target = active tab (Chrome) / active-or-first
            # top-level context here; then close EVERY OTHER tab in the same
            # window.  BiDi exposes no window grouping, so the whole
            # top-level tree is the close scope -- which is also exactly the
            # default window on a normal Firefox session.  A stale/missing
            # target must NOT silently degrade to closing everything:
            # Chrome tabs.get throws on a gone tabId, so an explicit context
            # that is not in the current tree is an error here too.
            ctx = self._resolve_context(args, tops)
            if not any(c.get("context") == ctx for c in tops):
                raise FfActionError(
                    "", f"target tab {ctx!r} not found among "
                    f"{len(tops)} top-level contexts")
            closed = 0
            for c in tops:
                if c.get("context") == ctx:
                    continue
                self.ff.command(
                    "browsingContext.close", {"context": c["context"]})
                closed += 1
            return 200, {"status": "ok", "data": {
                "value": {"closed": closed}}}

        if action == "tabs_activate":
            ctx = self._resolve_context(args, tops)
            try:
                self.ff.command("browsingContext.activate", {"context": ctx})
            except FfActionError as exc:
                # Not supported on this Firefox: acknowledge as no-op rather
                # than fail the whole action (P0 contract).
                if exc.code in ("unknown command", "unsupported operation",
                                "invalid argument") or \
                        "not implemented" in str(exc).lower() or \
                        "unknown method" in str(exc).lower():
                    log.info("browsingContext.activate unsupported (%s); "
                             "returning no-op for context %s", exc, ctx)
                    return 200, {"status": "ok", "data": {
                        "value": {"tabId": ctx, "active": True,
                                  "noop": "activate not supported by this Firefox"}}}
                raise
            return 200, {"status": "ok", "data": {
                "value": {"tabId": ctx, "active": True}}}

        if action == "find_tab":
            url = args.get("url")
            if not isinstance(url, str) or not url.strip():
                raise FfActionError("", "'args.url' (string) is required")

            def rank(candidate: str):
                if not candidate:
                    return None
                if candidate == url:
                    return 0
                if candidate.startswith(url):
                    return 1
                if url in candidate:
                    return 2
                return None

            found = None
            for level in (0, 1, 2):
                for c in tops:
                    if rank(c.get("url", "") or "") == level:
                        found = c
                        break
                if found:
                    break
            if found is None:
                return 200, {"status": "ok", "data": {
                    "value": {"success": False,
                              "error": f"no tab matches {url}"}}}
            ctx = found["context"]
            if args.get("active") is True:
                self.ff.command("browsingContext.activate", {"context": ctx})
            return 200, {"status": "ok", "data": {
                "value": {"success": True,
                          "url": found.get("url", "") or "",
                          "tabId": ctx}}}

        # -------- P1 actions (real input + capture; contract per docs) ----

        if action == "click":
            self._h_pre()
            sel = _p1_sel(args)
            ctx = self._resolve_context(args, tops)
            sel = self._resolve_selector(sel, ctx)
            geo = _p1_find_geo(self.ff, ctx, sel)
            if not geo.get("found"):
                raise FfActionError("", f"no element matches selector {sel}")
            _p1_pointer_click(self.ff, ctx, geo["x"], geo["y"])
            return 200, {"status": "ok", "data": {"value": {
                "success": True,
                "tag": geo.get("tag") or "",
                "text": geo.get("text") or ""}}}

        if action == "fill":
            self._h_pre()
            sel = _p1_sel(args)
            value = args.get("value")
            if not isinstance(value, str):
                raise FfActionError("", "'args.value' (string) is required")
            mode = args.get("mode", "auto")
            if mode not in ("auto", "value", "contenteditable"):
                raise FfActionError(
                    "", "'args.mode' must be 'auto', 'value' or "
                    "'contenteditable'")
            ctx = self._resolve_context(args, tops)
            sel = self._resolve_selector(sel, ctx)
            el = _p1_probe_el(self.ff, ctx, sel)
            if not el.get("found"):
                raise FfActionError("", f"no element matches selector {sel}")
            tag = el.get("tag") or ""
            # --- contenteditable path: real click + Ctrl+A + typed text ---
            if mode == "contenteditable" or (mode == "auto"
                                             and el.get("isCE")):
                if not el.get("isCE"):
                    raise FfActionError(
                        "", f"fill mode '{mode}' needs a contenteditable "
                        f"element; {sel} is <{tag}>")
                geo = _p1_find_geo(self.ff, ctx, sel)
                if not geo.get("found"):
                    raise FfActionError("",
                                        f"no element matches selector {sel}")
                _p1_pointer_click(self.ff, ctx, geo["x"], geo["y"])
                _p1_chord(self.ff, ctx, ["\uE009"], "a")     # select all
                _p1_chord(self.ff, ctx, [], "\uE003")        # clear
                _p1_type_text(self.ff, ctx, value, "ce",
                              humanize=self._h_on())
                return 200, {"status": "ok", "data": {"value": {
                    "success": True, "tag": tag,
                    "mode": "contenteditable"}}}
            # --- value path: native setter + input/change (React-safe) ---
            if tag not in ("input", "textarea", "select"):
                raise FfActionError(
                    "", f"fill mode '{mode}' targets form fields only; "
                    f"{sel} is <{tag}> (contenteditable text uses mode "
                    f"'contenteditable')")
            if el.get("type") == "file":
                raise FfActionError(
                    "", "cannot fill an <input type=file>; use the "
                    "upload action")
            proto = {"textarea": "HTMLTextAreaElement",
                     "select": "HTMLSelectElement"}.get(tag,
                                                        "HTMLInputElement")
            out = _p1_eval_json(self.ff, ctx,
                                "(()=>{const el=document.querySelector(%s);"
                                "const setter=Object.getOwnPropertyDescriptor("
                                "%s.prototype,'value').set;"
                                "setter.call(el,%s);"
                                "el.dispatchEvent(new Event('input',"
                                "{bubbles:true}));"
                                "el.dispatchEvent(new Event('change',"
                                "{bubbles:true}));"
                                "return{ok:true,value:el.value};})()"
                                % (json.dumps(sel), proto,
                                   json.dumps(value)))
            if not (out or {}).get("ok"):
                raise FfActionError("", f"fill failed on {sel}")
            return 200, {"status": "ok", "data": {"value": {
                "success": True, "tag": tag, "mode": "value"}}}

        if action == "type_text":
            self._h_pre()
            text = args.get("text")
            if not isinstance(text, str):
                raise FfActionError("", "'args.text' (string) is required")
            ctx = self._resolve_context(args, tops)
            sel = args.get("selector")
            if sel is not None:
                if not isinstance(sel, str) or not sel.strip():
                    raise FfActionError(
                        "", "'args.selector' must be a string")
                sel = self._resolve_selector(sel, ctx)
                geo = _p1_find_geo(self.ff, ctx, sel)
                if not geo.get("found"):
                    raise FfActionError(
                        "", f"no element matches selector {sel}")
                _p1_pointer_click(self.ff, ctx, geo["x"], geo["y"])
            kind = _p1_focused_kind(self.ff, ctx)
            _p1_type_text(self.ff, ctx, text, kind,
                          humanize=self._h_on())
            # len mirrors the Chrome edition's JS .length (UTF-16 units).
            n = sum(2 if ord(c) > 0xFFFF else 1 for c in text)
            return 200, {"status": "ok", "data": {"value": {
                "success": True, "len": n}}}

        if action == "send_key":
            self._h_pre()
            key = args.get("key")
            if not isinstance(key, str) or not key:
                raise FfActionError("", "'args.key' (string) is required")
            if key in P1_KEY_MAP:
                value = P1_KEY_MAP[key]
            elif len(key) == 1 and key.isalnum():
                value = key
            else:
                raise FfActionError(
                    "", f"unsupported key {key!r}: supported keys are "
                    "Enter/Tab/Escape/Backspace/Delete/ArrowUp/ArrowDown/"
                    "ArrowLeft/ArrowRight/Home/End/PageUp/PageDown/Space "
                    "or a single a-z/0-9")
            mods_raw = args.get("modifiers") or []
            if not isinstance(mods_raw, list):
                raise FfActionError(
                    "", "'args.modifiers' must be an array of strings")
            mods = []
            for m in mods_raw:
                if not isinstance(m, str) or m not in P1_MOD_MAP:
                    raise FfActionError(
                        "", f"unsupported modifier {m!r}: use alt/ctrl/"
                        "meta/shift")
                mods.append(P1_MOD_MAP[m])
            ctx = self._resolve_context(args, tops)
            sel = args.get("selector")
            if sel is not None:
                if not isinstance(sel, str) or not sel.strip():
                    raise FfActionError(
                        "", "'args.selector' must be a string")
                sel = self._resolve_selector(sel, ctx)
                geo = _p1_find_geo(self.ff, ctx, sel)
                if not geo.get("found"):
                    raise FfActionError(
                        "", f"no element matches selector {sel}")
                _p1_pointer_click(self.ff, ctx, geo["x"], geo["y"])
            _p1_chord(self.ff, ctx, mods, value)
            return 200, {"status": "ok", "data": {"value": {
                "success": True, "key": key}}}

        if action == "mouse_click":
            self._h_pre()
            ctx = self._resolve_context(args, tops)
            sel = args.get("selector")
            if sel is not None:
                if not isinstance(sel, str) or not sel.strip():
                    raise FfActionError(
                        "", "'args.selector' must be a string")
                sel = self._resolve_selector(sel, ctx)
                geo = _p1_find_geo(self.ff, ctx, sel)
                if not geo.get("found"):
                    raise FfActionError(
                        "", f"no element matches selector {sel}")
                x, y = geo["x"], geo["y"]
            else:
                x, y = args.get("x"), args.get("y")
                if (not isinstance(x, int) or isinstance(x, bool)
                        or not isinstance(y, int) or isinstance(y, bool)):
                    raise FfActionError(
                        "", "provide 'selector' or integer 'x'/'y' "
                        "(viewport CSS pixels)")
            _p1_pointer_click(self.ff, ctx, x, y)
            return 200, {"status": "ok", "data": {"value": {
                "success": True, "x": x, "y": y}}}

        if action == "screenshot":
            fmt = args.get("format", "png")
            if fmt not in ("png", "jpeg"):
                raise FfActionError(
                    "", "'args.format' must be 'png' or 'jpeg'")
            quality = args.get("quality")
            if quality is not None and (not isinstance(quality, int)
                                        or isinstance(quality, bool)
                                        or not 0 <= quality <= 100):
                raise FfActionError(
                    "", "'args.quality' must be an integer 0-100 "
                    "(jpeg only)")
            ctx = self._resolve_context(args, tops)
            sel = args.get("selector")
            if sel is not None:
                if not isinstance(sel, str) or not sel.strip():
                    raise FfActionError(
                        "", "'args.selector' must be a string")
                sel = self._resolve_selector(sel, ctx)
                sid = _p1_find_shared(self.ff, ctx, sel)
                if sid is None:
                    raise FfActionError(
                        "", f"no element matches selector {sel}")
                params = {"context": ctx,
                          "clip": {"type": "element",
                                   "element": {"sharedId": sid}}}
            elif args.get("fullPage") is True:
                params = {"context": ctx, "origin": "document"}
            else:
                params = {"context": ctx}
            if fmt == "png":
                params["format"] = {"type": "image/png"}
            elif quality is None:
                params["format"] = {"type": "image/jpeg"}
            else:
                params["format"] = {"type": "image/jpeg",
                                    "quality": quality / 100.0}
            res = self.ff.command("browsingContext.captureScreenshot",
                                  params)
            data = (res or {}).get("data")
            if not isinstance(data, str) or not data:
                raise FfActionError("", "screenshot returned no image data")
            w, h = _img_size(base64.b64decode(data))
            if w is None:
                w, h = _p1_viewport_size(self.ff, ctx)   # CSS-size fallback
            return 200, {"status": "ok", "data": {"value": {
                "base64": data,
                "mime": "image/png" if fmt == "png" else "image/jpeg",
                "width": w, "height": h}}}

        if action == "save_as_pdf":
            ctx = self._resolve_context(args, tops)
            res = self.ff.command("browsingContext.print",
                                  {"context": ctx, "background": True})
            data = (res or {}).get("data")
            if not isinstance(data, str) or not data:
                raise FfActionError("", "print returned no PDF data")
            return 200, {"status": "ok", "data": {"value": {
                "base64": data, "mime": "application/pdf"}}}

        if action == "upload":
            sel = _p1_sel(args)
            file_arg = args.get("file")
            if not isinstance(file_arg, str) or not file_arg.strip():
                raise FfActionError(
                    "", "'args.file' (absolute local path) is required")
            # Firefox's input.setFiles rejects non-native (forward-slash)
            # paths on Windows -- verified.  Normalise to backslashes.
            path = os.path.normpath(file_arg)
            if not os.path.isfile(path):
                raise FfActionError("", f"file not found: {file_arg}")
            ctx = self._resolve_context(args, tops)
            sel = self._resolve_selector(sel, ctx)
            el = _p1_probe_el(self.ff, ctx, sel)
            if not el.get("found"):
                raise FfActionError("", f"no element matches selector {sel}")
            if el.get("tag") != "input" or el.get("type") != "file":
                raise FfActionError(
                    "", f"selector must resolve to an <input type=file>; "
                    f"{sel} is <{el.get('tag')} type={el.get('type')}>")
            sid = _p1_find_shared(self.ff, ctx, sel)
            if sid is None:
                raise FfActionError("", f"no element matches selector {sel}")
            self.ff.command("input.setFiles", {
                "context": ctx,
                "element": {"sharedId": sid},
                "files": [path]})
            return 200, {"status": "ok", "data": {"value": {
                "success": True, "file": file_arg, "tag": "input"}}}

        # -------- P2 actions --------------------------------------------
        # Contract: docs/HTTP_API.md + the Chrome daemon's action entries
        # (daemon/webflow_bridge.py).  Semantics per the Chrome edition
        # unless a Firefox platform limit forces an explicit error.

        if action == "snapshot":
            start = args.get("start")
            if start is None:
                start = 0
            elif not isinstance(start, int) or isinstance(start, bool) \
                    or start < 0:
                raise FfActionError(
                    "", "'args.start' must be a non-negative integer "
                    "when provided")
            max_nodes = args.get("max")
            if max_nodes is None:
                max_nodes = SNAPSHOT_MAX_DEFAULT
            elif not isinstance(max_nodes, int) or isinstance(max_nodes, bool) \
                    or max_nodes <= 0:
                raise FfActionError(
                    "", "'args.max' must be a positive integer when provided")
            else:
                max_nodes = min(max_nodes, SNAPSHOT_MAX_CAP)
            ctx = self._resolve_context(args, tops)
            code = self._snapshot_source()
            if "__START__" not in code or "__LIMIT__" not in code:
                raise FfActionError(
                    "", "snapshot generator is missing its placeholders")
            code = code.replace("__START__", str(start))
            code = code.replace("__LIMIT__", str(max_nodes))
            res = self.ff.command(
                "script.evaluate",
                {"expression": code, "target": {"context": ctx},
                 "awaitPromise": True, "resultOwnership": "none"},
                timeout=EVAL_TIMEOUT)
            if res.get("type") == "exception":
                det = res.get("exceptionDetails") or {}
                exc = det.get("exception") or {}
                msg = (det.get("text") or exc.get("description")
                       or exc.get("message") or "snapshot generator threw")
                raise FfActionError("javascript error", msg)
            rv = _unwrap_remote((res.get("result") or {})
                                if isinstance(res, dict) else {})
            if not isinstance(rv, dict):
                raise FfActionError("", "snapshot returned no object")
            if isinstance(rv.get("error"), str):
                raise FfActionError("", rv["error"])
            nodes = rv.get("nodes")
            if not isinstance(nodes, list):
                nodes = []
            # Cache ref -> path so click/fill/... resolve @eN on the SAME
            # context; a fresh start=0 snapshot (or a different context)
            # resets the cache (Chrome handleSnapshot semantics).
            with self._snap_lock:
                if (start == 0 or self.last_snapshot is None
                        or self.last_snapshot.get("context") != ctx):
                    self.last_snapshot = {"context": ctx,
                                          "byRef": {}, "byIndex": []}
                by_ref = self.last_snapshot["byRef"]
                by_index = self.last_snapshot["byIndex"]
                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                    ref = node.get("ref")
                    path = node.get("path")
                    if isinstance(ref, str) and isinstance(path, str) and path:
                        if ref not in by_ref:
                            by_index.append(path)
                        by_ref[ref] = path
            out_nodes = [{k: node[k] for k in
                          ("ref", "tag", "role", "name", "text", "path")
                          if k in node}
                         for node in nodes if isinstance(node, dict)]
            total = rv.get("total")
            return 200, {"status": "ok", "data": {"value": {
                "url": rv.get("url"), "title": rv.get("title"),
                "total": total if isinstance(total, int) else len(nodes),
                "start": start, "nodes": out_nodes}}}

        if action == "handle_dialog":
            accept_arg = args.get("accept")
            action_arg = args.get("action")
            if accept_arg is not None and not isinstance(accept_arg, bool):
                raise FfActionError(
                    "", "'args.accept' must be a boolean when provided")
            if action_arg is not None and action_arg not in ("accept", "dismiss"):
                raise FfActionError(
                    "", "'args.action' must be 'accept' or 'dismiss' "
                    "when provided")
            accept = True
            if action_arg == "dismiss":
                accept = False
            if accept_arg is not None:
                accept = accept_arg
            prompt_text = args.get("promptText")
            if prompt_text is not None and not isinstance(prompt_text, str):
                raise FfActionError(
                    "", "'args.promptText' must be a string when provided")
            timeout_ms = args.get("timeoutMs")
            if timeout_ms is None:
                timeout_ms = DIALOG_WAIT_MS
            elif (not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool)
                  or timeout_ms <= 0 or timeout_ms > DIALOG_WAIT_MAX):
                raise FfActionError(
                    "", "'args.timeoutMs' must be a positive integer <= "
                    f"{DIALOG_WAIT_MAX}")
            ctx = self._resolve_context(args, tops)
            dlg = self._wait_dialog(ctx, timeout_ms)
            if dlg is None:
                raise FfActionError(
                    "", f"no JavaScript dialog is showing within "
                    f"{timeout_ms}ms")
            user_text = prompt_text
            if (accept and user_text is None
                    and dlg.get("type") == "prompt"
                    and dlg.get("defaultValue")):
                # Firefox handleUserPrompt WITHOUT userText makes prompt()
                # return "" (verified); Chrome keeps the dialog default.
                # Filling the default in keeps both backends aligned.
                user_text = dlg["defaultValue"]
            params: dict = {"context": ctx, "accept": accept}
            if user_text is not None:
                params["userText"] = user_text
            self.ff.command("browsingContext.handleUserPrompt", params)
            with self.ff._ev_lock:
                cur = self.ff.pending_dialog
                if cur is not None and cur.get("context") == ctx:
                    self.ff.pending_dialog = None
            return 200, {"status": "ok", "data": {"value": {
                "success": True,
                "dialog": {"type": dlg["type"],
                           "message": dlg.get("message") or "",
                           "defaultPrompt": dlg.get("defaultValue") or ""},
                "accept": accept,
                "promptText": prompt_text}}}

        if action == "handle_file_chooser":
            file_arg = args.get("file")
            if not isinstance(file_arg, str) or not file_arg.strip():
                raise FfActionError(
                    "", "'args.file' (absolute local path string) is required")
            # Firefox BiDi exposes NO native file-chooser interception (no
            # fileChooserOpened event class, no chooser answering command;
            # verified live: clicking a file input opens the OS dialog which
            # the remote agent cannot see, block or dismiss).  Explicit
            # platform error per the P2 task contract -- upload
            # (input.setFiles) is the supported path on this backend.
            raise FfActionError(
                "", "native file chooser interception is not supported on "
                "the firefox backend (no BiDi file-chooser mechanism); use "
                "the upload action (input.setFiles) instead")

        if action == "list_network_requests":
            limit = args.get("limit")
            if limit is not None and (not isinstance(limit, int)
                                      or isinstance(limit, bool) or limit <= 0):
                raise FfActionError(
                    "", "'args.limit' must be a positive integer when provided")
            with self.ff._ev_lock:
                reqs = [dict(x) for x in
                        self.ff.net_events[-(limit or EVENT_CAP):]]
            reqs.reverse()                       # newest first (Chrome)
            return 200, {"status": "ok", "data": {"value": {
                "requests": reqs}}}

        if action == "get_network_request":
            rid = args.get("requestId")
            if not isinstance(rid, str) or not rid.strip():
                raise FfActionError(
                    "", "'args.requestId' (string) is required -- see "
                    "list_network_requests")
            with self.ff._ev_lock:
                rec = next((x for x in self.ff.net_events
                            if x.get("requestId") == rid), None)
            rec_out = dict(rec) if rec else None
            return 200, {"status": "ok", "data": {"value": {
                "found": rec_out is not None, "request": rec_out}}}

        if action == "list_console_messages":
            limit = args.get("limit")
            if limit is not None and (not isinstance(limit, int)
                                      or isinstance(limit, bool) or limit <= 0):
                raise FfActionError(
                    "", "'args.limit' must be a positive integer when provided")
            with self.ff._ev_lock:
                msgs = [dict(x) for x in
                        self.ff.console_events[-(limit or EVENT_CAP):]]
            msgs.reverse()                       # newest first (Chrome)
            return 200, {"status": "ok", "data": {"value": {
                "messages": msgs}}}


# ---------------------------------------------------------------------------
# HTTP command server (:10096)
# ---------------------------------------------------------------------------

class CommandHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "WebflowBridgeFF/1.0"

    def do_POST(self):                                  # noqa: N802 (stdlib API)
        who = str(self.client_address[0]) if self.client_address else ""
        # Drain the request body (per Content-Length) BEFORE any rejection
        # check: on HTTP/1.1 keep-alive an unconsumed body leaves stray
        # bytes in the connection stream and corrupts the next request on
        # the same connection (observed as spurious 501s).  Every early
        # exit -- 404 / 401 / 403 / bad Content-Length -- must leave the
        # stream exactly as clean as the dispatch path further down.
        length = self.headers.get("Content-Length")
        try:
            length = int(length) if length else 0
        except ValueError:
            return self._send_json(200, {"status": "error",
                                         "error": "bad Content-Length"})
        raw = self.rfile.read(length) if length else b""
        if self.path != "/command":
            return self._send_json(404, {"error": "not found: use POST /command"})
        if not check_auth(self.headers.get("Authorization")):
            audit("unauthorized http", who, detail=self.path)
            return self._send_json(401, {
                "error": "unauthorized: missing or invalid bearer token"})
        # CSRF/Origin guard for browser-originated POSTs (absent Origin,
        # as native scripts/curl send, is always allowed).  Accepted: the
        # exact localhost origins above, or any moz-extension://<uuid>
        # source (see origin_allowed).  Auth runs before this guard, so a
        # malicious page without the token is already stopped with 401.
        origin = self.headers.get("Origin")
        if origin is not None and not origin_allowed(origin):
            return self._send_json(403, {"error": "cross-origin POST blocked"})
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return self._send_json(200, {"status": "error",
                                         "error": "invalid JSON body"})
        status, body = BRIDGE.dispatch(payload, who=who)
        self._send_json(status, body)

    def do_GET(self):                                   # noqa: N802
        if self.path == "/config":
            return self._send_json(200, {"token": AUTH_TOKEN or ""})
        return self._send_json(405, {"error": "only POST /command is supported"})

    def _send_json(self, status: int, obj) -> None:
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except OSError:
            pass

    def log_message(self, fmt, *args):                  # quieter console
        log.info("http: " + fmt % args)


# BRIDGE is a module global because CommandHandler.dispatch and main()'s
# shutdown path both reference it, but it is built at RUNTIME in main()
# once --ff-port has been parsed: a module-level Bridge(FfBiDi()) would
# hard-code the default 9222 and silently ignore --ff-port.
BRIDGE = None           # assigned in main() before serve_forever


# ---------------------------------------------------------------------------

def main() -> None:
    global AUTH_REQUIRED, AUTH_TOKEN, AUDIT_PATH, BRIDGE, HUMANIZE
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s")
    parser = argparse.ArgumentParser(
        prog="ff_bridge",
        description="Webflow Bridge for Firefox daemon -- HTTP :10096 "
                    "POST /command + resident WebDriver BiDi client to "
                    "ws://127.0.0.1:9222/session (Firefox remote agent).")
    parser.add_argument("--ff-port", type=int, default=FF_PORT,
                        help="Firefox remote-debugging port (default 9222)")
    parser.add_argument("--http-port", type=int, default=HTTP_PORT,
                        help="HTTP command port (default 10096)")
    parser.add_argument("--allow-no-auth", action="store_true",
                        help="disable bearer-token auth (INSECURE -- "
                             "migration only for old local scripts)")
    parser.add_argument("--audit", metavar="PATH",
                        help="append JSONL audit lines {ts,action,who,detail} "
                             "to PATH (info-logging is always on)")
    parser.add_argument("--humanize", action="store_true",
                        help="daemon-wide humanize pacing for input actions "
                             "(click/fill/type_text/send_key/mouse_click)")
    opts = parser.parse_args()
    if opts.allow_no_auth:
        AUTH_REQUIRED = False
    if opts.audit:
        AUDIT_PATH = opts.audit
    if opts.humanize:
        HUMANIZE = True
    AUTH_TOKEN = load_auth_token()
    # Fix 2: build the BiDi client + Bridge here, after --ff-port has been
    # parsed, so opts.ff_port (default 9222) actually reaches FfBiDi.
    log.info("targeting Firefox remote agent at ws://%s:%d/session",
             FF_HOST, opts.ff_port)
    BRIDGE = Bridge(FfBiDi(port=opts.ff_port))
    httpd = None
    try:
        httpd = ThreadingHTTPServer((HTTP_HOST, opts.http_port), CommandHandler)
    except OSError as exc:
        print(f"[ff-bridge] FATAL: cannot bind :{opts.http_port} -- {exc}\n"
              "  Is another Webflow Bridge (Firefox) already running?")
        raise SystemExit(1) from exc
    httpd.daemon_threads = True

    print()
    print("=" * 65)
    print("  Webflow Bridge for Firefox daemon started (P0)")
    print(f"    HTTP : http://{HTTP_HOST}:{opts.http_port}    POST /command")
    print(f"    BiDi : ws://{FF_HOST}:{opts.ff_port}/session   Firefox remote agent")
    if AUTH_TOKEN is None:
        print("  AUTH : DISABLED (--allow-no-auth) -- no bearer token required")
    elif os.environ.get("WBF_FF_TOKEN"):
        print("  AUTH : bearer token required (WBF_FF_TOKEN env var)")
    else:
        print(f"  AUTH : bearer token required -- file: "
              f"{os.environ.get('WBF_FF_TOKEN_FILE') or DEFAULT_TOKEN_PATH}")
        print("         (0600; the token value is never printed to the terminal)")
    if AUDIT_PATH:
        print(f"  AUDIT: JSONL -> {AUDIT_PATH}")
    if HUMANIZE:
        print("  MODE  : humanize pacing ON (daemon-wide)")
    print("  Open Firefox first with  ff-launch.bat  (real profile, port "
          f"{opts.ff_port}).")
    print("  Then evaluate:  curl -X POST "
          f"http://127.0.0.1:{opts.http_port}/command \\")
    print("    -H 'Content-Type: application/json' \\")
    print("    -H 'Authorization: Bearer <token>' \\")
    print("    -d '{\"action\":\"evaluate\",\"args\":"
          "{\"code\":\"(() => document.title)()\"}}'")
    print("  Ctrl+C to stop.")
    print("=" * 65)
    print(flush=True)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[ff-bridge] shutting down ...")
    finally:
        httpd.server_close()
        BRIDGE.ff.close()
    log.info("stopped")


if __name__ == "__main__":
    main()
