"""The ten bench tasks.

`judge` lives in judge.py and is shared byte-for-byte by both sides.

`goal` is the ONLY thing side B (browser-use) sees: one natural-language
sentence. It deliberately contains no CSS selector, no element id, no
expected value and no step list (red line 3).
"""
from common import FIXTURES, url
import os

SAMPLE_FILE = os.path.join(FIXTURES, "sample.txt")

TASKS = [
    {
        "id": "T1",
        "page": "hello.html",
        "goal": "Tell me the main heading text on this page.",
    },
    {
        "id": "T2",
        "page": "form.html",
        "goal": ("Fill in the form on this page with the name Ada, the email "
                 "ada@example.com and the pro plan, then submit the form."),
    },
    {
        "id": "T3",
        "page": "list.html",
        "goal": "Read the text of the first ten items on the list.",
    },
    {
        "id": "T4",
        "page": "dialog.html",
        "goal": ("Click the button on this page, then accept the confirmation "
                 "dialog that appears."),
    },
    {
        "id": "T5",
        "page": "upload.html",
        "goal": (f"Upload the local file {SAMPLE_FILE} using the file input "
                 "on this page."),
    },
    {
        "id": "T6",
        "page": "tabs.html",
        "goal": ("Click the link on this page to open it in a new tab, then "
                 "tell me the main heading on that new tab."),
    },
    {
        "id": "T7",
        "page": "list.html",
        "goal": "Go to the last page of the list.",
    },
    {
        "id": "T8",
        "page": "hello.html",
        "goal": ("Take a screenshot of the current page and save it as an "
                 "image file."),
    },
    {
        "id": "T9",
        "page": "hello.html",
        "goal": "Save the current page as a PDF file.",
    },
    {
        "id": "T10",
        "page": "login.html",
        "goal": ("Log in with the username bench and the password bench, then "
                 "open the private page."),
    },
]

TASK_BY_ID = {t["id"]: t for t in TASKS}


def start_url(task_id: str) -> str:
    return url(TASK_BY_ID[task_id]["page"])
