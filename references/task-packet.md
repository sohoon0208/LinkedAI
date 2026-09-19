# Evidence-preserving task packets

ASTRA and SOL receive packets, not repository access. The normal 1–3K-token target is
adaptive: tiny work may need much less, and risk-critical excerpts may justify
more. Never pad to a minimum, silently truncate evidence to a ceiling, or spend
another ASTRA call solely to satisfy a cosmetic packet length.

## Three layers

1. **Stable brief:** run ID, user intent, exact goal, scope/permissions,
   non-negotiable constraints, controller-issued plan ID, and the expected
   acceptance criteria or verification target. Include the frozen execution
   scope when known and preserve the exact packet sent to ASTRA HIGH.
   Preserve meaning; quote exact user constraints when needed.
2. **Decision evidence:** observed facts versus hypotheses, precise code/diff
   excerpts with paths and symbols, commands with exit codes, before/after
   reproduction, known failures, competing explanations, and missing evidence.
3. **Delta:** new observations, changed code, attempted fixes, and what is
   superseded since the previous packet. Preserve still-relevant negative
   evidence and reference the retained stable brief explicitly.

Send a self-contained initial snapshot. On follow-up in the same ASTRA or LUNA
context, send only the needed changes plus identifiers; do not append the
original packet and entire plan repeatedly. If context was lost or a new agent
starts, include a compact self-contained snapshot again. A path or hash alone
is not usable evidence for a packet-only ASTRA or SOL.

## Decision objective

`decision_objective` states the one decision, such as “Which fix satisfies
these constraints?” Related clarifications may use the optional `open_questions`
array; the older `open_question` field is optional, not the decision objective.
Do not split related questions into multiple handoffs for formatting reasons.

## Preserve versus compress

Preserve verbatim relevant code, exact error signatures, invariant/permission
constraints, acceptance criteria, and material uncertainties. Summarize repeated
logs, directory listings, unrelated history, and narration. Never replace actual
evidence with “looks good” or a model confidence score.

When trimming, retain a short list of omitted evidence and why it is not needed.
ASTRA may request named functions, caller context, diff hunks, test cases, or
command results while planning. LUNA execution receives the exact ASTRA plan,
frozen scope, acceptance criteria, and verification plan. SOL may return
`EVIDENCE` for missing proof.
LUNA supplies those bounded slices with freshness information; neither ASTRA
nor SOL writes or directly browses code.

## Freshness and validation

Create workspace fingerprints through the helper described in
[runtime-contracts](runtime-contracts.md). Include relevant verification files
and all changed paths. Test results, LUNA output, and SOL verification must refer
to the same tested state. Recompute after any further source change; do not
reuse a passing result against modified code.

Use the current task-packet schema for saved JSON. A token estimate must be
labeled as an estimate with its method. Characters/words are not exact model
tokens; exact usage comes from host counters, not packet formatting.

The controller can attach full fingerprint manifests and dispatch metadata to
saved artifacts after collecting the unmodified model response. ASTRA and SOL need
the tested-state digest and relevant code evidence, not a repeated listing of
every repository path. Do not spend ASTRA output tokens copying bookkeeping.
