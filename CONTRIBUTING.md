# Contributing

Preserve the ASTRA High/LUNA Max/SOL High role split and the no-automatic-AG
workflow. Keep one authoritative policy for each decision; link to it instead
of copying it into prompts and documentation.

Validate observable behavior: invalid DONE rejection, exact criterion coverage,
fresh evidence, model-receipt consistency, SOL-only DONE authority, intent
boundaries, bounded retry transitions, safe installation, Echo Mode's explicit
LUNA verification authority, and usage coverage. Matching a sentence in
SKILL.md is not a behavioral test.

Run `./scripts/linkedai validate` and `./scripts/linkedai test`. Test installers
only in temporary targets before touching an actual installation. Preserve
existing installations and source changes. Do not introduce API calls or
global settings changes in unit tests.

For workflow changes, state the expected effect on handoff count and context.
Use [usage and evaluation](references/usage-and-evaluation.md) for honest
comparisons. Do not claim measured savings or ASTRA-only quality from examples,
mocked host receipts, or synthetic counters.
