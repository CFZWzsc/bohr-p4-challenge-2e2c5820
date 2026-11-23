# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-2e2c5820` (track: `experimental-design`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable entry point and all supporting scripts. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `versioned-experiment-feasibility-review`
- Summary: Use when an experimental-design case supplies one or more versioned experimental plans plus equipment, material, price, booking, sample or ethics constraints and asks for a feasibility review; run scripts/run_skill.py to produce a contract-preserving result.json with per-version checks, resource status, time and sample arithmetic, conflicts and a defensible conclusion.

## Contents

| File |
|------|
| `SKILL.md` |
| `scripts/run_skill.py` |
| `README.md` |

## How to run

```bash
python scripts/run_skill.py --case /input/case.json --output /app/output/result.json
```

The entry point is `SKILL.md`; input/output contracts, error handling and a minimal
usage example are documented there.

## Notes

- Pure Python standard library; no network access required.
- The result JSON keeps the input case id, the main results, per-item evidence,
  a run status and an uncertainty section.
