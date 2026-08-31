# Observation Contract v0.3

Defines the unit that feeds **Interpretation**. No semantic outcomes in this layer.

**Status:** schema aligned with `FRAMEWORK_BOUNDARY.md` ground rules (LOCKED positions — 2026-08-29).  
v0.2 → v0.3: drop semantic pre-labels; surface detector language-neutral; interpretation observes contract outcomes only.

## Shape

```json
{
  "observation_id": "string",
  "candidate_id": "string",
  "text": "raw string as found (after exact-byte page dedupe only)",
  "channel": "candidate_claim | search_context | navigation | page_chrome | unknown",
  "scope": "unit | card | search | page | note | unknown",
  "provenance": {
    "origin": "shortlist | url_query | page_state | card_fields | candidate | fixture | notes",
    "source_url": "optional",
    "surface": "optional — list_results | live_detail | live_offer_state | site_marketing | …",
    "same_entity_path": "optional bool — structural path relation, not domain",
    "acquisition_step": "optional int"
  },
  "structural_signals": {
    "repeat_count": "optional int — bare page-level exact duplicate count (#1)",
    "currency_glyph_count": "optional int (#2)",
    "digit_run_count": "optional int (#2)"
  }
}
```

### Field rules (LOCKED)

| Field | Allowed | Forbidden |
|-------|---------|-----------|
| `text` | Raw bound fragment | Semantic rewrite; soft chrome drop before LLM (#3) |
| `channel` | Structural routing labels only | Domain roles (`TARGET`/`FRAGMENT` from member_role lexicon) |
| `scope` | unit/card/page/… | Offer/board enums |
| `provenance.surface` | Tag from **language-neutral** density + path rules (#10) | Tags driven by `vanaf`/`p.p.`/`from` word lists |
| `structural_signals.*` | Bare counts | `is_chrome`, lexicon `density_hits`, `offer_shape_score` |
| Outcomes | **Not on the observation** | `board_type`, PASS/FAIL, ROOM_ONLY, etc. — those appear only **after** interpretation against the frozen contract (#13) |

## Rules

| Layer | May do | Must not do |
|-------|--------|-------------|
| **Builder** | Attach text + channel + scope + provenance + optional structural_signals | Emit `board_type`, PASS/FAIL, `is_chrome`, offer_shape |
| **Channel filter** | Drop / force UNKNOWN if channel ∉ allowed for the decision | Invent meaning |
| **Interpretation LLM** | Map text (+ signals) → **contract** outcome set | Final STOP; invent outcomes not in frozen contract (#13) |
| **Eligibility / sufficiency** | AND on normalized **outcomes** vs frozen contract | Read raw page text as authority |

## Channel meanings

- `candidate_claim` — text attributable to a Candidate / bound unit
- `search_context` — query filters in URL (structural query params)
- `navigation` — URLs / paths
- `page_chrome` — optional routing hint when packager source is affordance-only **and** structural density counts are zero; **not** a lexicon chrome verdict (#5)
- `unknown` — default

## Notes policy

`origin=notes` is **not trusted** for eligibility by default (`include_notes=False`).  
Notes may still be emitted with `channel` set carefully; main path uses shortlist / page_state / candidate / URL.

## Provenance / surface (#10)

- Marketing hard-block via `surface=site_marketing` remains **framework**.
- Density feeding `list_results` must use **glyph/digit** (or equivalent structural) counts — not `_PRICE_LINE` word lists.
- Threshold for list vs detail: **not locked** (see FRAMEWORK_BOUNDARY Open items #10). Do not assume old `price_hits >= 3`.

## Binding via Candidates

Preferred production path:

```text
page → extract_candidates → candidates_to_observations → Interpretation
```

`scope` may be `unit` / `card` when the observation comes from a candidate package.  
Observations should carry `candidate_id` so interpretation sees **bound** multi-line evidence rather than an unordered claim soup.

## Related

- `docs/FRAMEWORK_BOUNDARY.md` — ground rules #1–#3, #5, #8–#13, Open #4/#6/#10  
- `docs/CANDIDATE_LAYER.md` §2 — Candidate schema  
- `docs/BOUNDARY_AUDIT_FINAL.md` — audit provenance  
