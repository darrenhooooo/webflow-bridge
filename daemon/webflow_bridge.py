#!/usr/bin/env python3
"""
web-flow daemon — local browser-automation bridge.

Two stdlib-only servers:

  * HTTP  : POST http://127.0.0.1:10086/command
            body  {"action":"evaluate","args":{"code":"..."},"session":"default"}
            -> 200 {"status":"ok","data":{"value": <result>}}
            -> 200 {"status":"error","error":"..."}   (evaluate-level failures)
            -> 503 {"error":"extension not connected"} (no extension WebSocket)
  * WS    : ws://127.0.0.1:10087  (the Chrome MV3 "Webflow Bridge" extension)

Flow: HTTP /command -> action "evaluate" is forwarded to the single extension
WebSocket connection (session "default") as {"id","action","code","tabId"?}
(an optional args.tabId, when given, targets another tab); the daemon waits
(max 120s) for {"id","ok":true,"value":...} and maps it back to the
{"status":"ok","data":{"value":...}} shape the publish scripts expect.

"probe" is forwarded the same way (code optional) and returns the extension's
raw per-path diagnostic matrix unwrapped under data.value
({"tab": {"id", "url", "title", ...}, "paths": {"<pathName>": {"ok", "value"|"error"}, ...}}).

"navigate" forwards {"url", "tabId"?} — or, when args.newTab is true,
{"newTab": true} plus an optional "group_title" (the extension opens a new
active tab and groups it under that title) — and answers 200
{"status":"ok","data":{}} for a plain navigate (pre-Phase-B wire shape,
unchanged) or {"status":"ok","data":{"value": {"success", "tabId",
"groupId"?}}} for newTab. The browser-driver actions are forwarded with
their args as flat WS fields:

  * "cdp"           {"method", "params"?, "tabId"?} — ANY DevTools Protocol
                    command via the extension's managed chrome.debugger
                    session; the raw CDP result object is unwrapped under
                    data.value (no method allowlist: local personal tool).
  * "tabs_list"     (no args) — [{id, url, title, active, windowId, index}]
                    per tab, unwrapped under data.value.
  * "tabs_open"     {"url"} (http(s), required) — opens a new tab;
                    data.value {"id": <tabId>, "url": <url>}.
  * "tabs_close"    {"tabId"?} — data.value {"closed": <tabId>}
  * "tabs_close_all_but" {"tabId"?} — closes every tab in tabId's window
                    except tabId itself (default: active tab); data.value
                    {"closed": <count>}.
  * "tabs_activate" {"tabId"?} — data.value {"tabId": <n>, "active": true}

Agent-tool actions (standard browser-bridge-compatible tool names — the
Phase-A gap) are forwarded the same way, with their args as flat WS fields:

  * "find_tab"     {"url", "active"?} — locate an open tab whose URL matches
                    url (exact, then prefix, then substring; current-window
                    tabs first, then all windows). Never creates tabs; with
                    "active": true the matched tab is activated. data.value
                    {"success": true, "url": <tab url>, "tabId": <id>} or
                    {"success": false, "error": "no tab matches <url>"}.
  * "snapshot"     {"max"?: int, "tabId"?} — accessibility-like snapshot of
                    the target tab (visible interactive/informative elements
                    only, max nodes default 400): data.value {"url",
                    "title", "nodes": [{"ref": "@e0", "tag", "role",
                    "name", "text", "path"}, ...]}. The @e refs stay valid
                    for click/fill on the same tab until the DOM changes.
  * "click"        {"selector": CSS | "@eN", "tabId"?} — click the first
                    element matching a CSS selector, or the element behind a
                    snapshot @e ref (same tab; call snapshot again when the
                    DOM changed). data.value {"success": true, "tag",
                    "text"}. Errors -> 200 {"status": "error", ...}.
  * "fill"         {"selector": CSS | "@eN", "value": str, "mode"?: "auto"
                    | "value" | "contenteditable", "tabId"?} — fill a form
                    control via the NATIVE value setter + input/change events
                    (React/DOM-safe; auto-detected for input/textarea/select),
                    or type into a contenteditable region (focus + CDP
                    Input.insertText). data.value {"success": true, "tag",
                    "mode": <actual mode used>}.
  * "screenshot"   {"format"?: "png"|"jpeg" (default "png"), "quality"?:
                    int 0-100 (jpeg only), "selector"?: CSS | "@eN",
                    "fullPage"?: bool, "tabId"?} — Page.captureScreenshot of
                    the target tab: whole viewport, the full page (fullPage),
                    or a clip of the element behind selector (scrolled into
                    view first). data.value {"base64", "mime", "width",
                    "height"} — the CLIENT writes the file (the extension
                    cannot write arbitrary local paths).
  * "upload"       {"selector": CSS | "@eN", "file": absolute local path,
                    "tabId"?} — DOM.setFileInputFiles puts the LOCAL file
                    onto the matched <input type="file"> (the BROWSER process
                    reads the path; no base64 round-trip). data.value
                    {"success": true, "file", "tag": "input"}.
  * "save_as_pdf"  (no args) — Page.printToPDF {printBackground: true} of
                    the ACTIVE tab. data.value {"base64", "mime":
                    "application/pdf"} — client writes the file.
  * "mouse_click"  {"x"?: int, "y"?: int, "selector"?: CSS | "@eN",
                    "tabId"?} — Input.dispatchMouseEvent mousePressed +
                    mouseReleased (button "left") at viewport CSS px; a
                    selector is scrolled into view and clicked at its element
                    center. data.value {"success": true, "x", "y"}.
  * "send_key"     {"key": str, "modifiers"?: ["alt"|"ctrl"|"meta"|"shift",
                    ...], "selector"?: CSS | "@eN", "tabId"?} — focus the
                    selector first when given, then Input.dispatchKeyEvent
                    keyDown + keyUp for the key (Enter/Tab/Escape/Backspace/
                    Delete/ArrowUp/Down/Left/Right/Home/End/PageUp/PageDown/
                    Space/a-z/0-9) with the CDP modifiers bitmask. data.value
                    {"success": true, "key"}.
  * "type_text"    {"text": str, "selector"?: CSS | "@eN", "tabId"?} —
                    focus the selector first when given, then CDP
                    Input.insertText types the text at the caret. data.value
                    {"success": true, "len": <chars>}.

tabId is optional on every action that targets an existing tab (evaluate,
navigate, cdp, snapshot, click, fill, screenshot, upload, mouse_click,
send_key, type_text, tabs_close, tabs_close_all_but, tabs_activate) and
defaults to the extension's active tab. save_as_pdf takes no tabId — it always
prints the ACTIVE tab. find_tab takes no tabId — it searches every window.

Auth: when enabled (default) every POST /command must carry an
"Authorization: Bearer <token>" header (token file: ~/.webflow_bridge/token;
--allow-no-auth disables this for old local scripts). The extension WS
handshake must present "?token=<tok>" (see _serve_ws). Origin guard (kept as
second layer): POSTs carrying an "Origin" header that is not in
{"http://127.0.0.1:10086", "http://localhost:10086"} are rejected with 403
{"error": "cross-origin POST blocked"} — a CSRF guard for
browser-originated requests. Native scripts/curl send no Origin header and
are unaffected. GET /config answers {"token": ...} to the extension only
(no CORS headers, so a web page cannot read it).

The WebSocket server is a minimal hand-rolled RFC 6455 server (no third-party
deps). Server frames are unmasked; client (browser) frames are masked.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import itertools
import json
import logging
import mimetypes
import os
import secrets
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTTP_HOST = "127.0.0.1"
HTTP_PORT = 10086
WS_HOST = "127.0.0.1"
WS_PORT = 10087

# Origins a browser page may POST from (CSRF guard for browser-originated
# requests; see do_POST). Native scripts/curl send no "Origin" header and are
# always allowed. The daemon's own loopback origin spellings are trusted so a
# local tool page can POST from either. The WebSocket handshake is a separate
# path, guarded by the shared token (see _serve_ws).
# NOTE: "null" (sandboxed/file-origin pages) is intentionally NOT allowed: a
# hostile web page can open a sandboxed iframe and fire a no-CORS fetch whose
# Origin serialises as "null", which would otherwise bypass this guard. Every
# request must instead present the shared bearer token (see AUTH_TOKEN).
ALLOWED_ORIGINS = {"http://127.0.0.1:10086", "http://localhost:10086"}

EVAL_TIMEOUT = 120          # seconds an HTTP caller waits for the extension
WS_ACCEPT_KEY = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"   # RFC 6455 GUID
MAX_FRAME = 64 << 20        # sanity cap for a single WS message (64 MiB)
KEEPALIVE_INTERVAL = 15     # daemon->extension WS ping period (MV3 SW keepalive)

# ---------------------------------------------------------------------------
# Shared-secret auth (default ON). The daemon owns a random token persisted at
# TOKEN_PATH (0600 on POSIX; Windows inherits the user-profile ACL). Every
# HTTP POST /command must carry "Authorization: Bearer <token>"; the extension
# WebSocket handshake must present ?token=<token>. A browser page cannot read
# the token file and cannot read GET /config (no CORS header), so a hostile
# page / sandboxed iframe / DNS-rebinding attempt is rejected. A local process
# running as the same user can read the file — that is outside this threat
# model (OS-level isolation would be needed); audit logging covers it.
# ---------------------------------------------------------------------------
DEFAULT_TOKEN_DIR = os.path.join(os.path.expanduser("~"), ".webflow_bridge")
DEFAULT_TOKEN_PATH = os.path.join(DEFAULT_TOKEN_DIR, "token")

AUTH_TOKEN = None            # set by load_auth_token(); None == auth disabled
AUTH_REQUIRED = True         # --allow-no-auth flips to False
AUDIT_PATH = None            # optional JSONL audit file (--audit)
CDP_ALLOWLIST = None         # optional set/list of CDP methods (--cdp-allowlist)
HUMANIZE = False             # --humanize: human-like pacing for every action


def load_auth_token(path: str | None = None) -> str | None:
    """Load (or create) the shared token file. Returns None when disabled."""
    if not AUTH_REQUIRED:
        return None
    token_path = path or os.environ.get("WBF_TOKEN_FILE") or DEFAULT_TOKEN_PATH
    env_token = os.environ.get("WBF_TOKEN")
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


def auth_headers(token: str) -> dict:
    """Header dict a native client sends to authenticate."""
    return {"Authorization": f"Bearer {token}"}


def check_auth(auth_header: str | None) -> bool:
    """True when the request authenticates (token matches or auth disabled)."""
    if AUTH_TOKEN is None:
        return True
    if not auth_header:
        return False
    scheme, _, cred = auth_header.partition(" ")
    return scheme.lower() == "bearer" and secrets.compare_digest(
        cred.strip(), AUTH_TOKEN)


log = logging.getLogger("webflow-bridge")


# ---------------------------------------------------------------------------
# minimal RFC 6455 framing helpers
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


def _read_http_headers(conn: socket.socket, limit: int = 1 << 16) -> str:
    """Read raw request head of the WS upgrade up to CRLFCRLF."""
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = conn.recv(4096)
        if not chunk:
            raise ConnectionError("connection closed during WS handshake")
        buf += chunk
        if len(buf) > limit:
            raise RuntimeError("WS handshake headers too large")
    head, _, _ = buf.partition(b"\r\n\r\n")
    return head.decode("latin-1")


def _parse_request_line(head: str) -> tuple[str, str, str]:
    """Split the WS/HTTP request line -> (method, path, version)."""
    line = head.split("\r\n", 1)[0]
    parts = line.split(" ")
    if len(parts) >= 2:
        return parts[0], parts[1], parts[2] if len(parts) > 2 else ""
    return "", "", ""


def _query_token(path: str) -> str | None:
    """Pull the ?token= value out of a WS request path (None if absent)."""
    if "?" not in path:
        return None
    query = path.split("?", 1)[1]
    for pair in query.split("&"):
        k, _, v = pair.partition("=")
        if k == "token":
            from urllib.parse import unquote
            return unquote(v)
    return None


def audit(action: str, who: str, detail: str = "") -> None:
    """Append one JSONL audit line (if --audit was given); always info-log."""
    entry = {"ts": time.time(), "action": action, "who": who, "detail": detail}
    log.info("audit action=%s who=%s%s", action, who,
             f" {detail}" if detail else "")
    if AUDIT_PATH:
        try:
            with open(AUDIT_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("audit write failed: %s", exc)


def _read_frame(conn: socket.socket):
    """Read one RFC 6455 frame -> (opcode, fin, payload). Unmasks if masked."""
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


def _build_frame(opcode: int, payload: bytes = b"") -> bytes:
    """Build an unmasked (server->client) frame."""
    head = bytearray([0x80 | opcode])
    n = len(payload)
    if n < 126:
        head.append(n)
    elif n < 65536:
        head.append(126)
        head += struct.pack(">H", n)
    else:
        head.append(127)
        head += struct.pack(">Q", n)
    return bytes(head) + payload


# ---------------------------------------------------------------------------

class ExtensionNotConnected(Exception):
    """Raised when the extension WebSocket is absent/just dropped."""


class Bridge:
    """Ties the HTTP command endpoint to the single extension WebSocket."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._ws_listener = None    # listening socket on :10087
        self._ws_sock = None        # current extension connection
        self._pending = {}          # request id -> concurrent.futures.Future
        self._ids = itertools.count(1)
        # Per-request humanize flag (P1): dispatch() sets it on the handling
        # thread, _roundtrip() reads it before forwarding the WS payload.
        # threading.local keeps concurrent HTTP requests on different threads
        # from leaking the flag into each other's roundtrips.
        self._humanize_tls = threading.local()

    # -------- WS server lifecycle -----------------------------------------

    def start_ws_server(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((WS_HOST, WS_PORT))
        srv.listen(1)                       # one extension connection at a time
        self._ws_listener = srv

    def ws_accept_loop(self) -> None:
        """Accept + serve extension connections forever (one at a time)."""
        while True:
            conn, addr = self._ws_listener.accept()
            log.info("extension connecting from %s", addr)
            try:
                self._serve_ws(conn)
            except Exception as exc:        # noqa: BLE001 - loop must survive
                log.warning("extension connection ended: %s", exc)
            finally:
                self._drop_connection()

    def _serve_ws(self, conn: socket.socket) -> None:
        # --- handshake ---
        head = _read_http_headers(conn)
        # P0-3: the extension must present the shared token as
        # "GET /?token=<tok>" in the handshake request line. A stale extension
        # (daemon rotated its token) or a local process probing the slot gets
        # a plain HTTP 403 and the connection is closed — no 101 upgrade.
        if AUTH_TOKEN is not None:
            _method, path, _ver = _parse_request_line(head)
            tok = _query_token(path)
            if not tok or not secrets.compare_digest(tok, AUTH_TOKEN):
                try:
                    conn.sendall(
                        "HTTP/1.1 403 Forbidden\r\n"
                        "Content-Length: 0\r\n"
                        "Connection: close\r\n\r\n".encode("ascii"))
                except OSError:
                    pass
                conn.close()
                return
        key = None
        for line in head.split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
                break
        if not key:
            raise RuntimeError("missing Sec-WebSocket-Key in handshake")
        accept = base64.b64encode(
            hashlib.sha1((key + WS_ACCEPT_KEY).encode()).digest()
        ).decode()
        conn.sendall(
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n".encode()
        )
        with self._lock:
            self._ws_sock = conn
        log.info("extension connected -> ws://%s:%d ready", WS_HOST, WS_PORT)

        # --- frame loop ---
        fragments = bytearray()
        while True:
            opcode, fin, payload = _read_frame(conn)
            if opcode == 0x8:                       # close
                try:
                    with self._lock:
                        conn.sendall(_build_frame(0x8, bytes(payload[:125])))
                except OSError:
                    pass
                return
            if opcode == 0x9:                       # ping -> pong
                with self._lock:
                    conn.sendall(_build_frame(0xA, bytes(payload)))
                continue
            if opcode == 0xA:                       # pong (heartbeat reply)
                continue
            if opcode in (0x1, 0x2):                # text / binary start
                fragments = bytearray(payload)
            elif opcode == 0x0:                     # continuation
                fragments += payload
            else:
                log.warning("unsupported ws opcode %d; closing", opcode)
                return
            if not fin:
                continue
            raw = bytes(fragments)
            fragments = bytearray()
            try:
                msg = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                log.warning("non-JSON ws message dropped")
                continue
            self._handle_ws_message(msg)

    # -------- message handling ---------------------------------------------

    def _handle_ws_message(self, msg) -> None:
        if not isinstance(msg, dict):
            return
        if msg.get("type") in ("ping", "pong", "hello"):
            return                                  # keepalive/greeting
        rid = msg.get("id")
        if rid is None:
            return
        with self._lock:
            fut = self._pending.pop(str(rid), None)
        if fut is None or fut.done():
            return
        # Accept both shapes: {"id", "ok", "value"} (background.js) and the
        # {"id", "data": {"value": ...}} shape from the spec's flow section.
        data = msg.get("data")
        if isinstance(data, dict) and "value" in data and "ok" not in msg:
            fut.set_result({"ok": True, "value": data.get("value")})
        else:
            fut.set_result(msg)

    def _drop_connection(self) -> None:
        """Extension went away: fail every in-flight request with 503 info."""
        with self._lock:
            self._ws_sock = None
            pending, self._pending = self._pending, {}
        err = {"ok": False, "disconnected": True}
        for fut in pending.values():
            if not fut.done():
                fut.set_result(err)

    def _send_ws(self, obj: dict) -> None:
        frame = _build_frame(0x1, json.dumps(obj, ensure_ascii=False).encode("utf-8"))
        with self._lock:
            sock = self._ws_sock
            if sock is None:
                raise ExtensionNotConnected()
            try:
                sock.sendall(frame)
            except OSError as exc:
                raise ExtensionNotConnected() from exc

    def ws_keepalive_loop(self) -> None:
        """Ping the connected extension every KEEPALIVE_INTERVAL seconds.

        Chrome suspends an idle MV3 service worker after ~30 s: its timers
        freeze and the extension WebSocket can go stale, so HTTP commands
        time out while the daemon still sees a live TCP connection. Any WS
        frame the worker receives resets that idle timer, so a periodic RFC
        6455 ping (opcode 0x9, empty payload) keeps the worker awake and the
        socket usable. Runs forever; daemon thread, exits with the process.
        """
        while True:
            time.sleep(KEEPALIVE_INTERVAL)
            with self._lock:
                sock = self._ws_sock
                if sock is None:
                    continue
                try:
                    sock.sendall(_build_frame(0x9, b""))
                except OSError:
                    # Socket is gone; the frame loop will notice and drop it.
                    log.warning("keepalive ping failed; extension socket gone")

    # -------- HTTP command dispatch ----------------------------------------

    def _roundtrip(self, ws_payload: dict):
        """Send a WS request and wait for the matching reply.

        Returns (ok, payload).  On failure payload carries
        {"http": <status>, "error": "..."} so dispatch() can shape the body
        exactly per the contract (503 for a missing extension, otherwise a
        200 {"status":"error",...} response).
        """
        if getattr(self._humanize_tls, "on", False):
            # P1: dispatch() humanized this request — stamp the WS payload so
            # the extension adds pacing to its browser actions.
            ws_payload["humanize"] = True
        rid = ws_payload["id"]
        fut = concurrent.futures.Future()
        with self._lock:
            if self._ws_sock is None:
                return False, {"http": 503, "error": "extension not connected"}
            self._pending[rid] = fut
        try:
            self._send_ws(ws_payload)
        except ExtensionNotConnected:
            with self._lock:
                self._pending.pop(rid, None)
            return False, {"http": 503, "error": "extension not connected"}
        try:
            resp = fut.result(timeout=EVAL_TIMEOUT)
        except concurrent.futures.TimeoutError:
            with self._lock:
                self._pending.pop(rid, None)
            return False, {"http": 200,
                           "error": f"timeout: extension did not reply within {EVAL_TIMEOUT}s"}
        if resp.get("ok"):
            return True, resp
        if resp.get("disconnected"):
            return False, {"http": 503, "error": "extension not connected"}
        return False, {"http": 200, "error": resp.get("error") or "extension reported failure"}

    @staticmethod
    def _next_request_id() -> str:
        import uuid
        return uuid.uuid4().hex

    def _validated_tab_id(self, args):
        """Optional 'args.tabId' -> (int | None, None) or (None, error_tuple).

        Absent or JSON null means "let the extension pick the active tab".
        Booleans are rejected even though they subclass int in Python.
        """
        tab_id = args.get("tabId")
        if tab_id is None:
            return None, None
        if not isinstance(tab_id, int) or isinstance(tab_id, bool):
            return (None, (200, {"status": "error",
                                 "error": "'args.tabId' must be an integer when provided"}))
        return tab_id, None

    @staticmethod
    def _audit_detail(action, args) -> str:
        """Audit detail at action/method/url level — never code/value bodies."""
        if not isinstance(args, dict):
            return ""
        parts = []
        method = args.get("method")
        if isinstance(method, str) and method:
            parts.append("method=" + method)
        url = args.get("url")
        if isinstance(url, str) and url:
            parts.append("url=" + url)
        return " ".join(parts)

    @staticmethod
    def _cdp_allowed(method: str) -> bool:
        """True when method passes CDP_ALLOWLIST (exact, or 'Domain.*' wild)."""
        for entry in CDP_ALLOWLIST or ():
            if entry.endswith(".*"):
                if method.startswith(entry[:-1]):
                    return True
            elif method == entry:
                return True
        return False

    def dispatch(self, payload, who: str = ""):
        """Handle one POST /command payload -> (http_status, response_dict).

        `who` (the HTTP client address) is passed on for audit logging; the
        WS-internal forward of an action is never audited again.
        """
        if not isinstance(payload, dict):
            return 200, {"status": "error", "error": "body must be a JSON object"}
        action = payload.get("action")
        args = payload.get("args") or {}
        session = payload.get("session", "default")
        if session != "default":
            return 200, {"status": "error",
                         "error": f"unsupported session {session!r}: only 'default' is served"}
        # P1: per-request humanize decision — daemon-wide --humanize, a
        # top-level "humanize": true, or args.humanize=true. _roundtrip()
        # stamps it onto the WS payload this request forwards.
        self._humanize_tls.on = bool(HUMANIZE) or payload.get("humanize") is True \
            or (isinstance(args, dict) and args.get("humanize") is True)
        # P0-5: audit every action BEFORE it runs. Detail stays at the
        # action/method/url level (never evaluate code or fill values).
        audit(action if isinstance(action, str) else "?", who,
              detail=self._audit_detail(action, args))

        if action == "evaluate":
            rid = self._next_request_id()
            code = args.get("code")
            if not isinstance(code, str) or not code.strip():
                return 200, {"status": "error", "error": "'args.code' (string) is required"}
            tab_id, err = self._validated_tab_id(args)   # optional: target a specific tab
            if err:
                return err
            ws_payload = {"id": rid, "action": "evaluate", "code": code}
            if tab_id is not None:
                ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "navigate":
            rid = self._next_request_id()
            url = args.get("url")
            if not isinstance(url, str) or not url.strip():
                return 200, {"status": "error", "error": "'args.url' (string) is required"}
            new_tab = args.get("newTab") is True
            group_title = args.get("group_title")
            if group_title is not None and not isinstance(group_title, str):
                return 200, {"status": "error",
                             "error": "'args.group_title' must be a string when provided"}
            tab_id, err = self._validated_tab_id(args)
            if err:
                return err
            ws_payload = {"id": rid, "action": "navigate", "url": url}
            if new_tab:
                ws_payload["newTab"] = True
            if group_title is not None and group_title.strip():
                ws_payload["group_title"] = group_title
            if tab_id is not None:
                ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                # No newTab: keep the pre-Phase-B reply byte-compatible
                # (data {}). newTab adds the extension's {success, tabId,
                # groupId?} under data.value.
                if new_tab:
                    return 200, {"status": "ok", "data": {"value": res.get("value")}}
                return 200, {"status": "ok", "data": {}}
        elif action == "tabs_open":
            rid = self._next_request_id()
            url = args.get("url")
            if not isinstance(url, str) or not url.strip():
                return 200, {"status": "error", "error": "'args.url' (string) is required"}
            ok, res = self._roundtrip({"id": rid, "action": "tabs_open", "url": url})
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "probe":
            rid = self._next_request_id()
            code = args.get("code")
            if code is not None and (not isinstance(code, str) or not code.strip()):
                return 200, {"status": "error",
                             "error": "'args.code' must be a non-empty string when provided"}
            ok, res = self._roundtrip({"id": rid, "action": "probe", "code": code})
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "cdp":
            rid = self._next_request_id()
            method = args.get("method")
            if not isinstance(method, str) or not method.strip():
                return 200, {"status": "error",
                             "error": "'args.method' (string) is required"}
            if CDP_ALLOWLIST is not None and not self._cdp_allowed(method):
                # P0-4: optional --cdp-allowlist turns the unrestricted CDP
                # passthrough into a minimal-permission allowlist.
                return 200, {"status": "error",
                             "error": "cdp method not allowed by --cdp-allowlist"}
            params = args.get("params")
            if params is not None and not isinstance(params, dict):
                return 200, {"status": "error",
                             "error": "'args.params' must be an object when provided"}
            tab_id, err = self._validated_tab_id(args)
            if err:
                return err
            ws_payload = {"id": rid, "action": "cdp", "method": method}
            if params is not None:
                ws_payload["params"] = params
            if tab_id is not None:
                ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "find_tab":
            rid = self._next_request_id()
            url = args.get("url")
            if not isinstance(url, str) or not url.strip():
                return 200, {"status": "error", "error": "'args.url' (string) is required"}
            ws_payload = {"id": rid, "action": "find_tab", "url": url}
            if args.get("active") is True:
                ws_payload["active"] = True
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "snapshot":
            rid = self._next_request_id()
            max_nodes = args.get("max")
            if max_nodes is not None and (
                not isinstance(max_nodes, int) or isinstance(max_nodes, bool) or max_nodes <= 0
            ):
                return 200, {"status": "error",
                             "error": "'args.max' must be a positive integer when provided"}
            start = args.get("start")
            if start is not None and (
                not isinstance(start, int) or isinstance(start, bool) or start < 0
            ):
                return 200, {"status": "error",
                             "error": "'args.start' must be a non-negative integer when provided"}
            tab_id, err = self._validated_tab_id(args)
            if err:
                return err
            ws_payload = {"id": rid, "action": "snapshot"}
            if max_nodes is not None:
                ws_payload["max"] = max_nodes
            if start is not None:
                ws_payload["start"] = start
            if tab_id is not None:
                ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "click":
            rid = self._next_request_id()
            selector = args.get("selector")
            if not isinstance(selector, str) or not selector.strip():
                return 200, {"status": "error", "error": "'args.selector' (string) is required"}
            index = args.get("index")
            if index is not None and (
                not isinstance(index, int) or isinstance(index, bool) or index < 0
            ):
                return 200, {"status": "error",
                             "error": "'args.index' must be a non-negative integer when provided"}
            tab_id, err = self._validated_tab_id(args)
            if err:
                return err
            ws_payload = {"id": rid, "action": "click", "selector": selector}
            if index is not None:
                ws_payload["index"] = index
            if tab_id is not None:
                ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "fill":
            rid = self._next_request_id()
            selector = args.get("selector")
            if not isinstance(selector, str) or not selector.strip():
                return 200, {"status": "error", "error": "'args.selector' (string) is required"}
            value = args.get("value")
            if not isinstance(value, str):
                return 200, {"status": "error", "error": "'args.value' (string) is required"}
            mode = args.get("mode")
            if mode is not None and mode not in ("auto", "value", "contenteditable"):
                return 200, {"status": "error",
                             "error": "'args.mode' must be one of 'auto', 'value', 'contenteditable'"}
            tab_id, err = self._validated_tab_id(args)
            if err:
                return err
            ws_payload = {"id": rid, "action": "fill",
                          "selector": selector, "value": value}
            if mode is not None:
                ws_payload["mode"] = mode
            if tab_id is not None:
                ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "screenshot":
            rid = self._next_request_id()
            fmt = args.get("format")
            if fmt is not None and fmt not in ("png", "jpeg"):
                return 200, {"status": "error",
                             "error": "'args.format' must be 'png' or 'jpeg' when provided"}
            quality = args.get("quality")
            if quality is not None and (
                not isinstance(quality, int) or isinstance(quality, bool) or not (0 <= quality <= 100)
            ):
                return 200, {"status": "error",
                             "error": "'args.quality' must be an integer 0-100 when provided"}
            selector = args.get("selector")
            if selector is not None and (not isinstance(selector, str) or not selector.strip()):
                return 200, {"status": "error",
                             "error": "'args.selector' must be a non-empty string when provided"}
            tab_id, err = self._validated_tab_id(args)
            if err:
                return err
            ws_payload = {"id": rid, "action": "screenshot"}
            if fmt is not None:
                ws_payload["format"] = fmt
            if quality is not None:
                ws_payload["quality"] = quality
            if selector is not None:
                ws_payload["selector"] = selector
            if args.get("fullPage") is True:
                ws_payload["fullPage"] = True
            if tab_id is not None:
                ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "upload":
            rid = self._next_request_id()
            selector = args.get("selector")
            if not isinstance(selector, str) or not selector.strip():
                return 200, {"status": "error", "error": "'args.selector' (string) is required"}
            file = args.get("file")
            if not isinstance(file, str) or not file.strip():
                return 200, {"status": "error",
                             "error": "'args.file' (absolute local path string) is required"}
            tab_id, err = self._validated_tab_id(args)
            if err:
                return err
            ws_payload = {"id": rid, "action": "upload",
                          "selector": selector, "file": file}
            if tab_id is not None:
                ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "save_as_pdf":
            rid = self._next_request_id()
            ok, res = self._roundtrip({"id": rid, "action": "save_as_pdf"})
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "mouse_click":
            rid = self._next_request_id()
            selector = args.get("selector")
            has_selector = isinstance(selector, str) and bool(selector.strip())
            x = args.get("x")
            y = args.get("y")
            has_xy = (isinstance(x, int) and not isinstance(x, bool) and
                      isinstance(y, int) and not isinstance(y, bool))
            if not (has_xy or has_selector):
                return 200, {"status": "error",
                             "error": "'args.x'/'args.y' (integers) or 'args.selector' is required"}
            tab_id, err = self._validated_tab_id(args)
            if err:
                return err
            ws_payload = {"id": rid, "action": "mouse_click"}
            if has_selector:
                ws_payload["selector"] = selector     # selector wins over x/y
            else:
                ws_payload["x"] = x
                ws_payload["y"] = y
            if tab_id is not None:
                ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "send_key":
            rid = self._next_request_id()
            key = args.get("key")
            if not isinstance(key, str) or key == "":
                return 200, {"status": "error", "error": "'args.key' (string) is required"}
            modifiers = args.get("modifiers")
            if modifiers is not None and not isinstance(modifiers, list):
                return 200, {"status": "error",
                             "error": "'args.modifiers' must be an array when provided"}
            selector = args.get("selector")
            if selector is not None and (not isinstance(selector, str) or not selector.strip()):
                return 200, {"status": "error",
                             "error": "'args.selector' must be a non-empty string when provided"}
            tab_id, err = self._validated_tab_id(args)
            if err:
                return err
            ws_payload = {"id": rid, "action": "send_key", "key": key}
            if modifiers is not None:
                ws_payload["modifiers"] = modifiers
            if selector is not None:
                ws_payload["selector"] = selector
            if tab_id is not None:
                ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "type_text":
            rid = self._next_request_id()
            text = args.get("text")
            if not isinstance(text, str):
                return 200, {"status": "error", "error": "'args.text' (string) is required"}
            selector = args.get("selector")
            if selector is not None and (not isinstance(selector, str) or not selector.strip()):
                return 200, {"status": "error",
                             "error": "'args.selector' must be a non-empty string when provided"}
            tab_id, err = self._validated_tab_id(args)
            if err:
                return err
            ws_payload = {"id": rid, "action": "type_text", "text": text}
            if selector is not None:
                ws_payload["selector"] = selector
            if tab_id is not None:
                ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "submit":
            rid = self._next_request_id()
            selector = args.get("selector")
            if not isinstance(selector, str) or not selector.strip():
                return 200, {"status": "error",
                             "error": "'args.selector' (CSS | @eN) is required"}
            tab_id, err = self._validated_tab_id(args)
            if err:
                return err
            ws_payload = {"id": rid, "action": "submit", "selector": selector}
            if tab_id is not None:
                ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "fill_form":
            rid = self._next_request_id()
            fields = args.get("fields")
            if not isinstance(fields, list) or not fields:
                return 200, {"status": "error",
                             "error": "'args.fields' (non-empty array of {selector, value}) is required"}
            for f in fields:
                if (not isinstance(f, dict) or not isinstance(f.get("selector"), str)
                        or not f["selector"].strip() or not isinstance(f.get("value"), str)):
                    return 200, {"status": "error",
                                 "error": "every 'args.fields' item needs {selector (CSS | @eN), value (string)}"}
            tab_id, err = self._validated_tab_id(args)
            if err:
                return err
            ws_payload = {"id": rid, "action": "fill_form", "fields": fields}
            if tab_id is not None:
                ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "wait_for":
            rid = self._next_request_id()
            selector = args.get("selector")
            if selector is not None and (not isinstance(selector, str) or not selector.strip()):
                return 200, {"status": "error",
                             "error": "'args.selector' must be a non-empty string when provided"}
            text = args.get("text")
            if text is not None and not isinstance(text, str):
                return 200, {"status": "error",
                             "error": "'args.text' must be a string when provided"}
            if (selector is None or not str(selector).strip()) and (
                    text is None or not str(text).strip()):
                return 200, {"status": "error",
                             "error": "'wait_for' needs 'args.selector' and/or 'args.text'"}
            for key in ("timeoutMs", "intervalMs"):
                val = args.get(key)
                if val is not None and (not isinstance(val, int) or isinstance(val, bool) or val <= 0):
                    return 200, {"status": "error",
                                 "error": f"'args.{key}' must be a positive integer when provided"}
            tab_id, err = self._validated_tab_id(args)
            if err:
                return err
            ws_payload = {"id": rid, "action": "wait_for"}
            if selector is not None:
                ws_payload["selector"] = selector
            if text is not None:
                ws_payload["text"] = text
            if args.get("timeoutMs") is not None:
                ws_payload["timeoutMs"] = args["timeoutMs"]
            if args.get("intervalMs") is not None:
                ws_payload["intervalMs"] = args["intervalMs"]
            if tab_id is not None:
                ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "handle_dialog":
            rid = self._next_request_id()
            accept = args.get("accept")
            if accept is not None and not isinstance(accept, bool):
                return 200, {"status": "error",
                             "error": "'args.accept' must be a boolean when provided"}
            prompt_text = args.get("promptText")
            if prompt_text is not None and not isinstance(prompt_text, str):
                return 200, {"status": "error",
                             "error": "'args.promptText' must be a string when provided"}
            tab_id, err = self._validated_tab_id(args)
            if err:
                return err
            timeout_ms = args.get("timeoutMs")
            if timeout_ms is not None:
                if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) \
                        or timeout_ms <= 0 or timeout_ms > 15000:
                    return 200, {"status": "error",
                                 "error": "'args.timeoutMs' must be a positive integer <= 15000"}
            ws_payload = {"id": rid, "action": "handle_dialog"}
            if accept is not None:
                ws_payload["accept"] = accept
            if prompt_text is not None:
                ws_payload["promptText"] = prompt_text
            if timeout_ms is not None:
                ws_payload["timeoutMs"] = timeout_ms
            if tab_id is not None:
                ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "handle_file_chooser":
            rid = self._next_request_id()
            file = args.get("file")
            if not isinstance(file, str) or not file.strip():
                return 200, {"status": "error",
                             "error": "'args.file' (absolute local path string) is required"}
            tab_id, err = self._validated_tab_id(args)
            if err:
                return err
            timeout_ms = args.get("timeoutMs")
            if timeout_ms is not None:
                if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) \
                        or timeout_ms <= 0 or timeout_ms > 15000:
                    return 200, {"status": "error",
                                 "error": "'args.timeoutMs' must be a positive integer <= 15000"}
            ws_payload = {"id": rid, "action": "handle_file_chooser", "file": file}
            if timeout_ms is not None:
                ws_payload["timeoutMs"] = timeout_ms
            if tab_id is not None:
                ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "drop":
            rid = self._next_request_id()
            selector = args.get("selector")
            if not isinstance(selector, str) or not selector.strip():
                return 200, {"status": "error",
                             "error": "'args.selector' (CSS | @eN drop-zone) is required"}
            # The daemon reads the local file(s) and forwards base64 payloads;
            # the extension cannot read arbitrary local paths.
            paths = []
            single = args.get("file")
            multi = args.get("files")
            if isinstance(single, str) and single.strip():
                paths = [single]
            elif isinstance(multi, list) and multi:
                if not all(isinstance(p, str) and p.strip() for p in multi):
                    return 200, {"status": "error",
                                 "error": "'args.files' must be an array of path strings"}
                paths = list(multi)
            else:
                return 200, {"status": "error",
                             "error": "'args.file' (single path) or 'args.files' (array) is required"}
            files = []
            try:
                for path in paths:
                    size = os.path.getsize(path)
                    if size > 32 << 20:
                        return 200, {"status": "error",
                                     "error": f"file too large for drop: {path} ({size} bytes > 32 MiB)"}
                    with open(path, "rb") as fh:
                        data = base64.b64encode(fh.read()).decode("ascii")
                    files.append({
                        "name": os.path.basename(path),
                        "mime": mimetypes.guess_type(path)[0] or "application/octet-stream",
                        "data": data,
                    })
            except OSError as exc:
                return 200, {"status": "error",
                             "error": f"cannot read drop file: {exc}"}
            tab_id, err = self._validated_tab_id(args)
            if err:
                return err
            ws_payload = {"id": rid, "action": "drop", "selector": selector,
                          "files": files}
            if tab_id is not None:
                ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "resize_page":
            rid = self._next_request_id()
            width = args.get("width")
            height = args.get("height")
            if (not isinstance(width, int) or isinstance(width, bool) or width <= 0
                    or not isinstance(height, int) or isinstance(height, bool) or height <= 0):
                return 200, {"status": "error",
                             "error": "'args.width'/'args.height' (positive integers) are required"}
            tab_id, err = self._validated_tab_id(args)
            if err:
                return err
            ws_payload = {"id": rid, "action": "resize_page",
                          "width": width, "height": height}
            if tab_id is not None:
                ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "list_network_requests":
            rid = self._next_request_id()
            ws_payload = {"id": rid, "action": "list_network_requests"}
            limit = args.get("limit")
            if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0):
                return 200, {"status": "error",
                             "error": "'args.limit' must be a positive integer when provided"}
            if limit is not None:
                ws_payload["limit"] = limit
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "get_network_request":
            rid = self._next_request_id()
            request_id = args.get("requestId")
            if not isinstance(request_id, str) or not request_id.strip():
                return 200, {"status": "error",
                             "error": "'args.requestId' (string) is required — see list_network_requests"}
            ok, res = self._roundtrip(
                {"id": rid, "action": "get_network_request", "requestId": request_id})
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action == "list_console_messages":
            rid = self._next_request_id()
            ws_payload = {"id": rid, "action": "list_console_messages"}
            limit = args.get("limit")
            if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0):
                return 200, {"status": "error",
                             "error": "'args.limit' must be a positive integer when provided"}
            if limit is not None:
                ws_payload["limit"] = limit
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action in ("tabs_list", "tabs_close", "tabs_close_all_but", "tabs_activate"):
            rid = self._next_request_id()
            ws_payload = {"id": rid, "action": action}
            if action in ("tabs_close", "tabs_close_all_but", "tabs_activate"):
                tab_id, err = self._validated_tab_id(args)
                if err:
                    return err
                if tab_id is not None:
                    ws_payload["tabId"] = tab_id
            ok, res = self._roundtrip(ws_payload)
            if ok:
                return 200, {"status": "ok", "data": {"value": res.get("value")}}
        elif action is None:
            return 200, {"status": "error", "error": "missing 'action'"}
        else:
            return 200, {"status": "error", "error": f"unknown action {action!r}"}

        # shared failure path
        if res.get("http") == 503:
            return 503, {"error": res.get("error", "extension not connected")}
        return 200, {"status": "error", "error": res.get("error", "extension error")}

    def close(self) -> None:
        with self._lock:
            sock, self._ws_sock = self._ws_sock, None
            lst, self._ws_listener = self._ws_listener, None
        for s in (sock, lst):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass


BRIDGE = Bridge()


# ---------------------------------------------------------------------------
# HTTP command server (:10086)
# ---------------------------------------------------------------------------

class CommandHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "WebflowBridge/1.0"

    def do_POST(self):                                  # noqa: N802 (stdlib API)
        if self.path != "/command":
            return self._send_json(404, {"error": "not found: use POST /command"})
        # P0-1: bearer-token auth comes BEFORE the Origin guard — a browser
        # page (sandboxed iframe Origin:null, DNS-rebinding) cannot know the
        # token and is stopped here with 401, whatever Origin it carries.
        who = str(self.client_address[0]) if self.client_address else ""
        if not check_auth(self.headers.get("Authorization")):
            audit("unauthorized http", who, detail=self.path)
            return self._send_json(401, {
                "error": "unauthorized: missing or invalid bearer token"})
        # CSRF/Origin guard, before the body is parsed: browsers attach an
        # "Origin" header to page-originated POSTs; reject any origin outside
        # ALLOWED_ORIGINS. Absent Origin (native scripts/curl) is allowed.
        origin = self.headers.get("Origin")
        if origin is not None and origin not in ALLOWED_ORIGINS:
            return self._send_json(403, {"error": "cross-origin POST blocked"})
        length = self.headers.get("Content-Length")
        try:
            length = int(length) if length else 0
        except ValueError:
            return self._send_json(200, {"status": "error", "error": "bad Content-Length"})
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return self._send_json(200, {"status": "error", "error": "invalid JSON body"})
        try:
            status, body = BRIDGE.dispatch(payload, who=who)
        except Exception as exc:                        # noqa: BLE001
            log.exception("dispatch failed")
            status, body = 200, {"status": "error", "error": f"internal error: {exc}"}
        self._send_json(status, body)

    def do_GET(self):                                   # noqa: N802
        if self.path == "/config":
            # P0-2: the extension bootstraps the shared token here (its
            # <all_urls> host permission lets it read the cross-origin body).
            # A hostile web page cannot: no Access-Control-Allow-Origin is
            # sent, so CORS keeps the response unreadable to page JS.
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


# ---------------------------------------------------------------------------

def main() -> None:
    global AUTH_REQUIRED, AUTH_TOKEN, AUDIT_PATH, CDP_ALLOWLIST, HUMANIZE
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s")
    # P0-4: CLI switches — auth is ON by default; opt out explicitly.
    parser = argparse.ArgumentParser(
        prog="webflow_bridge",
        description="Webflow Bridge daemon — local HTTP(:10086) + WS(:10087) "
                    "bridge to the Chrome 'Webflow Bridge' MV3 extension.")
    parser.add_argument("--allow-no-auth", action="store_true",
                        help="disable bearer-token auth (INSECURE — migration "
                             "only for old local scripts)")
    parser.add_argument("--audit", metavar="PATH",
                        help="append JSONL audit lines {ts,action,who,detail} "
                             "to PATH (info-logging is always on)")
    parser.add_argument("--cdp-allowlist", metavar="METHODS",
                        help="comma-separated CDP methods the cdp action may "
                             "call; 'Domain.*' allows a whole domain "
                             "(default: unrestricted passthrough)")
    parser.add_argument("--humanize", action="store_true",
                        help="human-like pacing for browser actions "
                             "(random delays/jitter/scroll micro-moves)")
    opts = parser.parse_args()
    if opts.allow_no_auth:
        AUTH_REQUIRED = False
    if opts.audit:
        AUDIT_PATH = opts.audit
    if opts.cdp_allowlist:
        CDP_ALLOWLIST = [s.strip() for s in opts.cdp_allowlist.split(",")
                         if s.strip()]
    if opts.humanize:
        HUMANIZE = True
    AUTH_TOKEN = load_auth_token()          # P0-1/P0-3: shared-secret source
    try:
        BRIDGE.start_ws_server()
        httpd = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), CommandHandler)
    except OSError as exc:
        print(f"[web-flow] FATAL: cannot bind ports — {exc}\n"
              "  Is another Webflow Bridge already running?")
        raise SystemExit(1) from exc
    httpd.daemon_threads = True

    print()
    print("=" * 65)
    print("  Webflow Bridge daemon started")
    print(f"    HTTP  : http://{HTTP_HOST}:{HTTP_PORT}    POST /command")
    print("            (existing publish scripts post here, unchanged)")
    print(f"    WS    : ws://{WS_HOST}:{WS_PORT}          Chrome extension connects here")
    if AUTH_TOKEN is None:
        print("  AUTH  : DISABLED (--allow-no-auth) — no bearer token required")
    elif os.environ.get("WBF_TOKEN"):
        print("  AUTH  : bearer token required (WBF_TOKEN env var)")
    else:
        print(f"  AUTH  : bearer token required — file: "
              f"{os.environ.get('WBF_TOKEN_FILE') or DEFAULT_TOKEN_PATH}")
        print("          (0600; the token value is never printed to the terminal)")
    if AUDIT_PATH:
        print(f"  AUDIT : JSONL -> {AUDIT_PATH}")
    if CDP_ALLOWLIST is not None:
        print("  CDP   : allowlist -> " + " ".join(CDP_ALLOWLIST))
    if HUMANIZE:
        print("  MODE  : humanize pacing ON (daemon-wide)")
    print("  Load the 'Webflow Bridge' extension:")
    print("    chrome://extensions  ->  Developer mode  ->  Load unpacked  ->  extension/")
    print("  Then evaluate:  curl -X POST http://127.0.0.1:10086/command \\")
    print("    -H 'Content-Type: application/json' \\")
    print("    -d '{\"action\":\"evaluate\",\"args\":{\"code\":\"(() => document.title)()\"},\"session\":\"default\"}'")
    print("  Ctrl+C to stop.")
    print("=" * 65)
    print(flush=True)

    threading.Thread(target=BRIDGE.ws_accept_loop, daemon=True,
                     name="ws-accept").start()
    threading.Thread(target=BRIDGE.ws_keepalive_loop, daemon=True,
                     name="ws-keepalive").start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[web-flow] shutting down ...")
    finally:
        httpd.server_close()
        BRIDGE.close()
    log.info("stopped")


if __name__ == "__main__":
    main()
