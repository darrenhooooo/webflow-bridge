# bench — Webflow Bridge (deterministic) vs browser-use (agent)

> **Published copy:** machine-specific absolute paths in `bench/results/` were
> replaced with `/path/to/...` placeholders. No measurement value was changed:
> each affected file is parsed as JSON (jsonl line by line) before and after,
> and every numeric field — including numbers embedded in string values — is
> compared field by field and must be equal.

A reproducible head-to-head on the same ten browser tasks: one side is a fixed
Webflow Bridge `POST /command` sequence with **no LLM**, the other is a
[browser-use](https://github.com/browser-use/browser-use) agent whose LLM
chooses every action itself. Both sides are scored by one shared judge.

## The two sides

| | side A | side B |
|---|---|---|
| driver | Webflow Bridge daemon + extension | browser-use `Agent` |
| decisions | a fixed command sequence per task (`harness/side_a.py`) | the model decides every action |
| LLM | none anywhere | DeepSeek over its OpenAI-compatible endpoint via `ChatOpenAI` |
| what it sees | the sequence in `side_a.py` | exactly `"<goal>\n\nStart from this page: <url>"` — one sentence, no selector, no element id, no expected value, no step list |
| success decided by | `harness/judge.py` | the same `harness/judge.py`, same code path, no `if side == ...` |

Each side has a 120 s timeout per task; a timeout is a failure and is never
retried away (bench-level retries are `0` on both sides).

## Layout

```
harness/   the runner: run.py, side_a.py, side_b.py, judge.py, tasks.py,
           wb_stack.py, common.py, summarize.py, representation.py
site/      the 8 static test pages (hello, form, list, dialog, upload, tabs,
           login, private)
fixtures/  sample.txt, the file T5 uploads
results/   the archived run, with machine-specific paths replaced by placeholders (see "Results")
```

## How to run

### Prerequisites

- [`uv`](https://docs.astral.sh/uv/) and Python 3.12.
- a Chrome/Chromium binary for side A (default
  `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`, override
  with `WB_CHROME`).
- the Webflow Bridge repo this `bench/` sits in, used read-only. It is found
  automatically (the parent of `bench/`); override with `WB_REPO`.
- network plus a DeepSeek key for side B. The harness reads it only from the
  environment variable `DEEPSEEK_API_KEY`, and never writes it to a file or a
  log. An optional `DEEPSEEK_BASE_URL` overrides the endpoint.

### Setup

Run everything from this `bench/` directory.

```bash
cd bench

# Python 3.12 venv (browser-use, playwright, the CDP client, tiktoken)
uv venv envs/.venv-bu --python 3.12
uv pip install --python envs/.venv-bu/bin/python \
    browser-use playwright websocket-client tiktoken
envs/.venv-bu/bin/python -m playwright install chromium

# side B needs DeepSeek credentials in the environment; see Prerequisites
```

### Run

```bash
# (1) token cost of one page's representation: ~1 min, no LLM, $0
envs/.venv-bu/bin/python harness/representation.py

# (2) the full A/B run: 10 tasks x 3 reps x both sides
envs/.venv-bu/bin/python harness/run.py \
    --tasks T1,T2,T3,T4,T5,T6,T7,T8,T9,T10 --sides a,b --reps 3 \
    --deadline-min 50

# (3) rebuild summary.md / summary.json from the raw records
envs/.venv-bu/bin/python harness/summarize.py
```

`run.py` starts and stops the local test site itself (`python3 -m http.server`
on port 8901). The other ports are: isolated Webflow Bridge daemon HTTP 20086
/ WS 20087, side A's isolated Chrome DevTools 20088, side B's playwright
chromium on its own ephemeral port. Ports 9222, 10086, 10087 and 10096 are
never used. Isolation details: the isolated daemon gets its own
`WBF_TOKEN[_FILE]` under `/tmp`, the extension is loaded from a `/tmp` copy
with its ports rewritten, and both browsers use throwaway `/tmp` profiles. The
repo is never modified by the harness.

### Expected duration and cost

Measured when the archived run was produced (Apple silicon, 2026-09-17):

| phase | wall clock | API cost |
|---|---|---|
| side A, 3 reps × 10 tasks | ~16 s | $0 (no LLM) |
| side B, 3 reps × 10 tasks | ~15 min | ~$0.17 estimated |
| representation measurement | ~1 min | $0 (no LLM) |
| whole run | ~16 min | ~$0.17 estimated |

Per side-B task the estimate landed between roughly $0.002 and $0.012. The
worst case is far worse: if all 30 side-B runs timed out at 120 s each that is
60 min, which is why the runner defaults to a 50-minute deadline and records
every `(side, rep, task)` it never started under `skipped` (counted as
not-attempted, never as a failure). Cost is an **estimate** from the upstream
LiteLLM price table via browser-use's `TokenCost`, not an invoice.

A fresh run writes its own `logs/` and `out/` directories; the archived run
shipped here lives separately in `results/` and is not overwritten.

## Results

`results/` holds the archived run, with machine-specific absolute paths
replaced by `/path/to/...` placeholders and no measurement value changed:

| file | what |
|---|---|
| `results.jsonl` | one raw record per (task, side, rep), the formal 60-record run |
| `results-artifacts.jsonl` | a separate T8/T9 rerun (run `20260917-153426`) |
| `run_meta.json` | run id, versions, model, per-rep times, skipped list |
| `summary.md` | the tables plus the honest notes, derived from the raw records |
| `summary.json` | the same summary as machine-readable JSON |
| `representation.json` | the three page representations measured in tokens |

These files are evidence and are otherwise kept exactly as produced. The
machine-specific absolute paths they originally embedded (the repo path and the
recorder's `wb-bench` path) were replaced with `/path/to/...` placeholders for
publication; that is the only edit, and every numeric value was verified
unchanged by re-parsing each file as JSON before and after and comparing all
numeric fields. The harness itself takes no absolute personal path (use
`WB_REPO` to point it at the repo).

A human-readable write-up of what the numbers mean lives in `docs/BENCH.md`.

## Honest notes

- **T8 on side B in `results.jsonl` (0/3) is a harness false negative, not a
  capability gap.** The judge scanned only the per-task artifact directory
  while browser-use writes downloads into a per-rep `downloads/` directory, so
  it could not see the PNG the agent really saved. The judge's directory scan
  was corrected and T8/T9 were rerun; that rerun is `results-artifacts.jsonl`,
  where T8 on side B is **1/3**. Both numbers are kept side by side — the
  original 0/3 is not deleted or edited.
- **Prompt-cache hits cut the bill, not the context.** About 94% of side-B
  prompt tokens were served from DeepSeek's prompt cache, which makes the
  billed input cheap, but cached tokens are still real context the model has
  to carry and still cost latency. Both the token count and the cost are
  reported.
- **The representation-cost numbers are proxy counts.** They come from
  `tiktoken` (`cl100k_base`, with `o200k_base` as a sensitivity check), not
  from DeepSeek's own tokenizer, which is not published as an installable
  counter. Absolute counts will differ from the model's by some percentage;
  only the relative size of the three representations of the same page is
  being compared. The file is marked `"proxy": true`.
- **The test site is local, minimal static HTML.** These pages are far smaller
  and simpler than a real production page, so the representation and latency
  figures here should not be read as what a real large page would cost.
