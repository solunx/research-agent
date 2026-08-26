# Semantic Interpretation v0

Offline experiment. **Does not change the retrieval agent pipeline.**

## Hypothesis

Meaning belongs to the LLM; certainty belongs to code.

```text
raw observation
      +
frozen contract (outcomes + definitions)
      ↓
Interpretation LLM  →  normalized outcome (enum)
      ↓
Generic gate (code)  →  PASS | FAIL | UNKNOWN
```

The gate never knows that "Enkel kamer" means ROOM_ONLY. It only sees
`observed_outcome` vs `required`.

## Two LLM roles (architecture)

| Role | Question | Output |
|------|----------|--------|
| **Discovery** | What must this *task* decide? | Contract (decisions, outcomes, sufficiency) |
| **Interpretation** | What does *this observation* mean *within that contract*? | `{outcome, confidence, reason}` |

Evidence_signals (pattern lists) were a useful intermediate proof that a
generic executor can be steered. They are **not** the preferred product model
for meaning.

## Fixed mini-contract (v0)

Decision `board_type` outcomes:

- `ALL_INCLUSIVE`
- `ROOM_ONLY` (meal plan — **not** occupancy)
- `BREAKFAST`
- `FULL_BOARD`
- `UNKNOWN`

Critical near-miss: **Single room / eenpersoonskamer → UNKNOWN**, not ROOM_ONLY.

## Golden set

`evals/interpretation_board_type_golden.jsonl` — NL/EN/FR synonyms + traps.

## How to run

```bash
# Gate dry-run (no Ollama)
python scripts/run_interpretation_v0.py --out ./interpretation_v0.json

# Full interpretation test
python scripts/run_interpretation_v0.py --llm --out ./interpretation_v0.json
```

## GO criteria (with --llm)

| Metric | Threshold |
|--------|-----------|
| accuracy | ≥ 0.8 (n ≥ 10) |
| critical_accuracy | ≥ 0.85 |
| single-room → ROOM_ONLY | **must not happen** |

## Explicitly out of scope

- Live agent wiring
- Per-page batching strategy
- Literature domain (next experiment after GO)
- Replacing Contract Discovery
