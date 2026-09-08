#!/usr/bin/env python3
"""Webflow Bridge for Firefox -- P2 end-to-end smoke test.

Connects to the ff daemon's HTTP endpoint (:10096) and drives a real
Firefox (opened by ff/ff-launch.bat, BiDi on :9222) through the P2 actions
against a LOCAL test page (no external network):

  1. navigate -> http://127.0.0.1:<port>/test_page_p2.html
  2. snapshot  (nodes non-empty, refs @eN contiguous, tag/path present)
  3. click by snapshot ref @eN (side effect on the target button)
  4. fill by snapshot ref @eN (value lands in the field)
  5. list_network_requests (after a page fetch) + get_network_request
  6. list_console_messages (console.log / console.error markers)
  7. handle_dialog alert accept / confirm dismiss / prompt +promptText
  8. handle_dialog with no dialog -> explicit error
  9. handle_file_chooser -> explicit platform error (no BiDi mechanism)
 10. humanize: type_text with humanize:true completes with the right value

Every step prints PASS/FAIL; exit code 0 only when all steps pass.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import sys
import threading
import urllib.error
import urllib.request
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TOKEN_PATH = os.path.join(
    os.path.expanduser("~"), ".webflow_bridge_ff", "token")

failures = []


def read_token(path: str) -> str:
    env = os.environ.get("WBF_FF_TOKEN")
    if env:
        return env.strip()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            tok = fh.read().strip()
            if tok:
                return tok
    except FileNotFoundError:
        pass
    return ""


def post(base: str, token: str, action: str, args: dict) -> dict:
    body = json.dumps({"action": action, "args": args}).encode("utf-8")
    req = urllib.request.Request(
        base + "/command", data=body,
        headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return {"http": resp.status,
                    "body": json.loads(resp.read().decode("utf-8"))}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = {"raw": raw}
        return {"http": exc.code, "body": parsed}
    except urllib.error.URLError as exc:
        return {"http": 0,
                "body": {"error": f"cannot reach daemon: {exc.reason}"}}


class Runner:
    """One smoke run: POST helper + step bookkeeping."""

    def __init__(self, base: str, token: str) -> None:
        self.base = base.rstrip("/")
        self.token = token
        self.n = 0

    def call(self, action: str, args: dict) -> dict:
        r = post(self.base, self.token, action, args)
        body = r.get("body") or {}
        if r.get("http") != 200 or body.get("status") != "ok":
            raise AssertionError(f"{action} failed: http={r.get('http')} "
                                 f"body={json.dumps(body, ensure_ascii=False)[:300]}")
        return body.get("data", {}).get("value")

    def call_raw(self, action: str, args: dict) -> dict:
        """POST an action and return the full response (for error asserts)."""
        r = post(self.base, self.token, action, args)
        return r

    def ev(self, code: str):
        return self.call("evaluate", {"code": code})

    def step(self, name: str, ok: bool, note: str = "") -> None:
        self.n += 1
        flag = "PASS" if ok else "FAIL"
        print(f"STEP {self.n}  {name}")
        print(f"  -> {flag}" + (f"  {note}" if note else ""))
        if not ok:
            failures.append(f"{name}: {note}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:10096",
                        help="ff daemon base URL")
    parser.add_argument("--token", default="",
                        help="bearer token (default: ~/.webflow_bridge_ff/token)")
    parser.add_argument("--no-auth", action="store_true",
                        help="daemon runs with --allow-no-auth")
    opts = parser.parse_args()

    token = "" if opts.no_auth else (opts.token or read_token(DEFAULT_TOKEN_PATH))
    r = Runner(opts.base, token)
    print(f"[ff-p2-smoke] daemon {r.base}  token={'<env/file>' if token else 'none'}")
    print()

    # ---- local http.server for the test page (random free port) ----------
    handler = functools.partial(SimpleHTTPRequestHandler, directory=HERE)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    page = f"http://127.0.0.1:{httpd.server_address[1]}/test_page_p2.html"
    print(f"[ff-p2-smoke] serving test page at {page}")
    print()

    # ---- STEP 1: navigate ------------------------------------------------
    r.n += 1
    print(f"STEP {r.n}  navigate {page}")
    try:
        r.call("navigate", {"url": page})
        title = r.ev("document.title")
        ok = title == "ff-p2-test-page"
        print(f"  -> {'PASS' if ok else 'FAIL'}  title={title!r}")
        if not ok:
            failures.append(f"navigate: title={title!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"navigate: {exc}")
    time.sleep(0.8)          # let img/fetch-ish subresources settle

    # ---- STEP 2: snapshot ------------------------------------------------
    r.n += 1
    print("STEP %d  snapshot {}" % r.n)
    try:
        snap = r.call("snapshot", {})
        nodes = snap.get("nodes") or []
        refs = [n.get("ref") for n in nodes]
        refs_ok = all(n.get("tag") and n.get("path") for n in nodes) \
            and refs == ["@e" + str(i) for i in range(len(refs))] \
            and len(nodes) >= 8
        url_ok = isinstance(snap.get("url"), str) and "test_page_p2" in snap["url"]
        ok = url_ok and snap.get("title") == "ff-p2-test-page" and refs_ok
        print(f"  -> {'PASS' if ok else 'FAIL'}  url_ok={url_ok} nodes={len(nodes)} "
              f"refs_ok={refs_ok}")
        if not ok:
            failures.append(f"snapshot: url_ok={url_ok} nodes={len(nodes)} "
                            f"refs={refs[:6]} nodes0={json.dumps(nodes[0] if nodes else None, ensure_ascii=False)[:200]}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"snapshot: {exc}")

    # ---- STEP 3: snapshot max cap ----------------------------------------
    r.n += 1
    print("STEP %d  snapshot max=3" % r.n)
    try:
        cap = r.call("snapshot", {"max": 3})
        ok = len(cap.get("nodes") or []) <= 3 and isinstance(cap.get("total"), int) \
            and cap["total"] >= 8
        print(f"  -> {'PASS' if ok else 'FAIL'}  nodes={len(cap.get('nodes') or [])} "
              f"total={cap.get('total')}")
        if not ok:
            failures.append(f"snapshot max: nodes={len(cap.get('nodes') or [])} "
                            f"total={cap.get('total')}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"snapshot max: {exc}")

    # ---- STEP 4: click via snapshot ref (full snapshot again first) -------
    r.n += 1
    print("STEP %d  click @eN (snapshot ref -> button)" % r.n)
    try:
        snap = r.call("snapshot", {})
        nodes = snap.get("nodes") or []
        target = None
        for n in nodes:
            if n.get("tag") == "button" and "snap target" in (n.get("text") or ""):
                target = n
                break
        if target is None:
            raise AssertionError("no snap-target button node in snapshot")
        ref = target["ref"]
        val = r.call("click", {"selector": ref})
        label = r.ev("document.querySelector('#btnlabel').textContent")
        ok = (isinstance(val, dict) and val.get("success") is True
              and val.get("tag") == "button" and label == "clicked 1x")
        print(f"  -> {'PASS' if ok else 'FAIL'}  ref={ref} value="
              f"{json.dumps(val, ensure_ascii=False)}  btnlabel={label!r}")
        if not ok:
            failures.append(f"click @ref: value={val!r} btnlabel={label!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"click @ref: {exc}")

    # ---- STEP 5: fill via snapshot ref ------------------------------------
    r.n += 1
    print("STEP %d  fill @eN = 'ref-fill-值'" % r.n)
    try:
        snap = r.call("snapshot", {})
        nodes = snap.get("nodes") or []
        target = None
        for n in nodes:
            if n.get("tag") == "input" and (n.get("name") or "").startswith("snap input"):
                target = n
                break
        if target is None:
            raise AssertionError("no 'snap input' node in snapshot")
        ref = target["ref"]
        val = r.call("fill", {"selector": ref, "value": "ref-fill-值"})
        got = r.ev("document.querySelector('#p2text').value")
        ok = (isinstance(val, dict) and val.get("success") is True
              and val.get("mode") == "value" and got == "ref-fill-值")
        print(f"  -> {'PASS' if ok else 'FAIL'}  ref={ref} value="
              f"{json.dumps(val, ensure_ascii=False)}  got={got!r}")
        if not ok:
            failures.append(f"fill @ref: value={val!r} got={got!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"fill @ref: {exc}")

    # ---- STEP 6: fetch + list_network_requests + get_network_request ------
    r.n += 1
    print("STEP %d  fetch + list_network_requests + get_network_request" % r.n)
    try:
        r.call("click", {"selector": "#btn-fetch"})
        time.sleep(1.2)
        flog = r.ev("document.querySelector('#fetchlog').textContent")
        lv = r.call("list_network_requests", {})
        reqs = lv.get("requests") or []
        hits = [x for x in reqs if "p2_data.txt" in (x.get("url") or "")]
        # The ring buffer accumulates across the session (Chrome semantics),
        # so a re-run of this smoke may see several p2_data.txt requests;
        # the NEWEST record is the one this step just triggered.
        hit = hits[0] if hits else None
        hit_ok = (hit is not None
                  and hit.get("status") == 200
                  and hit.get("method") == "GET"
                  and isinstance(hit.get("mimeType"), str)
                  and isinstance(hit.get("requestId"), str))
        gr = r.call("get_network_request", {"requestId": hit["requestId"]})
        gr_ok = gr.get("found") is True and gr.get("request", {}).get("url") \
            == hit["url"]
        ok = flog.startswith("fetched:p2-local-data-ok") and hit_ok and gr_ok
        print(f"  -> {'PASS' if ok else 'FAIL'}  fetchlog={flog!r} "
              f"total_reqs={len(reqs)} hit_ok={hit_ok} get={gr_ok} "
              f"rec={json.dumps(hit if hit else {}, ensure_ascii=False)[:220]}")
        if not ok:
            failures.append(f"network: flog={flog!r} hit_ok={hit_ok} "
                            f"gr_ok={gr_ok} "
                            f"rec={json.dumps(hit if hit else {}, ensure_ascii=False)[:300]}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"network: {exc}")

    # ---- STEP 7: console markers -------------------------------------------
    r.n += 1
    print("STEP %d  console.log / console.error markers" % r.n)
    try:
        r.call("click", {"selector": "#btn-conlog"})
        r.call("click", {"selector": "#btn-conerr"})
        time.sleep(1.0)
        lv = r.call("list_console_messages", {})
        msgs = lv.get("messages") or []
        log_hit = [m for m in msgs if "p2-console-marker" in (m.get("text") or "")]
        err_hit = [m for m in msgs if "p2-error-marker" in (m.get("text") or "")]
        log_ok = len(log_hit) >= 1 and log_hit[0].get("type") == "log"
        err_ok = len(err_hit) >= 1 and err_hit[0].get("type") == "error"
        ok = log_ok and err_ok
        print(f"  -> {'PASS' if ok else 'FAIL'}  log_ok={log_ok} err_ok={err_ok} "
              f"log_types={[m.get('type') for m in log_hit]} "
              f"err_types={[m.get('type') for m in err_hit]}")
        if not ok:
            failures.append(f"console: log_ok={log_ok} err_ok={err_ok} "
                            f"log_hit={json.dumps(log_hit[:1], ensure_ascii=False)[:200]} "
                            f"err_hit={json.dumps(err_hit[:1], ensure_ascii=False)[:200]}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"console: {exc}")

    # ---- STEP 8: handle_dialog alert (accept; click blocks until handled)
    # NOTE (firefox): a real click whose handler opens a JS dialog blocks the
    # performActions reply until the dialog is handled (same semantics as
    # Chrome's evaluate-based click hanging on the dialog).  The daemon is
    # multi-threaded, so the dialog action runs concurrently with the
    # in-flight click -- exactly how an agent script must drive dialogs.
    r.n += 1
    print("STEP %d  alert -> handle_dialog accept (click in flight)" % r.n)
    try:
        click_out = {}

        def _c1():
            try:
                click_out["value"] = r.call("click", {"selector": "#btn-alert"})
            except Exception as exc:  # noqa: BLE001
                click_out["error"] = str(exc)
        th = threading.Thread(target=_c1)
        th.start()
        time.sleep(0.8)                 # let the dialog open
        val = r.call("handle_dialog", {"action": "accept"})
        th.join(timeout=40)
        time.sleep(0.5)
        dlglog = r.ev("document.querySelector('#dlglog').textContent")
        ok = (click_out.get("value", {}).get("success") is True
              and isinstance(val, dict) and val.get("success") is True
              and val.get("dialog", {}).get("type") == "alert"
              and val.get("dialog", {}).get("message") == "p2-alert-message"
              and dlglog == "alert-accepted")
        print(f"  -> {'PASS' if ok else 'FAIL'}  click={json.dumps(click_out, ensure_ascii=False)[:180]}"
              f"  value={json.dumps(val, ensure_ascii=False)}  dlglog={dlglog!r}")
        if not ok:
            failures.append(f"handle_dialog alert: click={click_out!r} "
                            f"value={val!r} dlglog={dlglog!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"handle_dialog alert: {exc}")

    # ---- STEP 9: handle_dialog confirm (dismiss; concurrent click) ---------
    r.n += 1
    print("STEP %d  confirm -> handle_dialog dismiss" % r.n)
    try:
        click_out = {}

        def _c2():
            try:
                click_out["value"] = r.call("click", {"selector": "#btn-confirm"})
            except Exception as exc:  # noqa: BLE001
                click_out["error"] = str(exc)
        th = threading.Thread(target=_c2)
        th.start()
        time.sleep(0.8)
        val = r.call("handle_dialog", {"action": "dismiss"})
        th.join(timeout=40)
        time.sleep(0.5)
        dlglog = r.ev("document.querySelector('#dlglog').textContent")
        ok = (click_out.get("value", {}).get("success") is True
              and isinstance(val, dict) and val.get("success") is True
              and val.get("accept") is False
              and dlglog == "confirm=false")
        print(f"  -> {'PASS' if ok else 'FAIL'}  click={json.dumps(click_out, ensure_ascii=False)[:160]}"
              f"  value={json.dumps(val, ensure_ascii=False)}  dlglog={dlglog!r}")
        if not ok:
            failures.append(f"handle_dialog dismiss: click={click_out!r} "
                            f"value={val!r} dlglog={dlglog!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"handle_dialog dismiss: {exc}")

    # ---- STEP 10: handle_dialog prompt (accept + promptText; concurrent) ---
    r.n += 1
    print("STEP %d  prompt -> handle_dialog accept + promptText" % r.n)
    try:
        click_out = {}

        def _c3():
            try:
                click_out["value"] = r.call("click", {"selector": "#btn-prompt"})
            except Exception as exc:  # noqa: BLE001
                click_out["error"] = str(exc)
        th = threading.Thread(target=_c3)
        th.start()
        time.sleep(0.8)
        val = r.call("handle_dialog",
                     {"action": "accept", "promptText": "answer-x"})
        th.join(timeout=40)
        time.sleep(0.5)
        dlglog = r.ev("document.querySelector('#dlglog').textContent")
        ok = (click_out.get("value", {}).get("success") is True
              and isinstance(val, dict) and val.get("success") is True
              and val.get("dialog", {}).get("type") == "prompt"
              and dlglog == "prompt=answer-x")
        print(f"  -> {'PASS' if ok else 'FAIL'}  click={json.dumps(click_out, ensure_ascii=False)[:160]}"
              f"  value={json.dumps(val, ensure_ascii=False)}  dlglog={dlglog!r}")
        if not ok:
            failures.append(f"handle_dialog prompt: click={click_out!r} "
                            f"value={val!r} dlglog={dlglog!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"handle_dialog prompt: {exc}")

    # ---- STEP 11: handle_dialog with no dialog -> explicit error -----------
    r.n += 1
    print("STEP %d  handle_dialog with no dialog" % r.n)
    try:
        raw = r.call_raw("handle_dialog",
                         {"action": "accept", "timeoutMs": 1200})
        body = raw.get("body") or {}
        err = body.get("error") or ""
        ok = (raw.get("http") == 200 and body.get("status") == "error"
              and "no JavaScript dialog" in err)
        print(f"  -> {'PASS' if ok else 'FAIL'}  error={err[:120]!r}")
        if not ok:
            failures.append(f"handle_dialog none: raw={json.dumps(raw, ensure_ascii=False)[:250]}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"handle_dialog none: {exc}")

    # ---- STEP 12: handle_file_chooser -> explicit platform error -----------
    r.n += 1
    print("STEP %d  handle_file_chooser (unsupported on firefox)" % r.n)
    try:
        raw = r.call_raw("handle_file_chooser", {"file": os.path.abspath(__file__)})
        body = raw.get("body") or {}
        err = body.get("error") or ""
        ok = (raw.get("http") == 200 and body.get("status") == "error"
              and "not supported" in err and "upload" in err)
        print(f"  -> {'PASS' if ok else 'FAIL'}  error={err[:160]!r}")
        if not ok:
            failures.append(f"handle_file_chooser: raw={json.dumps(raw, ensure_ascii=False)[:250]}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"handle_file_chooser: {exc}")

    # ---- STEP 13: humanize pacing on type_text ------------------------------
    r.n += 1
    print("STEP %d  type_text humanize:true into #p2ta" % r.n)
    try:
        val = r.call("type_text",
                     {"text": "密算ok-1", "selector": "#p2ta",
                      "humanize": True})
        got = r.ev("document.querySelector('#p2ta').value")
        ok = (isinstance(val, dict) and val.get("success") is True
              and got == "密算ok-1")
        print(f"  -> {'PASS' if ok else 'FAIL'}  value={json.dumps(val, ensure_ascii=False)}"
              f"  ta.value={got!r}")
        if not ok:
            failures.append(f"humanize type_text: value={val!r} got={got!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"humanize type_text: {exc}")

    httpd.shutdown()
    print()
    if failures:
        print("[ff-p2-smoke] FAILED:")
        for f in failures:
            print("  - " + f)
        return 1
    print("[ff-p2-smoke] PASSED: all steps ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
