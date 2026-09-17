# Driving Webflow Bridge from an agent

This guide is for an AI agent — or the person wiring one up — that should
connect to Webflow Bridge and start using the browser. It assumes the repo is
cloned locally.

## Three steps to connect

1. **Start the daemon.** From the repo root:

   ```bash
   python3 daemon/webflow_bridge.py          # macOS / Linux
   py -3.11 daemon/webflow_bridge.py         # Windows
   ```

   It listens on `http://127.0.0.1:10086`. Full launchd/systemd options are in
   [INSTALL.md](INSTALL.md).

2. **Load the extension (once, by hand).** Open `chrome://extensions` or
   `edge://extensions`, turn on Developer mode → Load unpacked → pick the
   `extension/` folder. Keep a normal http(s) page in the active tab. This is
   the only step a human has to do, and it stays manual until the extension is
   on the browser stores. The Firefox edition is separate — see
   [../ff/README.md](../ff/README.md).

3. **Register MCP, or just POST.** Either register the stdio MCP server
   ([MCP.md](MCP.md)) or call the daemon directly over HTTP. Both reach the
   same daemon; MCP is a convenience wrapper.

## Minimal calls

Auth uses the shared token file at `~/.webflow_bridge/token`; every request
sends it as an `Authorization: Bearer` header. The body always carries
`"session": "default"`.

```bash
export WBF_TOKEN=$(cat ~/.webflow_bridge/token)

# probe — health check, no browser action
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"probe","args":{},"session":"default"}'

# evaluate — run JS in the active tab and get the value back
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"evaluate","args":{"code":"(() => document.title)()"},"session":"default"}'
```

The full action list with one curl each is in [HTTP_API.md](HTTP_API.md).

### MCP registration

The server lives in `mcp/` and speaks stdio. A minimal JSON client entry looks
like this (use the forward-slash path to your clone's `mcp/` directory):

```json
{
  "mcpServers": {
    "webflow": {
      "command": "uv",
      "args": ["run", "--project", "path/to/webflow-bridge/mcp", "mcp_server.py"]
    }
  }
}
```

It exposes `wf_evaluate`, `wf_cdp`, `wf_navigate`, `wf_tabs_list` and
`wf_tabs_activate`. Per-client config keys, the venv-python alternative, and
restart rules are in [MCP.md](MCP.md) — follow that file rather than copying
this snippet.

## Common pitfalls for agents

- **`503 {"error":"extension not connected"}`** — no Chrome/Edge extension is
  attached. Start the browser with the extension loaded; the daemon answers
  503 right away instead of hanging.
- **`403 {"error":"cross-origin POST blocked"}`** — the request carried a
  non-localhost `Origin` header. Plain scripts and curl send none, so do not
  add one.
- **`chrome://` / store / new-tab pages cannot be debugged.** The active tab
  must be a normal http(s) page.
- **"Another debugger is already attached"** — DevTools (or another CDP
  client) holds that tab. Close it and retry.
- **Errors mentioning "Content Security Policy"** mean a stale build — fully
  reload the extension at `chrome://extensions`.
- **MCP tools missing** — check the client's own config key and whether that
  client needs a restart. Hermes and Claude Desktop spawn servers at startup
  (restart the app); Claude Code, Codex and OpenClaw spawn on demand. A
  project-scope `.mcp.json` in Claude Code stays pending until approved.
- **`uv` not found by the client** — point `command` at the venv interpreter
  instead, as described in [MCP.md](MCP.md).

For a machine-readable summary of the product, read `llms.txt` at the repo
root.
