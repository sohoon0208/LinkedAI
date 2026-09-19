# Echo Mode workflow contract

The fixed sequence is:

`LUNA RECON -> PACKET -> ASTRA HIGH PLAN -> LUNA MAX EXECUTION -> LUNA MAX VERIFY`

ASTRA receives no repository access. LUNA execution receives the exact plan and
frozen scope. LUNA verification receives the plan, execution result, direct
evidence, and fresh snapshot, but must not edit source during verification.

The final artifact uses `authority: LUNA`, the
`luna-verification.schema.json` schema, and the
`workflow_variant: astra_high_luna_echo` bundle label. `DONE` requires every
criterion to be proven, required commands/observations to pass, no unresolved
failures or unknowns, and a fresh snapshot.

`RETRY`, `REPLAN`, `EVIDENCE`, and `BLOCKED` are explicit non-success states.
Echo Mode may not relabel its result as SOL verification or claim independent
review.
