# Webflow Bridge Privacy Policy

**Short version: everything stays on your computer.** Webflow Bridge is a
local browser-automation bridge. It never sends data anywhere else.

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
- `scripting` / `activeTab` — declared alongside `debugger` for extension API
  availability.
- `alarms` — a background watchdog that reconnects to the daemon if the
  connection drops.

## Removing Webflow Bridge

1. Uninstall the extension at `chrome://extensions` (remove "Webflow Bridge").
2. Delete this repository.
3. Stop the daemon process running `daemon/rhino_bridge.py`.

No data is stored anywhere, so there is nothing else to delete.
