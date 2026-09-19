# Changelog

## 0.12.0 — Balanced and Quick verification profiles

- Added `BALANCED` verification for normal FAST/STANDARD LinkedAI runs: SOL
  remains independent and authoritative, while full fingerprints, exact host
  receipts, and unrelated checks are no longer mandatory for bounded changes.
- Added `FULL` behavior for DEEP runs and preserved strict validation for
  legacy bundles without a profile.
- Added `QUICK` verification to Echo Mode with one plan, one repair budget, no
  automatic replan, and optional fingerprints for bounded source changes.
- Added profile-aware schemas, routing metadata, completion reports, and
  regression coverage.

## 0.11.0 — ASTRA HIGH fixed pipeline and Echo Mode

- Changed the active LinkedAI sequence to `LUNA RECON -> PACKET -> ASTRA HIGH
  PLAN -> LUNA MAX EXECUTION -> SOL HIGH VERIFY`.
- Removed the active user-approval pause and Tier-0 no-ASTRA bypass; old
  approval/FAST artifacts remain migration-compatible only.
- Added `luna-verification.schema.json` and the `astra_high_luna_echo` contract
  for the separately installed `linkedai-echo-mode` skill.
- Added the Echo Mode source package, UI metadata, verification contract, and
  safe installer.

## 0.10.0 — User-approved plan-first execution

- Added a STANDARD/DEEP `plan_approval_gate` that stops after ASTRA MEDIUM
  planning until the user approves the exact plan.
- Added canonical approval bindings for the plan, packet, baseline, scope,
  acceptance criteria, and verification plan, plus stale-baseline detection.
- Added distinct `APPROVED_PLAN_FAST` execution that preserves the ASTRA plan
  and receipt, skips a second ASTRA call, executes through LUNA MAX, and still
  requires SOL HIGH verification.
- Preserved automatic strict FAST as a separate no-ASTRA Tier-0 path.
- Added `check-plan`, approval/replan transition validation, documentation,
  and regression coverage.

## 0.9.0 — Real FAST workflow

- Made `FAST` an actual Tier-0 two-role path: `LUNA RECON -> PACKET -> LUNA
  MAX EXECUTION -> SOL HIGH VERIFY`.
- Kept ASTRA planning for STANDARD/DEEP and kept SOL as the only `DONE`
  authority on every change path.
- Added mode-conditional run-bundle validation, explicit FAST routing evidence,
  frozen packet scope/criteria/commands, and a two-verification FAST ceiling.
- Added regression coverage proving FAST omits ASTRA receipts and rejects scope
  drift.
- Reduced startup and follow-up context guidance by loading only the references
  needed by the selected workflow and reusing the LUNA worker and packet.

## 0.8.0 — SOL verification and retired AG bridge

- Changed the active workflow to `LUNA MAX -> PACKET -> ASTRA MEDIUM PLAN ->
  LUNA MAX EXECUTION -> SOL HIGH VERIFY`.
- Added a canonical SOL verification schema, receipt checks, bounded counters,
  and a SOL-only DONE gate.
- Retained ASTRA adjudication files only as deprecated migration artifacts.
- The earlier manual Antigravity bridge was retired from the installed skills;
  use ChatGravity for explicitly requested Antigravity workflows.

## 0.7.0 — V3 evidence and completion contracts

- Explicit ASTRA High and LUNA selection with isolated, non-recursive handoffs.
- Evidence-preserving adaptive packets and targeted REQUEST_EVIDENCE responses.
- One authoritative intent/tier/retry policy; no automatic planning restart.
- Schema and cross-artifact completion checks with workspace freshness checks.
- Conservative offline usage accounting with coverage and final-response limits.
- Recoverable installation, correct UI metadata, and archived dormant AG files.
- Behavioral regression tests replace wording-only confidence claims.

## 0.6.0 — ASTRA/LUNA-only default workflow

- Removed automatic external-agent pre-planning from the LinkedAI loop.
- Simplified every tier to `LUNA RECON -> PACKET -> ASTRA PLAN -> LUNA
  EXECUTION -> ASTRA ADJUDICATION`.
- Updated prompts, routing, verification, reports, documentation, UI metadata,
  and tests so `$linkedai` does not invoke or report an external-agent stage.
- Retained the older external-agent broker artifacts for explicit manual or
  future use only.

## 0.5.0 — GPT-6 Astra for ASTRA

- Set GPT-6 Astra (`gpt-6-astra`) with `high` reasoning as the ASTRA target for
  architecture planning and final adjudication.
- Applied the target to the skill contract, pasteable loop prompt, UI metadata,
  completion report, and validation tests.
- Added host confirmation rules so prompt text cannot falsely claim a model
  switch that the runtime did not perform.

## 0.4.0 — AG pre-planning before ASTRA

- Replaced the post-execution AG evidence phase with a packet-only AG
  pre-plan immediately after `PACKET` and before `ASTRA PLAN`.
- Added advisory pre-plan schemas, prompt, broker command, and fixtures.
- Made ASTRA explicitly accept, revise, reject, or replace AG's pre-plan.
- Removed repository access, tool permission, and source-edit paths from the AG
  pre-planning stage.
- Updated routing, role contracts, reports, documentation, and tests.

## 0.3.1 — Headless AG transport hardening

- Assemble streamed `step_update` response fragments before validation.
- Inline selected capsule text into the AG prompt to avoid headless read-tool
  permission stalls on bounded AG calls.
- Validate the structured AG response locally instead of relying on the
  installed AG CLI's intermittent schema-mode behavior.
- Keep concurrent pipe draining and fail-closed timeout/tool limits.

## 0.3.0 — Bounded AG broker

- Added a Codex-launched, bounded Antigravity CLI broker for advisory checks.
- Added stream parsing, concurrent pipe draining, capsule scoping, telemetry,
  idle/total/tool limits, and fail-closed structured results.
- Made the earlier optional AG evidence phase historical; normal work remains
-  an ASTRA/LUNA workflow.
- Kept ASTRA as the only role authorized to declare `DONE`.
- Made LUNA's verification plan and evidence the required input to ASTRA's final
  adjudication.

## 0.2.0 — ASTRA/LUNA workflow

- Removed the previous unbounded external verification orchestration.
- Simplified routing, role boundaries, schemas, prompts, helper commands, and
  completion reports to the ASTRA/LUNA workflow.
- Kept ASTRA as the only role authorized to declare `DONE`.

## 0.1.0 — Initial release

- Added compressed task packets, deterministic routing, role contracts, and
  standard-library validation/tests.
