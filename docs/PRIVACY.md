# Webflow Bridge Privacy Policy

**Short version: everything stays on your computer.** Webflow Bridge runs
entirely on your machine. It never sends data anywhere else.

Webflow Bridge has two parts, both of which you run on your own machine:

1. A Python daemon that listens on `http://127.0.0.1:10086` (HTTP) and
   `ws://127.0.0.1:10087` (WebSocket). You install and run it yourself.
2. A Chrome extension ("Webflow Bridge") that connects to that daemon.

## What the extension does

- **Connects only to `ws://127.0.0.1:10087`** — a local daemon running on your
  machine. It makes no other network connections.
- **Reads and can modify the content of the tab you drive.** It attaches to
  the active tab via `chrome.debugger` and evaluates scripts through CDP
  `Runtime.evaluate` — the same channel Chrome's DevTools console uses.
- **Evaluates scripts that you — or local scripts running on your machine —
  send to it**, and can navigate the active tab to other URLs and manage tabs.

## Data

- **All data stays on your machine.** Scripts, page content, and results move
  only between your local scripts, the daemon, and the extension, over the
  loopback addresses `127.0.0.1`.
- **Nothing is transmitted to any remote server.** There is no telemetry, no
  analytics, no usage tracking, and no third-party code.
- **Types of data processed (all local only):**
  - **Website content** — the page content, DOM, and screenshots of the tab you
    choose to drive.
  - **User activity** — the driven tab's network requests and console messages,
    read by the monitoring commands.
  - **Tab URLs and titles** — read for the current tab so the caller knows what
    it is driving.
  These move only in memory between your local scripts, the daemon, and the
  extension; they are not written to disk and not transmitted anywhere. The
  only data persisted locally is the local daemon token and the
  Disconnect/Reconnect state, stored in `chrome.storage.local`.

## Not a remote-code-execution service

The extension is not a cloud or hosted service and receives no commands from
the internet. The daemon is local software that you install and run yourself;
if you do not run it, the extension has nothing to connect to. Anyone with
access to your machine or its local ports could drive the extension, so only
run the daemon on machines you trust.

## Permissions

- `debugger` — attach to a tab (like DevTools) to evaluate scripts and run
  CDP commands.
- `tabs` — read tab URLs/titles and navigate, list, open, close, and activate
  tabs.
- Host permission `http://127.0.0.1/*` — read the local daemon's auth token
  from `http://127.0.0.1:10086/config` when it is not yet cached. Loopback
  only: the extension requests no access to any website.
- `alarms` — a background watchdog that reconnects to the daemon if the
  connection drops.
- `tabGroups` — name the tab group when a script opens a new tab with a group
  title (the `navigate` action's `group_title` option).
- `storage` — save the local daemon token and the Disconnect/Reconnect state
  on this machine, in your browser's local extension storage; this data is
  never uploaded.

## Limited Use

Webflow Bridge's use of user data is limited to providing its single purpose: running the
commands that a script or agent on the user's own machine sends, on the tab the user chooses
to drive.

- It does not sell or transfer user data to third parties.
- It does not use user data for advertising, profiling, or creditworthiness.
- It does not allow humans — including the developer — to read user data: the data never
  leaves the user's device.
- It does not transmit user data anywhere off the device. The only network endpoints are
  loopback: `http://127.0.0.1:10086` (local daemon HTTP) and `ws://127.0.0.1:10087` (local
  daemon WebSocket).

## Removing Webflow Bridge

1. Uninstall the extension at `chrome://extensions` (remove "Webflow Bridge").
2. Delete this repository.
3. Stop the daemon process running `daemon/webflow_bridge.py`.

No browsing data is stored anywhere. The only things the extension saves are
the local daemon token and the Disconnect/Reconnect state, kept in your
browser's local extension storage on this machine and removed when you
uninstall the extension.
