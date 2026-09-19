# Verification and completion

## Profiles

LinkedAI keeps one independent SOL authority but uses a verification profile
matched to the task:

| Profile | Route | What it proves |
| --- | --- | --- |
| `BALANCED` | FAST/STANDARD main workflow | All acceptance criteria, changed-file scope, relevant targeted checks, and unresolved failures. Fingerprints and exact host receipts are optional for bounded source changes. |
| `FULL` | DEEP main workflow and legacy bundles | The balanced checks plus fresh repository/baseline fingerprints, exact receipts, and every planned check/observation. |
| `QUICK` | Echo Mode | The balanced checks in a LUNA self-verification pass, with no independent SOL and no automatic replan. |

The profile changes evidence depth, not authority. Main LinkedAI still needs
SOL for `DONE`; Echo Mode still uses LUNA as its explicit self-verifying
authority.

ASTRA HIGH defines unique nonempty acceptance-criterion IDs for the plan.
LUNA covers exactly those IDs and returns direct evidence. SOL HIGH
independently reviews the goal, plan, code/test excerpts, command results,
observations, and profile-appropriate freshness evidence; it does not rely on
LUNA's confidence claim.

Choose proof that fits the claim: tests for behavior, builds for compilation,
runtime observations for runtime claims, and screenshots/direct observations
for visual claims. A passing build is not runtime/UI proof. Zero discovered or
all-skipped tests do not satisfy a required check. “Relevant” means a check
that directly exercises an acceptance criterion or the changed behavior; do
not add unrelated suites merely to make a light run look comprehensive.

Keep run ID, plan ID, actual host agent IDs, and fingerprints together.
Preserve reproduction and failed-verification history. A later passing run may
resolve a failure only through an explicit command link; do not erase it during
packet compression.

The local completion gate rejects missing or duplicate criterion coverage,
invalid scope, unresolved failures, and invalid counters. FULL also rejects
stale snapshots and invalid exact model receipts. A schema-valid artifact is
not enough.

SOL states are authoritative:

- `DONE`: every criterion and required check is proven, no unknowns or next
  action remain, and the current snapshot is fresh.
- `RETRY`: LUNA can correct a specified failure inside the current plan.
- `REPLAN`: the strategy, scope, or acceptance criteria must change. FULL may
  refresh the packet and ask ASTRA for a new plan; BALANCED and QUICK stop or
  escalate instead of automatically replanning.
- `EVIDENCE`: LUNA must collect named missing proof before SOL rechecks.
- `BLOCKED`: required evidence, capability, model confirmation, or a bounded
  ceiling is unavailable.

Only a controller-stamped SOL HIGH `DONE` closes the main workflow. Echo Mode
uses a separate LUNA verification contract and is explicitly self-verifying;
its completion authority is LUNA, not SOL.
