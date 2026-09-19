# LinkedAI operational guide

Every active LinkedAI task follows:

`LUNA MAX RECON -> PACKET -> ASTRA HIGH PLAN -> LUNA MAX EXECUTION -> SOL HIGH VERIFY`

LUNA recon is read-only. The packet is the only planning handoff. ASTRA HIGH
returns a structured plan; there is no user-approval pause. LUNA MAX executes
only the plan's scope and reports exact commands and evidence. SOL HIGH checks
the result independently and controls `DONE`.

Only `change` intent may mutate source. Investigation, review, and explanation
remain read-only even when they produce a plan. A timeout, permission error,
stale snapshot, missing runtime proof, or invalid artifact is `BLOCKED`,
`EVIDENCE`, `RETRY`, or `REPLAN`, never success.

Use [completion-report](../references/completion-report.md) for ordered model
reporting and [usage/evaluation](../references/usage-and-evaluation.md) for
token measurements. Unit tests and a live smoke test do not establish general
quality parity or guaranteed quota savings.

For Echo Mode, use the separately installed `linkedai-echo-mode` skill. Its
final stage is `LUNA MAX VERIFY`, not SOL verification.
