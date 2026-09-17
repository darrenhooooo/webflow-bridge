"""THE judge — one file, one code path, shared by both sides.

Both side A (Webflow Bridge, deterministic) and side B (browser-use agent)
hand this module the same kind of adapter, so there is exactly one definition
of "did the task succeed". There is no `if side == ...` anywhere here.

Adapter contract (`page`), all async:

    await page.evaluate(expression: str, tab=None) -> JSON-safe value
        Evaluate `expression` (a plain JS EXPRESSION, not a function body) in
        the page and return its value.  `tab=None` means the side's
        main/active page; `tab=<handle from page.tabs()>` means that tab.
        Any transport error raises.

    await page.tabs() -> list[handle]
        Every open page/tab.  Handles are comparable (equal iff same tab) but
        otherwise opaque to the judge.

Artifacts (T8/T9): `art_dirs` are directories the side may have written a
screenshot / PDF into; the judge validates whatever files it finds there.

Artifact freshness (T8/T9): a file only counts when its mtime is >= the
`art_since` value passed to judge() -- the task's start time minus 1 second.
That stops a same-named file left behind by an earlier task/rep from being
mistaken for this run's output.  `art_since=None` disables the check.
"""
import glob
import os

PNG_MIN_BYTES = 5120          # ">5KB"

H1 = ("document.querySelector('h1') "
      "? document.querySelector('h1').textContent.trim() : ''")


def _text_expr(selector):
    q = f"document.querySelector({selector!r})"
    return f"{q} ? {q}.textContent : null"


def _png_ok(path):
    try:
        if os.path.getsize(path) <= PNG_MIN_BYTES:
            return False, f"{os.path.basename(path)} is not >{PNG_MIN_BYTES}B"
        with open(path, "rb") as fh:
            head = fh.read(8)
        if head != b"\x89PNG\r\n\x1a\n":
            return False, f"{os.path.basename(path)} has a bad PNG header"
        return True, f"{os.path.basename(path)} ok ({os.path.getsize(path)}B)"
    except OSError as exc:
        return False, f"{os.path.basename(path)}: {exc}"


def _pdf_ok(path):
    try:
        with open(path, "rb") as fh:
            head = fh.read(5)
        if head != b"%PDF-":
            return False, f"{os.path.basename(path)} does not start with %PDF-"
        return True, f"{os.path.basename(path)} ok ({os.path.getsize(path)}B)"
    except OSError as exc:
        return False, f"{os.path.basename(path)}: {exc}"


def _fresh(path, since):
    try:
        return os.path.getmtime(path) >= since
    except OSError:
        return False


def _first_ok(art_dirs, ext, checker, since=None):
    files = []
    for d in art_dirs:
        files += sorted(glob.glob(os.path.join(d, f"**/*{ext}"), recursive=True))
    if since is not None:
        files = [p for p in files if _fresh(p, since)]
    if not files:
        return False, f"no {ext} file found in {art_dirs}"
    last = ""
    for path in files:
        ok, detail = checker(path)
        if ok:
            return True, detail
        last = detail
    return False, last


# ---------------------------------------------------------------------------
# per-task criteria (the objective success conditions from the task table)
# ---------------------------------------------------------------------------
async def _t1(page, art, before):
    got = await page.evaluate(H1)
    return (got == "Hello Bench"), f"h1={got!r}"


async def _t2(page, art, before):
    got = await page.evaluate(_text_expr("#result"))
    return (got == "OK:Ada|ada@example.com|pro"), f"#result={got!r}"


async def _t3(page, art, before):
    got = await page.evaluate(
        "[...document.querySelectorAll('.item')].slice(0, 10)"
        ".map(e => e.textContent.trim())")
    ok = (isinstance(got, list) and len(got) == 10
          and got[0] == "Item 1" and got[9] == "Item 10")
    return ok, f"first10={got!r}"


async def _t4(page, art, before):
    got = await page.evaluate(_text_expr("#status"))
    return (got == "accepted"), f"#status={got!r}"


async def _t5(page, art, before):
    got = await page.evaluate(_text_expr("#picked")) or ""
    return ("sample.txt" in got), f"#picked={got!r}"


async def _t6(page, art, before):
    seen = []
    for tab in await page.tabs():
        if tab in set(before or []):
            continue
        try:
            got = await page.evaluate(H1, tab=tab)
        except Exception as exc:                       # noqa: BLE001
            seen.append(("error", str(exc)[:80]))
            continue
        seen.append(got)
        if got == "Hello Bench":
            return True, f"new tab h1={got!r}"
    return False, f"no new tab with h1 'Hello Bench' (new tabs: {seen!r})"


async def _t7(page, art, before):
    got = await page.evaluate(_text_expr("#page"))
    return (got == "3"), f"#page={got!r}"


async def _t8(page, art, before, since=None):
    return _first_ok(art, ".png", _png_ok, since)


async def _t9(page, art, before, since=None):
    return _first_ok(art, ".pdf", _pdf_ok, since)


async def _t10(page, art, before):
    got = await page.evaluate(_text_expr("#secret"))
    return (got == "SECRET-OK"), f"#secret={got!r}"


CHECKS = {"T1": _t1, "T2": _t2, "T3": _t3, "T4": _t4, "T5": _t5,
          "T6": _t6, "T7": _t7, "T8": _t8, "T9": _t9, "T10": _t10}


ART_FRESH_TASKS = {"T8", "T9"}


def artifact_ok(task_id, art_dirs, since=None):
    """True iff a valid artifact for this task exists (T8 .png, T9 .pdf),
    with the same freshness rule as the judge.  None for other tasks."""
    if task_id == "T8":
        return _first_ok(list(art_dirs), ".png", _png_ok, since)[0]
    if task_id == "T9":
        return _first_ok(list(art_dirs), ".pdf", _pdf_ok, since)[0]
    return None


async def judge(task_id, page, art_dirs=(), before_tabs=None, art_since=None):
    """Return (success: bool, detail: str).  A transport error is reported as
    a failure detail, never swallowed.  For T8/T9, `art_since` is the mtime
    floor for artifact freshness (see the module docstring)."""
    try:
        if task_id in ART_FRESH_TASKS:
            ok, detail = await CHECKS[task_id](page, list(art_dirs),
                                               before_tabs, art_since)
        else:
            ok, detail = await CHECKS[task_id](page, list(art_dirs),
                                               before_tabs)
        return bool(ok), detail
    except Exception as exc:                           # noqa: BLE001
        return False, f"judge error: {type(exc).__name__}: {exc}"
