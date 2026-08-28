# Observation Contract v0.2

Defines the unit that feeds **Interpretation**. No semantic outcomes in this layer.

## Shape

```json
{
  "observation_id": "string",
  "candidate_id": "string",
  "text": "raw string as found",
  "channel": "candidate_claim | search_context | navigation | page_chrome | unknown",
  "scope": "card | search | page | note | unknown",
  "provenance": {
    "origin": "shortlist | url_query | page_state | card_fields | fixture | notes",
    "source_url": "optional",
    "surface": "optional"
  }
}
```

## Rules

| Layer | May do | Must not do |
|-------|--------|-------------|
| **Builder** | Attach text + channel + scope + provenance | Emit `board_type`, enums, PASS/FAIL |
| **Channel filter** | Drop / force UNKNOWN if channel ∉ allowed | Invent meaning |
| **Interpretation LLM** | Map text → contract outcome | — |
| **Eligibility** | AND on normalized outcomes | Read raw page text |

## Channel meanings

- `candidate_claim` — text attributable to this candidate/card
- `search_context` — query filters, e.g. `meal=all-inclusive` in URL
- `navigation` — URLs / paths
- `page_chrome` — CTA, sort, bagage UI, unrelated chrome

## Notes policy (v0.2)

`origin=notes` is **not trusted** for eligibility by default (`include_notes=False`).
Notes may still be emitted with `channel` set carefully, but main path uses shortlist / page_state / card fields / URL only.

## Provenance fixture GO

See `evals/observation_provenance_fixture_v0.json` + `scripts/run_observation_provenance_v0.py`.

## Binding via Candidates (2026-08-28)

Preferred production path: build `Candidate` objects (`candidates.py`), then emit observations with a stable `candidate_id` so interpretation sees **bound** multi-line evidence rather than an unordered claim soup.

```text
page → extract_candidates → candidates_to_observations → Interpretation
```

`scope` may be `unit` / `card` when the observation comes from a candidate package. Chrome should prefer `page_chrome` when packager source is affordance-only with zero density (filtering is ranking, not domain classification).
