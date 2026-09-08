# Webflow Bridge HTTP API — zero-SDK driver guide (standard browser-bridge agent-tool names)

**Webflow Bridge Command API v0.1.1** · base URL `http://127.0.0.1:10086`
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
```

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

## Error shapes (read them without an SDK)

| HTTP | Body | Meaning |
|---|---|---|
| 200 | `{"status": "ok", "data": {"value": ...}}` | Success; read `data.value`. |
| 200 | `{"status": "error", "error": "..."}` | Bad args / unknown action / extension failure / timeout. |
| 403 | `{"error": "cross-origin POST blocked"}` | A non-localhost `Origin` header was sent (see quickstart). |
| 503 | `{"error": "extension not connected"}` | No Chrome/Edge extension is connected to the daemon. |

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
