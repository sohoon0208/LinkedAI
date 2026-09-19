# LinkedAI V8 validation record

These checks validate the workflow mechanics and package installation. They
do not prove provider identity, semantic quality, or guaranteed token savings
for every application task.

## Package checks

- `scripts/linkedai validate`: passed; active Draft 2020-12 schemas, current
  example artifacts, required files, and UI metadata validated.
- `scripts/linkedai test`: 113 tests passed, with no failures or skips.
- Skill-authoring `quick_validate.py`: passed for LinkedAI and Echo Mode.
- Shell syntax checks for the helpers and installers: passed.
- Echo Mode package validation: passed.

Regression coverage includes invalid DONE claims, exact criterion coverage,
fresh evidence, model-receipt consistency, read-only mutation detection,
unresolved failed verification, retry/replan routing, safe installation,
usage coverage, the ASTRA HIGH active pipeline, and the distinct LUNA MAX Echo
verification contract.

The active workflow smoke tests prove that:

1. routing for FAST, STANDARD, and DEEP reports the same
   `LUNA RECON -> PACKET -> ASTRA HIGH PLAN -> LUNA MAX EXECUTION -> SOL LIGHT VERIFY`
   stages;
2. a BALANCED active bundle can omit full snapshots and treat unavailable
   receipt metadata as a warning, while a FULL bundle still rejects an ASTRA
   Medium receipt;
3. a valid main bundle accepts ASTRA HIGH, LUNA MAX, and SOL LIGHT; and
4. a valid Echo bundle accepts ASTRA HIGH, LUNA MAX, and LUNA MAX verification.

The installed source and active package contents were synchronized. The main
skill is installed at `~/.codex/skills/linkedai`; Echo Mode is installed at
`~/.codex/skills/linkedai-echo-mode`. The installer preserves recoverable
backups outside active skill discovery.

No model provider or Antigravity process is launched by these tests.
