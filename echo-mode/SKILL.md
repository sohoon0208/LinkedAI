---
name: linkedai-echo-mode
description: >
  Run the LinkedAI Echo Mode workflow: LUNA MAX recon, bounded packet, ASTRA
  HIGH plan, LUNA MAX execution, and LUNA MAX self-verification. Use for
  $linkedai-echo-mode or /linkedai-echo-mode when a faster non-independent
  verifier is preferred.
---

# LinkedAI Echo Mode

`LinkedAI_Echo_Mode` is the same planning and execution structure as LinkedAI,
with the final independent verifier replaced by a fresh LUNA MAX verification
pass:

`LUNA RECON -> PACKET -> ASTRA HIGH PLAN -> LUNA MAX EXECUTION -> LUNA MAX VERIFY`

This is an explicit tradeoff. Echo Mode is usually faster and uses fewer model
roles, but LUNA verifies work produced by LUNA, so it is not independent. In
this skill only LUNA may declare `DONE`.

## Roles

- **ASTRA HIGH** (`gpt-6-astra`, `high`) receives the bounded packet and
  targeted excerpts. It plans architecture, scope, acceptance criteria, and
  verification. It never edits.
- **LUNA MAX** (`gpt-5.6-luna`, `max`) performs recon, all coding/test work,
  commands, evidence collection, and the final verification pass.

Confirm host-selected model, reasoning effort, and agent ID. Never infer a
model switch from a role label.

## Workflow

1. **LUNA RECON**: read relevant code, tests, configuration, reproduction, and
   current state. Do not edit.
2. **PACKET**: send ASTRA only the goal, intent, relevant excerpts, constraints,
   attempted fixes, evidence, frozen scope, and decision objective.
3. **ASTRA HIGH PLAN**: require a structured plan. `IMPLEMENT` authorizes only
   a `change` intent; other intents remain read-only. Stop for `REQUEST_EVIDENCE`,
   `REPLAN`, or `BLOCKED`.
4. **LUNA MAX EXECUTION**: implement only the ASTRA plan's scope, run the
   planned checks, and capture a fresh snapshot. Return `IMPLEMENTATION_COMPLETE`
   or `IMPLEMENTATION_BLOCKED`, never `DONE` from this stage.
5. **LUNA MAX VERIFY**: start a verification pass after execution. Do not edit
   source while verifying. Review the plan, changed paths, command results,
   observations, failures, and fresh snapshot. Return `DONE`, `RETRY`,
   `REPLAN`, `EVIDENCE`, or `BLOCKED` using the Echo verification schema.

On `RETRY`, return to bounded LUNA execution. On `EVIDENCE`, collect the named
proof before verifying again. On `REPLAN`, refresh the packet and ask ASTRA for
a new plan. Normally cap at two LUNA execution attempts, two LUNA verification
passes, and two ASTRA plans. Never silently widen scope or reset counters.

## Reporting

Report the actual uppercase sequence, model/effort/agent IDs, counters, exact
commands/results, and token coverage:

`LUNA RECON -> PACKET -> ASTRA HIGH PLAN -> LUNA MAX EXECUTION -> LUNA MAX VERIFY -> FINAL STATE`

Report `TOKENS: COMPLETE`, `PARTIAL`, or `UNAVAILABLE` from host counters.
Packet length is not an exact token count. Clearly label the final decision as
`LUNA MAX VERIFY`; never call it SOL verification.

## Safety boundary

This skill does not launch Antigravity, grant permissions, bypass the host
sandbox, or invoke `$linkedai` recursively. Only explicit `change` intent may
mutate source. Use the bundled `luna-verification.schema.json` for the final
artifact and preserve fresh workspace evidence.
