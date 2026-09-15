#!/usr/bin/env python3
"""Webflow Bridge blocking-scenario range (permanent, self-contained).

A tiny stdlib-only HTTP server that reproduces the browser states which block
or silently break DevTools-protocol (CDP) control. It is meant for regression
testing the dialog / download / failed-page handling of the bridge:

  /                     index page linking/buttoning every scenario
  /beforeunload         arms window.onbeforeunload, then a link to /plain
  /download             Content-Disposition: attachment (native download)
  /auth                 401 + WWW-Authenticate: Basic (native credential box)
  /slow                 sleeps 12 s before responding (page stuck loading)
  /plain                ordinary page
  /dialogs              alert / confirm / prompt buttons (scheduled, so the
                        triggering command returns before the dialog opens)
  /autoalert            alerts on load (dialog opens before a debugger can
                        attach — the attach-before-dialog boundary)
  /popup                target=_blank link + window.open button

Usage:
    python tools/blocking_range.py [--port 8899] [--host 127.0.0.1]

Ctrl+C stops it. No third-party dependencies.
"""
from __future__ import annotations

import argparse
import http.server
import socketserver
import time

INDEX = b"""<!doctype html>
<meta charset=utf-8>
<title>blocking-range</title>
<h1>Webflow Bridge blocking range</h1>
<ul>
  <li><a id="nav" href="/plain">plain page</a></li>
  <li><a id="bu" href="/beforeunload">beforeunload page</a></li>
  <li><a id="dl" href="/download">download (attachment)</a></li>
  <li><a id="au" href="/auth">401 basic-auth page</a></li>
  <li><a id="sl" href="/slow">slow page (12s)</a></li>
  <li><a id="dg" href="/dialogs">dialogs page</a></li>
  <li><a id="aa" href="/autoalert">autoalert page (alert on load)</a></li>
  <li><a id="pp" href="/popup">popup page</a></li>
  <li><a id="fm" href="/form">form page</a></li>
  <li><a id="bg" href="/big">big page (PDF/screenshot)</a></li>
</ul>
<p>
  <button id="b-alert">alert (scheduled)</button>
  <button id="b-confirm">confirm (scheduled)</button>
  <button id="b-prompt">prompt (scheduled)</button>
</p>
<script>
  const schedule = (fn) => setTimeout(fn, 50);
  document.getElementById('b-alert').onclick = () => schedule(() => alert('range alert'));
  document.getElementById('b-confirm').onclick = () => schedule(() => confirm('range confirm?'));
  document.getElementById('b-prompt').onclick = () => schedule(() => prompt('range prompt?', 'default-text'));
</script>
"""

BEFOREUNLOAD = b"""<!doctype html>
<meta charset=utf-8>
<title>beforeunload armed</title>
<h1>beforeunload</h1>
<p><button id="arm">arm onbeforeunload</button>
   <a id="leave" href="/plain">leave this page</a></p>
<script>
  const arm = () => { window.onbeforeunload = () => 'leave?'; document.title = 'armed'; };
  document.getElementById('arm').onclick = arm;
  arm();   // armed on load too (sticky activation may still be required)
</script>
"""

DIALOGS = b"""<!doctype html>
<meta charset=utf-8>
<title>dialogs</title>
<h1>dialogs</h1>
<p><button id="al">alert</button>
   <button id="cf">confirm</button>
   <button id="pr">prompt</button></p>
<script>
  const schedule = (fn) => setTimeout(fn, 50);
  document.getElementById('al').onclick = () => schedule(() => alert('range alert'));
  document.getElementById('cf').onclick = () => schedule(() => confirm('range confirm?'));
  document.getElementById('pr').onclick = () => schedule(() => prompt('range prompt?', 'default-text'));
</script>
"""

AUTOALERT = b"""<!doctype html>
<meta charset=utf-8>
<title>autoalert</title>
<h1>autoalert</h1>
<p>this page opens an alert by itself, shortly after load</p>
<script>
  setTimeout(() => alert('range auto alert'), 150);
</script>
"""

POPUP = b"""<!doctype html>
<meta charset=utf-8>
<title>popup</title>
<h1>popup</h1>
<p><a id="blank" href="/plain" target="_blank">open _blank</a>
   <button id="win">window.open</button></p>
<script>
  document.getElementById('win').onclick = () => window.open('/plain', '_blank');
</script>
"""

PLAIN = b"<!doctype html><meta charset=utf-8><title>plain</title><h1>plain page</h1>"

FORM = b"""<!doctype html>
<meta charset=utf-8>
<title>form</title>
<h1>form</h1>
<p><input id="q" placeholder="type here">
   <button id="go" onclick="document.title='clicked'">go</button></p>
"""


def big_page() -> bytes:
    rows = b"".join(b"<p>row %d lorem ipsum dolor sit amet</p>" % i
                    for i in range(5000))
    return (b"<!doctype html><meta charset=utf-8><title>big</title>"
            b"<h1>big page</h1>" + rows)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):  # keep the console quiet
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 (stdlib API)
        path = self.path.split("?")[0]
        if path == "/":
            self._send(200, "text/html; charset=utf-8", INDEX)
        elif path == "/beforeunload":
            self._send(200, "text/html; charset=utf-8", BEFOREUNLOAD)
        elif path == "/dialogs":
            self._send(200, "text/html; charset=utf-8", DIALOGS)
        elif path == "/autoalert":
            self._send(200, "text/html; charset=utf-8", AUTOALERT)
        elif path == "/popup":
            self._send(200, "text/html; charset=utf-8", POPUP)
        elif path == "/plain":
            self._send(200, "text/html; charset=utf-8", PLAIN)
        elif path == "/form":
            self._send(200, "text/html; charset=utf-8", FORM)
        elif path == "/big":
            self._send(200, "text/html; charset=utf-8", big_page())
        elif path == "/download":
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition",
                             'attachment; filename="range-download.bin"')
            self.send_header("Content-Length", "1024")
            self.end_headers()
            self.wfile.write(b"x" * 1024)
        elif path == "/auth":
            # Native credential prompt; useful to reproduce the cancelled-auth
            # error page (chrome-error://chromewebdata/).
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="blocking-range"')
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/slow":
            time.sleep(12)
            self._send(200, "text/html; charset=utf-8",
                       b"<h1>slow page (12s)</h1>")
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found\n")


class ThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8899)
    opts = parser.parse_args()
    with ThreadingServer((opts.host, opts.port), Handler) as srv:
        print(f"blocking range on http://{opts.host}:{opts.port}  (Ctrl+C stops)")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nstopping")


if __name__ == "__main__":
    main()
