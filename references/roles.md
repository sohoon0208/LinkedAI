# Role boundaries

The authoritative active sequence is in [SKILL.md](../SKILL.md):

`LUNA RECON -> PACKET -> ASTRA HIGH PLAN -> LUNA MAX EXECUTION -> SOL HIGH VERIFY`

ASTRA HIGH owns packet-only strategic reasoning: root cause, architecture,
scope, tradeoffs, acceptance criteria, and test design. It must not edit or
directly browse the target repository and can never declare `DONE`.

LUNA MAX owns repository investigation and execution: targeted reads,
reproduction, all source/test edits, integration, commands, and evidence. Its
`IMPLEMENTATION_COMPLETE` result is submitted to SOL and is not completion.

SOL HIGH owns independent final verification. It reviews the goal, packet,
ASTRA plan, LUNA evidence, direct observations, and fresh snapshot. Only a
controller-stamped SOL verification with state `DONE`, followed by a passing
completion gate, closes a main LinkedAI run.

The controller may dispatch, attach host receipts, validate artifacts, track
counters, and report. It cannot claim to be another model, fabricate a
receipt, override scope, or turn a LUNA result or external AG message into
`DONE`.

`RETRY`, `REPLAN`, `EVIDENCE`, and `BLOCKED` remain explicit states. A legacy
approval gate or ASTRA adjudication is migration data only.
