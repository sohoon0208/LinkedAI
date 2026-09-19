# Verification and completion

ASTRA HIGH defines unique nonempty acceptance-criterion IDs for the plan.
LUNA covers exactly those IDs and returns direct evidence. SOL HIGH
independently reviews the goal, plan, code/test excerpts, command results,
observations, and fresh snapshot; it does not rely on LUNA's confidence claim.

Choose proof that fits the claim: tests for behavior, builds for compilation,
runtime observations for runtime claims, and screenshots/direct observations
for visual claims. A passing build is not runtime/UI proof. Zero discovered or
all-skipped tests do not satisfy a required check.

Keep run ID, plan ID, actual host agent IDs, and fingerprints together.
Preserve reproduction and failed-verification history. A later passing run may
resolve a failure only through an explicit command link; do not erase it during
packet compression.

The local completion gate rejects missing or duplicate criterion coverage,
stale snapshots, invalid model receipts, read-only mutations, unresolved
failures, and invalid counters. A schema-valid artifact is not enough.

SOL states are authoritative:

- `DONE`: every criterion and required check is proven, no unknowns or next
  action remain, and the current snapshot is fresh.
- `RETRY`: LUNA can correct a specified failure inside the current plan.
- `REPLAN`: the strategy, scope, or acceptance criteria must change; LUNA
  refreshes the packet and ASTRA issues a new plan.
- `EVIDENCE`: LUNA must collect named missing proof before SOL rechecks.
- `BLOCKED`: required evidence, capability, model confirmation, or a bounded
  ceiling is unavailable.

Only a controller-stamped SOL HIGH `DONE` closes the main workflow. Echo Mode
uses a separate LUNA verification contract and is explicitly self-verifying;
its completion authority is LUNA, not SOL.
