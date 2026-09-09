# Contributing to Webflow Bridge

Thanks for taking the time! Webflow Bridge is a small, local browser-
automation bridge: a pure-Python-stdlib daemon plus a browser extension that
drives the browser tab you already have open (plus a separate Firefox
edition over WebDriver BiDi). Everything — source, docs and issues — lives
at [github.com/darrenhooooo/webflow-bridge](https://github.com/darrenhooooo/webflow-bridge).

Maintainer contact: darren.hou@outlook.com.

## Reporting bugs

Open a GitHub issue with as much of the following as you can gather:

- **Environment** — OS and version; browser and version (Chrome / Edge /
  Firefox); which daemon you ran (`daemon/webflow_bridge.py` on `:10086` for
  Chrome & Edge, `ff/daemon/ff_bridge.py` on `:10096` for Firefox) and its
  version (startup banner or `git describe --tags`).
- **Steps to reproduce** — the exact commands/actions, kept as short as possible.
- **Expected vs actual** — what you expected to happen and what did.
- **Logs** — daemon console output; for Chrome/Edge the extension popup
  status and the background service-worker console (`chrome://extensions` →
  “Webflow Bridge” → “service worker”); for Firefox the daemon log.

**Security issues must not go into public issues** — email
darren.hou@outlook.com instead, see [SECURITY.md](SECURITY.md).

## Feature requests and questions

Use GitHub Issues too. Describe the real use case (the site, the flow, what
you want the script to end up doing) rather than just an action name — on
the 1.x line only backwards-compatible action additions are accepted (see
docs/VERSIONING.md), and good use-case context is what lets a maintainer
judge whether a request fits.

## Local development setup

Requirements: **Python 3.11+** and Chrome or Edge for the main edition
(Firefox for the `ff/` edition). There is no dependency install step — the
daemons and their smoke tests are **pure Python stdlib by design**; do not
add third-party imports to `daemon/` or `ff/daemon/`.

1. **Start the daemon** (repo root):
   `python3 daemon/webflow_bridge.py` (Windows: `py -3.11 daemon/webflow_bridge.py`,
   or `uv run --python 3.11 daemon/webflow_bridge.py`). First start writes a
   random bearer token to `~/.webflow_bridge/token` and enables auth.
2. **Load the extension**: `chrome://extensions` (or `edge://extensions`) →
   Developer mode → **Load unpacked** → the `extension/` folder. Keep a normal
   http(s) page in the active tab — `chrome://` pages and the stores cannot be
   debugged.
3. **Firefox edition**: follow [ff/README.md](ff/README.md) — its own daemon,
   launcher and optional companion panel.

## Running the smoke tests (required before a PR)

The smoke tests drive the real browser through the full pipeline and print
PASS/FAIL per check, exiting non-zero on any failure:

- Chrome / Edge: `python3 daemon/smoke.py` (optional `--navigate=<url>`).
- Firefox: `ff/daemon/ff_smoke.py`, plus `ff/daemon/ff_p1_smoke.py` and
  `ff/daemon/ff_p2_smoke.py` when your change touches Firefox behaviour.
- Docs-only changes may skip the smokes; anything touching the daemon,
  extension or an action must run the matching smoke green first.

## Pull requests

1. **Fork** the repo and create a **topic branch**. Never push to `main`
   directly — it is force-mirrored from the primary origin and local pushes
   are overwritten.
2. Make one logical change per PR. Keep the scope of edits small and
   self-explanatory.
3. Run the matching smoke tests above and make sure they pass.
4. Describe the change in the PR — especially *behaviour changes*. A change
   to an action's behaviour or response shape must follow the versioning
   policy in [docs/VERSIONING.md](docs/VERSIONING.md) (no silent bumps).
5. Commit style: a short summary line, first line under ~72 characters.
   Chinese or English are both fine — the history uses both (e.g.
   `fix(daemon): reject empty bearer tokens`). User-visible changes should
   get a CHANGELOG.md note; release entries themselves are curated by the
   maintainers at bump time.
6. Line endings: repository text files are **CRLF** — keep the ending style
   of the files you touch (`.gitattributes` forces LF for `*.sh` only).

A maintainer reviews and merges. Note the GitHub Actions workflow here only
mirrors `main` from the primary origin — there is no hosted test CI, so a
green local smoke run is the merge gate.

## Release process (maintainers)

- Version bumps follow [docs/VERSIONING.md](docs/VERSIONING.md) (SemVer 2.0;
  a security/bug fix ships as a patch, e.g. 1.0.0 → 1.0.1).
- Every bump synchronises the version carriers listed there:
  `extension/manifest.json` and `ff/extension/manifest.json`, the
  `docs/HTTP_API.md` title, the dist zip names, `CHANGELOG.md` and the git tag.
- Rebuild artifacts: Chrome/Edge — `python3 tools/rebuild_zip.py` →
  `dist/webflow-bridge-<ver>.zip`; Firefox AMO —
  `python3 ff/extension/rebuild_zip.py` → `dist/webflow-bridge-firefox-<ver>.zip`.
- Gate: Chrome smoke plus the Firefox smokes all green before tagging.
- Tag and push: `git tag v<ver>`, then `tools/push-both.sh "<msg>"` pushes the
  CNB origin and the GitHub public repo (GitHub's mirror workflow then stays
  in sync automatically).

## Code of conduct

Be respectful, constructive and assume good faith — this project follows the
[Contributor Covenant v2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).
Reports go to darren.hou@outlook.com.

