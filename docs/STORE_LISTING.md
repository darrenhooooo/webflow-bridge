# Chrome Web Store submission kit — Webflow Bridge

Everything needed to fill in the Chrome Web Store item (the `dist/` zip
provides the actual package). Operator fills in the placeholder bits before
uploading.

---

## Name

**Webflow Bridge**

## Summary (≤ 132 chars)

```
Run JS and CDP commands on your active tab from a local daemon. Browser-automation bridge — 100% local, no cloud.
```

(108 chars — copy as-is.)

## Category suggestion

**Developer Tools**

---

## Full description (~120–250 words, Markdown allowed)

> **What it is.** Webflow Bridge is a local browser-automation bridge. Your
> scripts — or any local automation — post commands to
> `http://127.0.0.1:10086`, and Webflow Bridge runs them in your
> real Chrome tab. It attaches to the **active tab** via `chrome.debugger` and
> executes through CDP `Runtime.evaluate` — the exact channel Chrome's DevTools
> console uses. That means arbitrary JavaScript you provide runs in the page's
> own world, immune to page Content-Security-Policy restrictions (strict sites
> like x.com included), and full CDP passthrough (`Input.*`, `Page.*`,
> `DOM.*`, `Network.*`, …) lets scripts drive every browser capability.
>
> A companion local daemon (Python stdlib only, no dependencies) ships in the
> open-source repo and is required — everything runs on your machine and
> **nothing leaves it**: no cloud, no accounts, no telemetry.
>
> **Install & use**
> 1. Load the extension at `chrome://extensions` → Developer mode → Load
>    unpacked → the `extension/` folder.
> 2. Run the daemon from the repo: `uv run --python 3.11 daemon/webflow_bridge.py`
>    (or `python daemon/webflow_bridge.py`).
> 3. Keep Chrome on a real website, then POST a command:
>
>    ```bash
>    curl -s -X POST http://127.0.0.1:10086/command \
>      -H "Content-Type: application/json" \
>      -d '{"action":"evaluate","args":{"code":"(() => document.title)()"},"session":"default"}'
>    ```
>
> **Open source.** MIT-licensed at <https://github.com/darrenhooooo/webflow-bridge>
>
> **Support / feedback.** File an issue at the GitHub repo above, or contact
> <darren.hou@outlook.com>

## Sensitive-permission justifications (paste into the review form)

### `debugger`

The `debugger` permission is the **only** Manifest V3 channel that can
evaluate an arbitrary JavaScript *string* in a page and get the result back:

- Content-script isolated worlds run under a **Chrome-hardcoded CSP** whose
  allowed `script-src` sources omit `eval`/`new Function`, so an in-content
  evaluator cannot work in stable MV3 regardless of the manifest.
- `chrome.scripting.executeScript` no longer accepts code strings at all
  (only `files`/`func`), and compiling the string inside an injected `func`
  is blocked by **page** CSP on strict sites (verified live on x.com).

`chrome.debugger` → CDP `Runtime.evaluate` is the same channel the built-in
DevTools console uses; this extension is effectively a **local DevTools
console driven by a local daemon**. There is no remote-code-execution surface:
the companion daemon binds `127.0.0.1` only and rejects cross-origin POSTs
(Origin guard). All evaluation targets the user's own active/selected tab,
and no data leaves the device.

### `tabs`

Used to pick the tab to drive (the active tab, or a specific tab via
`tabId`), read its URL/title for listings (`tabs_list`), and navigate / open /
close / activate tabs as scripted by the local caller. Same capabilities as
the window/tab management a user performs by hand.

### `scripting`

Used **only** by an opt-in diagnostic probe (`probe` action) that compares
JavaScript-injection paths and reports the results to the local caller. The
main evaluate path never calls `chrome.scripting`.

**Data flow note for all three:** every command originates from a process on
the user's own machine (scripts or `curl` to `http://127.0.0.1:10086`). The
extension makes no network connection except the local WebSocket
`ws://127.0.0.1:10087`; no telemetry, analytics, or third-party code.

## Single purpose statement

> Let users drive their own local browser session with scripted commands from
> a local daemon.

## Privacy

- Full plain-English policy: [`PRIVACY.md`](PRIVACY.md) in the
  repo (MIT, GitHub link above).
- The Chrome Web Store upload form requires a hosted privacy-policy URL —
  publish the policy and set it to **<https://<hosted>/privacy>** (placeholder:
  operator hosts `docs/PRIVACY.md`, e.g. via GitHub Pages).

## Screenshots

Store requires at least one screenshot, **1280×800 or 640×400**. Planned
captures (operator to take later):

1. The toolbar popup (status + "Test on active tab") on a dark background.
2. A "DevTools-like" usage shot: Chrome DevTools console open on a page
   showing the equivalent `Runtime.evaluate` output, or a terminal with the
   `curl` command and its JSON reply next to the page it drove.

## Notes

- Edge Add-ons store is a separate submission from Chrome Web Store (same
  zip/listing assets; different dashboard at microsoftedge.microsoft.com/addons).
