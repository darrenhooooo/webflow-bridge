"""Webflow Bridge MCP — MCP server bridging the local Webflow Bridge daemon.

Every ``wf_*`` tool POSTs a JSON command to the daemon at
``http://127.0.0.1:10086/command`` (session ``"default"``), parses the reply
and returns a compact human-readable string. The tools NEVER raise: every
failure mode (daemon down, extension missing, evaluate error, ...) comes back
as an ``ERROR: ...`` string inside the tool result, so the stdio JSON-RPC
stream stays clean and MCP clients always get a result.

Transports (one process per transport; run both for dual exposure):
  python mcp_server.py                  stdio (default — Claude/Cursor/Hermes)
  python mcp_server.py --http [--port 8931]   streamable HTTP at
                    http://127.0.0.1:<port>/mcp  (other clients, remote LAN)

Parameter names match the daemon wire protocol exactly (camelCase: tabId,
timeoutMs, promptText, ...) so a tool maps 1:1 onto the HTTP action.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

# The MCP server inherits a filtered environment from its host (Hermes strips
# most vars); WEBFLOW_DAEMON is honoured when present and 127.0.0.1:10086 is
# the fallback. The daemon requires the shared bearer token (P0): it is read
# from $WBF_TOKEN (host may strip it, so the file fallback is primary) or
# ~/.webflow_bridge/token — no other secrets are needed, only network to the
# local daemon.
DAEMON_BASE = os.environ.get("WEBFLOW_DAEMON", "http://127.0.0.1:10086").rstrip("/")
COMMAND_URL = DAEMON_BASE + "/command"
SESSION = "default"
HTTP_TIMEOUT = 125.0        # daemon allows 120 s per action; keep headroom
HTTP_HOST = "127.0.0.1"     # streamable-HTTP bind address (local tool)
HTTP_PORT = 8931


def _auth_headers() -> dict:
    """Bearer-token header for the daemon (empty when auth is off)."""
    token = os.environ.get("WBF_TOKEN")
    if not token:
        path = os.environ.get("WBF_TOKEN_FILE") or os.path.join(
            os.path.expanduser("~"), ".webflow_bridge", "token")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                token = fh.read().strip()
        except OSError:
            token = ""
    return {"Authorization": f"Bearer {token}"} if token else {}

server = FastMCP(
    "Webflow Bridge MCP",
    host=HTTP_HOST,
    port=HTTP_PORT,
    streamable_http_path="/mcp",
)


def _arg_err(msg: str) -> str:
    return "ERROR: " + msg


def _daemon_call(action: str, args: dict[str, Any] | None = None) -> str:
    """POST one daemon action and render the result as a compact string.

    ok    -> json.dumps(data.value, ensure_ascii=False)
    error -> "ERROR: <error>"
    503   -> "ERROR: extension not connected"
    """
    body = json.dumps(
        {"action": action, "args": args or {}, "session": SESSION}
    ).encode("utf-8")
    request = urllib.request.Request(
        COMMAND_URL, data=body,
        headers={"Content-Type": "application/json", **_auth_headers()}
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # urllib.error.HTTPError is a URLError
        if exc.code == 503:
            return "ERROR: extension not connected"
        return f"ERROR: HTTP {exc.code}"
    except Exception as exc:  # connection refused, timeout, non-JSON body, ...
        return f"ERROR: {exc}"

    if not isinstance(payload, dict):
        return f"ERROR: non-object daemon response: {payload!r}"
    if payload.get("status") == "ok":
        data = payload.get("data")
        value = data.get("value") if isinstance(data, dict) else None
        return json.dumps(value, ensure_ascii=False)
    error = payload.get("error") or payload.get("message") or "unknown daemon error"
    return f"ERROR: {error}"


def _with_tab(args: dict[str, Any], tabId: int | None) -> dict[str, Any]:
    """Add an optional tabId to the daemon args (None = active tab)."""
    if tabId is not None:
        args["tabId"] = tabId
    return args


def _b(value: Any) -> bool:
    return bool(value)


# ---------------- core / evaluate ----------------

@server.tool()
def wf_evaluate(code: str, tabId: int | None = None) -> str:
    """Evaluate JavaScript in a page of the connected browser (default active tab). Returns the JSON result or an error string."""
    if not isinstance(code, str) or not code.strip():
        return _arg_err("code (string) is required")
    return _daemon_call("evaluate", _with_tab({"code": code}, tabId))


@server.tool()
def wf_cdp(method: str, params: dict | None = None, tabId: int | None = None) -> str:
    """Send an arbitrary Chrome DevTools Protocol command to the connected browser tab. E.g. Input.insertText, Page.captureScreenshot."""
    if not isinstance(method, str) or not method.strip():
        return _arg_err("method (string) is required")
    args: dict[str, Any] = {"method": method}
    if isinstance(params, dict):
        args["params"] = params
    return _daemon_call("cdp", _with_tab(args, tabId))


@server.tool()
def wf_probe() -> str:
    """Extension health + per-path diagnostic matrix for the active tab (no args)."""
    return _daemon_call("probe")


# ---------------- navigation / tabs ----------------

@server.tool()
def wf_navigate(url: str, newTab: bool = False, group_title: str | None = None,
                tabId: int | None = None) -> str:
    """Navigate a tab (default active) to a URL. newTab=true opens it in a fresh active tab; group_title names a tab group for it."""
    if not isinstance(url, str) or not url.strip():
        return _arg_err("url (string) is required")
    args: dict[str, Any] = {"url": url}
    if _b(newTab):
        args["newTab"] = True
    if isinstance(group_title, str) and group_title.strip():
        args["group_title"] = group_title
    return _daemon_call("navigate", _with_tab(args, tabId))


@server.tool()
def wf_find_tab(url: str, active: bool = False) -> str:
    """Find an open tab whose URL matches url (exact, prefix, substring). active=true activates the match."""
    if not isinstance(url, str) or not url.strip():
        return _arg_err("url (string) is required")
    args: dict[str, Any] = {"url": url}
    if _b(active):
        args["active"] = True
    return _daemon_call("find_tab", args)


@server.tool()
def wf_tabs_list() -> str:
    """List open tabs: [{id, url, title, active}]. Pick a tabId from here for the other tools."""
    return _daemon_call("tabs_list")


@server.tool()
def wf_tabs_open(url: str) -> str:
    """Open a URL in a new tab (http/https); it becomes active. Returns {id, url}."""
    if not isinstance(url, str) or not url.strip():
        return _arg_err("url (string) is required")
    return _daemon_call("tabs_open", {"url": url})


@server.tool()
def wf_tabs_activate(tabId: int | None = None) -> str:
    """Activate a tab (default active)."""
    return _daemon_call("tabs_activate", _with_tab({}, tabId))


@server.tool()
def wf_tabs_close(tabId: int | None = None) -> str:
    """Close a tab (default active)."""
    return _daemon_call("tabs_close", _with_tab({}, tabId))


@server.tool()
def wf_tabs_close_all_but(tabId: int | None = None) -> str:
    """Close every tab in tabId's window (default active tab) except that tab."""
    return _daemon_call("tabs_close_all_but", _with_tab({}, tabId))


# ---------------- perception ----------------

@server.tool()
def wf_snapshot(max: int | None = None, start: int | None = None,
                tabId: int | None = None) -> str:
    """Accessibility-like snapshot of a tab: nodes [{ref:'@eN', tag, role, name, text, path}]. max=page size (default 400); start pages forward (total + refs are full-list indices, refs stay valid across pages until DOM changes). Use the @eN refs with click/fill/upload/screenshot."""
    args: dict[str, Any] = {}
    if isinstance(max, int) and max > 0:
        args["max"] = max
    if isinstance(start, int) and start > 0:
        args["start"] = start
    return _daemon_call("snapshot", _with_tab(args, tabId))


# ---------------- interaction ----------------

@server.tool()
def wf_click(selector: str, tabId: int | None = None) -> str:
    """Click an element by CSS selector or a snapshot '@eN' ref on the same tab."""
    if not isinstance(selector, str) or not selector.strip():
        return _arg_err("selector (CSS | @eN) is required")
    return _daemon_call("click", _with_tab({"selector": selector}, tabId))


@server.tool()
def wf_fill(selector: str, value: str, mode: str | None = None,
            tabId: int | None = None) -> str:
    """Fill a form control (CSS or @eN). mode auto/value for input/textarea/select, 'contenteditable' for editors (CDP insertText). React-safe native setter."""
    if not isinstance(selector, str) or not selector.strip():
        return _arg_err("selector (CSS | @eN) is required")
    if not isinstance(value, str):
        return _arg_err("value (string) is required")
    args: dict[str, Any] = {"selector": selector, "value": value}
    if isinstance(mode, str) and mode in ("auto", "value", "contenteditable"):
        args["mode"] = mode
    return _daemon_call("fill", _with_tab(args, tabId))


@server.tool()
def wf_fill_form(fields: list, tabId: int | None = None) -> str:
    """Fill several value-type controls (input/textarea/select) in ONE page pass. fields=[{selector:'CSS|@eN', value:'...'}, ...]. contenteditable fields are reported as errors — fill those with wf_fill mode contenteditable."""
    if not isinstance(fields, list) or not fields:
        return _arg_err("fields (non-empty array of {selector, value}) is required")
    return _daemon_call("fill_form", _with_tab({"fields": fields}, tabId))


@server.tool()
def wf_submit(selector: str, tabId: int | None = None) -> str:
    """Submit the form around selector (form / control / submit button) via requestSubmit (falls back to click)."""
    if not isinstance(selector, str) or not selector.strip():
        return _arg_err("selector (CSS | @eN) is required")
    return _daemon_call("submit", _with_tab({"selector": selector}, tabId))


@server.tool()
def wf_wait_for(selector: str | None = None, text: str | None = None,
                timeoutMs: int | None = None, intervalMs: int | None = None,
                tabId: int | None = None) -> str:
    """Wait until a selector (CSS | @eN) becomes visible and/or page text appears. selector and/or text required; timeoutMs default 10000, max 90000. Returns {found, elapsedMs}."""
    args: dict[str, Any] = {}
    if isinstance(selector, str) and selector.strip():
        args["selector"] = selector
    if isinstance(text, str) and text.strip():
        args["text"] = text
    if not args:
        return _arg_err("selector and/or text is required")
    if isinstance(timeoutMs, int) and timeoutMs > 0:
        args["timeoutMs"] = timeoutMs
    if isinstance(intervalMs, int) and intervalMs > 0:
        args["intervalMs"] = intervalMs
    return _daemon_call("wait_for", _with_tab(args, tabId))


@server.tool()
def wf_handle_dialog(accept: bool = True, promptText: str | None = None,
                     tabId: int | None = None) -> str:
    """Accept (default) or dismiss the JavaScript dialog (alert/confirm/prompt) currently showing. promptText answers a prompt()."""
    args: dict[str, Any] = {}
    if not _b(accept):
        args["accept"] = False
    if isinstance(promptText, str):
        args["promptText"] = promptText
    return _daemon_call("handle_dialog", _with_tab(args, tabId))


@server.tool()
def wf_drop(selector: str, file: str | None = None, files: list | None = None,
            tabId: int | None = None) -> str:
    """Drag local file(s) onto a drop zone (CSS | @eN). file = one absolute path, files = several. The daemon reads them and dispatches real DataTransfer drop events. Max 32 MiB per file."""
    if not isinstance(selector, str) or not selector.strip():
        return _arg_err("selector (drop-zone CSS | @eN) is required")
    args: dict[str, Any] = {"selector": selector}
    if isinstance(file, str) and file.strip():
        args["file"] = file
    elif isinstance(files, list) and files:
        args["files"] = [f for f in files if isinstance(f, str) and f.strip()]
    else:
        return _arg_err("file (single path) or files (array of paths) is required")
    return _daemon_call("drop", _with_tab(args, tabId))


@server.tool()
def wf_send_key(key: str, modifiers: list | None = None, selector: str | None = None,
                tabId: int | None = None) -> str:
    """Press a key: Enter/Tab/Escape/Backspace/Delete/Arrow*/Home/End/Page*/Space or a-z/0-9. modifiers=['ctrl','shift','alt','meta']. Optional selector is focused first."""
    if not isinstance(key, str) or not key:
        return _arg_err("key is required")
    args: dict[str, Any] = {"key": key}
    if isinstance(modifiers, list):
        args["modifiers"] = modifiers
    if isinstance(selector, str) and selector.strip():
        args["selector"] = selector
    return _daemon_call("send_key", _with_tab(args, tabId))


@server.tool()
def wf_type_text(text: str, selector: str | None = None,
                 tabId: int | None = None) -> str:
    """Type text at the caret (CDP insertText — reliable for CJK/emoji/long text). Optional selector is focused first."""
    if not isinstance(text, str):
        return _arg_err("text (string) is required")
    args: dict[str, Any] = {"text": text}
    if isinstance(selector, str) and selector.strip():
        args["selector"] = selector
    return _daemon_call("type_text", _with_tab(args, tabId))


@server.tool()
def wf_mouse_click(x: int | None = None, y: int | None = None,
                   selector: str | None = None, tabId: int | None = None) -> str:
    """Click the left button at viewport pixels (x/y) or at the element center of a selector (CSS | @eN)."""
    args: dict[str, Any] = {}
    if isinstance(selector, str) and selector.strip():
        args["selector"] = selector
    elif isinstance(x, int) and isinstance(y, int):
        args["x"] = x
        args["y"] = y
    else:
        return _arg_err("x/y (integers) or selector is required")
    return _daemon_call("mouse_click", _with_tab(args, tabId))


@server.tool()
def wf_resize_page(width: int, height: int, tabId: int | None = None) -> str:
    """Resize the page viewport (Emulation.setDeviceMetricsOverride). Call again with the real size or reload to restore."""
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        return _arg_err("width and height (positive integers) are required")
    return _daemon_call("resize_page",
                        _with_tab({"width": width, "height": height}, tabId))


# ---------------- capture / files ----------------

@server.tool()
def wf_screenshot(format: str | None = None, quality: int | None = None,
                  selector: str | None = None, fullPage: bool = False,
                  tabId: int | None = None) -> str:
    """Capture the tab: viewport, fullPage (whole page), or the element behind selector. Returns JSON {base64, mime, width, height} — the client writes the image file."""
    args: dict[str, Any] = {}
    if isinstance(format, str) and format in ("png", "jpeg"):
        args["format"] = format
    if isinstance(quality, int) and 0 <= quality <= 100:
        args["quality"] = quality
    if isinstance(selector, str) and selector.strip():
        args["selector"] = selector
    if _b(fullPage):
        args["fullPage"] = True
    return _daemon_call("screenshot", _with_tab(args, tabId))


@server.tool()
def wf_upload(selector: str, file: str, tabId: int | None = None) -> str:
    """Put a LOCAL absolute path onto an <input type='file'> (CSS | @eN) — real File, no base64. The browser process reads the path."""
    if not isinstance(selector, str) or not selector.strip():
        return _arg_err("selector (CSS | @eN) is required")
    if not isinstance(file, str) or not file.strip():
        return _arg_err("file (absolute path) is required")
    return _daemon_call("upload", _with_tab({"selector": selector, "file": file}, tabId))


@server.tool()
def wf_save_as_pdf() -> str:
    """Print the ACTIVE tab to PDF. Returns {base64, mime:'application/pdf'} — the client writes the file."""
    return _daemon_call("save_as_pdf")


# ---------------- observability ----------------

@server.tool()
def wf_list_network_requests(limit: int | None = None) -> str:
    """List network requests observed on the current debugger tab (newest first): [{requestId, url, method, type, status, mimeType, size, timestamp}]. limit caps the list (max 300)."""
    args: dict[str, Any] = {}
    if isinstance(limit, int) and limit > 0:
        args["limit"] = limit
    return _daemon_call("list_network_requests", args)


@server.tool()
def wf_get_network_request(requestId: str) -> str:
    """Get one network request record by requestId (see wf_list_network_requests)."""
    if not isinstance(requestId, str) or not requestId.strip():
        return _arg_err("requestId (string) is required")
    return _daemon_call("get_network_request", {"requestId": requestId})


@server.tool()
def wf_list_console_messages(limit: int | None = None) -> str:
    """List console messages observed on the current debugger tab (newest first): [{type, text, timestamp}]. limit caps the list (max 300)."""
    args: dict[str, Any] = {}
    if isinstance(limit, int) and limit > 0:
        args["limit"] = limit
    return _daemon_call("list_console_messages", args)


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Webflow Bridge MCP server (stdio default, --http for streamable HTTP)")
    parser.add_argument("--http", action="store_true",
                        help="run streamable-HTTP transport instead of stdio")
    parser.add_argument("--port", type=int, default=HTTP_PORT,
                        help=f"streamable-HTTP port (default {HTTP_PORT})")
    args = parser.parse_args(argv)

    if args.http:
        server.port = args.port
        print(f"[webflow-bridge-mcp] streamable HTTP on "
              f"http://{HTTP_HOST}:{args.port}/mcp", file=sys.stderr, flush=True)

    # Keep the stderr channel clean for stdio (stdout carries the JSON-RPC
    # stream; any stray output pollutes client logs).
    logging.getLogger("mcp").setLevel(logging.ERROR)
    server.run(transport="streamable-http" if args.http else "stdio")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
