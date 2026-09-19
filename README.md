# LinkedAI

LinkedAI is a pair of Codex skills that separate planning, implementation, and
verification into bounded model handoffs.

## Skills

### LinkedAI

```text
LUNA MAX RECON -> PACKET -> ASTRA HIGH PLAN -> LUNA MAX EXECUTION -> SOL LIGHT VERIFY
```

ASTRA plans, LUNA investigates and codes, and SOL independently verifies the
result. FAST/STANDARD use balanced SOL verification; DEEP uses the stricter
FULL profile. SOL is the only completion authority in this workflow.

### LinkedAI Echo Mode

```text
LUNA MAX RECON -> PACKET -> ASTRA HIGH PLAN -> LUNA MAX EXECUTION -> LUNA MAX VERIFY
```

Echo Mode uses a fresh LUNA verification pass instead of independent SOL
verification. It uses the QUICK profile for small bounded tasks. It is faster,
but its final check is not independent.

## Repository structure

```text
SKILL.md                 Main LinkedAI skill
agents/                  Codex UI metadata
docs/                    Architecture and safety notes
prompts/                 Role prompts
references/              Packets, routing, and reporting guidance
schemas/                 JSON workflow contracts
scripts/                 Validation, installation, and reporting helpers
tests/                   Offline regression tests
echo-mode/               LinkedAI Echo Mode package
```

## Install

```bash
./scripts/linkedai validate
./scripts/linkedai test
./scripts/linkedai install
./echo-mode/scripts/install.sh
```

The installers validate the packages and preserve existing installations as
recoverable backups. They do not dispatch models or change global settings.

MIT licensed; see [LICENSE](LICENSE).
