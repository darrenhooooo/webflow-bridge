# Cross-platform support — Webflow Bridge

Platform-neutral by design: pure-Python stdlib daemon + Chromium MV3 extension — the `chrome.debugger` API is identical on Chrome and Edge, macOS and Windows. One repo, one `extension/` folder/zip, two browsers.

## Platform matrix

| OS | Chrome | Microsoft Edge |
|---|---|---|
| macOS | expected-identical | expected-identical |
| Windows 11 | **verified 09-04** | expected-identical |

Verified on Windows 11 + Chrome 152 (2025-09-04); others expected-identical — checklist below.

## Verification checklist

For each new platform combo (macOS/Windows × Chrome/Edge):

1. Install uv (recommended) or Python 3.11+ (Windows: real interpreter, not the Microsoft Store stub).
2. From repo root start the daemon — `uv run --python 3.11 daemon/rhino_bridge.py` or `python3 daemon/rhino_bridge.py`; confirm the "Webflow Bridge daemon started" banner with :10086 / :10087.
3. Load the extension: `chrome://extensions` or `edge://extensions` → Developer mode → Load unpacked → `extension/`.
4. Run `uv run --python 3.11 daemon/smoke.py` (or `python3 daemon/smoke.py`) → expect **6/6 PASS**.
5. Keep an http(s) page active, POST an `evaluate` (curl example in README.md), confirm `document.title` returns.
6. Optional: run the publish-flow smoke against a test account.

## Notes

- Ports 10086/10087 must be free.
- macOS Gatekeeper matters only for a future PyInstaller binary — not this repo's uv/python3 run.
- Edge loads the identical MV3 zip as Chrome.
