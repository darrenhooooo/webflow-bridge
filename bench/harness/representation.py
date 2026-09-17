#!/usr/bin/env python3
"""Measure the token cost of three ways of putting ONE page in front of a model.

This is a SEPARATE measurement from the A/B end-to-end run.  It does not run
any agent and it does not touch success rates or latency; it only answers
"how many tokens does each representation of this page cost".

For every task's page it measures three representations:

  (a) a_browseruse_tree   browser-use's own serialized interactive-element /
                          accessibility tree (`dom_state.llm_representation()`),
                          i.e. what actually goes into side B's prompt.
  (b) b_wb_snapshot       the Webflow Bridge `snapshot` action's return value,
                          JSON-serialized.
  (c) c_decisive_evaluate the single `evaluate` the shared judge.py reads to
                          decide the task, JSON-serialized.

(a) and (b) are measured at the task's START page.  (c) is measured at the page
state the judge really reads it in (i.e. after side A's deterministic action
sequence, for tasks that need one).  T8/T9 need no `evaluate` at all — the
judge reads a local file — so their model-visible decisive value is 0 tokens.

    envs/.venv-bu/bin/python harness/representation.py
"""
import asyncio
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from common import LOGS, OUT, url                          # noqa: E402
from tasks import TASKS                                   # noqa: E402
from judge import judge                                   # noqa: E402
from side_a import WbPage, _navigate, run_task            # noqa: E402

TMP_ROOT = "/tmp/wb-bench-run"
ART_ROOT = os.path.join(TMP_ROOT, "repr-art")
REPR_JSON = os.path.join(OUT, "representation.json")

# --- token counting --------------------------------------------------------
import tiktoken                                           # noqa: E402

PRIMARY = "tiktoken cl100k_base"
SENSITIVITY = "tiktoken o200k_base"
TOKENIZER_NOTE = (
    "DeepSeek does not publish its production tokenizer as a pip-installable "
    "counter, so both counts are PROXY COUNTS produced by tiktoken BPE "
    "encodings and are NOT DeepSeek's own token counts. Absolute numbers will "
    "differ from DeepSeek's tokenizer by some percentage; what is being "
    "compared here is the relative size of the three representations of the "
    "same page text. o200k_base is reported alongside cl100k_base purely as a "
    "sensitivity check on that uncertainty.")

_ENC = tiktoken.get_encoding("cl100k_base")
_ENC2 = tiktoken.get_encoding("o200k_base")


def count_tokens(text):
    return {
        "tokens_cl100k": len(_ENC.encode(text)),
        "tokens_o200k": len(_ENC2.encode(text)),
        "chars": len(text),
    }


def _blob(value):
    """The exact bytes that would travel to the model for this value."""
    return json.dumps(value, ensure_ascii=False)


# ---------------------------------------------------------------------------
class RecordingPage:
    """judge.py adapter that records every evaluate the judge makes, so the
    decisive one can be picked without duplicating any judge logic here."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    async def evaluate(self, expression, tab=None):
        try:
            value = await self.inner.evaluate(expression, tab=tab)
        except Exception as exc:                       # noqa: BLE001
            self.calls.append({"expr": expression, "error": str(exc)[:200]})
            raise
        self.calls.append({"expr": expression, "value": value})
        return value

    async def tabs(self):
        return await self.inner.tabs()


DECISIVE_RULE = (
    "The decisive evaluate is the call whose returned payload the judge "
    "actually compares: for T6 that is the call that returned 'Hello Bench' "
    "on the new tab; for every other task the judge makes exactly one "
    "evaluate, so it is the last recorded call. Tasks whose judge reads a "
    "local file instead (T8/T9) make no evaluate call and their decisive "
    "representation cost is 0 tokens by construction.")


def _decisive(task_id, calls):
    vals = [c for c in calls if "value" in c]
    if not vals:
        return None
    if task_id == "T6":
        for c in vals:
            if c["value"] == "Hello Bench":
                return c
    return vals[-1]


# ---------------------------------------------------------------------------
# (b) + (c) over the isolated Webflow Bridge stack
# ---------------------------------------------------------------------------
async def measure_wb(tasks):
    from wb_stack import WbStack
    result = {}
    work = os.path.join(TMP_ROOT, "repr")
    os.makedirs(work, exist_ok=True)
    stack = WbStack(work)
    stack.start()
    try:
        page = WbPage(stack)
        for task in tasks:
            tid = task["id"]
            entry = {"page": task["page"]}
            art_dir = os.path.join(ART_ROOT, tid)
            os.makedirs(art_dir, exist_ok=True)
            try:
                # --- start page: (b) the snapshot -------------------------
                _navigate(stack, task["page"])
                snap = stack.cmd("snapshot", {}, timeout=60)
                if snap.get("status") != "ok":
                    raise RuntimeError(f"snapshot failed: {snap.get('error')}")
                snap_value = snap.get("data", {}).get("value")
                blob_b = _blob(snap_value)
                entry["b_wb_snapshot"] = {
                    **count_tokens(blob_b),
                    "nodes": (snap_value or {}).get("total"),
                    "sample": blob_b[:240],
                    "exact_payload": "the `value` object of the snapshot "
                                     "reply, JSON-serialized (the reply "
                                     "envelope is harness overhead, not the "
                                     "representation)",
                }
                # --- run side A's actions, then the shared judge ----------
                before = await page.tabs()
                rec = RecordingPage(page)
                seq_error, _ = await run_task(stack, tid, art_dir)
                ok, detail = await judge(tid, rec, [art_dir], before)
                dec = _decisive(tid, rec.calls)
                if dec is None:
                    entry["c_decisive_evaluate"] = {
                        **count_tokens(""), "value": None,
                        "note": "0 — no evaluate; judge reads a local file",
                    }
                else:
                    blob_c = _blob(dec["value"])
                    entry["c_decisive_evaluate"] = {
                        **count_tokens(blob_c),
                        "value": dec["value"],
                        "expr": dec["expr"],
                        "sample": blob_c[:240],
                    }
                entry["context"] = {
                    "judge_ok": ok, "judge_detail": detail,
                    "side_a_sequence_error": seq_error,
                    "evaluate_calls": len(rec.calls),
                }
            except Exception as exc:                   # noqa: BLE001
                entry["error"] = f"{type(exc).__name__}: {exc}"
            result[tid] = entry
    finally:
        stack.stop()
    return result


# ---------------------------------------------------------------------------
# (a) browser-use's own tree, over an isolated browser-use session
# ---------------------------------------------------------------------------
async def measure_bu(tasks):
    from browser_use import BrowserProfile, BrowserSession
    from side_b import find_chromium, tempfile_dir

    result = {}
    profile = BrowserProfile(
        executable_path=find_chromium(),
        user_data_dir=tempfile_dir("repr-profile"),
        headless=True,
        is_local=True,
        enable_default_extensions=False,
        viewport={"width": 1280, "height": 900},
    )
    session = BrowserSession(browser_profile=profile)
    await session.start()
    try:
        for task in tasks:
            tid = task["id"]
            try:
                await session.navigate_to(url(task["page"]))
                state = await session.get_browser_state_summary(
                    include_screenshot=False)
                text = state.dom_state.llm_representation()
                result[tid] = {
                    **count_tokens(text),
                    "interactive_elements": len(
                        getattr(state.dom_state, "selector_map", {}) or {}),
                    "sample": text[:240],
                    "exact_payload": "BrowserSession.get_browser_state_summary"
                                     "(include_screenshot=False)"
                                     ".dom_state.llm_representation()",
                }
            except Exception as exc:                   # noqa: BLE001
                result[tid] = {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        try:
            await session.stop()
        except Exception:                              # noqa: BLE001
            pass
    return result


# ---------------------------------------------------------------------------
def write(wb, bu, tasks):
    os.makedirs(OUT, exist_ok=True)
    payload = {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "site": url(""),
        "separate_from": ("out/summary.md's A/B end-to-end table — these token "
                          "numbers are representation size only, not latency "
                          "and not success rate"),
        "tokenizer": {
            "primary": PRIMARY,
            "sensitivity": SENSITIVITY,
            "proxy": True,
            "why": TOKENIZER_NOTE,
        },
        "definitions": {
            "a_browseruse_tree": ("browser-use's serialized interactive-element "
                                  "/ accessibility tree: "
                                  "`get_browser_state_summary(include_screenshot"
                                  "=False).dom_state.llm_representation()`, the "
                                  "text side B's prompt is built from. Measured "
                                  "at the task's START page."),
            "b_wb_snapshot": ("Webflow Bridge `POST /command "
                              "{action:'snapshot'}` return `value`, "
                              "JSON-serialized. Measured at the task's START "
                              "page."),
            "c_decisive_evaluate": ("the single `evaluate` the shared "
                                    "harness/judge.py reads to decide the task, "
                                    "JSON-serialized. " + DECISIVE_RULE),
        },
        "tasks": {},
    }
    for task in tasks:
        tid = task["id"]
        w = wb.get(tid) or {}
        payload["tasks"][tid] = {
            "page": task["page"],
            "a_browseruse_tree": bu.get(tid) or {},
            "b_wb_snapshot": w.get("b_wb_snapshot") or {},
            "c_decisive_evaluate": w.get("c_decisive_evaluate") or {},
            "measurement_context": w.get("context"),
            "error": w.get("error") or (bu.get(tid) or {}).get("error"),
        }
    with open(REPR_JSON, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    return payload


async def amain():
    os.makedirs(TMP_ROOT, exist_ok=True)
    os.makedirs(ART_ROOT, exist_ok=True)
    from run import kill, start_site
    site = start_site()
    try:
        return await _amain_with_site()
    finally:
        kill(site)


async def _amain_with_site():
    tasks = TASKS
    print("[repr] measuring (b) snapshot + (c) decisive evaluate on the "
          "isolated Webflow Bridge stack ...", flush=True)
    wb = await measure_wb(tasks)
    print("[repr] measuring (a) browser-use DOM tree on an isolated "
          "browser-use session ...", flush=True)
    bu = await measure_bu(tasks)

    payload = write(wb, bu, tasks)
    for task in tasks:
        t = payload["tasks"][task["id"]]
        print(f"[repr] {task['id']:>3} {task['page']:<13} "
              f"a_tree={t['a_browseruse_tree'].get('tokens_cl100k')} "
              f"b_snap={t['b_wb_snapshot'].get('tokens_cl100k')} "
              f"c_eval={t['c_decisive_evaluate'].get('tokens_cl100k')}",
              flush=True)
    print(f"[repr] wrote {REPR_JSON}", flush=True)
    return payload


if __name__ == "__main__":
    asyncio.run(amain())
