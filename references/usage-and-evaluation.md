# Usage coverage and quality evaluation

## Measure what the host exposes

Record run ID, participating thread/agent IDs, role/model assignments, and
usage-counter baselines before the run. Include the controller as well as ASTRA,
LUNA, and SOL; omitting a participant can create an illusory saving.

Where the host exposes usage events, retain only counters, identifiers, and
measurement boundaries in scoped run artifacts. Never collect raw reasoning,
credentials, or unrelated task histories. The local helper summarizes supplied
measurements; it does not attach to the desktop's private event stream or guess
missing telemetry.

Codex documents `thread/tokenUsage/updated` notifications. A host adapter may
export those events when available. Unsupported event shapes must be rejected
or explicitly reported as unavailable, not silently treated as zero.
See [official app-server events](https://learn.chatgpt.com/docs/app-server).

## Accounting rules

- Separate cumulative counters from per-call usage. Never sum repeated
  cumulative updates; use the final counter minus the known run baseline.
- A reused thread requires a baseline. Zero is valid only when its counters
  actually started at zero for this run.
- Deduplicate events, reject malformed/negative measurements, and handle
  counter resets and model reroutes explicitly.
- Cached input is a subset of input; reasoning output is a subset of output.
  Do not add either subset again to input + output.
- Missing or null means unknown. Report known subtotals and coverage; do not
  present a partial sum as a complete run total.
- An in-turn final report normally cannot include the end of its own output.
  Mark the measurement pre-final unless a later host observation includes it.
- Tokens are not account quota percentages. Do not infer subscription savings
  or dollar cost from token counts without the appropriate pricing/account data.

## Explicit stage intervals

The optional manifest `stage_intervals` array is the only stage-boundary
source. Each measured interval must provide a unique `id`, `stage`, positive
`attempt`, `thread_id`, `model`, `effort`, `counter_epoch`, and cumulative
`start`/`end` counter snapshots. Intervals may reuse a thread when their
explicit boundaries are disjoint. Boundaries are never inferred from event
order, timestamps, model names, or message text.

The usage helper keeps participant and role totals authoritative and emits
separate `stage_accounting` data. It validates duplicate IDs, overlap,
reversed or out-of-coverage boundaries, counter resets, incomplete metadata,
and ambiguous snapshots. Exact stage amounts are metric-wise; unknown values
remain unknown. Known participant totals reconcile against stage amounts plus
an explicit residual, while invalid attribution is PARTIAL or UNAVAILABLE.
Local non-model packet work may be recorded as `NOT_APPLICABLE` and contributes
no token count. Omitting `stage_intervals` preserves the legacy report shape.

Use `scripts/linkedai usage --help` for the accepted offline input and manifest
format. Keep role/model attribution tied to the explicit participant manifest.
Synthetic fixtures test arithmetic, not actual token use.

Coverage is relative to the supplied participant manifest. The helper cannot
discover an omitted controller or prove that the manifest lists every session.
Do not label its selected-participant total as a whole-run total unless that
inventory and the measurement boundaries are complete.

## Comparative evaluation

Before promising savings or ASTRA-only quality, evaluate both workflows on the
same starting snapshots, requirements, tools, permissions, and test budget.
Use a small fixed set representative of the user's projects: a local regression,
a cross-file change, a read-only diagnosis, a missing-evidence case, and a
high-risk boundary case. Do not use live production or deploy during a benchmark.

Run ASTRA-only and LinkedAI independently, with repeated trials where practical.
Keep task-specific hidden checks separate from the implementation agent's tests.
ASTRA-only is a comparison baseline, not proof of perfect correctness.

Record task/variant, resolved models/efforts, correctness, missed requirements,
regressions, retries, usage coverage and totals by role, and elapsed time. Count
failed runs and their usage too. Compare measured resources per correctly
completed task; cheaper failures must not look like an improvement.

Report observations and sample size, not a universal quality guarantee. A unit
suite and one live smoke test can validate mechanics while broader quality and
resource savings remain unmeasured.
