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

**Hand your browser to your AI: everything runs on your machine, and your data never leaves it.**

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
| 🌍 **Speaks 16 languages** | The popup and the intro line follow your browser's language automatically — nothing to configure. Arabic, Chinese (Simplified), Chinese (Traditional), English, French, German, Hindi, Indonesian, Italian, Japanese, Korean, Portuguese, Russian, Spanish, Thai, Vietnamese. |
| ⚡ **One click to connect** | The popup shows **Active** or **Inactive**. When inactive, just click the status card — it dials the daemon for you. If it can't, it names the reason: the daemon isn't running, or another browser already holds it. |
| 🔁 **Always on (macOS)** | Hand the daemon to launchd with one command and it starts at login — no terminal window to keep open. |
| 🔒 **Private by design** | Everything stays on your machine. No cloud, no accounts, no telemetry, nothing leaves the device. |
| 🧩 **One extension, two browsers** | The same `extension/` folder loads in Chrome and Edge; Firefox has its own separate edition (see [ff/README.md](ff/README.md)). |

## Typical uses

- **Publish automation** — post to X / LinkedIn / Facebook / blogs with your real accounts, exactly as you would by hand.
- **Scraping & monitoring** — read pages you can already access, click through pagination, watch network traffic and console logs.
- **End-to-end testing** — run real flows against a real browser session (DevTools open or not).
- **RPA glue** — any "I wish a script could click this for me" task on sites that fight plain HTTP.

It drives **one tab at a time** and never steals your cursor or focus — you can keep using other tabs, other browsers, or any other app while it works. Need it waiting after a reboot? On macOS, one command hands it to launchd.

## How it compares

| If you need… | Use… |
|---|---|
| An AI agent to do one thing in your real, logged-in browser | **Webflow Bridge** |
| An agent that runs multi-page tasks on its own, with cloud concurrency and built-in models | a Browser Use–style agent framework |
| End-to-end tests on the Playwright ecosystem | Playwright MCP |
| Deep DevTools capabilities (performance traces, network, Lighthouse) | Chrome DevTools MCP |

What sets it apart: it drives the browser you already have open and logged in — the same profile, the same cookies, the same session — through browser-extension permissions plus a local token. Nothing leaves your machine, and no remote-debugging port is left open for other local processes to use. On Firefox it likewise targets your real, everyday profile rather than a separate automation build.

---

## Install

Needs **Python 3.11+** and Chrome, Edge or Firefox — all local, no account, no cloud, no API key.

- **Chrome / Edge** — start the daemon, then load `extension/` unpacked once: `python3 daemon/webflow_bridge.py` (Windows: `py -3.11 daemon/webflow_bridge.py`), then `chrome://extensions` (Edge: `edge://extensions`) → Developer mode → **Load unpacked** → `extension/`.
- **Firefox** — separate edition on port `10096`: `ff/ff-launch.sh && python3 ff/daemon/ff_bridge.py` (Windows: `ff\ff-launch.bat && py -3.11 ff/daemon/ff_bridge.py`).
- **macOS, always on** — after the one-time launchd setup in [docs/INSTALL.md](docs/INSTALL.md), this line (re)starts it at every login: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.webflow.bridge.plist`.

Full detail — both launch methods, launchd/systemd, ports, tokens, uninstall and troubleshooting: **[docs/INSTALL.md](docs/INSTALL.md)**.

## Hand it to your agent

Paste this to a coding agent (Claude Code, Codex, Hermes, …) to let it wire itself up:

> You are connecting to Webflow Bridge in this repo. Start the daemon from the repo root (`python3 daemon/webflow_bridge.py`, or `py -3.11 daemon/webflow_bridge.py` on Windows). Then register the MCP server by following `docs/MCP.md`, and reload/restart your MCP client the way that guide requires. Finally, read `llms.txt` and `docs/AGENTS.md` and use them to drive the browser over `POST /command` or the MCP tools.
>
> One step needs a human first: the `extension/` folder must be loaded unpacked at `chrome://extensions` or `edge://extensions` (Developer mode → Load unpacked). The extension is not on the browser stores yet, so it cannot be installed automatically.

## Common issues (at a glance)

- **`503 {"error":"extension not connected"}`** — Chrome/Edge isn't running with the extension loaded. Start the browser, then check the "Webflow Bridge" popup shows *Daemon: connected*.
- **"chrome:// … cannot be debugged"** — the active tab must be a normal http(s) page; `chrome://`, the stores and new-tab pages are off-limits.
- **"Another debugger is already attached"** — DevTools (or another CDP client) is open on that tab. Close it and retry.
- **Port already in use** — another Webflow Bridge instance is running; stop it first.
- **Errors mention "Content Security Policy"** — you're on a stale, content-script-era build. Fully reload the extension at `chrome://extensions`; current builds run through the debugging channel, which page CSP cannot block.

The full troubleshooting table lives in [docs/INSTALL.md](docs/INSTALL.md).

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

## Documentation

| Doc | What's inside |
|---|---|
| [docs/INSTALL.md](docs/INSTALL.md) | Install, launchd/systemd, ports & tokens, verification, uninstall, full troubleshooting. |
| [docs/HTTP_API.md](docs/HTTP_API.md) | The `POST /command` contract — every core action with one curl each, error shapes, a complete zero-SDK demo flow. |
| [docs/PRIVACY.md](docs/PRIVACY.md) | Plain-English privacy policy (what the extension does, data, permissions). |
| [ff/README.md](ff/README.md) | Firefox edition — install, action matrix, platform status, known limits. |
| [Releases](https://github.com/darrenhooooo/webflow-bridge/releases) | Release history and notes. |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute. |
| [SECURITY.md](SECURITY.md) | Security policy and how to report an issue. |

## License & support

Webflow Bridge is **free and open source (MIT)** — see [LICENSE](LICENSE). If it saves you time:

- ⭐ Star — [github.com/darrenhooooo/webflow-bridge](https://github.com/darrenhooooo/webflow-bridge)
- 🐛 Report bugs / request features — [Issues](https://github.com/darrenhooooo/webflow-bridge/issues)
- 📦 Releases — [v1.3.0](https://github.com/darrenhooooo/webflow-bridge/releases)
- ✉️ Contact — darren.hou@outlook.com
