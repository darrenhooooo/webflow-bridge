#!/usr/bin/env python3
"""wb-bench runner.

Runs the ten tasks on one or both sides and writes one raw JSONL record per
(task, side, rep).  Everything in the record is produced here by actually
running the task — nothing is hand-written (red line 4).

    envs/.venv-bu/bin/python harness/run.py --tasks T1 --sides a,b --reps 1

Artifacts: out/<side>/rep<N>/<task>/  (screenshots, PDFs, downloads)
Logs:      logs/results.jsonl, logs/run_meta.json, logs/site.log
"""
import argparse
import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from common import (CONNECTION_JSONL, LOGS, OUT, RESULTS_JSONL,  # noqa: E402
                    SITE_DIR, SITE_PORT,
                    TASK_TIMEOUT, WB_REPO, append_jsonl, truncate)
from judge import artifact_ok, judge          # noqa: E402  (one shared judge, both sides)
from tasks import TASK_BY_ID     # noqa: E402

TMP_ROOT = "/tmp/wb-bench-run"

# Global wall-clock budget for the whole run (red line: stop at 50 min and
# summarise what finished).  Set by --deadline-min.
DEADLINE = {"deadline_min": None, "t0": None}
REP_TIMES = []            # real per-rep start/end, written into run_meta.json
SKIPPED = []              # (side, rep, task) never started because of the deadline


def deadline_hit():
    if not DEADLINE["deadline_min"] or DEADLINE["t0"] is None:
        return False
    return (time.time() - DEADLINE["t0"]) > DEADLINE["deadline_min"] * 60


def _rep_time(side, rep, started, finished):
    REP_TIMES.append({
        "side": side, "rep": rep,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started)),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(finished)),
        "seconds": round(finished - started, 3),
    })


# The meta dict of the run in flight; flushed to disk after every record so a
# crash mid-run still leaves an honest, complete-as-of-then run_meta.json.
META = {}


def _read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return [ln for ln in fh if ln.strip()]


def _flush_meta():
    if not META:
        return
    META["rep_times"] = REP_TIMES
    META["skipped"] = SKIPPED
    META["records"] = len(_read_lines(RESULTS_JSONL))
    META["deadline_hit"] = deadline_hit()
    os.makedirs(LOGS, exist_ok=True)
    with open(os.path.join(LOGS, "run_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(META, fh, indent=2)


# ---------------------------------------------------------------------------
# the local test site
# ---------------------------------------------------------------------------
def start_site():
    os.makedirs(LOGS, exist_ok=True)
    log = open(os.path.join(LOGS, "site.log"), "wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(SITE_PORT), "--bind",
         "127.0.0.1", "--directory", SITE_DIR],
        stdout=log, stderr=subprocess.STDOUT)
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{SITE_PORT}/hello.html",
                                        timeout=1) as r:
                if r.status == 200:
                    return proc
        except Exception:                              # noqa: BLE001
            time.sleep(0.1)
    proc.terminate()
    raise RuntimeError("local test site did not start on port "
                       f"{SITE_PORT}")


def kill(proc):
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:                                  # noqa: BLE001
        try:
            proc.kill()
        except Exception:                              # noqa: BLE001
            pass


def port_free(port):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


# ---------------------------------------------------------------------------
# one record
# ---------------------------------------------------------------------------
def record(run_id, task_id, side, rep, success, judge_detail, seconds,
           t_first, metrics, error):
    steps = metrics.get("steps_b", 0) or 0
    prompt = metrics.get("prompt_tokens_b", 0) or 0
    return {
        "run_id": run_id,
        "task": task_id,
        "side": side,
        "rep": rep,
        "success": bool(success),
        "seconds": round(seconds, 3),
        "time_to_first_action_s": (None if t_first is None
                                   else round(t_first, 3)),
        "steps_b": metrics.get("steps_b", 0),
        # Side A has no LLM: every `_b` token/cost field is an explicit 0
        # (never omitted).  Side B's numbers come from browser-use's usage.
        "prompt_tokens_b": metrics.get("prompt_tokens_b", 0) or 0,
        "completion_tokens_b": metrics.get("completion_tokens_b", 0) or 0,
        # avg prompt tokens per step = total prompt tokens summed over every
        # LLM call in the task / number of agent steps (0 when no steps ran).
        "avg_prompt_tokens_per_step_b": (round(prompt / steps, 2)
                                         if steps else 0.0),
        "est_cost_usd_b": metrics.get("est_cost_usd_b", 0.0) or 0.0,
        "error": truncate(error) if error else "",
        # additive, non-required context
        "judge_detail": judge_detail,
        "llm_used": side == "B",
        "cached_tokens_b": metrics.get("cached_tokens_b", 0),
        "cost_source": metrics.get("cost_source"),
        "final_result": metrics.get("final_result"),
        "agent_errors": metrics.get("agent_errors", []),
    }


# ---------------------------------------------------------------------------
# side A (deterministic)
# ---------------------------------------------------------------------------
async def run_side_a(tasks, reps, run_id):
    from wb_stack import WbStack
    from side_a import WbPage, run_task as a_run_task

    records = []
    for rep in range(1, reps + 1):
        rep_started = time.time()
        tmp = os.path.join(TMP_ROOT, f"a-rep{rep}")
        os.makedirs(tmp, exist_ok=True)
        stack = WbStack(tmp)
        try:
            probe = stack.start()
            append_jsonl(CONNECTION_JSONL,
                         {"run_id": run_id, "rep": rep, "probe": probe,
                          "extension_id": stack.extension_id,
                          "connected_after_s": stack.connected_after_s})
            page = WbPage(stack)
            for task in tasks:
                if deadline_hit():
                    SKIPPED.append({"side": "A", "rep": rep,
                                    "task": task["id"],
                                    "reason": "global wall-clock deadline"})
                    continue
                art_dir = os.path.join(OUT, "a", f"rep{rep}", task["id"])
                art_dirs = [art_dir]
                before = await page.tabs()
                t0 = time.time()
                error, t_first = await a_run_task(stack, task["id"], art_dir)
                success, detail = await judge(task["id"], page, art_dirs, before,
                                              art_since=t0 - 1)
                rec = record(run_id, task["id"], "A", rep, success, detail,
                             time.time() - t0, t_first, {}, error)
                rec["artifact_ok"] = artifact_ok(task["id"], art_dirs, t0 - 1)
                rec["within_timeout"] = not (error and "timeout" in str(error))
                records.append(rec)
                append_jsonl(RESULTS_JSONL, rec)
                _flush_meta()
                print(f"[A rep{rep} {task['id']}] success={success} "
                      f"{rec['seconds']}s :: {detail}", flush=True)
        finally:
            stack.stop()
            shutil.rmtree(tmp, ignore_errors=True)
            _rep_time("A", rep, rep_started, time.time())
    return records


# ---------------------------------------------------------------------------
# side B (browser-use agent)
# ---------------------------------------------------------------------------
async def run_side_b(tasks, reps, run_id):
    from side_b import SideB, find_chromium, MODEL

    records = []
    for rep in range(1, reps + 1):
        rep_started = time.time()
        art_root = os.path.join(OUT, "b", f"rep{rep}")
        os.makedirs(art_root, exist_ok=True)
        side = SideB(art_root)
        cdp = await side.open()
        append_jsonl(CONNECTION_JSONL,
                     {"run_id": run_id, "rep": rep, "side": "B",
                      "model": MODEL, "cdp_url": cdp,
                      "chromium": find_chromium()})
        try:
            page = None
            for task in tasks:
                if deadline_hit():
                    SKIPPED.append({"side": "B", "rep": rep,
                                    "task": task["id"],
                                    "reason": "global wall-clock deadline"})
                    continue
                from side_b import BuPage
                page = BuPage(side.session)
                art_dir = os.path.join(art_root, task["id"])
                # browser-use downloads land in <art_root>/downloads, not in
                # the per-task dir; scan both (red-line: judge change only).
                art_dirs = [art_dir, os.path.join(art_root, "downloads")]
                before = await page.tabs()
                t0 = time.time()
                error, metrics = await side.run_task(task, art_dir)
                success, detail = await judge(task["id"], page, art_dirs, before,
                                              art_since=t0 - 1)
                rec = record(run_id, task["id"], "B", rep, success, detail,
                             time.time() - t0,
                             metrics.get("time_to_first_action_s"),
                             metrics, error)
                rec["artifact_ok"] = artifact_ok(task["id"], art_dirs, t0 - 1)
                rec["within_timeout"] = not (error and "timeout" in str(error))
                records.append(rec)
                append_jsonl(RESULTS_JSONL, rec)
                _flush_meta()
                print(f"[B rep{rep} {task['id']}] success={success} "
                      f"{rec['seconds']}s tokens={rec['prompt_tokens_b']}/"
                      f"{rec['completion_tokens_b']} "
                      f"cost=${rec['est_cost_usd_b']:.6f} :: {detail}",
                      flush=True)
        finally:
            await side.close()
            _rep_time("B", rep, rep_started, time.time())
    return records


def software_versions():
    """Real versions, read from the installed packages / manifests.  No git
    command is run anywhere in this bench (red line 7)."""
    import importlib.metadata as md

    def _v(pkg):
        try:
            return md.version(pkg)
        except Exception:                              # noqa: BLE001
            return None

    here = os.path.dirname(os.path.abspath(__file__))
    ext_manifest = os.path.join(WB_REPO, "extension", "manifest.json")
    ext_version = None
    try:
        with open(ext_manifest, "r", encoding="utf-8") as fh:
            ext_version = json.load(fh).get("version")
    except Exception:                                  # noqa: BLE001
        pass

    from side_b import MODEL
    return {
        "side_a": {
            "product": "Webflow Bridge (daemon + extension)",
            "extension_version": ext_version,
            "daemon": os.path.join(WB_REPO, "daemon", "webflow_bridge.py"),
            "llm": None,
        },
        "side_b": {
            "product": "browser-use agent",
            "browser_use": _v("browser-use"),
            "playwright": _v("playwright"),
            "model": MODEL,
            "llm_client": "browser_use.ChatOpenAI -> DeepSeek OpenAI-compatible",
        },
        "python": sys.version.split()[0],
        "harness": here,
    }


# ---------------------------------------------------------------------------
async def amain(args):
    os.makedirs(LOGS, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(TMP_ROOT, exist_ok=True)

    tasks = [TASK_BY_ID[t] for t in args.tasks]
    run_id = time.strftime("%Y%m%d-%H%M%S")
    DEADLINE["deadline_min"] = args.deadline_min
    DEADLINE["t0"] = time.time()
    if not args.append:
        for p in (RESULTS_JSONL, CONNECTION_JSONL):
            if os.path.exists(p):
                os.remove(p)

    META.clear()
    META.update({
        "run_id": run_id,
        "tasks": args.tasks,
        "sides": args.sides,
        "reps": args.reps,
        "task_timeout_s": TASK_TIMEOUT,
        "task_timeout_is_failure": True,
        "retries": 0,
        "retry_policy": "none on either side: a failure/timeout is recorded "
                         "as a failure, it is never retried away",
        "site_port": SITE_PORT,
        "wb_http_port": 20086,
        "wb_ws_port": 20087,
        "wb_cdp_port": 20088,
        "deadline_min": args.deadline_min,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "software": software_versions(),
    })
    site = start_site()
    try:
        if "a" in args.sides:
            from wb_stack import WB_HTTP_PORT, WB_WS_PORT, WB_CDP_PORT
            META["wb_ports_free_before"] = {
                str(p): port_free(p) for p in
                (WB_HTTP_PORT, WB_WS_PORT, WB_CDP_PORT)}
        records = []
        if "a" in args.sides:
            records += await run_side_a(tasks, args.reps, run_id)
        if "b" in args.sides:
            records += await run_side_b(tasks, args.reps, run_id)
        META["records"] = len(records)
        META["rep_times"] = REP_TIMES
        META["skipped"] = SKIPPED
        META["deadline_hit"] = deadline_hit()
        META["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(os.path.join(LOGS, "run_meta.json"), "w", encoding="utf-8") as fh:
            json.dump(META, fh, indent=2)
        # summary.md / summary.json are derived from the raw records only.
        from summarize import write_summary
        write_summary(RESULTS_JSONL, os.path.join(OUT, "representation.json"),
                      LOGS)
        return records
    finally:
        kill(site)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="T1",
                    help="comma-separated task ids (default T1)")
    ap.add_argument("--sides", default="a,b", help="a,b (default both)")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--append", action="store_true",
                    help="append to logs/results.jsonl instead of truncating")
    ap.add_argument("--deadline-min", type=float, default=50.0,
                    help="stop starting new tasks after this many minutes "
                         "(default 50); skipped (side,rep,task) are recorded")
    args = ap.parse_args()
    args.tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]
    args.sides = [s.strip().lower() for s in args.sides.split(",") if s.strip()]
    for t in args.tasks:
        if t not in TASK_BY_ID:
            raise SystemExit(f"unknown task {t}")
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
