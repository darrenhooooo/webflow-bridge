#!/usr/bin/env python3
"""Webflow Bridge for Firefox -- P1 end-to-end smoke test.

Connects to the ff daemon's HTTP endpoint (:10096) and drives a real
Firefox (opened by ff/ff-launch.bat, BiDi on :9222) through the P1 actions
against a LOCAL test page (no external network):

  1. navigate  -> http://127.0.0.1:<port>/test_page.html   (local http.server)
  2. click #btn                 (real pointer click; button counter side effect)
  3. fill #text / #ta / #ce / #sel   (value setter + contenteditable typing)
  4. type_text into #ta         (real key events, CJK + newline)
  5. send_key Enter on #text    (keydown reaches the page)
  6. mouse_click #btn           (selector center + raw coordinates)
  7. screenshot                 (PNG default / JPEG quality / element clip)
  8. save_as_pdf                (PDF base64)
  9. upload #file               (input.setFiles with a repo file)

Every step prints PASS/FAIL; exit code 0 only when all steps pass.
"""
from __future__ import annotations

import argparse
import base64
import functools
import json
import os
import struct
import sys
import threading
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TOKEN_PATH = os.path.join(
    os.path.expanduser("~"), ".webflow_bridge_ff", "token")
UPLOAD_FILE = os.path.join(
    os.path.dirname(HERE), os.pardir, "LICENSE")

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
        """POST an action; expect HTTP 200 + status ok -> data.value."""
        r = post(self.base, self.token, action, args)
        body = r.get("body") or {}
        if r.get("http") != 200 or body.get("status") != "ok":
            raise AssertionError(f"{action} failed: http={r.get('http')} "
                                 f"body={json.dumps(body, ensure_ascii=False)[:300]}")
        return body.get("data", {}).get("value")

    def ev(self, code: str):
        """evaluate JS -> unwrapped value (raises when evaluate errors)."""
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
    print(f"[ff-p1-smoke] daemon {r.base}  token={'<env/file>' if token else 'none'}")
    print(f"[ff-p1-smoke] upload file: {UPLOAD_FILE} "
          f"(exists={os.path.isfile(UPLOAD_FILE)})")
    print()

    # ---- local http.server for the test page (random free port) ----------
    handler = functools.partial(SimpleHTTPRequestHandler, directory=HERE)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    page = f"http://127.0.0.1:{httpd.server_address[1]}/test_page.html"
    print(f"[ff-p1-smoke] serving test page at {page}")
    print()

    # ---- STEP: navigate + title ------------------------------------------
    r.n += 1
    print(f"STEP {r.n}  navigate {page}")
    try:
        r.call("navigate", {"url": page})
        title = r.ev("document.title")
        ok = title == "ff-p1-test-page"
        print(f"  -> {'PASS' if ok else 'FAIL'}  title={title!r}")
        if not ok:
            failures.append(f"navigate/title: expected ff-p1-test-page, got {title!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"navigate: {exc}")

    # ---- STEP: click #btn (counter side effect) ---------------------------
    r.n += 1
    print(f"STEP {r.n}  click #btn")
    try:
        val = r.call("click", {"selector": "#btn"})
        label = r.ev("document.querySelector('#btnlabel').textContent")
        ok = (isinstance(val, dict) and val.get("success") is True
              and val.get("tag") == "button" and label == "clicked 1x")
        print(f"  -> {'PASS' if ok else 'FAIL'}  value={json.dumps(val, ensure_ascii=False)}"
              f"  btnlabel={label!r}")
        if not ok:
            failures.append(f"click: value={val!r} btnlabel={label!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"click: {exc}")

    # ---- STEP: fill #text (value setter path) -----------------------------
    r.n += 1
    print(f"STEP {r.n}  fill #text = 'hello 世界'")
    try:
        val = r.call("fill", {"selector": "#text", "value": "hello 世界"})
        got = r.ev("document.querySelector('#text').value")
        ok = (isinstance(val, dict) and val.get("success") is True
              and val.get("mode") == "value" and val.get("tag") == "input"
              and got == "hello 世界")
        print(f"  -> {'PASS' if ok else 'FAIL'}  value={json.dumps(val, ensure_ascii=False)}"
              f"  input.value={got!r}")
        if not ok:
            failures.append(f"fill #text: value={val!r} got={got!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"fill #text: {exc}")

    # ---- STEP: type_text into empty #ta (real keys, CJK + newline) --------
    r.n += 1
    print(f"STEP {r.n}  type_text #ta = '第一行\\n第二行😀'")
    try:
        val = r.call("type_text", {"text": "第一行\n第二行😀", "selector": "#ta"})
        got = r.ev("document.querySelector('#ta').value")
        want = "第一行\n第二行😀"
        ok = (isinstance(val, dict) and val.get("success") is True
              and val.get("len") == 9 and got == want)
        print(f"  -> {'PASS' if ok else 'FAIL'}  value={json.dumps(val, ensure_ascii=False)}"
              f"  ta.value={got!r}")
        if not ok:
            failures.append(f"type_text: value={val!r} got={got!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"type_text: {exc}")

    # ---- STEP: fill #ta multiline overwrite (value setter) ----------------
    r.n += 1
    print(f"STEP {r.n}  fill #ta multiline")
    try:
        val = r.call("fill", {"selector": "#ta",
                              "value": "第一行\n第二行\n第三行"})
        got = r.ev("document.querySelector('#ta').value")
        ok = (isinstance(val, dict) and val.get("success") is True
              and val.get("tag") == "textarea" and got == "第一行\n第二行\n第三行")
        print(f"  -> {'PASS' if ok else 'FAIL'}  value={json.dumps(val, ensure_ascii=False)}"
              f"  ta.value={got!r}")
        if not ok:
            failures.append(f"fill #ta: value={val!r} got={got!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"fill #ta: {exc}")

    # ---- STEP: fill #ce contenteditable (real click + typed keys) ---------
    r.n += 1
    print(f"STEP {r.n}  fill #ce contenteditable = '密算✨ok'")
    try:
        val = r.call("fill", {"selector": "#ce", "value": "密算✨ok",
                              "mode": "contenteditable"})
        got = r.ev("document.querySelector('#ce').innerText")
        ok = (isinstance(val, dict) and val.get("success") is True
              and val.get("mode") == "contenteditable"
              and got == "密算✨ok")
        print(f"  -> {'PASS' if ok else 'FAIL'}  value={json.dumps(val, ensure_ascii=False)}"
              f"  ce.innerText={got!r}")
        if not ok:
            failures.append(f"fill #ce: value={val!r} got={got!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"fill #ce: {exc}")

    # ---- STEP: fill #sel select -------------------------------------------
    r.n += 1
    print(f"STEP {r.n}  fill #sel = 'beta'")
    try:
        val = r.call("fill", {"selector": "#sel", "value": "beta"})
        got = r.ev("document.querySelector('#sel').value")
        ok = (isinstance(val, dict) and val.get("success") is True
              and val.get("tag") == "select" and got == "beta")
        print(f"  -> {'PASS' if ok else 'FAIL'}  value={json.dumps(val, ensure_ascii=False)}"
              f"  sel.value={got!r}")
        if not ok:
            failures.append(f"fill #sel: value={val!r} got={got!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"fill #sel: {exc}")

    # ---- STEP: send_key Enter on #text ------------------------------------
    r.n += 1
    print(f"STEP {r.n}  send_key Enter on #text")
    try:
        val = r.call("send_key", {"key": "Enter", "selector": "#text"})
        got = r.ev("document.querySelector('#enterlog').textContent")
        ok = (isinstance(val, dict) and val.get("success") is True
              and val.get("key") == "Enter" and got == "Enter seen")
        print(f"  -> {'PASS' if ok else 'FAIL'}  value={json.dumps(val, ensure_ascii=False)}"
              f"  enterlog={got!r}")
        if not ok:
            failures.append(f"send_key: value={val!r} enterlog={got!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"send_key: {exc}")

    # ---- STEP: mouse_click #btn (selector center) -------------------------
    r.n += 1
    print(f"STEP {r.n}  mouse_click #btn (selector)")
    try:
        val = r.call("mouse_click", {"selector": "#btn"})
        label = r.ev("document.querySelector('#btnlabel').textContent")
        ok = (isinstance(val, dict) and val.get("success") is True
              and label == "clicked 2x")
        print(f"  -> {'PASS' if ok else 'FAIL'}  value={json.dumps(val, ensure_ascii=False)}"
              f"  btnlabel={label!r}")
        if not ok:
            failures.append(f"mouse_click selector: value={val!r} label={label!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"mouse_click selector: {exc}")

    # ---- STEP: mouse_click raw coordinates --------------------------------
    r.n += 1
    print(f"STEP {r.n}  mouse_click (x,y of #btn center)")
    try:
        rc = json.loads(r.ev(
            "JSON.stringify((()=>{const b=document.querySelector('#btn');"
            "const r=b.getBoundingClientRect();"
            "return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})())"))
        val = r.call("mouse_click", {"x": rc["x"], "y": rc["y"]})
        label = r.ev("document.querySelector('#btnlabel').textContent")
        ok = (isinstance(val, dict) and val.get("success") is True
              and val.get("x") == rc["x"] and val.get("y") == rc["y"]
              and label == "clicked 3x")
        print(f"  -> {'PASS' if ok else 'FAIL'}  value={json.dumps(val, ensure_ascii=False)}"
              f"  btnlabel={label!r}")
        if not ok:
            failures.append(f"mouse_click coords: value={val!r} label={label!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"mouse_click coords: {exc}")

    # ---- STEP: screenshot (png default + jpeg + element) ------------------
    r.n += 1
    print(f"STEP {r.n}  screenshot png / jpeg / element")
    try:
        png = r.call("screenshot", {})
        raw_png = base64.b64decode(png.get("base64", ""))
        ok_png = (isinstance(png, dict) and png.get("mime") == "image/png"
                  and raw_png[:8] == b"\x89PNG\r\n\x1a\n"
                  and isinstance(png.get("width"), int) and png["width"] > 0
                  and isinstance(png.get("height"), int) and png["height"] > 0)
        # daemon-reported size must match the real PNG IHDR
        ih_w, ih_h = struct.unpack(">II", raw_png[16:24])
        ok_size = ok_png and ih_w == png["width"] and ih_h == png["height"]

        jpg = r.call("screenshot", {"format": "jpeg", "quality": 60})
        raw_jpg = base64.b64decode(jpg.get("base64", ""))
        ok_jpg = (isinstance(jpg, dict) and jpg.get("mime") == "image/jpeg"
                  and raw_jpg[:3] == b"\xff\xd8\xff")

        el = r.call("screenshot", {"selector": "#btn"})
        raw_el = base64.b64decode(el.get("base64", ""))
        ok_el = (isinstance(el, dict) and el.get("mime") == "image/png"
                 and raw_el[:8] == b"\x89PNG\r\n\x1a\n"
                 and isinstance(el.get("width"), int) and el["width"] > 0)

        ok = ok_png and ok_size and ok_jpg and ok_el
        print(f"  -> {'PASS' if ok else 'FAIL'}  png(w={png.get('width')},"
              f"h={png.get('height')},ihdr={ih_w}x{ih_h},head={raw_png[:4]!r})"
              f"  jpeg(mime={jpg.get('mime')},head={raw_jpg[:3]!r})"
              f"  element(w={el.get('width')})")
        if not ok:
            failures.append(f"screenshot: png_ok={ok_png} size_ok={ok_size} "
                            f"jpeg_ok={ok_jpg} el_ok={ok_el} "
                            f"png={png!r} jpg={jpg!r} el={el!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"screenshot: {exc}")

    # ---- STEP: save_as_pdf ------------------------------------------------
    r.n += 1
    print(f"STEP {r.n}  save_as_pdf")
    try:
        val = r.call("save_as_pdf", {})
        raw = base64.b64decode(val.get("base64", ""))
        ok = (isinstance(val, dict) and val.get("mime") == "application/pdf"
              and raw[:5] == b"%PDF-")
        print(f"  -> {'PASS' if ok else 'FAIL'}  mime={val.get('mime')} "
              f"pdfHead={raw[:5]!r} bytes={len(raw)}")
        if not ok:
            failures.append(f"save_as_pdf: {val!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"save_as_pdf: {exc}")

    # ---- STEP: upload #file ------------------------------------------------
    r.n += 1
    print(f"STEP {r.n}  upload #file <- {os.path.basename(UPLOAD_FILE)}")
    try:
        val = r.call("upload", {"selector": "#file", "file": UPLOAD_FILE})
        got = r.ev("document.querySelector('#filename').textContent")
        ok = (isinstance(val, dict) and val.get("success") is True
              and val.get("tag") == "input" and got == os.path.basename(UPLOAD_FILE))
        print(f"  -> {'PASS' if ok else 'FAIL'}  value={json.dumps(val, ensure_ascii=False)}"
              f"  filename={got!r}")
        if not ok:
            failures.append(f"upload: value={val!r} filename={got!r}")
    except AssertionError as exc:
        print(f"  -> FAIL  {exc}")
        failures.append(f"upload: {exc}")

    httpd.shutdown()
    print()
    if failures:
        print("[ff-p1-smoke] FAILED:")
        for f in failures:
            print("  - " + f)
        return 1
    print("[ff-p1-smoke] PASSED: all steps ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
