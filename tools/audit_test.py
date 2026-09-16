#!/usr/bin/env python3
"""Phase 0.6 audit event stream v0 — acceptance tests (docs/COMMERCIALIZATION.md §5).

Standalone stdlib-only; run:  python3 tools/audit_test.py

Covers the §5 v0 acceptance criteria:
  (1) 3 actions -> exactly 3 records, all schema fields present
  (2) hash chain verifies end to end
  (3) tampering any record -> verification fails and pinpoints it
  (4) rotation keeps the chain continuous (small threshold to force rotation)
  (5) privacy: a URL ?token=SECRET never appears verbatim; params_hash != raw
  (6) crash/restart: already-persisted events still verify (+ torn tail)
Also: fail-open when the audit path is unwritable.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import tempfile
import time

logging.disable(logging.CRITICAL)             # silence the fail-open warning

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_spec = importlib.util.spec_from_file_location(
    "audit", os.path.join(ROOT, "daemon", "audit.py"))
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)
FIELDS = ("event_id", "ts", "actor", "session_id", "action", "target",
          "params_hash", "result", "duration_ms", "policy_decision",
          "prev_hash", "hash")

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name}" + (f"  -- {detail}" if detail else ""))


def read_events(path):
    with open(path, "r", encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def main() -> int:
    # ---- (1)+(2)+(5) three actions, fields, chain, privacy -------------
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "audit-20250101.jsonl")
        log = audit.AuditLog(path=path)
        log.record("click", actor="127.0.0.1", args={"selector": "#go"})
        log.record("fill", actor="127.0.0.1",
                   args={"selector": "#pwd", "value": "hunter2"})
        log.record("upload", actor="127.0.0.1",
                   args={"selector": "#f", "file": "/tmp/secret.pdf",
                         "url": "https://example.com/apply?token=SECRET"})
        events = read_events(path)

        check("(1) exactly 3 records for 3 actions", len(events) == 3,
              f"got {len(events)}")
        missing = [f for f in FIELDS
                   if any(f not in e for e in events)]
        check("(1) every schema field present in every record", not missing,
              f"missing {missing}")
        check("(1) result/status/policy_decision shaped per schema",
              all(e["result"]["status"] == "ok"
                  and e["result"]["error_code"] is None
                  and e["policy_decision"] == "allow"
                  and isinstance(e["duration_ms"], (int, float))
                  and isinstance(e["ts"], int)
                  and len(e["event_id"]) == 32 for e in events))
        check("(1) first prev_hash is genesis, then linked",
              events[0]["prev_hash"] == ""
              and events[1]["prev_hash"] == events[0]["hash"]
              and events[2]["prev_hash"] == events[1]["hash"])

        res = audit.verify([path], anchor="")
        check("(2) hash chain verifies end to end", res["ok"],
              str(res.get("error")))

        blob = open(path, encoding="utf-8").read()
        check("(5) URL query SECRET never in file", "SECRET" not in blob)
        check("(5) raw fill value never in file", "hunter2" not in blob)
        check("(5) file path never in file", "secret.pdf" not in blob)
        check("(5) target keeps domain+path, drops query",
              events[2]["target"] == {"domain": "example.com",
                                      "url": "example.com/apply"})
        check("(5) params_hash is a hash, not raw args",
              all(isinstance(e["params_hash"], str)
                  and len(e["params_hash"]) == 64 for e in events))

        # ---- (3) tamper the 2nd record -> locate it --------------------
        tampered = os.path.join(tmp, "tampered.jsonl")
        raw = [ln for ln in open(path, encoding="utf-8").read().splitlines() if ln]
        ev = json.loads(raw[1])
        ev["action"] = "exfiltrate"
        raw[1] = json.dumps(ev, ensure_ascii=False, sort_keys=True)
        with open(tampered, "w", encoding="utf-8") as fh:
            fh.write("\n".join(raw) + "\n")
        res2 = audit.verify([tampered], anchor="")
        check("(3) tamper detected", not res2["ok"])
        check("(3) first mismatch located at record 2 (file line 2)",
              res2["error"] and res2["error"]["index"] == 2
              and res2["error"]["line"] == 2
              and res2["error"]["reason"] == "hash mismatch",
              str(res2.get("error")))

    # ---- (4) rotation keeps the chain continuous -----------------------
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "audit-20250101.jsonl")
        log = audit.AuditLog(path=path, max_bytes=400, keep=3)
        for i in range(12):
            log.record("click", actor="a", args={"i": i, "url":
                       f"https://site{i}.example.com/p?q={i}"})
        files = log.files()
        check("(4) rotation produced multiple files", len(files) >= 2,
              f"{len(files)} files")
        check("(4) retention keeps at most 3 files", len(files) <= 3,
              f"{len(files)} files")
        linked = True
        for prev_f, cur_f in zip(files, files[1:]):
            last = read_events(prev_f)[-1]
            first = read_events(cur_f)[0]
            if first["prev_hash"] != last["hash"]:
                linked = False
        check("(4) each new file starts where the previous file ended", linked)
        res = audit.verify(files, anchor=None)
        check("(4) retained window still verifies", res["ok"],
              str(res.get("error")))

    # ---- (6) crash / restart continuity + torn tail --------------------
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "audit-20250101.jsonl")
        a = audit.AuditLog(path=path)
        a.record("click", args={"n": 1})
        a.record("fill", args={"n": 2})
        del a                                     # simulate process death
        b = audit.AuditLog(path=path)             # fresh instance, same dir
        b.record("click", args={"n": 3})
        events = read_events(path)
        check("(6) restart chains from the persisted tail",
              len(events) == 3
              and events[2]["prev_hash"] == events[1]["hash"])
        check("(6) persisted events verify after restart",
              audit.verify([path], anchor="")["ok"])
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('{"event_id": "torn')       # crash mid-write
        check("(6) a torn trailing line is tolerated",
              audit.verify([path], anchor="")["ok"])

    # ---- fail-open: unwritable audit path must not raise ---------------
    with tempfile.TemporaryDirectory() as tmp:
        blocker = os.path.join(tmp, "not-a-dir")
        open(blocker, "w").close()
        bad = audit.AuditLog(path=os.path.join(blocker, "audit.jsonl"))
        raised = False
        try:
            bad.record("click", args={"x": 1})
        except Exception:                         # noqa: BLE001
            raised = True
        check("fail-open: unwritable audit path never raises", not raised)
        check("fail-open: disabled log returns None",
              bad.record("click") is None)

    # ---- performance: instrumentation overhead per action --------------
    with tempfile.TemporaryDirectory() as tmp:
        log = audit.AuditLog(path=os.path.join(tmp, "perf.jsonl"))
        log.record("warmup")
        n = 500
        t0 = time.perf_counter()
        for i in range(n):
            log.record("click", actor="127.0.0.1",
                       args={"selector": "#a", "url": "https://e.com/p"})
        avg_us = (time.perf_counter() - t0) / n * 1e6
        print(f"[INFO] audit record() overhead: {avg_us:.1f} us/action "
              f"({avg_us/1000:.3f} ms) over {n} calls")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
