# Benchmark — Webflow Bridge vs. a browser-use agent

A reproducible head-to-head on the same ten scripted browser tasks: one side is
a fixed Webflow Bridge `POST /command` sequence with no LLM anywhere, the other
is a browser-use agent whose model chooses every action. The rig, the harness
and the raw logs live in [`bench/`](../bench/).

## Setup

| | side A | side B |
|---|---|---|
| driver | Webflow Bridge daemon + extension | browser-use 0.13.10 with playwright 1.63 |
| decisions | a fixed `POST /command` sequence per task | the model decides every action |
| model | none | DeepSeek, via browser-use's `ChatOpenAI` |
| page-to-model input | none | text only — `use_vision=False`, so no screenshots are sent |

Both sides ran on the same machine: 10 tasks × 3 repetitions × both sides. Each
task has a 120 s timeout and a timeout is recorded as a failure; neither side is
retried away (bench-level retries are `0` on both sides). Success is decided by
one shared judge — the same `bench/harness/judge.py` code path for both sides,
with no `if side == ...` branch.

## Main results

Averages are over the three repetitions; successes are `passed/3`.

| Task | Our side (success · avg s) | Agent side (success · avg s) | Agent steps | Agent prompt tokens | Agent cost |
|---|---|---|---|---|---|
| T1 read the page heading | 3/3 · 1.04 | 3/3 · 11.95 | 5.7 | 43,939 | $0.002419 |
| T2 fill and submit a form | 3/3 · 0.07 | 3/3 · 16.51 | 6.0 | 37,857 | $0.002768 |
| T3 read the first ten list items | 3/3 · 0.06 | 3/3 · 18.89 | 6.0 | 45,042 | $0.003644 |
| T4 accept a confirm dialog | 3/3 · 0.58 | 3/3 · 15.79 | 3.7 | 26,964 | $0.002133 |
| T5 upload a local file | 3/3 · 0.07 | 3/3 · 46.87 | 8.3 | 59,956 | $0.009557 |
| T6 open a new tab and read it | 3/3 · 0.43 | 3/3 · 17.62 | 6.7 | 51,542 | $0.003279 |
| T7 page to the third page | 3/3 · 0.07 | 3/3 · 25.93 | 7.3 | 48,675 | $0.004396 |
| T8 screenshot to a file | 3/3 · 0.11 | 0/3 · 58.91 | 7.3 | 53,603 | $0.011948 |
| T9 save the page as PDF | 3/3 · 1.11 | 3/3 · 38.89 | 7.3 | 56,199 | $0.007960 |
| T10 read a page behind a login | 3/3 · 0.12 | 3/3 · 53.67 | 10.7 | 82,327 | $0.009395 |

## Totals

| | our side | agent side |
|---|---|---|
| successes | 30/30 | 27/30 |
| wall clock, 30 runs | 11.00 s | 915.15 s |
| prompt tokens | 0 | 1,518,312 (1,429,120 cached — 94.13%) |
| completion tokens | 0 | 114,303 |
| steps | — | 207 |
| cost | $0 | $0.172496 (estimated, not an invoice) |

## The one T8 failure

T8 on the agent side reads `0/3` in the table above, and that number is a
harness false negative, not an agent failure. The judge scanned only the
per-task artifact directory, while browser-use writes downloads into a per-rep
`downloads/` directory; the agent produced a valid PNG in all three original
repetitions, and the judge never looked at those files. After the judge's
directory scan was corrected, T8/T9 were re-run: our side 3/3 (≈1.1 s), the
agent side 1/3 (one success at 45.9 s, two 120 s timeouts). Both numbers are
kept side by side — the original `0/3` record is not deleted or edited, and the
re-run is stored separately in `bench/results/results-artifacts.jsonl`.

## Representation cost

Tokens to put one page in front of a model, summed over the ten tasks' start
pages. Column (c) is only the single `evaluate` the judge actually reads to
decide the task — not what either side sends to a model.

| (a) agent's full tree | (b) our `snapshot` | (c) the one `evaluate` the judge needs |
|---|---|---|
| 340 | 1,029 | 84 |

These are proxy counts from `tiktoken` (`cl100k_base`), not DeepSeek's own
tokenizer, which is not published as an installable counter; the `o200k_base`
sensitivity check gives 341 / 1,019 / 84. Absolute values will differ from the
model's by some percentage, so only the relative size of the three
representations of the same page is being compared. This set measures
representation cost only and is not merged with the latency or success-rate
results above.

## What this does and does not show

- (a) Across this batch the two sides' success rates are comparable, so what
  differs here is cost and reproducibility, not the ability to complete the
  tasks.
- (b) Our `snapshot` representation is larger than the agent's tree —
  1,029 tokens against 340 — which is a known improvement point, not an
  advantage.
- (c) The local minimal test pages cannot stand in for a real large page, so
  these representation and latency figures should not be read as what
  production pages would cost.

## Reproduce

The full method, prerequisites, commands and archived raw logs are in
[`bench/README.md`](../bench/README.md).
