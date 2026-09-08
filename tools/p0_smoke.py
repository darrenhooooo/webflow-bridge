#!/usr/bin/env python3
"""Webflow Bridge P0 smoke test — exercises every new P0 action end to end.

Covers (daemon HTTP :10086 -> WS :10087 -> extension -> real tab):
  evaluate isolation (replMode), snapshot pagination (start/total/@eN across
  pages), fill_form, submit (requestSubmit), wait_for (dynamic element),
  handle_dialog (confirm dismiss + prompt answer), drop (local file drag),
  resize_page (+clear), list/get network requests, list console messages.

Prerequisites (one-time):
  1. daemon running with the NEW code:
       python3 daemon/webflow_bridge.py            (restart if it was running)
  2. extension reloaded at chrome://extensions (after the background.js edit)
  3. this page server running:
       python3 -m http.server 8921 -d tools/devtest
  4. Chrome open, ACTIVE tab on a normal page (the script navigates it)

Usage:
    python3 tools/p0_smoke.py            (full run, ~25 s)
Prints PASS/FAIL per check; exits non-zero when anything fails.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request

ENDPOINT = "http://127.0.0.1:10086/command"
PAGE = "http://127.0.0.1:8921/p0_test_page.html"


def post(payload: dict):
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=140) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"raw": raw}
    except urllib.error.URLError as exc:
        return None, {"error": f"cannot reach daemon: {exc.reason}"}


def act(action: str, args=None):
    return post({"action": action, "args": args or {}, "session": "default"})


def evaluate(code: str):
    return act("evaluate", {"code": code})


def ok_value(resp):
    """(status, body) -> (True, value) on ok, else (False, error-text)."""
    status, body = resp
    if status is None:
        return False, f"daemon unreachable: {body.get('error')}"
    if status == 503 or "extension not connected" in str(body.get("error", "")):
        return False, "extension not connected — load/reload the extension and keep Chrome on a page"
    if status != 200 or body.get("status") != "ok":
        return False, f"expected ok, got status={status} body={body}"
    return True, body.get("data", {}).get("value")


def check(name: str, fn) -> bool:
    try:
        ok, detail = fn()
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, f"unexpected exception: {exc!r}"
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok and detail:
        print(f"        {detail}")
    return ok


# One injected initialiser: the test page is STATIC html; the harness wires
# window.__p0, listeners and the 60 #many buttons after navigation via
# Runtime.evaluate (avoids any inline-script timing under debugger attach).
INIT_JS = r'''(() => {
  if (window.__p0init) return "already";
  window.__p0 = { submit: 0, submitBtnClicked: 0, submitData: null,
                  confirm: null, prompt: null, drop: 0, dropNames: [] };
  const $ = (id) => document.querySelector(id);
  document.getElementById("f1").addEventListener("submit", (e) => {
    e.preventDefault();
    const d = new FormData(e.target);
    window.__p0.submit = 1;
    window.__p0.submitData = { name: d.get("name"), email: d.get("email"),
                               role: d.get("role"), bio: d.get("bio") };
    $("#submit-result").textContent = "submitted:" + JSON.stringify(window.__p0.submitData);
  });
  $("#btn-submit").addEventListener("click", () => { window.__p0.submitBtnClicked = 1; });
  $("#btn-confirm").addEventListener("click", () => {
    setTimeout(() => {
      window.__p0.confirm = window.confirm("confirm-msg-77");
      $("#dialog-result").textContent = "confirm:" + window.__p0.confirm;
    }, 30);
  });
  $("#btn-prompt").addEventListener("click", () => {
    setTimeout(() => {
      const v = window.prompt("prompt-msg-77");
      window.__p0.prompt = v;
      $("#dialog-result").textContent = "prompt:" + String(v);
    }, 30);
  });
  $("#btn-late").addEventListener("click", () => {
    setTimeout(() => {
      const div = document.createElement("div");
      div.id = "late-target";
      div.textContent = "late element alpha-42";
      $("#late-zone").appendChild(div);
    }, 1200);
  });
  const dz = $("#dropzone");
  ["dragenter", "dragover"].forEach((t) => dz.addEventListener(t, (e) => e.preventDefault()));
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    window.__p0.drop = e.dataTransfer.files.length;
    window.__p0.dropNames = Array.from(e.dataTransfer.files).map((f) => f.name + ":" + f.size);
    $("#dropinfo").textContent = "dropped:" + window.__p0.dropNames.join(",");
  });
  const wrap = document.createElement("div");
  wrap.id = "many";
  for (let i = 0; i < 60; i += 1) {
    const b = document.createElement("button");
    b.textContent = "item-" + i;
    b.className = "many-item";
    wrap.appendChild(b);
  }
  document.body.appendChild(wrap);
  window.__p0init = 1;
  console.log("page-console-ready-88");
  return "init-ok";
})()'''


def main() -> int:
    print("Webflow Bridge P0 smoke (new actions, live browser)")
    failures = 0
    cases = []

    # ---- navigation + readiness ---------------------------------------
    def c_navigate():
        st, body = act("navigate", {"url": PAGE})
        if st != 200 or body.get("status") != "ok":
            return False, f"navigate failed: {body}"
        # wait for FULL document (readyState complete + static form present)
        # before injecting — evaluating mid-parse hits a partial document.
        deadline = time.time() + 8
        while time.time() < deadline:
            time.sleep(0.3)
            ok, v = ok_value(evaluate(
                "(() => (document.readyState === 'complete' && "
                "!!document.getElementById('f1')))()"))
            if ok and v is True:
                break
            if not ok and 'not connected' in str(v).lower():
                return False, v
        else:
            return False, "document never reached complete with #f1"
        ok, v = ok_value(evaluate(INIT_JS))
        if not ok:
            return False, f"init injection failed: {v}"
        deadline = time.time() + 5
        while time.time() < deadline:
            time.sleep(0.2)
            ok, v = ok_value(evaluate(
                "(() => { const m = document.getElementById('many'); "
                "return m ? m.children.length : -1; })()"))
            if ok and isinstance(v, int) and v >= 60:
                return True, "page ready (init injected + 60 buttons)"
        return False, f"#many never reached 60: last={v!r}"
    cases.append(("navigate + inject P0 test page", c_navigate))

    # ---- 1. evaluate isolation (replMode: repeated top-level let/const) ----
    def c_eval_iso():
        ok, v = ok_value(evaluate("let __iso_v = 41; __iso_v"))
        if not ok:
            return False, f"first let-run failed: {v}"
        ok2, v2 = ok_value(evaluate("let __iso_v = 42; __iso_v"))
        if not ok2:
            return False, f"SECOND let-run failed (replMode missing?): {v2}"
        if v != 41 or v2 != 42:
            return False, f"values wrong: {v!r} {v2!r}"
        return True, "let redeclaration is legal (console semantics)"
    cases.append(("evaluate isolation: repeated top-level let", c_eval_iso))

    # ---- 2/3. snapshot pagination --------------------------------------
    def c_snap_p0():
        ok, v = ok_value(act("snapshot", {"max": 10}))
        if not ok:
            return False, v
        nodes = (v or {}).get("nodes") or []
        total = (v or {}).get("total")
        if not isinstance(total, int) or total < 60:
            return False, f"expected total >= 60, got {total}"
        if len(nodes) != 10 or nodes[0].get("ref") != "@e0":
            return False, f"page0 wrong: len={len(nodes)} first={nodes[0] if nodes else None}"
        return True, f"total={total} page0 @e0..@e{9}"
    cases.append(("snapshot page 0 (max=10, total reported)", c_snap_p0))

    def c_snap_p1():
        ok, v = ok_value(act("snapshot", {"max": 10, "start": 10}))
        if not ok:
            return False, v
        nodes = (v or {}).get("nodes") or []
        if len(nodes) != 10:
            return False, f"expected 10 nodes on page 1, got {len(nodes)}"
        refs = [n.get("ref") for n in nodes]
        if refs[0] != "@e10":
            return False, f"page1 must start at @e10 (full-list ref), got {refs[:3]}"
        return True, f"refs {refs[0]}..{refs[-1]}"
    cases.append(("snapshot page 1 (start=10, full-list @e refs)", c_snap_p1))

    # @eN 是全列表文档序索引, 与页面元素编号无关: 可见可交互元素从
    # input#name 起为 @e0..@e7, INIT_JS 注入的 #many 按钮从 @e8 起,
    # 因此 item-2 = @e10。不能硬编码 "点击 @e10 就是 item-10",
    # 而是从快照拿 page-1 第一个 ref 再点击, 验证其点击结果与快照一致。
    def c_click_page1_ref():
        ok, v = ok_value(act("snapshot", {"max": 10, "start": 10}))
        if not ok:
            return False, f"page-1 snapshot failed: {v}"
        nodes = (v or {}).get("nodes") or []
        if not nodes:
            return False, "page-1 snapshot returned no nodes"
        ref = nodes[0].get("ref")
        snap_text = (nodes[0].get("text") or "").strip()
        if not ref or not snap_text:
            return False, f"page-1 first node lacks ref/text: {nodes[0]}"
        ok, v = ok_value(act("click", {"selector": ref}))
        if not ok:
            return False, f"click {ref} failed: {v}"
        if not (v or {}).get("success"):
            return False, f"click not success: {v}"
        text = (v or {}).get("text", "").strip()
        if text != snap_text:
            return False, f"clicked wrong element (text={text!r}, snapshot={snap_text!r}); page-1 @e ref must stay valid"
        return True, f"clicked {ref}: {text!r}"
    cases.append(("click page-1 snapshot ref matches snapshot", c_click_page1_ref))

    # ---- 4/5. fill_form + verify ---------------------------------------
    def c_fill_form():
        fields = [
            {"selector": "#name", "value": "Ada"},
            {"selector": "#email", "value": "ada@example.com"},
            {"selector": "#role", "value": "beta"},
            {"selector": "#bio", "value": "hello p0"},
        ]
        ok, v = ok_value(act("fill_form", {"fields": fields}))
        if not ok:
            return False, v
        if not (v or {}).get("success"):
            return False, f"fill_form not success: {v}"
        if len((v or {}).get("filled", [])) != 4 or (v or {}).get("errors"):
            return False, f"expected 4 filled / 0 errors, got {v}"
        return True, f"filled: {v.get('filled')}"
    cases.append(("fill_form batch (input/email/select/textarea)", c_fill_form))

    def c_verify_filled():
        ok, v = ok_value(evaluate(
            "(() => ({n: document.getElementById('name').value,"
            " e: document.getElementById('email').value,"
            " r: document.getElementById('role').value,"
            " b: document.getElementById('bio').value}))()"))
        if not ok:
            return False, v
        want = {"n": "Ada", "e": "ada@example.com", "r": "beta", "b": "hello p0"}
        if v != want:
            return False, f"values mismatch: {v!r} != {want!r}"
        return True, "all four controls hold the filled values"
    cases.append(("fill_form values readable back", c_verify_filled))

    # ---- 6. submit -----------------------------------------------------
    def c_submit():
        ok, v = ok_value(act("submit", {"selector": "#f1"}))
        if not ok:
            return False, f"submit failed: {v}"
        if not (v or {}).get("success") or (v or {}).get("mode") != "requestSubmit":
            return False, f"unexpected submit reply: {v}"
        ok2, v2 = ok_value(evaluate("(() => window.__p0.submit)()"))
        if not ok2 or v2 != 1:
            return False, f"form submit handler not reached: {v2}"
        return True, f"mode=requestSubmit; submit handler fired"
    cases.append(("submit requestSubmit on form #f1", c_submit))

    # ---- 7. wait_for ---------------------------------------------------
    def c_wait_for():
        ok, _ = ok_value(act("click", {"selector": "#btn-late"}))
        if not ok:
            return False, "cannot click #btn-late"
        ok, v = ok_value(act("wait_for", {"text": "late element alpha-42", "timeoutMs": 6000}))
        if not ok:
            return False, f"wait_for failed: {v}"
        if not (v or {}).get("found"):
            return False, f"not found: {v}"
        elapsed = (v or {}).get("elapsedMs", 0)
        if elapsed < 900:
            return False, f"returned too fast ({elapsed}ms) — element appears after 1200ms"
        return True, f"found in {elapsed}ms (dynamic 1.2s element)"
    cases.append(("wait_for dynamic element (text)", c_wait_for))

    # ---- 8/9. handle_dialog --------------------------------------------
    def c_dialog_confirm_dismiss():
        ok, _ = ok_value(act("click", {"selector": "#btn-confirm"}))
        if not ok:
            return False, "cannot click #btn-confirm"
        time.sleep(0.4)
        ok, v = ok_value(act("handle_dialog", {"accept": False}))
        if not ok:
            return False, f"handle_dialog failed: {v}"
        time.sleep(0.2)
        ok2, v2 = ok_value(evaluate("(() => window.__p0.confirm)()"))
        if not ok2 or v2 is not False:
            return False, f"confirm should be dismissed (false), got {v2!r}"
        return True, "confirm dialog dismissed (accept=false)"
    cases.append(("handle_dialog dismiss confirm", c_dialog_confirm_dismiss))

    def c_dialog_prompt_answer():
        ok, _ = ok_value(act("click", {"selector": "#btn-prompt"}))
        if not ok:
            return False, "cannot click #btn-prompt"
        time.sleep(0.4)
        ok, v = ok_value(act("handle_dialog", {"accept": True, "promptText": "typed-77"}))
        if not ok:
            return False, f"handle_dialog prompt failed: {v}"
        time.sleep(0.2)
        ok2, v2 = ok_value(evaluate("(() => window.__p0.prompt)()"))
        if not ok2 or v2 != "typed-77":
            return False, f"prompt should return 'typed-77', got {v2!r}"
        return True, "prompt answered with promptText"
    cases.append(("handle_dialog answer prompt", c_dialog_prompt_answer))

    # ---- 10. drop ------------------------------------------------------
    def c_drop():
        fd, path = tempfile.mkstemp(prefix="p0_drop_", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("hello-p0-file")
        try:
            ok, v = ok_value(act("drop", {"selector": "#dropzone", "file": path}))
            if not ok:
                return False, f"drop failed: {v}"
            if not (v or {}).get("success") or (v or {}).get("dropped") != 1:
                return False, f"drop reply: {v}"
            ok2, v2 = ok_value(evaluate(
                "(() => ({c: window.__p0.drop, names: window.__p0.dropNames}))()"))
            if not ok2 or v2.get("c") != 1:
                return False, f"dropzone got no file: {v2}"
            name = os.path.basename(path)
            if not any(n.startswith(name) for n in (v2.get("names") or [])):
                return False, f"dropped name mismatch: {v2.get('names')} vs {name}"
            return True, f"dropped {name} onto #dropzone (DataTransfer)"
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
    cases.append(("drop local file onto dropzone", c_drop))

    # ---- 10b. file chooser upload --------------------------------------
    def c_file_chooser_upload():
        # ensure the fixed local upload file exists (rewrite each run)
        try:
            open("/tmp/p0_upload.txt", "w").write("p0-file-upload")
        except OSError as exc:
            return False, f"cannot write /tmp/p0_upload.txt: {exc}"
        # 1. inject a file input if it is not already there
        ok, v = ok_value(evaluate(
            "(() => { if (!document.getElementById('fc1')) {"
            " const i = document.createElement('input');"
            " i.type = 'file'; i.id = 'fc1'; document.body.appendChild(i); }"
            " return 'injected'; })()"))
        if not ok or v != "injected":
            return False, f"inject #fc1 failed: {v!r}"
        # 2. click it -> native chooser intercepted (no system dialog)
        ok, v = ok_value(act("click", {"selector": "#fc1"}))
        if not ok:
            return False, f"click #fc1 failed: {v}"
        # 3. answer the intercepted chooser with the local file
        ok, v = ok_value(act("handle_file_chooser",
                             {"file": "/tmp/p0_upload.txt", "timeoutMs": 5000}))
        if not ok:
            return False, f"handle_file_chooser failed: {v}"
        if not (v or {}).get("success"):
            return False, f"handle_file_chooser not success: {v}"
        # 4. the input must now hold the file
        ok, v = ok_value(evaluate(
            "(() => { const f = document.getElementById('fc1').files;"
            " return { len: f.length, name: f.length ? f[0].name : '' }; })()"))
        if not ok:
            return False, f"read files failed: {v}"
        if (v or {}).get("len", 0) < 1:
            return False, f"#fc1.files empty after upload: {v}"
        if (v or {}).get("name") != "p0_upload.txt":
            return False, f"file name mismatch: {v}"
        return True, f"uploaded {v.get('name')} via intercepted chooser"
    cases.append(("file chooser upload via handle_file_chooser", c_file_chooser_upload))

    # ---- 11. resize_page + clear ---------------------------------------
    def c_resize():
        ok, before = ok_value(evaluate("(() => window.innerWidth)()"))
        if not ok:
            return False, before
        ok, v = ok_value(act("resize_page", {"width": 900, "height": 700}))
        if not ok:
            return False, f"resize_page failed: {v}"
        time.sleep(0.5)
        ok, after = ok_value(evaluate("(() => window.innerWidth)()"))
        if not ok:
            return False, after
        if after != 900:
            return False, f"innerWidth should be 900 after resize, got {after} (was {before})"
        ok, _ = ok_value(act("cdp", {"method": "Emulation.clearDeviceMetricsOverride"}))
        time.sleep(0.4)
        ok, restored = ok_value(evaluate("(() => window.innerWidth)()"))
        if ok and restored == 900:
            return False, "viewport stayed 900 after clearDeviceMetricsOverride"
        return True, f"innerWidth {before} -> {after} -> {restored if ok else '?'}"
    cases.append(("resize_page 900px + clear override", c_resize))

    # ---- 12. network requests ------------------------------------------
    def c_network():
        ok, v = ok_value(evaluate(
            "fetch('/data.json').then(r => r.text())"))
        if not ok:
            return False, f"fetch evaluate failed: {v}"
        time.sleep(0.3)
        ok, v = ok_value(act("list_network_requests", {"limit": 30}))
        if not ok:
            return False, f"list_network_requests failed: {v}"
        reqs = (v or {}).get("requests") or []
        hit = [r for r in reqs if "/data.json" in str(r.get("url", ""))]
        if not hit:
            return False, f"/data.json not seen in network log ({len(reqs)} entries)"
        target = hit[0]
        rid = target.get("requestId")
        ok2, v2 = ok_value(act("get_network_request", {"requestId": rid}))
        if not ok2 or not (v2 or {}).get("found"):
            return False, f"get_network_request failed: {v2}"
        return True, f"/data.json seen; status={target.get('status')} size={target.get('size')}"
    cases.append(("list/get network requests (fetch /data.json)", c_network))

    # ---- 13. console messages ------------------------------------------
    def c_console():
        ok, _ = ok_value(evaluate("console.log('p0-console-tag-42'); 1"))
        if not ok:
            return False, "console.log evaluate failed"
        time.sleep(0.3)
        ok, v = ok_value(act("list_console_messages", {"limit": 50}))
        if not ok:
            return False, f"list_console_messages failed: {v}"
        msgs = (v or {}).get("messages") or []
        if not any("p0-console-tag-42" in str(m.get("text", "")) for m in msgs):
            return False, f"p0-console-tag-42 not in console log ({len(msgs)} messages)"
        return True, "console log captured the evaluate console.log"
    cases.append(("list console messages", c_console))

    for name, fn in cases:
        if not check(name, fn):
            failures += 1

    total = len(cases)
    print()
    print(f"summary: {total - failures}/{total} passed")
    if failures:
        print("HINT: daemon running the NEW webflow_bridge.py? extension reloaded?")
        print("      page server on :8921? Chrome on a normal page?")
    return 1 if failures else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
