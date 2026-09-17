"""Side A — Webflow Bridge, deterministic.  No LLM anywhere in this file.

Each task is a fixed command sequence posted to the isolated daemon.  The
sequence is only the *actions*; the success decision is made by the shared
judge.py, exactly as for side B.
"""
import base64
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import truncate, url                              # noqa: E402
from tasks import SAMPLE_FILE                                 # noqa: E402

READY = "document.readyState"


class StepError(RuntimeError):
    pass


def _call(stack, action, args, timeout=60):
    resp = stack.cmd(action, args, timeout=timeout)
    if resp.get("status") != "ok":
        raise StepError(f"{action}: {resp.get('error') or repr(resp)}")
    return resp.get("data", {}).get("value")


class WbPage:
    """judge.py adapter for side A."""

    def __init__(self, stack):
        self.s = stack

    async def evaluate(self, expression, tab=None):
        args = {"code": expression}
        if tab is not None:
            args["tabId"] = tab
        resp = self.s.cmd("evaluate", args)
        if resp.get("status") != "ok":
            raise RuntimeError(resp.get("error") or repr(resp))
        return resp.get("data", {}).get("value")

    async def tabs(self):
        return _tabs(self.s)


def _tabs(stack):
    value = _call(stack, "tabs_list", {})
    return [t["id"] for t in value]


def _wait_ready(stack, tab=None, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        args = {"code": READY}
        if tab is not None:
            args["tabId"] = tab
        try:
            if _call(stack, "evaluate", args) == "complete":
                return True
        except StepError:
            pass
        time.sleep(0.1)
    return False


def _navigate(stack, page_name, tab=None):
    args = {"url": url(page_name)}
    if tab is not None:
        args["tabId"] = tab
    _call(stack, "navigate", args)
    _wait_ready(stack, tab)


def _screenshot(stack, path):
    value = _call(stack, "screenshot", {}, timeout=60)
    with open(path, "wb") as fh:
        fh.write(base64.b64decode(value["base64"]))


def _pdf(stack, path):
    value = _call(stack, "save_as_pdf", {}, timeout=60)
    with open(path, "wb") as fh:
        fh.write(base64.b64decode(value["base64"]))


# ---------------------------------------------------------------------------
# the deterministic sequences
# ---------------------------------------------------------------------------
async def _t1(stack, art_dir):
    _navigate(stack, "hello.html")


async def _t2(stack, art_dir):
    _navigate(stack, "form.html")
    _call(stack, "fill", {"selector": "#name", "value": "Ada"})
    _call(stack, "fill", {"selector": "#email", "value": "ada@example.com"})
    _call(stack, "fill", {"selector": "#plan", "value": "pro"})
    _call(stack, "click", {"selector": "#submit"})


async def _t3(stack, art_dir):
    _navigate(stack, "list.html")


async def _t4(stack, art_dir):
    _navigate(stack, "dialog.html")
    _call(stack, "click", {"selector": "#ask"})
    time.sleep(0.5)                       # let the auto-accept policy settle


async def _t5(stack, art_dir):
    _navigate(stack, "upload.html")
    _call(stack, "upload", {"selector": "#file", "file": SAMPLE_FILE})


async def _t6(stack, art_dir):
    before = len(_tabs(stack))
    _navigate(stack, "tabs.html")
    _call(stack, "click", {"selector": "#open"})
    deadline = time.time() + 10
    while time.time() < deadline:
        if len(_tabs(stack)) > before:
            break
        time.sleep(0.2)
    _wait_ready(stack)                    # the new tab is now active
    time.sleep(0.3)


async def _t7(stack, art_dir):
    _navigate(stack, "list.html")
    _call(stack, "click", {"selector": "#next"})
    _call(stack, "click", {"selector": "#next"})


async def _t8(stack, art_dir):
    _navigate(stack, "hello.html")
    _screenshot(stack, os.path.join(art_dir, "T8.png"))


async def _t9(stack, art_dir):
    _navigate(stack, "hello.html")
    _pdf(stack, os.path.join(art_dir, "T9.pdf"))


async def _t10(stack, art_dir):
    _navigate(stack, "login.html")
    _call(stack, "fill", {"selector": "#user", "value": "bench"})
    _call(stack, "fill", {"selector": "#pass", "value": "bench"})
    _call(stack, "click", {"selector": "#go"})
    _navigate(stack, "private.html")


SEQUENCES = {"T1": _t1, "T2": _t2, "T3": _t3, "T4": _t4, "T5": _t5,
             "T6": _t6, "T7": _t7, "T8": _t8, "T9": _t9, "T10": _t10}


async def run_task(stack, task_id, art_dir):
    """Run one side-A task.  Returns (error|None, time_to_first_action_s)."""
    os.makedirs(art_dir, exist_ok=True)
    t0 = time.time()
    first = [None]
    orig = stack.cmd

    def timed_cmd(action, args=None, timeout=60):
        resp = orig(action, args, timeout=timeout)
        if first[0] is None:
            first[0] = time.time() - t0
        return resp

    stack.cmd = timed_cmd
    try:
        await SEQUENCES[task_id](stack, art_dir)
        return None, first[0]
    except Exception as exc:                        # noqa: BLE001
        return truncate(f"{type(exc).__name__}: {exc}"), first[0]
    finally:
        stack.cmd = orig
