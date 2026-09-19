# Routing and transitions

Record `change`, `investigate`, `review`, or `explain` from the user's actual
request. Only `change` authorizes source/test edits. A pure investigation,
review, or explanation remains read-only.

## Active dispatch

Risk tier still controls evidence depth and escalation metadata, but it does
not change the stage order or insert an approval pause. Every active LinkedAI
run uses:

`LUNA RECON -> PACKET -> ASTRA HIGH PLAN -> LUNA MAX EXECUTION -> SOL LIGHT VERIFY`

`FAST`, `STANDARD`, and `DEEP` are retained as controller metadata for
compatibility and reporting. FAST and STANDARD select
`verification_profile: BALANCED`; DEEP selects `verification_profile: FULL`.
New routing returns `approval_policy: AUTO`, `approval_required: false`, and
`workflow_variant: astra_high_luna_sol` for all three modes. The old FAST
no-ASTRA and approval-gate variants are not emitted.

ASTRA `IMPLEMENT` authorizes LUNA to execute only the plan's frozen scope for
a `change` intent. ASTRA `REQUEST_EVIDENCE`, `REPLAN`, or `BLOCKED` must be
handled before execution. No model may silently widen scope.

## Transitions

| State | Next work | Rule |
| --- | --- | --- |
| `RETRY` | LUNA execution | Correct only the named failure inside the plan |
| `REPLAN` | Escalate to FULL or stop | BALANCED does not automatically replan; FULL may refresh facts and ask ASTRA for a new plan |
| `EVIDENCE` | LUNA evidence, then SOL verify | Collect the named proof before rechecking |
| `DONE` | Stop | Requires SOL `DONE` and passing `check-run` |
| `BLOCKED` | Stop | Report the missing evidence/capability or ceiling |

Use bounded counters. The BALANCED ceiling is two LUNA attempts, two SOL
verifications, and one ASTRA plan. FULL may use the caller-selected larger
ceiling for deep work. QUICK has the same two-attempt/two-verification/one-plan
ceiling. Never reset counters silently.

Antigravity is outside the LinkedAI routing graph. LinkedAI itself does not
launch AG or grant AG permissions; use ChatGravity when that separate workflow
is explicitly requested.

Historical approval-gate transitions remain in the validator solely so old
artifacts can be inspected; they are not active routing decisions.
