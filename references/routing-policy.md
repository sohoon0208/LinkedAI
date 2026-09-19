# Routing and transitions

Record `change`, `investigate`, `review`, or `explain` from the user's actual
request. Only `change` authorizes source/test edits. A pure investigation,
review, or explanation remains read-only.

## Active dispatch

Risk tier still controls evidence depth and escalation metadata, but it does
not change the stage order or insert an approval pause. Every active LinkedAI
run uses:

`LUNA RECON -> PACKET -> ASTRA HIGH PLAN -> LUNA MAX EXECUTION -> SOL HIGH VERIFY`

`FAST`, `STANDARD`, and `DEEP` are retained as controller metadata for
compatibility and reporting. New routing returns `approval_policy: AUTO`,
`approval_required: false`, and `workflow_variant: astra_high_luna_sol` for
all three modes. The old FAST no-ASTRA and approval-gate variants are not
emitted.

ASTRA `IMPLEMENT` authorizes LUNA to execute only the plan's frozen scope for
a `change` intent. ASTRA `REQUEST_EVIDENCE`, `REPLAN`, or `BLOCKED` must be
handled before execution. No model may silently widen scope.

## Transitions

| State | Next work | Rule |
| --- | --- | --- |
| `RETRY` | LUNA execution | Correct only the named failure inside the plan |
| `REPLAN` | LUNA recon, then ASTRA plan | Refresh facts; never reuse the old plan silently |
| `EVIDENCE` | LUNA evidence, then SOL verify | Collect the named proof before rechecking |
| `DONE` | Stop | Requires SOL `DONE` and passing `check-run` |
| `BLOCKED` | Stop | Report the missing evidence/capability or ceiling |

Use bounded counters. The normal ceiling is two LUNA attempts, two SOL
verifications, and two ASTRA plans including replans. Never reset counters
silently.

Antigravity is outside the LinkedAI routing graph. LinkedAI itself does not
launch AG or grant AG permissions; use ChatGravity when that separate workflow
is explicitly requested.

Historical approval-gate transitions remain in the validator solely so old
artifacts can be inspected; they are not active routing decisions.
