# Runtime contracts and local checks

The host performs model dispatch. These helpers validate controller-stamped
artifacts and evidence freshness; they do not run model sessions, run AG, or
grant permissions. Python dependencies are declared in `requirements.txt`.

## Active run

The active bundle contains the packet, ASTRA HIGH plan, LUNA result, SOL
verification, intent, profile, and separate host receipts under
`workflow_variant: astra_high_luna_sol`. New FAST/STANDARD bundles use
`verification_profile: BALANCED`; DEEP uses `FULL`.

Validate artifacts before relying on them:

```bash
./scripts/linkedai check schemas/astra-plan.schema.json /path/to/plan.json
./scripts/linkedai check schemas/sol-verification.schema.json /path/to/verification.json
./scripts/linkedai check-run /path/to/run/bundle.json --root /path/to/project
```

For a BALANCED change run, `check-run` may omit repository fingerprints and
exact host receipt metadata, but it still requires criterion coverage, scope,
relevant passing checks, and no unresolved failures. Only accept `DONE` if
`check-run` succeeds, the verification authority is `SOL`, and the
verification state is `DONE`. FULL additionally requires the fresh snapshot,
baseline, and exact `gpt-5.6-sol` / `high` SOL receipt.

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

The gate checks criterion coverage, relevant required commands/observations,
user intent, scope, unresolved failures, and bounded counters. FULL also checks
fresh snapshots and exact model receipts.
Reproduction failures and earlier verification failures remain visible. A
passing rerun must explicitly resolve the same failed command.

`linkedai next-stage` maps SOL outcomes to bounded work. `REPLAN` returns to
fresh LUNA recon and ASTRA planning. `linkedai usage` summarizes explicitly
supplied cumulative counters; unknown host data stays unknown and is never
turned into zero.

The `luna-verification` schema and `astra_high_luna_echo` bundle are reserved
for the separately installed Echo Mode skill. Echo uses
`verification_profile: QUICK`; completion is intentionally self-verifying and
must not be reported as SOL verification.
