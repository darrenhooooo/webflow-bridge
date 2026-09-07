#!/usr/bin/env python3
"""
web-flow daemon — protocol-compatible Kimi WebBridge replacement.

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

Agent-tool actions (OFFICIAL Kimi WebBridge-compatible tool names — the
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

Origin guard: POSTs carrying an "Origin" header that is not in
{"http://127.0.0.1:10086", "http://localhost:10086", "null"} are rejected
with 403 {"error": "cross-origin POST blocked"} — a CSRF guard for
browser-originated requests. Native scripts/curl send no Origin header and
are unaffected; the WebSocket handshake path is not subject to the guard.

The WebSocket server is a minimal hand-rolled RFC 6455 server (no third-party
deps). Server frames are unmasked; client (browser) frames are masked.
"""
from __future__ import annotations

import base64
import concurrent.futures
import hashlib
import itertools
import json
import logging
import socket
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTTP_HOST = "127.0.0.1"
HTTP_PORT = 10086
WS_HOST = "127.0.0.1"
WS_PORT = 10087

# Origins a browser page may POST from (CSRF guard for browser-originated
# requests; see do_POST). Native scripts/curl send no "Origin" header and are
# always allowed. "null" covers sandboxed/file-origin pages. The daemon's own
# loopback origin spellings are trusted so a local tool page can POST from
# either. The WebSocket handshake is a separate path, not guarded here.
ALLOWED_ORIGINS = {"http://127.0.0.1:10086", "http://localhost:10086", "null"}

EVAL_TIMEOUT = 120          # seconds an HTTP caller waits for the extension
WS_ACCEPT_KEY = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"   # RFC 6455 GUID
MAX_FRAME = 64 << 20        # sanity cap for a single WS message (64 MiB)

log = logging.getLogger("rhino-bridge")


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
    """Read raw request head of the WS upgrade up to \\r\\n\\r\\n."""
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

    # -------- HTTP command dispatch ----------------------------------------

    def _roundtrip(self, ws_payload: dict):
        """Send a WS request and wait for the matching reply.

        Returns (ok, payload).  On failure payload carries
        {"http": <status>, "error": "..."} so dispatch() can shape the body
        exactly per the contract (503 for a missing extension, otherwise a
        200 {"status":"error",...} response).
        """
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

    def dispatch(self, payload):
        """Handle one POST /command payload -> (http_status, response_dict)."""
        if not isinstance(payload, dict):
            return 200, {"status": "error", "error": "body must be a JSON object"}
        action = payload.get("action")
        args = payload.get("args") or {}
        session = payload.get("session", "default")
        if session != "default":
            return 200, {"status": "error",
                         "error": f"unsupported session {session!r}: only 'default' is served"}

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
            tab_id, err = self._validated_tab_id(args)
            if err:
                return err
            ws_payload = {"id": rid, "action": "snapshot"}
            if max_nodes is not None:
                ws_payload["max"] = max_nodes
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
            status, body = BRIDGE.dispatch(payload)
        except Exception as exc:                        # noqa: BLE001
            log.exception("dispatch failed")
            status, body = 200, {"status": "error", "error": f"internal error: {exc}"}
        self._send_json(status, body)

    def do_GET(self):                                   # noqa: N802
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
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s")
    try:
        BRIDGE.start_ws_server()
        httpd = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), CommandHandler)
    except OSError as exc:
        print(f"[web-flow] FATAL: cannot bind ports — {exc}\n"
              "  Is another web-flow / WebBridge already running?")
        raise SystemExit(1) from exc
    httpd.daemon_threads = True

    print()
    print("=" * 65)
    print("  Webflow Bridge daemon started")
    print(f"    HTTP  : http://{HTTP_HOST}:{HTTP_PORT}    POST /command")
    print("            (existing publish scripts post here, unchanged)")
    print(f"    WS    : ws://{WS_HOST}:{WS_PORT}          Chrome extension connects here")
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
