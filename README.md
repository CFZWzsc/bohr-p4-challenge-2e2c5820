# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-2e2c5820` (track: `experimental-design`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable pipeline and all supporting documents. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `experimental-plan-checklist-review`
- Summary: Use for experimental-design cases that require a checklist-based feasibility review of a protocol against equipment, materials, samples, time, ethics, parameter and risk constraints. Runs scripts/sk_entry.py over /input and writes /app/output/result.json plus /app/output/run-review.md with locator-verified findings and explicit required conditions. Standard library only, offline, deterministic.

## Contents

| File |
|------|
| `SKILL.md` |
| `assets/checklist.json` |
| `examples/demo-case/case.json` |
| `examples/demo-case/inventory.csv` |
| `examples/demo-case/protocol.md` |
| `examples/quickstart.md` |
| `references/estimation-rules.md` |
| `references/review-checklist.md` |
| `references/verdict-and-evidence.md` |
| `scripts/run_skill.py` |
| `scripts/sk_entry.py` |
| `README.md` |

## How to run

```bash
python scripts/sk_entry.py --input /input --work /app/work --out /app/output
```

Two passes are intended: the first writes `/app/work/agent_tasks.json` (evidence
skeleton) and `/app/output/result.json`; after the agent writes
`/app/work/agent_judgement.json`, the second pass merges and validates the result.
See `SKILL.md` and `references/two-phase-workflow.md`.

## Notes

- Pure Python standard library; no network access required.
- Every claim is anchored to paragraph-level evidence; unknown items are reported
  in `uncertainty` instead of being fabricated.
