# specs/run.md — P6a: Batch runner & orchestration

Authority: `04-build-standards.md` §1 (P6a), §4 (fail loud), §10 (logging and
the run summary); `03-architecture.md` §2 (artifacts keyed by `row_uid`), §5
(determinism, resumability, observability, budget). Security: `05` §5
(config/prompt version skew).

Depends on P2, P3, P5, P6. Depends on nothing downstream — the stages that do
not exist yet are simply not in the sequence, and adding them later is adding
a call, not restructuring the runner.

**Why this phase exists at all** is worth restating, because it was not in the
original P0–P15 plan. `04` §2's layout lists `src/nimo/run/` as "batch runner,
CLI"; `04` §4 routes *all* per-row failure handling through "the runner";
`03` §2 requires every stage to write artifacts keyed by `row_uid`; `03` §5
requires the runner to process by `row_uid`, skip completed rows and survive
interruption. Four load-bearing requirements across three documents, and no
phase owned any of them — `src/nimo/run/__init__.py` was 0 bytes. See
`02-decision-log.md`.

---

## 1. Scope

The runner drives every `dev` or `qa` row through the stages that exist today:

    [0] normalize   (P3)  RawRow          -> ProductQuery
    [1] registry    (P6)  ProductQuery    -> RegistryLookupResult
    [5] classify    (P5)  ProductQuery    -> ModulePrediction

Stages 2–4 (retrieval, fetch, match) and 6–8 (characteristics, reasoning,
assembly) are not built. The runner's sequence is explicit and ordered, so
inserting them later is inserting a call and a stage name, not a redesign.

**Not in scope:** the submission file. That is P14 (assembly), and writing a
half-populated `qa` sheet now would be exactly the "partial output row" `04`
§4 forbids. The runner produces per-row artifacts, a trace, a failure log and
a summary.

## 2. Failure handling — the one rule this phase exists to enforce

`04` §4: per-row failures are "caught at exactly one place — the runner —
recorded as a typed `RowFailure` with stage, exception type, and message, and
the row continues as a failure, not as a partial success."

Concretely, and these are requirements:

- **Exactly one `except Exception` in the codebase, here.** `04` §4 forbids
  `except Exception` without "re-raise or an explicit, logged, typed failure
  record"; this is that sanctioned typed-failure-record site and the only one.
  A stage raising anything at all becomes a `RowFailure`.
- **The stage is attributed, not guessed.** A cursor variable advances as the
  row moves through the sequence, so the `RowFailure.stage` is the stage that
  actually raised rather than the last one anybody remembers.
- **One failing row never aborts the run.** 411 good rows are worth more than
  a clean traceback.
- **A failed row writes no artifacts at all.** Not a partial set, not a
  best-effort subset — `04` §4's "never write a partial output row" applies to
  the intermediate artifacts too, because a later stage reading a
  half-populated artifact set is exactly how a plausible wrong answer gets
  built.
- **What does abort the run:** a batch-level failure — the workbook missing,
  the config invalid, the classifier failing to fit. Those are not per-row
  conditions and retrying 412 times would just print the same error 412 times.

## 3. Artifacts and resumability

`03` §2: every stage writes its intermediate artifact to disk keyed by
`row_uid`. `03` §5: the runner processes by `row_uid`, skips completed rows,
and survives interruption.

    data/out/artifacts/<stage>/<sheet>-<index>.json    one row, one stage
    data/out/trace.jsonl                               one record per row
    data/out/failures.jsonl                            one RowFailure per failed row

**`row_uid` is sanitized for the filename, never for the content.** `dev:0`
becomes `dev-0.json`, because `:` is not a legal filename character on
Windows — a detail that would otherwise surface as a mid-run crash on the
machine this project is being built on. The `row_uid` inside the file stays
`dev:0`.

**One file per row per stage, written atomically** (temp file, then rename)
rather than one appended JSONL per stage. A `SIGKILL` mid-append leaves a
truncated final line whose recovery is a judgement call — "is this corruption
or a partial write?" — and a runner that guesses wrong either loses good rows
or resumes from bad ones. A rename is atomic on both POSIX and Windows, so a
file either exists complete or does not exist. 412 rows × 3 stages is ~1236
small files, which is a price worth paying for a resume path with no
ambiguity in it.

**Resume rule:** a row is complete when every stage in the sequence has a
readable artifact for it. Complete rows are skipped entirely — no
re-normalizing, no re-predicting. A row with *some* artifacts is re-run from
the start and its artifacts overwritten; partial state is never trusted,
because the run that produced it was interrupted for an unknown reason.

## 4. Determinism

`04` §5: a re-run with no code change produces byte-identical output.

The artifacts satisfy this exactly — `ProductQuery`, `RegistryLookupResult`
and `ModulePrediction` carry no clock, no RNG and no set iteration.

Two things deliberately do *not*, and saying so is the point:

- **`RunSummary.wall_time_s`** measures wall time. It is an observability
  number, not output.
- **`RowFailure.occurred_at`** is a timestamp. `03` §3 already marks it
  "metadata only, never read by logic". The runner takes its clock as a
  parameter so tests can pin it; production passes `datetime.now(UTC)`.

The byte-identical claim therefore covers the artifact tree and the trace,
which is what downstream stages read, and not the summary line.

## 5. `config_hash` — `05` §5's version-skew guardrail

`05` §5 requires recording a config+prompt hash per row so that "which config
produced this output" is answerable after the fact. `RunSummary.config_hash`
is `sha256` over the sorted contents of every file in `config/`, and it goes
into every trace record.

Hashing file *contents*, not mtimes: a checkout, a copy or a `git clone`
changes mtimes without changing behavior, and a hash that moves when nothing
meaningful changed teaches people to ignore it.

## 6. The run summary

`04` §10 requires every run to print rows processed, rows failed by stage, LLM
calls, tokens, cost, wall time and cache hit rate. `RunSummary` (`03` §3)
carries all of it. At P6a the LLM and cache counters are structurally zero —
there is no LLM client and no fetch cache yet — and they are **reported as
zero rather than omitted**, so the fields are wired end-to-end before the
phases that populate them arrive.

`tier_counts` is the one that earns its place immediately: it is the evidence
for `03` §1a's efficiency claim, and on a cold registry it reads
`tier2_retrieval: 412`, which is the honest cold-start number.

## 7. Acceptance criteria

1. All 412 `dev` rows are driven through normalize → registry → classify, and
   412 artifact sets exist afterwards.
2. **A deliberately failing row is recorded as a typed `RowFailure` with the
   correct stage, does not abort the run, and leaves no artifacts behind.**
   The other 411 rows complete.
3. Killing a run partway and restarting resumes without redoing completed
   rows — asserted by counting stage invocations, not by timing.
4. A second full run over a complete artifact tree performs zero work and
   produces a byte-identical tree.
5. `RunSummary` reports `rows_total`, `rows_succeeded`, `rows_failed`,
   `failures_by_stage` and `tier_counts` that add up.
6. `config_hash` is stable across runs and changes when a `config/` file
   changes.
7. `row_uid` survives the filename round trip: the artifact for `dev:0` is at
   `dev-0.json` and contains `"row_uid": "dev:0"`.
8. Zero network, zero LLM, `data/raw/` never written.

## 8. Files

```
src/nimo/run/__init__.py    public surface
src/nimo/run/artifacts.py   paths, atomic write, read, completeness check
src/nimo/run/runner.py      the per-row driver, the one except, RunSummary
src/nimo/run/__main__.py    CLI — `uv run python -m nimo.run --sheet dev`
tests/run/                  mirrors the above
```

## 9. Tests

Beyond `04` §11:

- **The failing-row test is the phase**, and it asserts three things at once:
  the `RowFailure` has the right stage, the run completes, and the failed
  row's artifact directory is empty.
- **Resume counts work, not wall time.** A counting wrapper around a stage
  asserts it is invoked 0 times on the second run.
- **Byte-identical re-run** over the artifact tree.
- **`row_uid` filename round trip**, including that `:` never reaches a path.
- **`config_hash` changes when a config file changes**, using a temp config
  directory rather than mutating the real one.
- **Failure attribution per stage**: a stage forced to raise reports *that*
  stage, for each of the three.
- No test touches the network (`04` §6).

## 10. Definition of Done

`04` §11's checklist, plus:

- [ ] Exactly one `except Exception` in `src/`, in the runner, with the typed
  failure record `04` §4 mandates — asserted by a test that greps the tree
- [ ] `04` §1's P6a row marked done with the gate numbers
- [ ] Decision-log entry for anything this phase changes in `03`/`04`
