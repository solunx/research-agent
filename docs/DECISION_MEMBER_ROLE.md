# Decision type: MEMBER_ROLE (experiment v0)

Isolated semantic decision. Code is the driver; LLM is a typed coprocessor only on `UNCERTAIN`.

## Hypothesis under test

A small, enum-only LLM call can classify ambiguous structure members that generic deterministic rules cannot, without changing the rest of the pipeline.

## Why not TARGET_OFFER / AMENITY?

Those labels are **vertical** (travel). A generic agent needs **structural roles**. The *task contract* binds which role is admissible for evidence.

| Role | Meaning (domain-agnostic) |
|------|---------------------------|
| `TARGET` | Matches the task’s primary subject type (whatever the contract says) |
| `NAVIGATION` | Aggregate / destination / browse node, not a concrete subject instance |
| `ACTION` | CTA / imperative control (“view package”, “personalize”) |
| `FRAGMENT` | Attribute / amenity / line-item chrome next to a subject |
| `CHROME` | Page UI noise (type-only labels, slogans without subject body) |
| `UNKNOWN` | Not enough signal — **fail closed** (no evidence) |

`TARGET` ≠ “hotel”. For this task, contract says subject ≈ accommodation/package offer; for a laptop search it would mean a product SKU. Same enum.

## Flow

```
STRUCTURE candidate
      ↓
deterministic pre-classifier  (existing structural features)
   ├── ACCEPT  → role path TARGET (no LLM)
   ├── REJECT  → drop (reason code)
   └── UNCERTAIN
            ↓
       LLM MEMBER_ROLE  (enum only)
            ↓
       code validates
            ↓
   TARGET → admissible → MinAC → evidence
   else / UNKNOWN → reject (fail closed)
```

## LLM contract

**Input (minimal):**

```json
{
  "task_subject_type": "accommodation_offer",
  "candidate": {
    "text": "Gran Canaria",
    "value": "€2328",
    "raw_evidence": "..."
  },
  "dominant_list_schema": {
    "sample_targets": ["Sercotel …", "Cordial …"],
    "typical_signals": ["price", "board_or_flight", "reviews_or_distance"]
  }
}
```

**Output (exact one token / JSON):**

```json
{ "role": "NAVIGATION" }
```

`role ∈ { TARGET, NAVIGATION, ACTION, FRAGMENT, CHROME, UNKNOWN }`

**Forbidden:** free text, navigation, constraint evaluation, inventing facts.

## StageResult (log only in v0)

`PASS | FAIL | UNKNOWN | SPEC_GAP | SEMANTIC_AMBIGUITY`  
SPEC_GAP is logged, not auto-patched.

## Metrics

- candidate precision (true TARGET / promoted)
- LLM escalation rate (calls / candidates)
- agreement vs `evals/member_role_golden.jsonl`
- false-positive awareness (non-TARGET never enters evidence)
- tokens / latency

## Out of scope (v0)

Contract refinement loop, host routing, OCR/AX, other decision types, dynamic enum generation.
