# Echo Mode workflow contract

The fixed sequence is:

`LUNA RECON -> PACKET -> ASTRA HIGH PLAN -> LUNA MAX EXECUTION -> LUNA MAX VERIFY`

ASTRA receives no repository access. LUNA execution receives the exact plan and
frozen scope. LUNA verification receives the plan, execution result, direct
evidence, and targeted checks. In QUICK mode a full snapshot is optional for a
bounded source change, but any supplied snapshot must be internally
consistent. LUNA must not edit source during verification.

The final artifact uses `authority: LUNA`, the
`luna-verification.schema.json` schema, and the
`workflow_variant: astra_high_luna_echo` bundle label. `DONE` requires every
criterion to be proven, relevant required commands/observations to pass, and
no unresolved failures or unknowns. QUICK does not require a full snapshot for
a bounded source change.

`RETRY`, `REPLAN`, `EVIDENCE`, and `BLOCKED` are explicit non-success states.
Echo Mode may not relabel its result as SOL verification or claim independent
review. QUICK does not automatically replan; a strategy change is BLOCKED or
escalated to the main FULL path.
