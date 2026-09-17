# wb-bench — phase 2 summary

* records: 60 (A=30, B=30)

## Main table — task x side (success = how many of the 3 reps passed)

| task | side | success | avg s | B steps | B prompt tok | B cached tok | B completion tok | B prompt tok/step | B cost USD |
|---|---|---|---|---|---|---|---|---|---|
| T1 | A | 3/3 | 1.04 | 0 | 0 | 0 | 0 | 0 | 0.000000 |
| T1 | B | 3/3 | 11.95 | 5.7 | 43939.0 | 42112.0 | 1348.3 | 7772.40 | 0.002419 |
| T2 | A | 3/3 | 0.07 | 0 | 0 | 0 | 0 | 0 | 0.000000 |
| T2 | B | 3/3 | 16.51 | 6.0 | 37857.0 | 35626.7 | 1571.0 | 6438.70 | 0.002768 |
| T3 | A | 3/3 | 0.06 | 0 | 0 | 0 | 0 | 0 | 0.000000 |
| T3 | B | 3/3 | 18.89 | 6.0 | 45041.7 | 42453.3 | 2177.0 | 7441.32 | 0.003644 |
| T4 | A | 3/3 | 0.58 | 0 | 0 | 0 | 0 | 0 | 0.000000 |
| T4 | B | 3/3 | 15.79 | 3.7 | 26964.3 | 25813.3 | 1361.0 | 7183.40 | 0.002133 |
| T5 | A | 3/3 | 0.07 | 0 | 0 | 0 | 0 | 0 | 0.000000 |
| T5 | B | 3/3 | 46.87 | 8.3 | 59955.7 | 56064.0 | 6711.0 | 7214.94 | 0.009557 |
| T6 | A | 3/3 | 0.43 | 0 | 0 | 0 | 0 | 0 | 0.000000 |
| T6 | B | 3/3 | 17.62 | 6.7 | 51542.3 | 48981.3 | 1847.3 | 7771.74 | 0.003279 |
| T7 | A | 3/3 | 0.07 | 0 | 0 | 0 | 0 | 0 | 0.000000 |
| T7 | B | 3/3 | 25.93 | 7.3 | 48675.3 | 45738.7 | 2700.7 | 6510.64 | 0.004396 |
| T8 | A | 3/3 | 0.11 | 0 | 0 | 0 | 0 | 0 | 0.000000 |
| T8 | B | 0/3 | 58.91 | 7.3 | 53603.0 | 49792.0 | 8755.0 | 7466.05 | 0.011948 |
| T9 | A | 3/3 | 1.11 | 0 | 0 | 0 | 0 | 0 | 0.000000 |
| T9 | B | 3/3 | 38.89 | 7.3 | 56199.0 | 52778.7 | 5514.0 | 7431.28 | 0.007960 |
| T10 | A | 3/3 | 0.12 | 0 | 0 | 0 | 0 | 0 | 0.000000 |
| T10 | B | 3/3 | 53.67 | 10.7 | 82326.7 | 77013.3 | 6115.7 | 7632.44 | 0.009395 |

### Totals (over every record actually run, all reps)

* Side A: 30/30 succeeded, 11.00 s wall clock over all reps (3.67 s/rep), $0.000000 total (no LLM).
* Side B: 27/30 succeeded, 915.15 s wall clock over all reps (305.05 s/rep), $0.172496 total ($0.057499/rep).
* Side B tokens: prompt 1518312 (cached 1429120, 94.1%), completion 114303, steps 207.
* The per-task rows above are means over the reps; these totals are sums over every record, so they are ~reps-times larger than a single column of the table.

## Representation cost — tokens to put one page in front of a model

* primary counter: `tiktoken cl100k_base`  (**PROXY COUNT**)
* sensitivity cross-check: `tiktoken o200k_base`

| task | page | (a) browser-use full tree | (b) our snapshot | (c) the one evaluate the judge needs |
|---|---|---|---|---|
| T1 | hello.html | 4 | 45 | 4 tokens |
| T2 | form.html | 110 | 288 | 11 tokens |
| T3 | list.html | 52 | 83 | 50 tokens |
| T4 | dialog.html | 14 | 83 | 3 tokens |
| T5 | upload.html | 40 | 84 | 4 tokens |
| T6 | tabs.html | 11 | 84 | 4 tokens |
| T7 | list.html | 52 | 83 | 3 tokens |
| T8 | hello.html | 4 | 45 | 0 tokens (0 — no evaluate; judge reads a local file) |
| T9 | hello.html | 4 | 45 | 0 tokens (0 — no evaluate; judge reads a local file) |
| T10 | login.html | 49 | 189 | 5 tokens |

## Honest notes / things that are not fair or not certain

* Cache: DeepSeek prompt-cache hits make billed input cheap, but the cache is a price discount only. The cached tokens are still real context the model must carry and still cost latency, so both the token count and the cost are reported: side B total prompt tokens 1518312 of which 1429120 were cache hits (94.1% of prompt tokens), yet all 30 side-B runs together cost an estimated $0.172496. Cost is an ESTIMATE from the LiteLLM price table via browser-use's TokenCost, not an invoice; DeepSeek's real bill can differ (cache pricing tiers, off-peak discounts, rounding).
* use_vision=False: DeepSeek here is a text-only model, so browser-use sends no screenshots. Every screenshot-sized image would otherwise be converted to image tokens, so this setting is a token SAVING for side B, not a handicap; a vision model's side-B token cost would be higher. Side A is unaffected (it never sends a page to a model at all).
* time_to_first_action_s is NOT the same measurement on the two sides. Side A = wall time to the first /command reply (a local HTTP call). Side B = wall time to the end of the agent's first LLM step, which includes one full network round-trip to the model. It is not used for any conclusion here.
* Representation cost is a SEPARATE measurement from the end-to-end A/B table: it only counts how many tokens each way of describing one page would cost, measured on an isolated browser, with no agent running. It must not be read as a success-rate or latency result.
* Token counts are PROXY counts: DeepSeek does not publish its production tokenizer as a pip-installable counter, so both counts are PROXY COUNTS produced by tiktoken BPE encodings and are NOT DeepSeek's own token counts. Absolute numbers will differ from DeepSeek's tokenizer by some percentage; what is being compared here is the relative size of the three representations of the same page text. o200k_base is reported alongside cl100k_base purely as a sensitivity check on that uncertainty.
* Both sides run the same judge.py with no `if side == ...`; a failure or a 120s timeout is recorded as a failure on both sides and is never retried away (run_meta.json: retries=0).
* Bench-level retries are 0 for both sides, but browser-use runs its own model-output retry loop: 18/30 side-B records carry 32 agent-internal errors in total (mostly DeepSeek emitting raw DSML tool-call markup instead of the JSON the schema asks for). Those retries are the model's real reliability cost and are left visible in `agent_errors`.
* T8 on side B is the one row that is NOT a clean agent failure: 0/3. Side B's agent did save screenshots - 5 valid PNG file(s) were found under out/b/rep*/downloads/ - but browser-use's `downloads_path` is set per rep, while judge.py scans only the per-task artifact directory (out/b/rep*/T8). Side A writes straight into that per-task directory, so the two sides do not place artifacts in the same folder. The judge was NOT changed to paper over this (that would violate red line 1), so T8 is reported as a failure on side B; treat it as a harness artifact, not a capability gap.


## Addendum — T8/T9 artifact-judging re-run (after fixing the judge)

### Why T8 on side B failed in the original run

* Judge scanned the wrong directory: side B's browser-use downloads land in
  `out/b/rep<N>/downloads/` (`side_b.py` sets `downloads_path=<art_root>/downloads`),
  but the judge only scanned the per-task dir `out/b/rep<N>/T8/`. The agent's
  file was real and valid (`out/b/rep1/downloads/hello-screenshot.png`, 31,668 B,
  valid PNG header) yet was never looked at.
* Correction to the premise that the original B/T8 failure was a 120 s timeout:
  the original records in `logs/results.jsonl` carry `error=""` for all three
  B/T8 reps, with durations 40.58 s / 46.21 s / 89.95 s and the failure detail
  "no .png file found". So the original failure was *only* the judge directory
  miss, not a timeout. Reported honestly per red line 4; the "120s timeout"
  reading is not present in the original data.

### The fix (minimal, both sides)

* Side B artifact dirs changed from `[out/b/rep<N>/T8]` to
  `[out/b/rep<N>/T8, out/b/rep<N>/downloads]`.
* Freshness rule added for both sides: a file only counts when its mtime is
  >= task start - 1 s, so a stale same-named file from an earlier rep is never
  mistaken for this run's output (documented in `judge.py`'s docstring).
* No success criterion was relaxed and no assertion was changed.

Command: `--tasks T8,T9 --sides a,b --reps 3`, written to the new log
`logs/results-artifacts.jsonl`; the original `logs/results.jsonl` was not
touched (byte-identical before/after).

### Re-run results (T8/T9, both sides, 3 reps)

| task | side | rep | success | within 120 s | artifact valid | seconds |
|---|---|---|---|---|---|---|
| T8 | A | 1 | yes | yes | yes | 1.094 |
| T8 | A | 2 | yes | yes | yes | 1.062 |
| T8 | A | 3 | yes | yes | yes | 1.070 |
| T8 | B | 1 | no | no | no | 120.143 |
| T8 | B | 2 | no | no | no | 120.071 |
| T8 | B | 3 | yes | yes | yes | 45.865 |
| T9 | A | 1 | yes | yes | yes | 1.133 |
| T9 | A | 2 | yes | yes | yes | 1.132 |
| T9 | A | 3 | yes | yes | yes | 1.137 |
| T9 | B | 1 | yes | yes | yes | 12.454 |
| T9 | B | 2 | yes | yes | yes | 9.551 |
| T9 | B | 3 | yes | yes | yes | 7.588 |

* B/T8 rep1 and rep2 genuinely timed out at ~120 s and produced no fresh
  artifact; the stale `downloads/screenshot.png` files from the original run
  were correctly rejected by the freshness rule. B/T8 rep3 produced a fresh
  `downloads/screenshot.png` (31,668 B) in 45.9 s and passed.

### Honest statement

This is a re-run performed AFTER fixing the judge. The original B/T8 failure
record is still present in `logs/results.jsonl` and was not edited: the two
numbers are kept side by side — original B/T8 = 0/3 (judge scanned the wrong
directory) and re-run B/T8 = 1/3 under the same judging logic (2 genuine 120 s
timeouts, 1 valid fresh PNG).
