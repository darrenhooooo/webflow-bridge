# Security Policy

## Reporting a vulnerability

Please report security issues **privately** — do not open a public GitHub
issue. Email **darren.hou@outlook.com** with:

- **Affected component and version** — Chrome/Edge daemon (`daemon/`),
  extension, or Firefox edition (`ff/daemon/`); daemon version from the
  startup banner or `git describe --tags`.
- **Environment** — OS, browser and version.
- **Steps to reproduce** and expected vs actual behaviour.
- (Optional) a suggested fix.

**Response commitment**: we acknowledge within **48 hours**, keep you posted
on progress, and ship a fix as a patch release (see the versioning policy in
[docs/VERSIONING.md](docs/VERSIONING.md)). We support coordinated disclosure
and ask that you hold details until the fix is out.

## Supported versions

Current stable line: **1.1.0+**. Security fixes land on the newest stable
line only — older versions should upgrade to the latest release.

## Security posture (as implemented)

Webflow Bridge is local-only by design. The posture below is what the code
actually does — for the threat model behind it, see
[docs/ANTI_ABUSE_PLAN.md](docs/ANTI_ABUSE_PLAN.md); for data handling,
[docs/PRIVACY.md](docs/PRIVACY.md).

- **Loopback only.** The daemon binds `127.0.0.1` — HTTP `:10086` and
  WS `:10087` for Chrome/Edge, HTTP `:10096` for the Firefox edition.
  Nothing is exposed to the LAN or other machines.
- **Shared-secret auth.** Every `POST /command` must carry an
  `Authorization: Bearer` header with the shared token. The token is random,
  generated on first start and stored at `~/.webflow_bridge/token`
  (Chrome/Edge) or `~/.webflow_bridge_ff/token` (Firefox), 0600 on POSIX.
  `--allow-no-auth` exists only as a local migration window.
- **Origin guard.** Browser-originated POSTs are rejected with `403` unless
  the `Origin` is one of the loopback spellings — a CSRF defence against
  malicious web pages; the Firefox companion panel's `moz-extension://`
  origin is additionally allowed.
- **No cloud, no telemetry.** The extension connects only to the local
  daemon; commands and results never leave your device.
- **Minimal dependencies.** Both daemons are pure Python stdlib — no
  third-party runtime packages to audit.
- **Manual install only.** The extension is MV3, loaded unpacked by you; it
  holds a debugger session only on the active tab you drive.

## Scope

This tool drives your own logged-in browser on your command. Treat the token
like a credential — never send it to, or paste it into, a remote process or
a web page. Bugs in documentation or example scripts are appreciated but are
not security issues.

