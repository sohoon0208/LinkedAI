# Runtime contracts and local checks

The host performs model dispatch. These helpers validate controller-stamped
artifacts and evidence freshness; they do not run model sessions, run AG, or
grant permissions. Python dependencies are declared in `requirements.txt`.

## Active run

The active bundle contains the packet, ASTRA HIGH plan, LUNA result, SOL HIGH
verification, baseline/current state, intent, and separate host receipts under
`workflow_variant: astra_high_luna_sol`.

Validate artifacts before relying on them:

```bash
./scripts/linkedai check schemas/astra-plan.schema.json /path/to/plan.json
./scripts/linkedai check schemas/sol-verification.schema.json /path/to/verification.json
./scripts/linkedai check-run /path/to/run/bundle.json --root /path/to/project
```

Only accept `DONE` if `check-run` succeeds, the verification authority is
`SOL`, the SOL receipt is `gpt-5.6-sol` / `high`, and the verification state is
`DONE`.

## Workspace state

Keep run outputs outside the subject repository. Record a baseline before
recon and planning:

```bash
./scripts/linkedai fingerprint --root /path/to/project
```

Git mode covers tracked and nonignored untracked files. For a non-Git project,
use explicit relative paths covering every changed and relevant verification
file. Recompute the final snapshot immediately before SOL verification; a
mismatch never silently rebases the run.

## Cross-artifact checks

The gate checks criterion coverage, required commands/observations, fresh
snapshots, user intent, model receipts, scope, and bounded counters.
Reproduction failures and earlier verification failures remain visible. A
passing rerun must explicitly resolve the same failed command.

`linkedai next-stage` maps SOL outcomes to bounded work. `REPLAN` returns to
fresh LUNA recon and ASTRA planning. `linkedai usage` summarizes explicitly
supplied cumulative counters; unknown host data stays unknown and is never
turned into zero.

The `luna-verification` schema and `astra_high_luna_echo` bundle are reserved
for the separately installed Echo Mode skill. Echo completion is intentionally
self-verifying and must not be reported as SOL verification.
