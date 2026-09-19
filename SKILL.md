---
name: linkedai
description: >
  Coordinate LUNA MAX execution, ASTRA HIGH planning, and lightweight SOL HIGH
  verification with bounded packets and checked completion. Use for $linkedai,
  /linkedai, or an explicitly requested planning/execution split.
---

# LinkedAI V8

LinkedAI uses one predictable pipeline for every applicable run:

`LUNA RECON -> PACKET -> ASTRA HIGH PLAN -> LUNA MAX EXECUTION -> SOL LIGHT VERIFY`

`SOL LIGHT VERIFY` is the default for FAST and STANDARD routing. DEEP routing
uses `SOL FULL VERIFY` when the task needs strict repository freshness and
complete evidence.

There is no automatic AG stage and no user-approval pause in the active
workflow. The user's request supplies the authorization boundary; only an
explicit `change` intent permits source or test mutation.

## Roles and authority

- **ASTRA HIGH** (`gpt-6-astra`, `high`) receives only the bounded packet and
  targeted excerpts. It decides root cause, architecture, scope, acceptance
  criteria, and verification strategy. It never edits the repository.
- **LUNA MAX** (`gpt-5.6-luna`, `max`) reads the repository, reproduces the
  issue, applies the ASTRA plan, edits code/tests, runs commands, and collects
  evidence. It never declares `DONE` for the main LinkedAI workflow.
- **SOL HIGH** (`gpt-5.6-sol`, `high`) independently verifies the plan,
  changes, evidence, and profile-appropriate freshness proof. Only SOL may
  return completion state `DONE` in LinkedAI.

Confirm the actual host model, reasoning effort, and agent ID for every role.
Never treat a label or prompt as proof that the host selected that model.

## Execution contract

1. **LUNA RECON**: inspect the relevant repository files, tests, configuration,
   reproduction, and current state. Do not edit.
2. **PACKET**: compress only the facts that can change ASTRA's decision: goal,
   intent, relevant code, constraints, attempted fixes, evidence, scope, and
   the decision objective. Do not send the full repository or conversation.
3. **ASTRA HIGH PLAN**: dispatch one packet-only planning handoff. Require a
   structured plan. `IMPLEMENT` may proceed for a `change` intent; an
   investigation/review/explanation remains read-only. `REQUEST_EVIDENCE`,
   `REPLAN`, or `BLOCKED` stops or routes to the named bounded next stage.
4. **LUNA MAX EXECUTION**: give LUNA the exact plan, frozen scope, acceptance
   criteria, and verification commands. Edit only the permitted scope. Run
   narrow checks first, then the required regression/build/runtime checks.
5. **SOL VERIFY**: give SOL the packet, ASTRA plan, LUNA result, direct
   evidence, and any available snapshot. The default `BALANCED` profile checks
   every acceptance criterion, changed-file scope, relevant commands, and
   unresolved failures. It does not require a full repository fingerprint or
   unrelated test categories for a bounded source change. `FULL` keeps the
   strict snapshot and receipt checks for DEEP work. SOL returns `DONE`,
   `RETRY`, `REPLAN`, `EVIDENCE`, or `BLOCKED`; a timeout, missing required
   proof, stale snapshot when one is required, or invalid artifact is never a
   pass.

On `RETRY`, LUNA performs one bounded repair inside the existing plan. On
`EVIDENCE`, LUNA collects the named proof and SOL verifies again. Balanced
verification does not automatically replan; a `REPLAN` escalates to `FULL` or
stops as `BLOCKED`. DEEP/FULL may refresh the packet and request a new ASTRA
plan. Never silently widen scope or reset counters. Balanced work normally
allows two LUNA attempts, two SOL verifications, and one ASTRA plan; stop as
`BLOCKED` when the ceiling is reached.

## Context and evidence discipline

- Keep ASTRA and SOL packet-only; they do not browse or edit the target repo.
- Prefer one long-lived LUNA worker and send deltas on follow-ups.
- Preserve exact errors, failed checks, unknowns, command exit codes, and
  before/after evidence.
- Recompute the final workspace snapshot immediately before SOL for FULL runs;
  BALANCED source changes may use scoped evidence instead.
- Keep raw logs and run artifacts outside the subject repository.
- Count actual participant and controller usage only from host counters.
  Packet length is not an exact token measurement.

## Reporting

Report the actual chronological uppercase stages, model/effort/agent IDs,
retries or replans, verification state, counters, and token coverage:

`LUNA RECON -> PACKET -> ASTRA HIGH PLAN -> LUNA MAX EXECUTION -> SOL LIGHT VERIFY -> FINAL STATE`

For DEEP runs, report `SOL FULL VERIFY` instead of `SOL LIGHT VERIFY`.

Report `TOKENS: COMPLETE`, `PARTIAL`, or `UNAVAILABLE` based on host usage
events. Never invent exact provider token counts. `DONE` requires a valid
SOL artifact and a passing `check-run` completion gate.

## Supporting checks

Use the packet, role, verification, runtime-contract, and completion-report
references only when needed. `scripts/linkedai check-run` validates the final
bundle; helpers do not dispatch models, authenticate providers, launch AG, or
manufacture `DONE`.

The historical approval-gate, FAST bypass, and ASTRA-adjudication artifacts
remain only for migration validation. They are not active LinkedAI routing.
