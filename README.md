# Webflow Bridge

**[English](README.md) | [中文](README.zh-CN.md)**

> A free, local browser-automation bridge for your real, already-logged-in Chrome or Edge. No cloud, no accounts.

**License:** MIT.

**Supported:** Chrome & Microsoft Edge on macOS and Windows (Chromium MV3 — identical chrome.debugger API). Not supported: Firefox/Safari (no chrome.debugger equivalent).

---

## What it does

Webflow Bridge lets scripts drive **the browser tab you already have open** — the one where you are already logged in. No separate automation browser, no copied cookies, no cloud. Your existing publish scripts keep POSTing to `http://127.0.0.1:10086/command` **unchanged**, and Webflow Bridge executes the JS in your real Chrome tab.

## Features

| | |
|---|---|
| 🖥️ **Real browser, real session** | Runs on your live tab — logged-in state, cookies, and page globals all there. No phantom browser to keep in sync. |
| 🔌 **Agent-tool compatible** | Same `POST /command` protocol. Agent skills written for browser bridges map 1:1. |
| 🎯 **30+ actions** | Click, type, fill forms, drag-drop files, screenshot, save PDF, read the page, switch tabs, watch network traffic and console logs, and more. |
| 🪟 **JS dialogs handled** | alert/confirm/prompt don't stall your automation — accept, dismiss, or answer them programmatically. |
| 📎 **File uploads, no OS dialog** | Click an upload button and hand it a local file path — the system "Open File" window never appears. |
| 🔓 **CSP-immune** | Runs through the debugger channel, so it works even on strict sites like x.com. |
| 🔒 **Private by design** | Everything stays on your machine. No cloud, no accounts, no data leaves the device. |
| 🧩 **One extension, two browsers** | The same `extension/` folder loads in Chrome and Edge. |

## Typical uses

- **Publish automation** — post to X / LinkedIn / Facebook / blogs with your real accounts, exactly as you would by hand.
- **Scraping & monitoring** — read pages that need login, click through pagination, watch XHR traffic.
- **Testing** — end-to-end flows against a real browser session (with or without DevTools open).
- **RPA glue** — any "I wish a script could click this for me" task on sites that fight plain HTTP.

It drives one tab at a time and never steals your cursor or focus — you can keep using other tabs, other browsers, or any other app while it works.

---

## How it fits together

Three local pieces: your script (or an AI agent) POSTs commands to a small
Python daemon, the daemon relays them over a local WebSocket to the extension,
and the extension executes them in your real tab through Chrome's debugger
channel.

```
┌──────────────────────────┐   POST /command   ┌──────────────────────────────┐
│ existing publish scripts │ ----------------> │ Python daemon  :10086 HTTP   │
│ (unchanged) - POST       │ <---------------- │ daemon/webflow_bridge.py       │
└──────────────────────────┘   JSON response   └──────────────┬───────────────┘
                                                              │  WebSocket ws://127.0.0.1:10087
                                                              ▼
                                             ┌────────────────────────────────┐
                                             │ Webflow Bridge (MV3 Chrome     │
                                             │ extension — background.js      │
                                             │ service worker only)           │
                                             └───────────────┬────────────────┘
                                                             │  chrome.debugger attach
                                                             │  CDP Runtime.evaluate
                                                             ▼
                                             ┌────────────────────────────────┐
                                             │ ACTIVE tab (your real Chrome)  │
                                             │ page MAIN world — page-CSP-    │
                                             │ immune (DevTools-console-      │
                                             │ equivalent); returnByValue     │
                                             │ JSON-safe result back          │
                                             └────────────────────────────────┘
```

- **Daemon**: Python stdlib only (a minimal hand-rolled RFC 6455 WebSocket
  server; no third-party deps). Backwards compatible — evaluate/navigate/probe
  behave exactly as before; the browser-driver actions below are additions.
- **Extension**: Chrome Manifest V3 — `manifest.json`, `background.js` and a
  small toolbar popup (`popup.html`/`popup.css`/`popup.js`) that pings the
  background worker and can test-evaluate the active tab. The worker connects
  to the daemon, attaches a `chrome.debugger` session to the **active tab**,
  and evaluates snippets through CDP `Runtime.evaluate` (the DevTools-console
  channel). Because that session is a full DevTools connection, the extension
  also exposes the **entire CDP surface** (`Input.*`, `Page.*`, `DOM.*`, `Network.*`, ...) through a generic
  `cdp` passthrough action — scripts can drive every browser capability, not
  just evaluation. On top of it the worker implements the **standard
  browser-bridge agent-tool surface** — find_tab/snapshot/click/fill/screenshot/
  upload/save_as_pdf/mouse_click/send_key/type_text and a navigate that can
  open & title new tabs (action table below). **`content.js` was removed** —
  see "How the code runs" for why.
- **smoke.py**: end-to-end smoke test (evaluate, cdp, tabs_list — see below).

## Files

```
webflow/
├── LICENSE              # MIT
├── README.md
├── daemon/
│   ├── webflow_bridge.py     # HTTP :10086 (POST /command) + WS :10087
│   └── smoke.py            # end-to-end smoke test (real page)
├── docs/
│   └── PRIVACY.md          # plain-English privacy policy
├── extension/
│   ├── manifest.json       # MV3; permissions: scripting, activeTab, tabs, debugger, alarms, tabGroups.
│   │                       # No content_scripts block, NO content_security_policy key.
│   ├── background.js       # service worker: WS client + chrome.debugger driver
│   │                       # (session manager; dispatch: evaluate/cdp/navigate/tabs_*/probe
│   │                       #  + find_tab/snapshot/click/fill/screenshot/upload/save_as_pdf/
│   │                       #  mouse_click/send_key/type_text)
│   ├── popup.html          # toolbar popup UI (Webflow Bridge)
│   ├── popup.css           # popup styles (dark theme, no external assets)
│   ├── popup.js            # popup <-> background runtime messages (wf-ping/wf-evaluate)
│   └── assets/icons/       # icon16/32/48/128.png (toolbar / Chrome Web Store)
└── tools/
    └── make_icons.py       # regenerates extension/assets/icons/*.png (Pillow only)
```

## Install / run

### 1. Start the daemon

```bash
cd /path/to/webflow        # project root (this repo: daemon/, extension/, ...)
# Runtime A — uv (recommended; works the same on every OS):
uv run --python 3.11 daemon/webflow_bridge.py
# Runtime B — plain Python 3.11+ (no uv needed):
python3 daemon/webflow_bridge.py
```

> `python3` is the real interpreter on macOS/Linux. On Windows it must be a
> real Python 3.11 (e.g. from python.org) — not the Microsoft Store stub
> (`py -3.11 daemon/webflow_bridge.py` also works there).

You should see the startup banner with both listening ports:

```
========================================
  Webflow Bridge daemon started
    HTTP  : http://127.0.0.1:10086    POST /command
    WS    : ws://127.0.0.1:10087          Chrome extension connects here
```

### 2. Load the extension — Chrome or Edge (manual, one time)

The identical `extension/` folder loads in both browsers (and the same
`dist/` zip packages both — no Chrome-only vs Edge-only build).

1. Open `chrome://extensions` in Chrome, or `edge://extensions` in Edge.
2. Enable **Developer mode** (top-right toggle — same in both browsers;
   Edge shows the same "Developer mode" switch).
3. **Load unpacked** → select the `extension/` folder (the same folder for
   Chrome and Edge).
4. Pin "Webflow Bridge"; keep the browser open on a normal website in the
   **active tab** (`chrome.debugger` cannot attach to `chrome://` /
   `edge://` pages, the Web Store / Edge Add-ons store, or new-tab pages —
   the publish flows need a real http(s) page).

> **Reload the extension after any change**: unpacked extensions do *not*
> hot-apply edits — click the refresh (reload) icon on the "Webflow Bridge" card
> at `chrome://extensions` (or `edge://extensions`) after changing
> `manifest.json` or `background.js`.
> There is no `content_security_policy` key in the manifest anymore (MV3
> forbids extension pages from permitting eval — Chrome rejects the manifest
> if it appears — and none is needed here), so no CSP concerns apply. Removing
> the content script is silent.

The extension reconnects automatically (backoff up to 30 s), so you can
restart the daemon freely.

### 3. Verify with curl

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -d '{"action":"evaluate","args":{"code":"(() => document.title)()"},"session":"default"}'
```

Expected (title of your active tab):

```json
{"status": "ok", "data": {"value": "..."}}
```

### 4. Smoke test

```bash
uv run --python 3.11 daemon/smoke.py
# (no uv? python3 daemon/smoke.py works too)
# optional live navigation check (reloads the tab):
uv run --python 3.11 daemon/smoke.py --navigate=https://example.com
```

## Protocol contract

`POST /command` with a JSON body:

```json
{
  "action": "evaluate",
  "args":   {"code": "(() => document.title)()"},
  "session": "default"
}
```

| Response | Meaning |
|---|---|
| `200 {"status":"ok","data":{"value": <result>}}` | code ran; result JSON-safe (string/number/bool/array/object/null) |
| `200 {"status":"error","error":"..."}` | evaluate failure (code threw, timeout after 120 s, unknown action, ...) |
| `503 {"error":"extension not connected"}` | no extension WebSocket — start Chrome with the extension loaded |

Beyond `evaluate`, the daemon forwards this full browser-driver surface over
the same pipeline. Action names and args use the familiar agent-tool
conventions for browser bridges (the well-known `list_tabs` maps to this
bridge's pre-existing `tabs_list`), so agent skills written against a
`POST /command` browser-bridge surface map onto these actions 1:1. `"tabId"`
is optional on every action that targets an existing tab and defaults to the
active tab (use `tabs_list` to discover tab ids) — `save_as_pdf` takes no
`tabId` (it always prints the active tab) and `find_tab` takes no `tabId`
(it searches every window and never opens a tab):

| Action | `args` | `data` in the reply |
|---|---|---|
| `evaluate` | `{"code": "...", "tabId"?: <n>}` | `{"value": <evaluation result>}` |
| `cdp` | `{"method": "...", "params"?: {...}, "tabId"?: <n>}` | `{"value": <raw CDP result>}` |
| `snapshot` | `{"max"?: <int, default 400>, "tabId"?: <n>}` | `{"value": {url, title, nodes: [{ref: "@e0", tag, role, name, text, path}, ...]}}` |
| `click` | `{"selector": <CSS or "@eN">, "tabId"?: <n>}` | `{"value": {success, tag, text}}` |
| `fill` | `{"selector", "value", "mode"?: "auto"/"value"/"contenteditable", "tabId"?: <n>}` | `{"value": {success, tag, mode}}` |
| `find_tab` | `{"url", "active"?: true}` (exact → prefix → substring) | `{"value": {success, url, tabId}}` or `{success: false, error}` |
| `navigate` | `{"url", "newTab"?: true, "group_title"?, "tabId"?: <n>}` | `{}` (tab updated); with `newTab`: `{"value": {success, tabId, groupId?}}` |
| `tabs_list` | `{}` | `{"value": [{id, url, title, active, windowId, index}, ...]}` |
| `tabs_open` | `{"url": "https://..."}` | `{"value": {"id": <tabId>, "url": <url>}}` |
| `tabs_close` | `{"tabId"?: <n>}` | `{"value": {"closed": <tabId>}}` |
| `tabs_close_all_but` | `{"tabId"?: <n>}` | `{"value": {"closed": <count>}}` |
| `tabs_activate` | `{"tabId"?: <n>}` | `{"value": {"tabId": <n>, "active": true}}` |
| `probe` | `{}` | `{"value": {tab, paths}}` (extension health matrix) |
| `screenshot` | `{"format"?: "png"/"jpeg", "quality"?: 0-100, "selector"?, "fullPage"?: true, "tabId"?: <n>}` | `{"value": {base64, mime, width, height}}` — client writes the file |
| `upload` | `{"selector", "file": <absolute local path>, "tabId"?: <n>}` | `{"value": {success, file, tag}}` |
| `save_as_pdf` | `{}` (always the active tab) | `{"value": {base64, mime: "application/pdf"}}` — client writes the file |
| `mouse_click` | `{"x"?: <int>, "y"?: <int>, "selector"?, "tabId"?: <n>}` (selector wins) | `{"value": {success, x, y}}` |
| `send_key` | `{"key", "modifiers"?: ["alt"/"ctrl"/"meta"/"shift"], "tabId"?: <n>}` | `{"value": {success, key}}` |
| `type_text` | `{"text", "selector"?, "tabId"?: <n>}` | `{"value": {success, len}}` |
`cdp` is a generic passthrough with **no method allowlist**: any command the
extension's debugger session can reach can be fired, e.g.

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -d '{"action":"cdp","args":{"method":"Input.insertText","params":{"text":"hi"}},"session":"default"}'

curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -d '{"action":"tabs_list","args":{},"session":"default"}'
```

`data.value` is whatever the CDP method returns (methods like
`Input.insertText` return `{}`; `Runtime.evaluate` returns
`{"result": {"type": ..., "value": ...}}`), and `tabs_list` returns one entry
per tab with undefined fields omitted (`chrome://` pages may expose no
url/title). `tabs_open` requires an http(s) url; `tabs_close_all_but` closes
every tab in the target tab's window except the target itself.

Scripts read `response.get("data", {}).get("value")`, so error responses (no
`data`) behave exactly as before.

Origin guard: any POST whose `Origin` header is not
`http://127.0.0.1:10086`, `http://localhost:10086`, or `null` is answered
`403 {"error":"cross-origin POST blocked"}`. Native scripts/curl send no
`Origin` header and are unaffected; the WebSocket handshake is not guarded.

### Internal WebSocket wire format (daemon ↔ extension, :10087)

```jsonc
// daemon -> extension
{"id": "<request_id>", "action": "evaluate", "code": "(() => ... )()"}
{"id": "<request_id>", "action": "evaluate", "code": "(() => ... )()", "tabId": 7}
{"id": "<request_id>", "action": "navigate",  "url": "https://..."}
{"id": "<request_id>", "action": "navigate",  "url": "https://...", "tabId": 7}
{"id": "<request_id>", "action": "cdp", "method": "Input.insertText", "params": {"text": "hi"}, "tabId": 7}
{"id": "<request_id>", "action": "tabs_list"}
{"id": "<request_id>", "action": "tabs_open", "url": "https://example.com"}
{"id": "<request_id>", "action": "tabs_close",  "tabId": 7}
{"id": "<request_id>", "action": "tabs_close_all_but", "tabId": 7}
{"id": "<request_id>", "action": "tabs_activate", "tabId": 7}
{"id": "<request_id>", "action": "navigate", "url": "https://...", "newTab": true, "group_title": "Scratch"}
{"id": "<request_id>", "action": "find_tab", "url": "example.com", "active": true}
{"id": "<request_id>", "action": "snapshot", "max": 400}
{"id": "<request_id>", "action": "click", "selector": "@e0"}
// ... find_tab/snapshot/click/fill/screenshot/upload/save_as_pdf/mouse_click/send_key/type_text all ride this same flat-envelope shape (action name + its args)

// extension -> daemon
{"id": "<request_id>", "ok": true,  "value": <json-safe result>}
{"id": "<request_id>", "ok": false, "error": "..."}
{"type": "ping"}            // keepalive, daemon ignores
```

The daemon accepts `{"id", "data":{"value": ...}}` replies as well.

## How the code runs in the page

An `evaluate` snippet runs through **`chrome.debugger` → CDP
`Runtime.evaluate` on the active tab** — the exact channel the DevTools console
uses. It executes in the page's **MAIN world** with `returnByValue: true`, so
the completion value of the snippet (e.g. an IIFE's return value) comes back as
JSON-safe data and never as a raw CDP handle. Because it is the debugger
channel it is **immune to page CSP**: snippets can be arbitrary strings even on
strict sites like x.com, and because it runs in the page's own world, snippets
see the page's DOM *and* its JavaScript globals, and the events they dispatch
(including `DataTransfer` drag-drop file uploads, `DragEvent`,
`File`/`Blob`, `.click()`) trigger the page's real listeners — React's
delegated handlers included. That is what the publish flows depend on when
composing tweets/posts on x.com.

Why not a content script or `executeScript`? This is evidence-based, not
theoretical: content-script isolated worlds run under a **Chrome-hardcoded
CSP** whose allowed `script-src` sources omit `eval`/`new Function`, so a
`content.js` evaluator cannot work under stable MV3 regardless of the
manifest. `chrome.scripting.executeScript` no
longer accepts a `'code'` string at all (only `'files'` or `'func'`), and
compiling the snippet string in the MAIN world (`func` that calls
`new Function`) is blocked by **page** CSP on x.com. The one channel that
arbitrary-string evaluation provably survives on is the debugger
(`Runtime.evaluate`) — verified live on x.com with Chrome 152.

The extension attaches **one** debugger session per active tab and reuses it
across evaluate calls — no attach/detach flicker during long publish runs. The
session survives same-tab navigation, so `navigate` keeps it; it is detached
when the daemon WebSocket closes, when a different tab is targeted, when
`chrome.debugger.onDetach` fires (tab closed, DevTools took over, ...), or when
a command fails because the session died. The next evaluate re-attaches
transparently.

That session makes the **full CDP surface available to scripts**: the `cdp`
action fires any protocol method (`Input.*` for real mouse/keyboard/touch and
`DataTransfer` drag-drop events, `Page.*` for reload/capture/print, `DOM.*`,
`Network.*`, `Emulation.*`, `Runtime.*`, ...) over the same managed session —
no method allowlist, raw result returned. Passing a `tabId` that differs from
the current session's switches the session to that tab before the command runs
(the same detach/re-attach `evaluate` uses); `navigate` never switches it — a
CDP session only ever targets the tab it was attached to, and survives
same-tab navigation.

Details:

- `"(() => {...})()"` works because `Runtime.evaluate` returns the value of
  the last expression.
- Promise results are awaited (`awaitPromise: true`); a hung async snippet
  surfaces as the daemon's 120 s timeout.
- Results are JSON-cloned (objects/arrays/numbers/strings/booleans/null
  survive; `undefined` becomes a JSON-safe `{type:"undefined"}` marker).
- Thrown errors come back as `{"status":"error","error":<message>}` with the
  error text intact.
- `background.js` keeps its WebSocket to the daemon alive with a 15 s heartbeat
  and reconnects with exponential backoff (cap 30 s).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `503 {"error":"extension not connected"}` | Chrome/Edge open? Extension loaded (`chrome://extensions` / `edge://extensions`)? Check `background.js` console for "connected to daemon". |
| evaluate replies "no active tab found" or "cannot attach debugger ... chrome:// and Web Store pages cannot be debugged" | The active tab is `chrome://...` / new tab / Web Store — those cannot be debugged. Open a real website in the active tab and retry. |
| evaluate fails with "Another debugger is already attached" | DevTools (or another CDP client) is open on that tab. Close the DevTools window on that tab and retry. |
| evaluate error mentions "Content Security Policy" | Stale build from the content-script era (the old MAIN-world `new Function` / content-script eval paths are CSP-blocked). Fully reload "Webflow Bridge" at `chrome://extensions` (or `edge://extensions`) — the current build evaluates through `chrome.debugger`, which neither page CSP nor the extension can block. |
| Timeout after 120 s | Active tab busy (modal dialog / blocked script) or the page code never finished. CDP awaits Promise completion values, so a hung async snippet lands here. |
| Port already in use | Another Webflow Bridge instance is running — stop it first. |
| Extension lost connection after daemon restart | Automatic: reconnects with backoff up to 30 s. The debugger session is detached on WS close and re-attached on the next evaluate — no action needed. |

## Constraints honoured

- Developed and verified on Windows 11 + Chrome 152; platform-neutral by
  design — pure-Python stdlib daemon and Chromium MV3 extension. macOS + Edge
  supported; see `docs/CROSS_PLATFORM.md`.
- Extension is loaded manually (Developer mode → Load unpacked) and never
  auto-installed; no browser profiles are touched.
- Daemon uses Python stdlib only.
