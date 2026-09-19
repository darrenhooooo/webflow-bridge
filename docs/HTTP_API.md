# Webflow Bridge HTTP API — zero-SDK driver guide (standard browser-bridge agent-tool names)

**Webflow Bridge Command API v1.4.0** · base URL `http://127.0.0.1:10086`
· OpenAPI description: [`../openapi/openapi.yaml`](../openapi/openapi.yaml)

## What this proves

The bridge is drivable by **ANY generic HTTP tool** — `curl`, `n8n` HTTP
Request nodes, browser `fetch`, PowerShell, Postman, a cron job — with **zero
bespoke SDK**. There is no client library and no magic header: one
`POST /command` with a JSON body (plus the shared-secret bearer token below)
is the entire surface. The OpenAPI file
above lets codegen / n8n / Postman import the API; this guide is enough for a
human with curl.

```
your tool ──POST /command──▶ daemon (127.0.0.1:10086) ──WebSocket──▶ Chrome extension ──CDP──▶ real tab
```

> **Firefox edition (`ff/`).** The same `POST /command` contract runs on
> `http://127.0.0.1:10096` (token in `~/.webflow_bridge_ff/token`), backed by
> WebDriver BiDi instead of the extension. v1.4 failure handling is identical
> (`args.retry`, `captureOnError`, `error_details`, `wait_for` semantics).
> Actions not available on that backend answer an explicit `status:error`:
> `cdp`, `handle_file_chooser`, and — not yet ported — `fill_form`, `submit`,
> `drop`, `list_downloads`, `resize_page`.

## Quickstart

| Thing | Value |
|---|---|
| Base URL | `http://127.0.0.1:10086` |
| Endpoint | `POST /command` |
| Content-Type | `application/json; charset=utf-8` |
| Auth | `Authorization: Bearer <token>` (required; token in `~/.webflow_bridge/token`) |
| Request body | `{"action": "<action>", "args": {...}, "session": "default"}` |

**Auth.** The daemon runs shared-secret auth by default. On first start it
creates `~/.webflow_bridge/token` (random). Send it on every POST as
`Authorization: Bearer <token>` (or `export WBF_TOKEN=$(cat ~/.webflow_bridge/token)`
and use `$WBF_TOKEN` below). Start the daemon with `--allow-no-auth` only as a
local migration window. The extension gets the token automatically from
`GET /config`.

**Origin-guard rule.** After auth passes, the daemon rejects any POST that
carries an `Origin` header which is not `http://127.0.0.1:10086` or
`http://localhost:10086`, answering `403 {"error":"cross-origin POST blocked"}`.
This is a CSRF guard for browser-originated requests only (`null` origins —
sandboxed iframes / file pages — are deliberately rejected; they cannot know
the token anyway). **Plain scripts and curl send no `Origin` header and are
unaffected** — just don't copy an `Origin` header out of a browser, and don't
set one yourself.

Sanity check that the daemon is up and the extension is connected:

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"probe","args":{},"session":"default"}'
# => {"status": "ok", "data": {"value": {"tab": {...}, "paths": {...}}}}
# If the extension is not connected you instead get:
#    503 {"error": "extension not connected"}
# A disconnected (or silently dead) extension fails fast: the daemon answers
# 503 right away instead of letting the request hang for the 120 s round-trip
# cap.
```

Every `/command` response — success or error, including `401`/`403`/`503` —
also carries a top-level `browser` field naming which browser the extension is
connected in: `"chrome"`, `"edge"`, or `""` when no extension is connected.
A response may additionally carry a top-level `notice` object (unsolicited
feedback: an auto dialog-accept failure, a download started, control handed to
a new tab); see [Native dialogs, downloads and failed pages](#native-dialogs-downloads-and-failed-pages).

## GET /status

Ask the daemon **which browser it is connected to** — and whether anything is
connected at all — **without triggering any browser action**. Same shared
bearer token as `POST /command`; a missing or invalid token answers `401`.
Unlike `/command`, this endpoint returns `200` even when nothing is connected
— answering "is it connected?" is its whole job.

`/status` is deliberately a **connection + settings** endpoint, and it always
answers in milliseconds. It does **not** prove the debugger can act on the
current page: native dialogs (when the policy is `manual`) and credential
prompts block the page, and only a real browser action can reveal that. For an
activity check use `probe` — while a native dialog is blocking the page it now
answers in milliseconds with `dialog.blocking: true` and the affected paths
marked `skipped` (see
[Native dialogs, downloads and failed pages](#native-dialogs-downloads-and-failed-pages)).

```bash
curl -s http://127.0.0.1:10086/status \
  -H "Authorization: Bearer $WBF_TOKEN"
```

Connected to Edge:

```json
{"status": "ok", "data": {"extension_connected": true, "browser": "edge", "ws_port": 10087, "connected_since": "2026-09-15T14:32:07.123456+08:00", "extension_stale": false, "last_extension_frame_ms_ago": 120, "dialog_policy": "auto-accept", "last_notice": null}}
```

Nothing connected:

```json
{"status": "ok", "data": {"extension_connected": false, "browser": "", "ws_port": 10087, "connected_since": null, "extension_stale": false, "last_extension_frame_ms_ago": null, "dialog_policy": "auto-accept", "last_notice": null}}
```

`browser` is `"chrome"`, `"edge"` or `""`; `connected_since` is a
local-timezone ISO 8601 timestamp (or `null` when nothing is connected).
`extension_stale` / `last_extension_frame_ms_ago` describe the extension's own
**JS heartbeat** (its `{"type":"ping"}` frames): a stale value means the MV3
service worker went quiet — it says nothing about the debugger session.
`dialog_policy` is the live native-dialog policy (`auto-accept` | `manual`,
see `set_dialog_policy`). `last_notice` is the newest unsolicited extension
feedback (auto-accept failure / download started / control moved to a new
tab), and the same object is attached to the next `POST /command` response as
an additive top-level `notice` field.

## Actions — one curl per action

> **Which tab?** `evaluate`/`cdp`/`snapshot`/`click`/`fill`/`screenshot`/`upload`/
> `mouse_click`/`send_key`/`type_text` act on the **active tab unless `tabId`
> is given**. `save_as_pdf` always prints the **active tab**. `tabs_open` makes
> the new tab active. `tabs_close`, `tabs_close_all_but` and `tabs_activate`
> also default to the active tab. `find_tab` searches every window (no
> `tabId`). Replace `<TAB_ID>` below with a real id from `tabs_list` /
> `tabs_open`.

**probe** — extension health + per-path diagnostic matrix (no args):

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"probe","args":{},"session":"default"}'
```

**tabs_list** — every open tab as `[{id, url, title, active, windowId, index}, ...]`:

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"tabs_list","args":{},"session":"default"}'
```

**tabs_open** — open `url` in a new tab (http/https); it becomes active and the
response carries its id: `{"value": {"id": <TAB_ID>, "url": <url>}}`:

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"tabs_open","args":{"url":"https://example.com"},"session":"default"}'
```

**evaluate** — run JS in the page MAIN world and get the JSON-safe value back
(`document.title` → `{"value": "Example Domain"}`); add `"tabId": <TAB_ID>` to
target a non-active tab:

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"evaluate","args":{"code":"(() => document.title)()"},"session":"default"}'

# targeted at a specific tab instead of the active one:
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"evaluate","args":{"code":"document.location.href","tabId":<TAB_ID>},"session":"default"}'
```

**navigate** — point the active tab (or `tabId`) at a url (reply is `data:
{}`):

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"navigate","args":{"url":"https://example.com"},"session":"default"}'
```

**navigate into a NEW tab** — `newTab: true` opens the url in a fresh active
tab; the response carries its id (`{"value": {"success": true, "tabId": <n>}}`).
An optional `group_title` also groups that tab under a named tab group
(`groupId` is then included):

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"navigate","args":{"url":"https://example.com","newTab":true,"group_title":"Scratch"},"session":"default"}'
# => {"status": "ok", "data": {"value": {"success": true, "tabId": 9, "groupId": 2}}}
```

**cdp** — fire ANY DevTools Protocol method on the managed debugger session (no
allowlist). Example: real keyboard input via `Input.insertText` (result `{}`):

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"cdp","args":{"method":"Input.insertText","params":{"text":"hi"}},"session":"default"}'

# arbitrary CDP: {"method":"Runtime.evaluate","params":{"expression":"1+1"}} returns {"value": {"result": {...}}}
```

**find_tab / snapshot / click / fill / screenshot / upload / save_as_pdf /
mouse_click / send_key / type_text** — these carry the standard
browser-bridge **agent-tool names**, so a reference skill written against a
browser-bridge surface (navigate(url, newTab, group_title) / find_tab /
list_tabs / snapshot / click / fill / screenshot / upload / save_as_pdf /
mouse_click / send_key / type_text / evaluate / cdp) maps onto the actions
here 1:1 — the familiar `list_tabs` is this bridge's pre-existing
`tabs_list`.

**find_tab** — find an open tab whose URL matches (exact, then prefix, then
substring; current-window tabs preferred; **never opens a tab**):

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"find_tab","args":{"url":"example.com"},"session":"default"}'
# => {"status": "ok", "data": {"value": {"success": true, "url": "https://example.com/", "tabId": 7}}}
# nothing matched:
#    {"status": "ok", "data": {"value": {"success": false, "error": "no tab matches example.com"}}}

# bring the matched tab to the front too:
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"find_tab","args":{"url":"https://example.com/","active":true},"session":"default"}'
```

**snapshot** — accessibility-like snapshot of the current tab: visible
interactive/informative elements as `{ref: "@e0", tag, role, name, text,
path}` in document order (`"max"` caps the list, default 400). `@eN` refs /
`path` stay reusable by `click`/`fill` until the DOM changes:

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"snapshot","args":{},"session":"default"}'
# => {"status": "ok", "data": {"value": {"url": "https://example.com/",
#     "title": "Example Domain",
#     "nodes": [
#       {"ref": "@e0", "tag": "a", "role": "link", "name": "",
#        "text": "More information...",
#        "path": "div:nth-of-type(1) > p:nth-of-type(2) > a:nth-of-type(1)"},
#       {"ref": "@e1", "tag": "a", "role": "link", "name": "",
#        "text": "Example Domains",
#        "path": "div:nth-of-type(1) > p:nth-of-type(3) > a:nth-of-type(1)"}
#     ]}}}
# snapshot the same tab again with a smaller cap: {"action":"snapshot","args":{"max":50},...}
```

**click** — click an element by CSS selector or by a snapshot `@eN` ref (the
ref must come from the **same tab** as the last snapshot; after the DOM
changes, call `snapshot` again):

```bash
# click the first snapshot node (@e0):
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"click","args":{"selector":"@e0"},"session":"default"}'
# => {"status": "ok", "data": {"value": {"success": true, "tag": "a", "text": "More information..."}}}

# a plain CSS selector works too (first match wins):
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"click","args":{"selector":"p a"},"session":"default"}'
```

**fill** — type into a form field or a contenteditable region. `mode`
defaults to `"auto"`: `input`/`textarea`/`select` are filled through the
native value setter + `input`/`change` events (React-safe); contenteditable
regions get real text via CDP `Input.insertText` after focusing. `"value"` /
`"contenteditable"` force one path:

```bash
# auto -> value mode for an input/textarea/select (selector from snapshot/HTML):
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"fill","args":{"selector":"#search","value":"webflow bridge"},"session":"default"}'
# => {"status": "ok", "data": {"value": {"success": true, "tag": "input", "mode": "value"}}}

# contenteditable (e.g. a rich-text composer) — focus + CDP-typed real text:
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"fill","args":{"selector":"[contenteditable]","value":"hello world","mode":"contenteditable"},"session":"default"}'
# => {"status": "ok", "data": {"value": {"success": true, "tag": "div", "mode": "contenteditable"}}}
```

**screenshot** — capture the active tab. Defaults to a PNG of the visible
viewport; `format: "jpeg"` + `quality` (0-100, jpeg only) choose the
transcoding; `selector` (CSS or `@eN`) captures just that element (scrolled
into view first); `fullPage: true` captures the whole page height. The value
is **base64 image data** — the **client writes the file** (the extension
cannot write arbitrary local paths):

```bash
# whole visible viewport, PNG (default)
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"screenshot","args":{},"session":"default"}'
# => {"status": "ok", "data": {"value": {"base64": "iVBORw0KGgoAAAANSUhEUgAA...",
#     "mime": "image/png", "width": 1280, "height": 720}}}

# JPEG of one element (@e0 from snapshot) — save it yourself, e.g.:
#   echo '<base64>' | base64 -d > element.jpg
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"screenshot","args":{"format":"jpeg","quality":80,"selector":"@e0"},"session":"default"}'

# full-page capture
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"screenshot","args":{"fullPage":true},"session":"default"}'
```

**upload** — put a **local file onto an `<input type="file">`** so the page
receives a real `File`. `file` is an **absolute local path** on the machine
running Chrome; the browser process reads it directly (no base64 needed). The
selector must resolve to an `<input type="file">` (hidden file inputs work):

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"upload","args":{"selector":"input[type=file]","file":"C:\\Users\\me\\Documents\\resume.pdf"},"session":"default"}'
# => {"status": "ok", "data": {"value": {"success": true, "file": "C:\\Users\\me\\Documents\\resume.pdf", "tag": "input"}}}
# selector does not match a file input / element missing:
#    {"status": "ok", "data": ... } -> 200 {"status": "error", "error": "..."}
```

**save_as_pdf** — print the **active tab** to PDF (background graphics
included). The value is **base64 PDF data** — the client writes the file:

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"save_as_pdf","args":{},"session":"default"}'
# => {"status": "ok", "data": {"value": {"base64": "JVBERi0xLjQK...", "mime": "application/pdf"}}}
```

**mouse_click** — click at viewport CSS-pixel coordinates (real
`mousePressed` + `mouseReleased`, left button), or pass a `selector`/`@eN` to
scroll it into view and click its center:

```bash
# raw coordinates
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"mouse_click","args":{"x":420,"y":260},"session":"default"}'
# => {"status": "ok", "data": {"value": {"success": true, "x": 420, "y": 260}}}

# by element (selector wins over x/y)
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"mouse_click","args":{"selector":"#search-btn"},"session":"default"}'
```

**send_key** — press one key (Enter, Tab, Escape, Backspace, Delete,
ArrowUp/Down/Left/Right, Home, End, PageUp, PageDown, Space, or a single
character a-z/0-9). `modifiers` takes an array of `"alt"`/`"ctrl"`/`"meta"`/
`"shift"` (CDP bitmask Alt=1 Ctrl=2 Meta=4 Shift=8); an optional `selector`
focuses that element first. Unknown keys/modifiers answer an explicit error:

```bash
# press Enter in the focused field
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"send_key","args":{"key":"Enter"},"session":"default"}'
# => {"status": "ok", "data": {"value": {"success": true, "key": "Enter"}}}

# Ctrl+A (select all) inside #editor — modifier shortcut, no text inserted
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"send_key","args":{"key":"a","modifiers":["ctrl"],"selector":"#editor"},"session":"default"}'
```

**type_text** — convenience typing: focus `selector` first (when given) then
insert `text` at the caret via CDP `Input.insertText` (reliable for CJK /
emoji / long text — no per-key events):

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"type_text","args":{"text":"hello 世界","selector":"#editor"},"session":"default"}'
# => {"status": "ok", "data": {"value": {"success": true, "len": 8}}}
```

**wait_for** — poll the target tab until a condition holds. `appear` (default)
waits for an element with a layout box (optionally containing `text`), `gone`
waits for the `selector` to leave the DOM, `hidden` waits for it to lose its
layout box (`display:none`, `visibility:hidden`) — and an optional
`networkIdleMs` additionally waits for that many ms without a request/response
event on the tab. Answer: `{"found": true, "elapsedMs": N, "matched": ...}`
(plus `lastNetworkActivityMs` when `networkIdleMs` was given):

```bash
# appear (default): the element shows up within 10s
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"wait_for","args":{"selector":"#result","timeoutMs":8000},"session":"default"}'
# => {"status":"ok","data":{"value":{"found":true,"elapsedMs":1234,"matched":"appear"}}}

# gone (selector is mandatory): wait for a spinner to leave the DOM
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"wait_for","args":{"selector":"#spinner","until":"gone","timeoutMs":8000},"session":"default"}'
# => {"status":"ok","data":{"value":{"found":true,"elapsedMs":420,"matched":"gone"}}}

# hidden + network-idle: element is invisible AND the tab has been quiet for 800ms
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"wait_for","args":{"selector":"#spinner","until":"hidden","networkIdleMs":800,"timeoutMs":15000},"session":"default"}'
# => {"status":"ok","data":{"value":{"found":true,"elapsedMs":900,"matched":"hidden","lastNetworkActivityMs":812}}}
```

`until` semantics: `appear` = element exists **and** has a layout box; `gone` =
`document.querySelector(selector)` is `null`; `hidden` = no layout box or
`visibility:hidden`/`display:none`. `until="gone"` requires a `selector` (a
`text`-only `gone` is rejected, never silently treated as `appear`). With both
`selector` and `text`, `hidden` is satisfied by **"element not visible OR text
no longer present"**, and `gone` requires both the element and the text to be
gone. `networkIdleMs` counts `Network.requestWillBeSent` /
`Network.responseReceived` events on the target tab (1..30000 ms, default off);
on timeout the error says which part was unmet — `condition not met
(until=...)` or `condition met but the page was not network-idle for Nms`.

**tabs_activate** — focus a tab (default active): `{"value": {"tabId": <n>, "active": true}}`:

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"tabs_activate","args":{"tabId":<TAB_ID>},"session":"default"}'
```

**tabs_close** — close a tab (default active): `{"value": {"closed": <TAB_ID>}}`:

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"tabs_close","args":{"tabId":<TAB_ID>},"session":"default"}'
```

**tabs_close_all_but** — close every tab in a window except the target
(default active): `{"value": {"closed": <count>}}`:

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"tabs_close_all_but","args":{"tabId":<TAB_ID>},"session":"default"}'
```

## Native dialogs, downloads and failed pages

### handle_dialog — resolve a native JavaScript dialog

A page can block itself on a **native JavaScript dialog** (`alert`, `confirm`,
`prompt`, `beforeunload`). While such a dialog is showing, the page's main
thread is frozen: `Runtime.evaluate`, screenshots and DOM actions on that tab
cannot complete. `handle_dialog` accepts, dismisses or answers the dialog that
is currently showing on the target tab (default: the active tab).

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"handle_dialog","args":{"accept":true},"session":"default"}'
# => {"status":"ok","data":{"value":{"success":true,"dialog":{"type":"confirm","message":"sure?","defaultPrompt":""},"accept":true,"promptText":null}}}
```

Args:

| arg | type | meaning |
|---|---|---|
| `accept` | boolean, optional, default `true` | `true` = OK, `false` = Cancel / leave. |
| `promptText` | string, optional | text returned by a `prompt()`; without it a `prompt` returns its default value. |
| `timeoutMs` | integer 1..15000, optional, default `2000` | how long to wait for the dialog to open before failing. |
| `tabId` | integer, optional | target tab (default: active). |

**2000 ms wait semantics.** `handle_dialog` does **not** open dialogs. It waits
up to `timeoutMs` (default 2000 ms) for a `Page.javascriptDialogOpening` event
on the target tab — the caller usually clicks the element that opens the dialog
first — then resolves it. If no dialog appears in that window it answers:

```json
{"status": "error", "error": "no JavaScript dialog is showing within 2000ms", "browser": "chrome"}
```

**Default policy: auto-accept.** Since v1.2.1 the bridge accepts every native
dialog automatically the moment it opens (`accept: true`; a `prompt` returns
its default text), so a blocked page unblocks by itself and the next command
succeeds in milliseconds. This is the daemon's default and the extension's
default, so it works with no configuration. The known cost (accepted): a
`beforeunload` dialog is dismissed with *leave*, so unsaved page state can be
lost.

**Turning it off (manual mode).** Start the daemon with `--no-auto-dialog`, or
switch at runtime:

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"set_dialog_policy","args":{"policy":"manual"},"session":"default"}'
# => {"status":"ok","data":{"value":{"policy":"manual","extension_notified":true}}}
```

`policy` is `auto-accept` | `manual`. The value is mirrored in `GET /status`
(`dialog_policy`) and pushed to the extension immediately (no browser action,
so it works even while a dialog is blocking a page).

**Manual mode is a fast failure, not a 30 s wait.** Once the extension has seen
a `Page.javascriptDialogOpening`, every debugger action on that tab fails
immediately (tens of milliseconds) with the dialog named — its type, message
and source URL — plus the two ways out:

```json
{"status": "error", "error": "a native alert dialog is blocking this tab ('range alert') from http://127.0.0.1:8917/dialogs: call handle_dialog (accept=true) or switch the policy to auto-accept", "browser": "chrome"}
```

The same fast failure applies when an automatic accept itself failed
(`lastError` set) — the auto-accept failure reason is appended. The in-flight
command is **not** detached, so `handle_dialog` still owns the session and
resolves the dialog (and `probe` keeps working, below).

This fast failure is **tab-scoped**: the pending dialog belongs to one tab,
and a command (or `probe`) targeting a *different* tab is never
short-circuited by it. A dialog on tab A marks no path `skipped` on tab B and
does not fail B's evaluate/click/screenshot. `dialog.pending` carries the
owning `tabId`, and switching away from the dialog tab does not lose it: the
extension keeps that tab's debugger session attached ("pinned") so switching
back still finds the dialog and `handle_dialog` can resolve it. You do not even
have to switch back: pass that tab's id as `handle_dialog`'s `tabId` and its
dialog is resolved while another tab stays the active one.

**Known boundary (the 30 s fallback is still real).** The extension can only
learn about a dialog after it is attached and the `Page` domain is enabled. A
dialog that was already open **before** the debugger attached never fires
`Page.javascriptDialogOpening`, so the bridge cannot see it: that case still
falls back to the `CDP Runtime.evaluate did not respond within 30s` timeout
(plus up to ~10 s of attach-time setup), and `handle_dialog` cannot resolve it
either — the page was blocking before the bridge ever had a handle. This is
accepted and documented rather than papered over.

If an automatic accept itself fails, the failure is never swallowed: it is
recorded in `GET /status` (`last_notice`) and on `probe`
(`dialog.lastError`/`dialog.policy`), and it rides the next `/command`
response as a top-level `notice`.

### probe while a dialog blocks the page

`probe` no longer hangs behind a dialog. When the extension knows the target
tab is blocked (a pending `Page.javascriptDialogOpening`, or a very recent CDP
timeout on the session) it answers in milliseconds with
`dialog.blocking: true`, and every injection path is marked skipped instead of
running into the frozen renderer:

```json
{"status":"ok","data":{"value":{
  "tab":{"id":7,"url":"http://127.0.0.1:8917/dialogs","title":"dialogs"},
  "paths":{
    "P4_executeScript_func_MAIN":{"ok":false,"error":"skipped: a native alert dialog is blocking this tab ('range alert') ..."},
    "P5_executeScript_func_eval_MAIN":{"ok":false,"error":"skipped: ..."},
    "P6_executeScript_func_ISOLATED":{"ok":false,"error":"skipped: ..."},
    "P7_chromeDebugger_evaluate":{"ok":false,"error":"skipped: ..."}},
  "dialog":{"policy":"manual","pending":{"tabId":7,"type":"alert","message":"range alert","defaultPrompt":"","url":"..."},"lastError":null,"blocking":true},
  "downloads":{"count":0,"last":null}}}}
```

`dialog.pending` is the pending native dialog, tagged with the `tabId` it
belongs to (`dialog.lastError` carries the same `tabId`). The dialog block is
**per tab**: `dialog.blocking` is `true` only when the pending dialog belongs
to the probed tab, and only then are the four paths marked `skipped`. A dialog
pending on another tab may still appear in `dialog.pending` (so callers can
see it, including its `tabId`) but it does **not** set `blocking`, and the
probed tab's paths run normally and report their real results.

Without a dialog the response is unchanged except for the additive
`dialog.blocking: false`.

### list_downloads — native downloads are no longer invisible

Navigating to a URL with `Content-Disposition: attachment` starts a download
without changing the page. The extension records each `Page.downloadWillBegin`
and reports it: the triggering `navigate` response carries an additive
`notice` (`{"kind":"download_started", ...}`), and the full (newest-first)
record is queryable with no browser action:

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"list_downloads","args":{},"session":"default"}'
# => {"status":"ok","data":{"value":{"downloads":[{"guid":"...","url":"...","suggestedFilename":"report.pdf","state":"started","at":1700000000000}],"count":1}}}
```

The download's destination is **not** changed (no `downloadPath` is set).
`limit` (positive integer) caps the returned list.

### Popups move control silently — watch the notice

A page that opens a popup (`target="_blank"` / `window.open`) makes the new tab
active, so the next active-tab action targets the popup. When the extension
sees a tab created by the controlled tab it adds a `notice`
(`{"kind":"control_moved", "tabId": <n>, "url": "..."}`) to the response;
`tabs_list` keeps listing every tab. Pass an explicit `tabId` to keep driving
the original page.

### Failed pages are classified, not opaque

`evaluate` (and the other actions that read the page) refuse to return
meaningless values from a browser error page and name the reason: **protected
page** (`chrome://` / Web Store — "*the browser does not allow debugger access
to ...*"), **failed to load / certificate / cancelled auth**
(`chrome-error://chromewebdata/`, with the unreachable URL), and the
`Cannot attach to this target.` case. The three no longer look alike.

### Troubleshooting a stuck command

| Symptom | Cause | Fix |
|---|---|---|
| A debugger action fails at once with `a native <type> dialog is blocking this tab` | A native dialog is pending in `manual` mode | `handle_dialog` (accept/dismiss), or switch to `auto-accept`; JS dialogs are auto-accepted by default |
| A debugger action hangs, then a `CDP ... did not respond within 30s` error mentioning a dialog | The dialog was already open **before** the debugger attached (or a credential prompt is blocking) — the bridge has no event for it | `handle_dialog` cannot help in the pre-attach case; dismiss it in the browser, then retry. JS dialogs are auto-accepted by default |
| `probe` used to hang behind a dialog | The injection paths wait on the frozen renderer | No longer: `probe` answers in ms with `dialog.blocking: true` and the paths marked `skipped`; resolve the dialog with `handle_dialog` |
| `screenshot {fullPage: true}` answers `{"code":-32000,"message":"Page is too large."}` | Chrome's own cap on capture dimensions (common for very tall pages, and more easily hit in `--headless`) | Not a bridge defect: use a viewport screenshot, a smaller viewport, or a headed browser; the same page's viewport screenshot and `save_as_pdf` still work |
| `no JavaScript dialog is showing within 2000ms` | No dialog was open (already auto-accepted?) or the dialog is on another tab | Check `dialog.policy` via `probe`; pass `tabId` |
| `extension_connected: true` but nothing works | The WebSocket is up but the debugger is blocked/dead | `/status` is connection-only; run `probe`, or send the same request again with `args.retry` (transient debugger/extension errors are retried automatically when you opt in — see Failure handling below) |

## Failure handling — screenshots, retries, waits

Both features are additive: they never change a successful reply and never
replace the original `error`. Legacy requests (no new args) behave exactly as
before.

### Failure screenshots (`captureOnError`)

When a **browser action** fails, the daemon takes one PNG of the target tab and
reports its absolute path in the optional `error_details` field:

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"click","args":{"selector":"#does-not-exist"},"session":"default"}'
# => {"status":"error","error":"...","error_details":{"screenshot":"/Users/me/.webflow_bridge/captures/2025-01-02/030405-click-9df6.png","capturedMs":118}}
```

* Path rule: `<captures>/<YYYY-MM-DD>/<HHMMSS>-<action>-<4 hex>.png`.
* Default root `~/.webflow_bridge/captures`; override with the `WBF_CAPTURE_DIR`
  environment variable.
* Turn it off globally with `WBF_CAPTURE_ON_ERROR=0`, or per request with
  `"captureOnError": false` in `args` (not forwarded to the extension).
* Only a browser action that actually reached the transport is captured;
  a **parameter-validation failure** (bad/missing args, file-not-found for
  `drop`, ...) is never screenshotted. If the extension is not connected
  (HTTP 503) there is no page to capture.
* If the capture itself fails, the original error is untouched and the reason
  is reported instead: `"error_details": {"screenshot_error": "..."}`.

```bash
# per-request opt out (same failing click, no file written)
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"click","args":{"selector":"#does-not-exist","captureOnError":false},"session":"default"}'
```

### Transient-error retry (`retry`)

Add `"retry": {"attempts": N, "backoffMs": M}` to `args` to re-run a request
that failed on a transient transport/debugger error. **Retry is off unless you
ask for it.** `attempts` is the number of *extra* tries (0..5, default 2 when
the object is given without it); `backoffMs` is the base delay (0..5000,
default 400) and grows exponentially with ±25% jitter, capped at 5000 ms:

```bash
# retry a flaky read twice, 400ms base backoff
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"evaluate","args":{"code":"(() => document.title)()","retry":{"attempts":2,"backoffMs":400}},"session":"default"}'
# => {"status":"ok","data":{"value":"Example Domain","retries":1}}
```

What may be retried:

| Action | Retried? |
|---|---|
| `evaluate`, `snapshot`, `screenshot`, `save_as_pdf`, `probe`, `find_tab`, `tabs_list`, `list_downloads`, `list_network_requests`, `get_network_request`, `list_console_messages`, `wait_for` (read-only) | yes, on any recognised transient error |
| `click`, `fill`, `type_text`, `submit`, `fill_form`, `upload`, `drop`, `mouse_click`, `send_key`, `navigate` (side effects) | **only** when the failure happened *before* the command reached the page (debugger attach failure, extension disconnected, `No tab with id`, ...) — a command already delivered to the page is never retried, so a click cannot fire twice |
| everything else (e.g. `cdp`, `handle_dialog`, tab close/activate) | never |

Transient error text recognised (case-insensitive): `did not respond within`,
`debugger` (attach/detach/disconnect), `No tab with id`, `Extension ...
disconnected` / `not connected`, `connection closed`, `reconnect`.

On success the reply reports the real number of retries in `data.retries`
(`0` included); on final failure `error_details` carries `retries` and one
`attempts` entry per re-run (`{"attempt", "error", "delivered"}`). Every audit
event for the request also carries `retries`. A bad `args.retry` object is a
parameter error (no retry, no screenshot).

## Error shapes (read them without an SDK)

| HTTP | Body | Meaning |
|---|---|---|
| 200 | `{"status": "ok", "data": {"value": ...}}` | Success; read `data.value`. With `args.retry`, `data.retries` reports how many re-runs happened. |
| 200 | `{"status": "error", "error": "..."}` | Bad args / unknown action / extension failure / timeout. May carry `error_details` (see below). |
| 403 | `{"error": "cross-origin POST blocked"}` | A non-localhost `Origin` header was sent (see quickstart). |
| 503 | `{"error": "extension not connected"}` | No Chrome/Edge extension is connected to the daemon. |

Optional `error_details` on a failed action (never replaces `error`):

| field | when | meaning |
|---|---|---|
| `screenshot` | browser action failed and the capture succeeded | absolute path of a PNG of the target tab |
| `capturedMs` | with `screenshot` | how long the capture took |
| `screenshot_error` | capture was attempted but failed | why (the original error is unchanged) |
| `retries` | `args.retry` was given | re-runs actually performed |
| `attempts` | with `retries` | one `{attempt, error, delivered}` summary per re-run |

Scripts should treat `200` with `status == "ok"` as success and pull the result
from `data.value`; anything else is a failure even when it is HTTP 200.

## Complete demo flow — zero SDK, 5 steps

Opens its **own scratch tab** on `https://example.com`, proves it can read the
page back, then closes that tab. Never touches your other tabs.

Inline (step by step, run each in bash):

```bash
BASE=http://127.0.0.1:10086/command
CT='Content-Type: application/json'

# (1) open the scratch tab; the response carries the new tab's id
OPEN=$(curl -s -X POST "$BASE" -H "$CT" \
  -d '{"action":"tabs_open","args":{"url":"https://example.com"},"session":"default"}')
echo "tabs_open -> $OPEN"
TAB_ID=$(printf '%s' "$OPEN" | sed -nE 's/.*"id": ?([0-9]+).*/\1/p')
[ -n "$TAB_ID" ] && echo "PASS tabs_open captured tab id $TAB_ID" || { echo "FAIL tabs_open"; exit 1; }

# (2) let example.com settle
sleep 4

# (3) evaluate document.title on the (now active) scratch tab
TITLE=$(curl -s -X POST "$BASE" -H "$CT" \
  -d "{\"action\":\"evaluate\",\"args\":{\"code\":\"(() => document.title)()\"},\"session\":\"default\"}")
echo "evaluate -> $TITLE"
printf '%s' "$TITLE" | grep -q 'Example Domain' && echo "PASS evaluate title is Example Domain" \
  || { echo "FAIL evaluate expected Example Domain"; exit 1; }

# (4) brief pause
sleep 1

# (5) close the scratch tab by its captured id
CLOSE=$(curl -s -X POST "$BASE" -H "$CT" \
  -d "{\"action\":\"tabs_close\",\"args\":{\"tabId\":$TAB_ID},\"session\":\"default\"}")
echo "tabs_close -> $CLOSE"
printf '%s' "$CLOSE" | grep -q '"closed":' && echo "PASS tabs_close closed $TAB_ID" \
  || { echo "FAIL tabs_close"; exit 1; }

echo "ALL PASS — zero-SDK curl driving the Webflow Bridge"
```

Run the same flow as a ready-made script (prints PASS per step, exits non-zero
on any mismatch):

```bash
bash tools/flow_demo.sh
```

That script is the canonical copy of the flow above; `bash tools/flow_demo.sh`
is the one-liner to run the whole proof.

## Notes

- **JSON parsing is optional**: the only value the demo *must* capture is the
  `tabs_open` tab id, extracted with one `sed` — no `jq`, no SDK, pure bash.
- `data.value` is whatever the browser returned (evaluate → the value; cdp →
  the raw CDP result; tabs_* → the shapes in the tables above); error
  responses have no `data`, which makes failure detection a single null-check.
- The daemon answers the `session` field only as `"default"`; any other value
  is a 200-level error.
- Works identically from Python (`requests`/`urllib`), Node (`fetch`), n8n
  (HTTP Request node with `application/json` body) — nothing bridge-specific is
  needed on the client side.
