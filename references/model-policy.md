# Model selection and context isolation

## Active roles

| Role | Model ID | Reasoning | Work |
| --- | --- | --- | --- |
| ASTRA | `gpt-6-astra` | `high` | Packet-only architecture and planning |
| LUNA | `gpt-5.6-luna` | `max` | Recon, code/test edits, commands, evidence |
| SOL | `gpt-5.6-sol` | `high` | Packet-only independent verification and DONE authority |

The active LinkedAI path dispatches all three roles in this order:

`LUNA RECON -> PACKET -> ASTRA HIGH PLAN -> LUNA MAX EXECUTION -> SOL HIGH VERIFY`

The host must support and confirm the requested model/effort pair before each
role is dispatched. If it cannot be selected or confirmed, report `MODEL
UNCONFIRMED` and stop the affected handoff. A prompt label cannot switch a
running task's model.

## Context boundaries

- ASTRA receives the stable brief, compressed packet, and targeted excerpts. It
  does not browse or edit the repository.
- SOL receives the bounded packet, ASTRA plan, LUNA result, direct evidence,
  and fresh snapshot. It does not browse or edit the repository.
- LUNA receives the existing workspace, ASTRA plan, execution scope, criteria,
  and verification commands. Prefer one long-lived LUNA worker.
- The controller forwards artifacts and records receipts; it must not duplicate
  role reasoning or manufacture a completion result.
- Never pass `$linkedai` to a role worker or let a worker recursively start the
  workflow.

## Usage accounting

Record actual participants and the controller in the usage manifest. Exact
provider totals are available only when the host supplies complete cumulative
counters and a final-response boundary. Packet length, model names, and test
counts are not token measurements.

Historical ASTRA Medium and approval-gate receipts remain readable only for
migration validation; new LinkedAI runs require ASTRA HIGH.
