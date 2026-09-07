"""Feasibility smoke harness: drive the Webflow Bridge MCP server over stdio
with the OFFICIAL mcp Python SDK — the same library Hermes Agent's native-mcp
client is built on — end to end through the real daemon.

Run with the mcp project venv python (this file imports `mcp`, which is NOT
installed in the shared uv python):

    cd C:/Users/darre/webflow
    mcp/.venv/Scripts/python.exe tools/mcp_smoke.py     (Windows)
    mcp/.venv/bin/python tools/mcp_smoke.py             (macOS/Linux)

The harness spawns the MCP server itself with the mcp venv interpreter, so it
inherits our full environment (no Hermes-style env filtering here). The daemon
base URL is read from WEBFLOW_DAEMON (default http://127.0.0.1:10086).

Exit code: 0 = feasibility PASS, 1 = hard protocol failure.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parent.parent
MCP_DIR = REPO_ROOT / "mcp"
DAEMON_BASE = os.environ.get("WEBFLOW_DAEMON", "http://127.0.0.1:10086").rstrip("/")

EXPECTED_TOOLS = [
    "wf_evaluate", "wf_cdp", "wf_probe",
    "wf_navigate", "wf_find_tab", "wf_tabs_list", "wf_tabs_open",
    "wf_tabs_activate", "wf_tabs_close", "wf_tabs_close_all_but",
    "wf_snapshot", "wf_click", "wf_fill", "wf_fill_form", "wf_submit",
    "wf_wait_for", "wf_handle_dialog", "wf_drop", "wf_send_key",
    "wf_type_text", "wf_mouse_click", "wf_resize_page",
    "wf_screenshot", "wf_upload", "wf_save_as_pdf",
    "wf_list_network_requests", "wf_get_network_request",
    "wf_list_console_messages",
]
EVAL_CODE = "(() => ({title: document.title, ok: 1+1}))()"


def _venv_python() -> Path:
    if sys.platform == "win32":
        exe = MCP_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        exe = MCP_DIR / ".venv" / "bin" / "python"
    if not exe.exists():
        raise SystemExit(
            f"venv python not found: {exe}\n"
            f"create it first:  cd {MCP_DIR} && uv sync"
        )
    return exe


def _step(ok: bool, name: str, detail: str = "") -> bool:
    tag = "PASS" if ok else "FAIL"
    line = f"[{tag}] {name}"
    if detail:
        line += f" — {detail}"
    print(line, flush=True)
    return ok


def _result_text(result) -> tuple[str, bool]:
    """Extract plain text + isError flag from a CallToolResult (API-tolerant)."""
    is_error = bool(getattr(result, "isError", False))
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
    text = "".join(parts) or str(result)
    return text, is_error


def _tool_names(list_result) -> list[str]:
    """List tool names from tools/list (API-tolerant across mcp SDK versions)."""
    tools = getattr(list_result, "tools", None)
    if tools is None and isinstance(list_result, (list, tuple)):
        tools = list_result
    return [getattr(t, "name", "") for t in tools or []]


async def main() -> int:
    print(f"Webflow Bridge MCP smoke — daemon base: {DAEMON_BASE}", flush=True)
    print(f"server: {_venv_python()} mcp_server.py", flush=True)

    try:
        # ClientSession initializes automatically on entry.
        params = StdioServerParameters(
            command=str(_venv_python()),
            args=[str(MCP_DIR / "mcp_server.py")],
        )
        try:
            client_ctx = stdio_client(params, read_timeout_seconds=130)
        except TypeError:  # older mcp SDK without read_timeout_seconds
            client_ctx = stdio_client(params)

        async with client_ctx as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                _step(True, "connect + initialize MCP session (stdio)")

                # ---- tools/list -------------------------------------------------
                list_result = await session.list_tools()
                names = _tool_names(list_result)
                missing = [t for t in EXPECTED_TOOLS if t not in names]
                if missing:
                    _step(False, "tools/list exposes the wf_* tool set",
                          f"missing: {missing}; got: {sorted(names)}")
                    return 1
                _step(True, "tools/list exposes the wf_* tool set",
                      f"{len(EXPECTED_TOOLS)} tools: {', '.join(EXPECTED_TOOLS)}")

                # ---- wf_tabs_list (hard gate: protocol round-trip to daemon) ----
                res = await session.call_tool("wf_tabs_list", {})
                text, is_error = _result_text(res)
                tabs_ok = (not is_error and not text.startswith("ERROR:")
                           and ('"url"' in text or '"title"' in text
                                or text.strip().startswith("[")))
                if not tabs_ok:
                    _step(False, "wf_tabs_list round-trip",
                          f"tool returned: {text[:300]}")
                    print("      -> daemon down or extension not connected; "
                          "start the daemon + load the extension, then rerun.",
                          flush=True)
                    return 1
                _step(True, "wf_tabs_list round-trip (daemon live)")
                print(f"      tabs_list -> {text[:400]}", flush=True)

                # ---- wf_evaluate (informational: E2E or expected ERROR) ---------
                res = await session.call_tool("wf_evaluate", {"code": EVAL_CODE})
                text, is_error = _result_text(res)
                if '"ok": 2' in text:
                    _step(True, "wf_evaluate E2E on active tab", text[:300])
                elif text.startswith("ERROR:"):
                    known = "not a debuggable page" in text
                    _step(True, "wf_evaluate round-trip (protocol OK, eval ERROR)",
                          text[:300])
                    print("      -> expected when the active tab is not an "
                          "http(s) page", flush=True)
                    print("      -> (feasibility = MCP round-trip works; "
                          "tabs_list already proved the daemon path)",
                          flush=True)
                else:
                    _step(True, "wf_evaluate returned (unexpected shape)",
                          text[:300])

                print("\nRESULT: MCP feasibility PASS — a third-party MCP client "
                      "drives the Webflow Bridge daemon via standard MCP tool "
                      "calls.", flush=True)
                return 0

    except Exception as exc:  # noqa: BLE001 - connection refused / spawn failure
        _step(False, "MCP round-trip (connection / initialize)", repr(exc))
        print("      -> could not talk to the MCP server. If the daemon is "
              "down, start it (it does NOT need to be up for tools/list).",
              flush=True)
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):  # keep Windows consoles utf-8-safe
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main()))
