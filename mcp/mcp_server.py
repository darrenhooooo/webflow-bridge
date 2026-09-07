"""Webflow Bridge MCP — stdio MCP server bridging the local Webflow Bridge daemon.

Every ``wf_*`` tool POSTs a JSON command to the daemon at
``http://127.0.0.1:10086/command`` (session ``"default"``), parses the reply
and returns a compact human-readable string. The tools NEVER raise: every
failure mode (daemon down, extension missing, evaluate error, ...) comes back
as an ``ERROR: ...`` string inside the tool result, so the stdio JSON-RPC
stream stays clean and MCP clients always get a result.

Run as:  python mcp_server.py        (stdio transport, default)
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

# The MCP server inherits a filtered environment from its host (Hermes strips
# most vars); WEBFLOW_DAEMON is honoured when present and 127.0.0.1:10086 is
# the fallback. It needs no secrets — only network to the local daemon.
DAEMON_BASE = os.environ.get("WEBFLOW_DAEMON", "http://127.0.0.1:10086").rstrip("/")
COMMAND_URL = DAEMON_BASE + "/command"
SESSION = "default"
# The daemon allows up to 120 s per in-flight action (evaluate can be slow);
# give urllib a little headroom so long evaluations are not cut short.
HTTP_TIMEOUT = 125.0

server = FastMCP("Webflow Bridge MCP")


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
        COMMAND_URL, data=body, headers={"Content-Type": "application/json"}
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


@server.tool()
def wf_evaluate(code: str, tabId: int | None = None) -> str:
    """Evaluate JavaScript in a page of the connected browser (default active tab). Returns the JSON result or an error string."""
    return _daemon_call("evaluate", _with_tab({"code": code}, tabId))


@server.tool()
def wf_cdp(method: str, params: dict | None = None, tabId: int | None = None) -> str:
    """Send an arbitrary Chrome DevTools Protocol command to the connected browser tab. E.g. Input.insertText, Page.captureScreenshot."""
    args: dict[str, Any] = {"method": method}
    if params is not None:
        args["params"] = params
    return _daemon_call("cdp", _with_tab(args, tabId))


@server.tool()
def wf_navigate(url: str, tabId: int | None = None) -> str:
    """Navigate a tab (default active) to a URL."""
    return _daemon_call("navigate", _with_tab({"url": url}, tabId))


@server.tool()
def wf_tabs_list() -> str:
    """List open tabs: [{id, url, title, active}]."""
    return _daemon_call("tabs_list")


@server.tool()
def wf_tabs_activate(tabId: int | None = None) -> str:
    """Activate a tab (default active)."""
    return _daemon_call("tabs_activate", _with_tab({}, tabId))


if __name__ == "__main__":
    # FastMCP's __init__ calls configure_logging(INFO), which prints request
    # traces ("Processing request of type ...") to stderr via a root handler.
    # The stderr channel must stay clean for a stdio server (stdout carries
    # the JSON-RPC stream, and any stray output pollutes client logs).
    logging.getLogger("mcp").setLevel(logging.ERROR)
    server.run()
