# Contract Execution (v0.2 — evidence channels)

Offline experiment. **Does not change the retrieval agent pipeline.**

## Hypothesis

A domain-agnostic executor can evaluate decisions described only in a Research
Contract and emit `PASS | FAIL | UNKNOWN | SPEC_GAP` without
`if decision_id == ...`.

**v0.2:** evidence is provenance-aware. Signals declare which *channels* they
may read so search-URL filters cannot silently become candidate claims.

## Evidence channels (code-owned labels)

| Channel | Typical content |
|---------|-----------------|
| `candidate_claims` | name, price, raw card / entity text |
| `search_context` | URL query params (`meal=`, `dateFrom=`) |
| `navigation` | path / list-vs-detail URL shape |
| `page_context` | page_role, light chrome labels |

Default when a signal omits `evidence_channels`: **`candidate_claims` only**
(fail-closed).

## Signal shape (schema 0.3)

```json
{
  "outcome": "ALL_INCLUSIVE",
  "patterns": ["all-inclusive", "all inclusive"],
  "polarity": "supports",
  "evidence_channels": ["candidate_claims"]
}
```

## GO criteria

| Metric | Threshold |
|--------|-----------|
| `false_pass` | **0** |
| `spec_gap_rate` | **0** |
| `blocker_recall` | ≥ 0.9 when oracle marks blockers |
| `oracle_accuracy` | ≥ 0.8 if n ≥ 5 |

`ABSENT` ≈ `SEARCH_LIST_ONLY` in oracle scoring.

## How to run

```bash
python scripts/run_contract_execution_v0.py --fixture

python scripts/run_contract_discovery_v0.py \
  --run-dir runs/YYYY-… \
  --llm --out ./contract_discovery_v0_llm.json

python scripts/run_contract_execution_v0.py \
  --run-dir runs/YYYY-… \
  --contract ./contract_discovery_v0_llm.json \
  --out ./contract_execution_v0_llm.json
```

## Explicitly out of scope

Live agent wiring, FREEZE, multi-task until packages `false_pass=0` with LLM contract.
