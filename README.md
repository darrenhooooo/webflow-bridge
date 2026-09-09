# Webflow Bridge

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
  <a href="https://github.com/darrenhooooo/webflow-bridge"><img src="https://img.shields.io/badge/GitHub-darrenhooooo%2Fwebflow-bridge-181717?style=for-the-badge&logo=github&logoColor=white" alt="GitHub: darrenhooooo/webflow-bridge"></a>
  <a href="docs/HTTP_API.md"><img src="https://img.shields.io/badge/Docs-HTTP%20API-FFD700?style=for-the-badge" alt="Docs: HTTP API"></a>
  <!-- TODO: replace # with the live Chrome Web Store listing URL once published -->
  <a href="#"><img src="https://img.shields.io/badge/Chrome%20Web%20Store-Coming%20soon-4285F4?style=for-the-badge&logo=googlechrome&logoColor=white" alt="Chrome Web Store — coming soon"></a>
  <!-- TODO: replace # with the live Firefox AMO listing URL once published -->
  <a href="#"><img src="https://img.shields.io/badge/Firefox%20AMO-Coming%20soon-FF7139?style=for-the-badge&logo=firefox&logoColor=white" alt="Firefox AMO — coming soon"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/Lang-中文-red?style=for-the-badge" alt="中文"></a>
</p>

**A free, local browser-automation bridge that drives YOUR real, already-logged-in Chrome or Edge. No cloud, no accounts, no copied cookies.**

Webflow Bridge is not a cloud browser service, not a cookie jar, and not a second "automation browser" to keep in sync. Your scripts and AI agents POST JSON commands to a small daemon running on your machine, and the daemon drives the very tab you already have open — your session, your cookies, your logins. Everything stays local; nothing ever leaves your device.

**Agent-tool compatible.** Webflow Bridge speaks the standard `POST /command` browser-bridge protocol, so scripts and agent skills already written for browser bridges keep working unchanged — point them at `http://127.0.0.1:10086` and go.

## What it does for you

| Capability | What it solves |
|---|---|
| 🖥️ **Drives the browser you already use** | Runs on your live, logged-in tab — real session, cookies and page state, no phantom browser to keep in sync. |
| 🤖 **Talks to scripts & AI agents** | One `POST /command` protocol; browser-bridge agent skills map over 1:1. |
| 🎯 **30+ browser actions** | Click, type, fill forms, upload/drop files, screenshot, save PDF, read pages, switch tabs, watch network traffic & console logs — and more. |
| 🪟 **Dialogs never stall a run** | alert / confirm / prompt are answered automatically — accept, dismiss, or type an answer. |
| 📎 **Uploads without the OS dialog** | Point at an upload button, hand it a local file path — the system "Open File" window never appears. |
| 🔓 **Works on locked-down sites** | Runs your JS even where the page forbids its own scripts — x.com and friends included. |
| 🔒 **Private by design** | Everything stays on your machine. No cloud, no accounts, no telemetry, nothing leaves the device. |
| 🧩 **One extension, two browsers** | The same `extension/` folder loads in Chrome and Edge; Firefox has its own separate edition (see [ff/README.md](ff/README.md)). |

## Typical uses

- **Publish automation** — post to X / LinkedIn / Facebook / blogs with your real accounts, exactly as you would by hand.
- **Scraping & monitoring** — read pages you can already access, click through pagination, watch network traffic and console logs.
- **End-to-end testing** — run real flows against a real browser session (DevTools open or not).
- **RPA glue** — any "I wish a script could click this for me" task on sites that fight plain HTTP.

It drives **one tab at a time** and never steals your cursor or focus — you can keep using other tabs, other browsers, or any other app while it works.

---

## Quick Install

You need: **Python 3.11+** and Chrome or Edge. Everything runs locally — no account, no cloud, no API key.

### Chrome & Edge — macOS / Windows

**1. Start the daemon** (from the repo root — one command):

```bash
# macOS / Linux (or Git Bash on Windows)
python3 daemon/webflow_bridge.py
```

```powershell
# Windows (native — use a real Python 3.11+, not the Microsoft Store stub)
py -3.11 daemon/webflow_bridge.py
```

On any OS with [uv](https://astral.sh/uv/): `uv run --python 3.11 daemon/webflow_bridge.py`

First start creates a random shared-secret token at `~/.webflow_bridge/token` and enables auth. The extension bootstraps the token automatically; your own scripts must send `Authorization: Bearer <token>` on every POST (or export `WBF_TOKEN`). `--allow-no-auth` exists only as a local migration window.

You should see the startup banner with both listening ports:

```
========================================
  Webflow Bridge daemon started
    HTTP  : http://127.0.0.1:10086    POST /command
    WS    : ws://127.0.0.1:10087          Chrome extension connects here
========================================
```

**2. Load the extension** — once, ~30 seconds, manual by design (nothing is ever auto-installed):

1. Open `chrome://extensions` (Chrome) or `edge://extensions` (Edge).
2. Turn on **Developer mode** (top-right toggle, identical in both browsers).
3. **Load unpacked** → select the `extension/` folder (the same folder for Chrome and Edge).
4. Pin "Webflow Bridge", and keep a normal website in the **active tab** — `chrome://` pages, the Web Store / Edge Add-ons store and new-tab pages cannot be debugged.
5. After editing `manifest.json` or `background.js`, reload the extension — unpacked extensions don't hot-apply changes.

**3. Verify with one command** — it should return your active tab's title:

```bash
# macOS / Linux
export WBF_TOKEN="$(cat ~/.webflow_bridge/token)"
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"evaluate","args":{"code":"(() => document.title)()"},"session":"default"}'
```

```powershell
# Windows (PowerShell)
$env:WBF_TOKEN = (Get-Content "$HOME\.webflow_bridge\token" -Raw).Trim()
curl.exe -s -X POST http://127.0.0.1:10086/command -H "Content-Type: application/json" -H "Authorization: Bearer $env:WBF_TOKEN" -d '{"action":"evaluate","args":{"code":"(() => document.title)()"},"session":"default"}'
```

Expected: `{"status": "ok", "data": {"value": "<your tab title>"}}`

**4. (Optional) smoke test** — prints PASS/FAIL per check, non-zero exit on failure:

```bash
python3 daemon/smoke.py          # Windows: py -3.11 daemon/smoke.py
```

### Firefox (separate edition)

Firefox runs through its own daemon on `:10096` over WebDriver BiDi — the core driver needs **no extension installed**, and it drives your real daily Firefox profile. Same action surface, same `POST /command` shape; point scripts at `http://127.0.0.1:10096`:

```bash
# Windows
ff\ff-launch.bat
py -3.11 ff/daemon/ff_bridge.py

# macOS
chmod +x ff/ff-launch.sh && ff/ff-launch.sh
python3 ff/daemon/ff_bridge.py
```

Full guide (launcher, auth, action matrix, known limits): **[ff/README.md](ff/README.md)**.

## Drive it from your own code — no SDK

The curl above *is* the whole protocol. Here is the same call from a plain Python script (stdlib only) — this is the shape your existing publish scripts already use:

```python
import json, os, urllib.request

token = open(os.path.expanduser("~/.webflow_bridge/token")).read().strip()

def command(action, **args):
    req = urllib.request.Request(
        "http://127.0.0.1:10086/command",
        data=json.dumps({"action": action, "args": args,
                         "session": "default"}).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + token})
    return json.load(urllib.request.urlopen(req))

print(command("evaluate", code="(() => document.title)()")["data"]["value"])
```

Run it with the daemon up and a website in the active tab — it prints that tab's title. Anything that speaks `POST /command` works the same way: curl, Python, Node, or an AI agent with a browser-bridge tool. A complete zero-SDK walkthrough (5 steps against a real page) lives in [docs/HTTP_API.md](docs/HTTP_API.md).

## Common issues (at a glance)

- **`503 {"error":"extension not connected"}`** — Chrome/Edge isn't running with the extension loaded. Start the browser, then check the "Webflow Bridge" popup shows *Daemon: connected*.
- **"chrome:// … cannot be debugged"** — the active tab must be a normal http(s) page; `chrome://`, the stores and new-tab pages are off-limits.
- **"Another debugger is already attached"** — DevTools (or another CDP client) is open on that tab. Close it and retry.
- **Port already in use** — another Webflow Bridge instance is running; stop it first.
- **Errors mention "Content Security Policy"** — you're on a stale, content-script-era build. Fully reload the extension at `chrome://extensions`; current builds run through the debugging channel, which page CSP cannot block.

The full troubleshooting table is at the bottom of this file.

## Documentation

| Doc | What's inside |
|---|---|
| [docs/HTTP_API.md](docs/HTTP_API.md) | The `POST /command` contract — every core action with one curl each, error shapes, a complete zero-SDK demo flow. |
| [docs/PRIVACY.md](docs/PRIVACY.md) | Plain-English privacy policy (what the extension does, data, permissions). |
| [docs/STORE_LISTING.md](docs/STORE_LISTING.md) | Chrome Web Store submission kit — name, summary, description, permission justifications. |
| [CHANGELOG.md](CHANGELOG.md) | Release history. |
| [docs/VERSIONING.md](docs/VERSIONING.md) | Versioning policy and bump checklist. |
| [ff/README.md](ff/README.md) | Firefox edition — install, action matrix, platform status, known limits. |

## Supported platforms

| Browser | Status | How |
|---|---|---|
| Chrome — macOS & Windows | ✅ | `extension/` loaded unpacked; `chrome.debugger` |
| Microsoft Edge — macOS & Windows | ✅ | same `extension/` folder |
| Firefox | ✅ separate edition | WebDriver BiDi on `:10096` — [ff/README.md](ff/README.md) |
| Safari | ❌ not supported | — |

Honest limits: it drives **one tab at a time** and never steals your cursor or focus; `chrome://`-type pages, the stores and new-tab pages can't be debugged; on the Firefox edition `navigator.webdriver === true` cannot be turned off (it's designed to drive your own logged-in sites, not to fight anti-bot systems).

## Privacy & constraints

- **All local.** The daemon runs on your machine; commands and results never leave the device. No cloud, no accounts, no telemetry — see [docs/PRIVACY.md](docs/PRIVACY.md).
- **Loopback only.** The daemon binds to `127.0.0.1` — nothing is exposed to your network or to other machines.
- **Manual install only.** The extension is loaded by you (Developer mode → Load unpacked), never auto-installed; no browser profile is touched, copied or rewritten. The Firefox edition drives your real daily profile too.
- **No third-party deps.** The daemon is pure Python stdlib.
- **MIT licensed** — free to use, modify and embed.

## Troubleshooting (full)

| Symptom | Fix |
|---|---|
| `503 {"error":"extension not connected"}` | Chrome/Edge open? Extension loaded (`chrome://extensions` / `edge://extensions`)? Check the background worker's console for "connected to daemon". |
| evaluate replies "no active tab found" or "chrome:// … cannot be debugged" | The active tab is `chrome://…`, a new-tab page or a store page — none can be debugged. Open a real website in the active tab and retry. |
| evaluate fails with "Another debugger is already attached" | DevTools (or another CDP client) is attached to that tab. Close it and retry. |
| evaluate error mentions "Content Security Policy" | Stale content-script-era build. Fully reload "Webflow Bridge" at `chrome://extensions` (or `edge://extensions`) — current builds evaluate through the debugger channel, which neither page CSP nor the extension CSP can block. |
| Timeout after 120 s | The active tab is busy (modal dialog / blocked script) or the async snippet never resolved — CDP awaits Promise completion values. |
| Port already in use | Another Webflow Bridge instance is running — stop it first. |
| Extension lost connection after a daemon restart | Automatic: reconnects with backoff (up to 30 s); the debugger session re-attaches on the next evaluate — nothing to do. |
| A JS dialog appeared but `handle_dialog` says "no dialog" | Old extension build (Page domain not enabled on attach). Reload the extension at `chrome://extensions`. |
| Clicking an upload button opens the OS "Open File" dialog | Old build without file-chooser interception. Reload the extension, then call `handle_file_chooser` after the click. |

## License & support

Webflow Bridge is **free and open source (MIT)** — see [LICENSE](LICENSE). If it saves you time:

- ⭐ Star — [github.com/darrenhooooo/webflow-bridge](https://github.com/darrenhooooo/webflow-bridge)
- 🐛 Report bugs / request features — [Issues](https://github.com/darrenhooooo/webflow-bridge/issues)
- 📦 Releases — [v1.1.0](https://github.com/darrenhooooo/webflow-bridge/releases)
- ✉️ Contact — darren.hou@outlook.com
