# MCP server for Webflow Bridge

A thin **Model Context Protocol (MCP)** server that turns the local Webflow
Bridge daemon into five standard MCP tools. Any MCP-capable agent — Hermes
Agent's native-mcp, Claude Code, Codex, Kimi, Claude Desktop, Cursor, VS Code
Copilot, etc. — can then drive your real Chrome/Edge through Webflow Bridge
with **zero bespoke integration**: no custom skills, no per-agent glue, no
direct HTTP calls from the agent.

```
┌────────────────────────────┐   stdio JSON-RPC   ┌─────────────────────────┐
│ MCP client (any agent —    │  <──────────────>  │ mcp/mcp_server.py       │
│ Hermes native-mcp, Claude  │  tools/list,       │ FastMCP server           │
│ Desktop, Cursor, ...)      │  tools/call        │ .venv (mcp>=1.2,<2)      │
└────────────────────────────┘                    └───────────┬─────────────┘
                                                   POST /command │ urllib
                                                 http://127.0.0.1:10086
                                                               ▼
                                              Webflow Bridge daemon + Chrome
                                              extension (existing project)
```

- The server lives in `mcp/` with its **own venv** (`mcp/.venv`) because the
  official `mcp` package is not installed in the shared uv python.
- `mcp` is pinned to the **1.x line** (`mcp>=1.2,<2`): mcp 2.x removed
  `mcp.server.fastmcp.FastMCP` (renamed to `MCPServer`), and this server is
  written against the FastMCP API the spec calls for.
- Transport is **stdio** (the MCP default) — no ports, no tokens, no cloud.
- Each `wf_*` tool POSTs the matching daemon action (`session: "default"`) and
  returns a compact string. Tools **never raise**: failures come back as
  `ERROR: ...` text inside the tool result, which is how MCP servers are
  supposed to behave.
- Feasibility is verified end-to-end: `tools/mcp_smoke.py` connects with the
  **official `mcp` Python SDK** over stdio (the same library Hermes Agent's
  native-mcp client is built on), lists the tools and round-trips
  `wf_tabs_list` / `wf_evaluate` against the live daemon (see Setup below).

## Tools

| Tool | Description |
|---|---|
| `wf_evaluate(code: str, tabId?: int)` | Evaluate JavaScript in a page (default active tab). Returns the JSON result or an error string. |
| `wf_cdp(method: str, params?: dict, tabId?: int)` | Send an arbitrary CDP command (e.g. `Input.insertText`, `Page.captureScreenshot`). |
| `wf_navigate(url: str, tabId?: int)` | Navigate a tab (default active) to a URL. |
| `wf_tabs_list()` | List open tabs: `[{id, url, title, active}]`. |
| `wf_tabs_activate(tabId?: int)` | Activate a tab (default active). |

**Every tool result is a plain string.** On success it is the JSON value of
the daemon's `data.value` (`json.dumps(..., ensure_ascii=False)` — an array,
object, number, etc., rendered as text). On failure it is a text string that
starts with `ERROR: `, e.g. `ERROR: extension not connected` (HTTP 503) or
`ERROR: <urlopen error ... Connection refused>`. Tools never raise — errors
travel inside the result, so the stdio JSON-RPC stream stays clean and any MCP
client always gets a well-formed tool result.

`tabId` is optional everywhere and defaults to the active tab (discover ids
with `wf_tabs_list`). The daemon base URL can be overridden with the
`WEBFLOW_DAEMON` env var; it defaults to `http://127.0.0.1:10086`.

## Setup & feasibility verification

```bash
cd C:/Users/darre/webflow/mcp
uv sync --python 3.11        # creates .venv with mcp>=1.2,<2 (FastMCP 1.x API)
```

Verify the daemon is up with an extension connected (see the repo README), then
run the feasibility smoke harness from the repo root:

```bash
mcp/.venv/Scripts/python.exe tools/mcp_smoke.py      # Windows
mcp/.venv/bin/python tools/mcp_smoke.py              # macOS/Linux
```

It connects with the **official `mcp` Python client** (the same library Hermes
Agent's native-mcp client uses), lists the tools and calls `wf_tabs_list` /
`wf_evaluate` against the live daemon. Exit 0 = feasibility PASS.

## Launch-command building blocks

Every client registration below wraps **one of two identical spawn blocks** in
its own config format (YAML / JSON / TOML). Both run the same
`mcp_server.py` stdio server; pick by what is available at the *agent's*
runtime, not what you used at setup time.

**Block A — uv form (recommended).** `uv run` resolves the `mcp/` project and
checks its environment on every spawn, so it works from a bare `uv` on PATH
with no venv bookkeeping:

```text
command: "uv"
args: ["run", "--project", "<PROJECT>/mcp", "mcp_server.py"]
```

**Block B — venv-python form.** When `uv` is *not* on the client's PATH but
the venv exists (created once by `uv sync`), point `command` straight at the
venv interpreter — zero tooling dependency, instant spawn:

```text
Windows:     command: "<PROJECT>/mcp/.venv/Scripts/python.exe"
macOS/Linux: command: "<PROJECT>/mcp/.venv/bin/python"
             args: ["<PROJECT>/mcp/mcp_server.py"]
```

In every snippet below, **`<PROJECT>` is the repo root** — on the machine this
guide was written on, `C:/Users/darre/webflow` (Windows). Substitute your own
clone path on any OS. The forward-slash form (`<PROJECT>/mcp`) is valid in
JSON, YAML and TOML on Windows too (see the adaptability matrix below).

**Prerequisite for every client**: the Webflow Bridge daemon is running on
`127.0.0.1:10086` with a Chrome/Edge extension connected (see the repo
README). The MCP server only adds a stdio front-end onto that loopback
connection — no daemon, no tools that do anything useful.

## Per-agent registration

### Hermes Agent (native-mcp)

Add a `mcp_servers` entry to `~/.hermes/config.yaml` (create the key if it is
not there yet):

```yaml
mcp_servers:
  webflow:
    command: uv
    args:
      - run
      - --project
      - <PROJECT>/mcp
      - mcp_server.py
```

(An inline map works too: `mcp_servers.webflow: {command: "uv", args: ["run", "--project", "<PROJECT>/mcp", "mcp_server.py"]}`.)

Notes:

- **Restart Hermes** after editing the config — servers are spawned at startup.
- Tool names appear namespaced: `mcp_webflow_wf_evaluate`, `mcp_webflow_wf_cdp`,
  `mcp_webflow_wf_navigate`, `mcp_webflow_wf_tabs_list`,
  `mcp_webflow_wf_tabs_activate`.
- Paths: the examples use forward slashes (`<PROJECT>/mcp`), which work fine in
  YAML on Windows. If you prefer backslashes they must be escaped in YAML, e.g.
  `C:\\Users\\darre\\webflow\\mcp`. Forward slashes avoid the whole class of
  escaping bugs — prefer them.
- If `uv` is not on the PATH Hermes spawns with, use Block B
  (`<PROJECT>/mcp/.venv/Scripts/python.exe` on Windows,
  `<PROJECT>/mcp/.venv/bin/python` on macOS/Linux) with
  `args: ["<PROJECT>/mcp/mcp_server.py"]`.
- Hermes launches the server with a **filtered environment** (most env vars are
  stripped) — that is fine here: the server needs no secrets, only loopback
  network to `127.0.0.1:10086`.

### Claude Code

Register with the CLI (stdio is the default transport — no `--transport`
flag needed):

```bash
claude mcp add webflow -- uv run --project <PROJECT>/mcp mcp_server.py
```

- Defaults to **user scope**: the entry is written to `~/.claude.json`.
- Add `--scope project` to write a **project-scope** `.mcp.json` into the repo
  instead (shared via version control; the file is
  `{ "mcpServers": { ... } }` at the top level).

Manual JSON — paste into `~/.claude.json` (under its top-level `mcpServers`
object) or into `.mcp.json` in the repo:

```json
{
  "mcpServers": {
    "webflow": {
      "command": "uv",
      "args": ["run", "--project", "<PROJECT>/mcp", "mcp_server.py"]
    }
  }
}
```

- **stdio is implicit when `"command"` is present — omit `"type"`.** (Some
  templates add `"type": "stdio"`, but the field is only needed for non-stdio
  transports and is ignored/unknown in most clients.)
- Verify with `claude mcp list` (entry `webflow` present). The tools appear as
  `wf_evaluate`, `wf_cdp`, `wf_navigate`, `wf_tabs_list`, `wf_tabs_activate`
  (no Hermes-style `mcp_webflow_` prefix here).
- A project-scope server stays **pending until you approve it** in a session —
  accept it (e.g. via `/mcp`), then retry.

### OpenAI Codex CLI

Register with the CLI:

```bash
codex mcp add webflow -- uv run --project <PROJECT>/mcp mcp_server.py
```

This writes `~/.codex/config.toml`. Manual TOML — same thing:

```toml
[mcp_servers.webflow]
command = "uv"
args = ["run", "--project", "<PROJECT>/mcp", "mcp_server.py"]
startup_timeout_sec = 30
```

WARNINGS:

- Codex's config is **TOML, not JSON** — do not paste a JSON block into
  `config.toml`.
- The table key is **`mcp_servers` (underscore)** at top level, *not*
  `mcp.servers`. A wrong key is **silently ignored** — no error, no tools.
- Codex's default server-startup budget is short (~10 s); `uv run` can need a
  few seconds to boot, so set `startup_timeout_sec = 30` (already in the
  snippet above).
- If `uv` is not on Codex's PATH, use Block B (venv interpreter) instead.

Verify with `codex mcp list`, or `/mcp` inside the TUI. Tools are named
`wf_evaluate`, `wf_cdp`, `wf_navigate`, `wf_tabs_list`, `wf_tabs_activate`.

### OpenClaw

Register with the CLI (each argument is passed through verbatim):

```bash
openclaw mcp add webflow --command uv --arg run --arg --project --arg <PROJECT>/mcp --arg mcp_server.py
```

Then verify with a **live probe** — it actually connects and lists the tools:

```bash
openclaw mcp doctor webflow --probe
```

Manual config: `~/.openclaw/openclaw.json` — a `mcpServers` block with
`{command, args}`:

```json
{
  "mcpServers": {
    "webflow": {
      "command": "uv",
      "args": ["run", "--project", "<PROJECT>/mcp", "mcp_server.py"]
    }
  }
}
```

Restart the OpenClaw gateway after adding/editing (or run
`openclaw mcp reload` if your build supports it) — the gateway caches the
server list.

### Kimi Code

Current `kimi-code` binary (v0.12+): edit `~/.kimi-code/mcp.json` (per-user),
or a **project** `.kimi-code/mcp.json` in the repo — same JSON shape as
Claude Code:

```json
{
  "mcpServers": {
    "webflow": {
      "command": "uv",
      "args": ["run", "--project", "<PROJECT>/mcp", "mcp_server.py"]
    }
  }
}
```

You can also register interactively with `/mcp-config` in the TUI instead of
hand-editing the file.

> **Legacy `kimi-cli` variant.** Older Kimi releases used a different binary
> and layout: registration went through
> `kimi mcp add --transport stdio webflow -- uv run --project <PROJECT>/mcp mcp_server.py`
> and the config lived at `~/.kimi/mcp.json`. If tools never show up, check
> which binary you are on — `kimi-code` reads `~/.kimi-code/mcp.json`,
> `kimi-cli` reads `~/.kimi/mcp.json`, and editing the wrong file changes
> nothing.

### Claude Desktop

Same `mcpServers` block, in the app's desktop config (no `type` key — stdio is
implied by `command`):

```json
{
  "mcpServers": {
    "webflow": {
      "command": "uv",
      "args": ["run", "--project", "<PROJECT>/mcp", "mcp_server.py"]
    }
  }
}
```

File location by OS:

| OS | Path |
|---|---|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

Notes:

- **Restart the app** (fully quit — not just close the window) after editing;
  servers are spawned at startup.
- On macOS/Linux the only change is the `<PROJECT>` path — point it at the
  repo's `mcp/` directory wherever you cloned it. The `.venv` is
  per-machine, so re-run `uv sync` after moving the repo.
- If Claude Desktop can't find `uv` (spawned via a shell without uv on PATH),
  use Block B: `command: "C:/Users/darre/webflow/mcp/.venv/Scripts/python.exe"`
  on Windows / `"<PROJECT>/mcp/.venv/bin/python"` on macOS/Linux, with
  `args: ["<PROJECT>/mcp/mcp_server.py"]`.

### Other JSON-based clients (Cursor / Windsurf / Cline / VS Code Copilot)

One-liner: paste the **same `mcpServers` block** into that tool's MCP config —
the stdio command shape inside is identical:

```json
{
  "mcpServers": {
    "webflow": {
      "command": "uv",
      "args": ["run", "--project", "<PROJECT>/mcp", "mcp_server.py"]
    }
  }
}
```

Where the wrapper goes (per current versions):

- **Cursor** — `mcpServers` in project `.cursor/mcp.json`, or Settings → MCP.
- **Windsurf** — `mcpServers` in its MCP settings (global or workspace).
- **Cline** — `mcpServers` inside its `cline_mcp_settings.json` (the file's
  own key is `mcpServers`; older docs call the setting `cline.mcpServers`).
- **VS Code Copilot** — `mcp.servers` (or a `context_servers` equivalent)
  section in VS Code settings.

Only the **wrapper key name** differs (`mcpServers`,
`cline.mcpServers`, `mcp.servers`, `context_servers`, ...) — the
`command` / `args` pair inside is byte-for-byte the same as everywhere else in
this guide. When a client shows no tools, first check you used its *own* key
name (this is the #1 silent failure mode across JSON clients).

## Execution-environment adaptability matrix

| OS | uv present (recommended) | uv absent, venv exists | Daemon start command |
|---|---|---|---|
| Windows | `command: "uv"`<br>`args: ["run", "--project", "<PROJECT>/mcp", "mcp_server.py"]` | `command: "<PROJECT>/mcp/.venv/Scripts/python.exe"`<br>`args: ["<PROJECT>/mcp/mcp_server.py"]` | with uv: `uv run --python 3.11 daemon/rhino_bridge.py`<br>no uv: `py -3.11 daemon/rhino_bridge.py` |
| macOS | identical uv block | `command: "<PROJECT>/mcp/.venv/bin/python"`<br>`args: ["<PROJECT>/mcp/mcp_server.py"]` | with uv: `uv run --python 3.11 daemon/rhino_bridge.py`<br>no uv: `python3 daemon/rhino_bridge.py` |
| Linux | identical uv block | identical macOS block | identical to macOS |

Notes:

- **The uv block is OS-independent** — the same two strings work on Windows,
  macOS and Linux. Only Block B (venv interpreter) is OS-sensitive: `Scripts/`
  on Windows, `bin/` elsewhere. Daemon start commands run from the **repo
  root** and need Python 3.11+ (on Windows a real interpreter — python.org or
  the `py` launcher — not the Microsoft Store stub).
- **Forward slashes are safe in JSON/YAML/TOML on Windows.** Backslashes in
  JSON must be escaped (`C:\\Users\\...`), which is a standing bug source —
  always use the forward-slash form (`<PROJECT>/mcp`) in config files. Only
  YAML accepts raw backslashes with escaping, and that's still avoidable.
- **No secrets, filtered env is fine.** The MCP server itself needs no API
  keys, tokens or browser binaries; agent clients spawn it with a filtered
  environment and that is fine. The only hard requirements are: loopback
  reachability to `127.0.0.1:10086`, and the Webflow Bridge daemon running
  with an extension connected in Chrome or Edge. The daemon is pure Python
  stdlib — the macOS/Linux run is identical to Windows, no platform-specific
  code or binaries.
- **Timeout guidance.** `uv run` pays a small boot cost (project resolution +
  environment check) on every spawn. Clients with a short startup budget can
  kill the server before uv finishes — Codex defaults to ~10 s. Raise
  `startup_timeout_sec` to `30` (the Codex snippet above already does). Block B
  (venv interpreter) boots in well under a second if your client cannot raise
  its timeout.
- **`<PROJECT>` is your repo root** — `C:/Users/darre/webflow` on the machine
  this guide was written on. The `mcp/.venv` is per-machine: created by
  `uv sync` inside `mcp/`, re-run it after moving the repo.

## Troubleshooting

- **`ERROR: extension not connected`** — the daemon is up but no Chrome/Edge
  extension WebSocket is attached. Start Chrome with the Webflow Bridge
  extension loaded (see repo README); the extension reconnects automatically.
- **Tool times out / connection refused** — the daemon is not running. Start
  it, then retry the tool call (MCP servers need no restart for this).
- **`ERROR: extension not connected` comes back from a tool call** — that
  string is the daemon's HTTP 503 answer: either the daemon is down or no
  browser extension is connected (if the daemon is fully down you instead get
  a connection-refused `ERROR:` from urllib). Either way the fix is the same:
  start the daemon
  (`uv run --python 3.11 daemon/rhino_bridge.py` from the repo root) and keep
  Chrome/Edge open with the Webflow Bridge extension loaded on a normal page.
- **`wf_evaluate` returns an ERROR on the active tab** — the active tab must be
  an **http(s) page** for the debugger to attach; `chrome://`, the Chrome Web
  Store, and some browser-internal pages are not debuggable. Run
  `wf_tabs_list`, pick a normal web page, and target it with
  `wf_evaluate(..., tabId)` or activate it first.
- **`cannot attach debugger ... chrome:// and edge:// URLs`** — same root
  cause, seen as the extension's raw error: the active tab is a
  browser-internal page (`chrome://…`, `edge://…`, Web Store / Edge Add-ons,
  or the new-tab page) and `chrome.debugger` cannot attach there. Open a real
  http(s) site first, or switch to a normal tab with `wf_tabs_list` +
  `wf_tabs_activate(tabId)` and retry.
- **`uv` is not found by the client** — Hermes/Claude Desktop/Codex spawn the
  command through a shell that may not have `uv` on PATH. If so, point
  `command` at the venv interpreter directly instead (Block B):
  `<PROJECT>/mcp/.venv/Scripts/python.exe` on Windows /
  `<PROJECT>/mcp/.venv/bin/python` on macOS/Linux, with
  `args: ["<PROJECT>/mcp/mcp_server.py"]`.
- **Tools don't appear after adding** — per-client gotchas, in order of
  likelihood:
  - *Codex*: the config is TOML and the table key is **`mcp_servers`**
    (underscore). A `mcp.servers` typo is silently ignored. Check with
    `codex mcp list` or `/mcp` in the TUI.
  - *Claude Code*: a project-scope `.mcp.json` server stays **pending** until
    you accept it in a session — approve it via `/mcp`, then the tools load.
  - *OpenClaw*: run `openclaw mcp doctor webflow --probe` — it live-connects
    and lists (or fails with) the tools, which separates a config problem from
    a spawn problem.
  - *Kimi*: check **which binary you are on** — `kimi-code` reads
    `~/.kimi-code/mcp.json`; legacy `kimi-cli` reads `~/.kimi/mcp.json`.
    Editing the wrong file changes nothing.
  - *JSON clients generally*: confirm you used that client's **own wrapper
    key** (`mcpServers` vs `mcp.servers` vs `context_servers` vs
    `cline.mcpServers`) — a wrong key fails silently.
  - *Hermes / Claude Desktop*: servers spawn at startup — **restart the app**
    after editing. Claude Code / Codex / OpenClaw spawn on demand — start a
    new session or refresh `/mcp`.
- **Tools added but every call errors** — check the daemon is up and an
  extension is connected first (rows above); a healthy server exposes tools
  even when the daemon is down (`tools/list` needs no daemon), so *seeing* the
  tools proves nothing about the browser link.
- **Environment**: the server inherits a filtered environment under Hermes and
  needs no secrets — only loopback network to `127.0.0.1`. No API keys, no
  browser binaries.
