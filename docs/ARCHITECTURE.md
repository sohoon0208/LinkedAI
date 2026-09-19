# LinkedAI V8 architecture

The active architecture is deliberately fixed:

```text
LUNA MAX RECON
      |
    PACKET
      |
ASTRA HIGH PLAN
      |
LUNA MAX EXECUTION
      |
SOL LIGHT VERIFY
      |
FINAL STATE
```

LUNA retains repository context. ASTRA HIGH receives a bounded packet and
targeted excerpts only, so the expensive planning context does not contain the
whole repository. LUNA executes the frozen plan and collects proof. SOL HIGH
receives the plan, result, direct evidence, and profile-appropriate freshness
evidence and is the only completion authority. FAST/STANDARD use BALANCED
verification; DEEP uses FULL.

There is no active user-approval gate, no automatic ASTRA bypass, and no AG
stage. Risk modes remain reporting metadata and do not alter this sequence.
The old approval and FAST artifacts remain readable only for migration.

`RETRY` stays inside the current plan. BALANCED `REPLAN` escalates to FULL or
stops; FULL can return to fresh LUNA recon and ASTRA planning. `EVIDENCE`
returns to LUNA before SOL rechecks. `BLOCKED` is terminal for the current
bounded run when evidence, capability, model support, or a hard ceiling is
unavailable.

Echo Mode uses the same first four stages but replaces the last stage with
`LUNA MAX VERIFY`. It is intentionally self-verifying and is a separate
opt-in skill.
