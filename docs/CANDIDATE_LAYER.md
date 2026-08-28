# Candidate Layer — the intermediate abstraction

**Status:** introduced 2026-08-28 after contract-driven runs on tasks 01/02 exposed a repeated pattern: navigation and sufficiency work, but page understanding stays fragmented.

**Purpose of this doc:** explain *why* this layer exists, what it is, what it is not, and how to verify it offline before wiring it deeper into live acquisition.

---

## 1. The problem in one picture

Human on a list page:

```text
Grand Park Lara
Ultra All Inclusive
03 jan 2027
vanaf Brussel
€547 p.p.
[Bekijk vakantie]
```

→ **one object** with bound facts and one action.

Earlier agent path:

```text
claim, claim, claim, claim, link, surface, ranking, provenance, …
```

→ reconstruct togetherness after the fact.

That reconstruction produced a long chain of real but local fixes:

| Fix | Symptom solved | Next symptom |
|-----|----------------|--------------|
| STOP gate (code) | LLM stopped while gaps remained | — |
| Anti-repeat | Same toggle clicked forever | — |
| Panel options | Closed filters invisible | — |
| Soft-fail | One bad click killed the run | — |
| Provenance relax on list | 248 blocked obs | Outcomes still UNKNOWN |
| Unit packaging + item-link bias | Navigation to offer cards | Interpretation still saw bags of lines; chrome units mixed in |

**Diagnosis (2026-08-28):** contract/sufficiency is not the bottleneck. Representation of “what is one thing on this page?” is.

---

## 2. Definition (framework contract)

**A Candidate is:**

> a recognizable potential entity or offer on a page, with evidence that can be structurally bound to it, and an optional primary action to inspect that candidate further.

### Shape (no domain fields)

```text
candidate_id       # stable id within the page extraction
identity_hints[]   # short strings that appear to name/locate the object
evidence[]         # ordered text fragments bound to this candidate
primary_action?    # {text, href} — open/inspect further
source_url
surface            # structural tag from observer (list_results, live_detail, …)
density_hits       # structural score (€ / from / va shapes only)
packager_source    # blank_block | link_anchor | affordance_only
```

**Not candidate fields (never hardcode as schema):**

- `board_type`, `price_scope`, `flight_inclusion`, `airport`, `SKU`, …
- Those are **contract outcomes** produced when the LLM interprets candidate evidence under a frozen task contract.

---

## 3. Boundary (aligns with FRAMEWORK_BOUNDARY)

| Layer | Owner | May do | Must not do |
|-------|--------|--------|-------------|
| Packaging (`candidate_units` → `candidates`) | **Code** | Cluster by blank lines, local links, density shapes | Invent board/price/airport enums |
| Interpretation | **LLM** | Map candidate evidence → contract outcomes | Final STOP |
| Sufficiency | **Code** | Compare outcomes to frozen `sufficiency.required` | Domain taxonomies |
| Acquisition | LLM propose / code enforce | Prefer `primary_action` of a candidate when gaps remain | Site-specific ifs |

---

## 4. Intended flow (target architecture)

```text
TASK.md
  → contract synthesis → FREEZE
  → loop:
       observe page
       → extract Candidates (structural)
       → interpret Candidates (LLM: evidence → outcomes for this contract)
       → sufficiency gate (CODE)
       → if gaps: choose candidate / primary_action or other affordance
       → execute (anti-repeat, soft-fail)
  → STOP only when contract satisfied
```

Acquisition becomes conceptually:

```text
gaps
  → which candidate could supply missing evidence?
  → open primary_action
  → new page → new candidates
```

instead of:

```text
page → 30+ loose claims → rank → hope
```

---

## 5. Implementation map

| Module | Role |
|--------|------|
| `candidate_units.py` | Structural packager (blank blocks, link anchors, density) |
| `candidates.py` | First-class `Candidate` model + `extract_candidates` |
| `scripts/run_candidate_extraction_offline_v0.py` | **Offline-only** verification (no browser, no LLM, no planner) |
| `live_offer_state_slice.py` | Live path still uses units; will consume Candidates after offline GO |
| `evidence_acquisition.py` | Item-link bias; later: prefer candidate primary_action |

---

## 6. Offline verification protocol

**Goal:** answer one scientific question before more live patches:

> Can we generically produce coherent candidates from page observation?

**Not in scope for offline v0:** planner, STOP, sufficiency, contract outcomes.

### Commands

```bash
# Synthetic multi-offer + real 01/02 fixtures
python scripts/run_candidate_extraction_offline_v0.py \
  --manifest evals/candidate_offline/fixtures_from_traces/manifest.json \
  --outdir ./evals/candidate_offline

# Or any live trace artifacts directory
python scripts/run_candidate_extraction_offline_v0.py \
  --artifacts-dir path/to/run/artifacts \
  --label 01_list_step0 \
  --outdir ./evals/candidate_offline
```

### Pass signals

| Case | Expect |
|------|--------|
| Synthetic multi-offer list | ≥2 candidates, each with identity_hint + primary_action, no spillover across cards |
| Property detail (task 02) | ≥1 candidate whose evidence/identity includes the property name-ish lines |
| Price/list surface (task 01) | Dense candidate(s) with price-ish lines + local action |

### Fail signals (do not “fix” with domain ifs)

- One unit swallowing two cards
- All candidates are chrome (FAQ, language switcher) with density 0 and no useful identity
- Empty extraction on pages that clearly show offer blocks

---

## 7. What we deliberately do *not* do next

Until offline candidate quality is accepted:

- No extra surface heuristics as the main project
- No ranking “intelligence” beyond structural density/action
- No raising max acquisition steps as a substitute
- No site-specific Corendon rules
- No full 8-task batch as the primary experiment

After offline GO:

1. Interpret **per candidate** (or top-K) instead of whole-page claim soup  
2. Acquisition prefers `primary_action` when gaps remain  
3. Re-run contract-driven 01 + 02  
4. Only then broader batch

---

## 8. Relation to Observation Contract

Observations remain the wire format into interpretation (`OBSERVATION_CONTRACT.md`).  
Candidates **produce** observations with `candidate_id` set so evidence stays bound:

```text
Candidate → candidates_to_observations → channel=candidate_claim, candidate_id=cN
```

Interpretation and eligibility still must not invent schema fields outside the frozen contract.

---

## 9. Why this is not a rewrite

Existing work is evidence, not waste:

- Contract synthesis + freeze proved task-dependent “done”
- STOP authority + anti-repeat + soft-fail proved control plane
- Packaging + item-link bias proved structural clustering is feasible

The Candidate layer **names and stabilizes** that clustering as the object the rest of the system reasons about.

---

## 10. Quality v1 (2026-08-28 offline)

After first offline run showed chrome pollution and identity ranked below density:

1. **Chrome flag** — nav/FAQ/season/review-date clusters marked `is_chrome` (structural patterns only).
2. **primary_action gate** — help paths and chrome labels → no action (null preferred over wrong link).
3. **select_top_candidates** — dense non-chrome first; always try to keep substantive identity candidates; drop chrome from interpret set.

Synthetic multi-offer remains the regression for multi-card separation. Real detail pages: top-K should include both price-dense and name/board identity candidates without FAQ/menu.

Still **not** solved: automatic merge of identity candidate + price candidate into one object on single-entity pages. That is a separate, explicit next research step if interpret still fails with split candidates.


---

## 11. Interpret over candidates (next measured step)

**Hypothesis:** a quality-selected top-K candidate set is enough for the interpretation
layer to fill frozen-contract outcomes — without mandatory same-entity merge.

**Offline probe (no browser):**

```bash
python scripts/run_interpret_candidates_offline_v0.py \
  --candidates evals/candidate_offline/<run>/candidates_02_monica_detail_*.json \
  --contract evals/contract_synthesis/<run>/contract_02_web_hotel_property_only_*.json \
  --llm --outdir ./evals/interpret_candidates
```

**Live path:** `live_offer_state_slice` builds observations from `extract_candidates` +
`candidates_to_observations`; acquisition prefers `primary_action` links from selected
candidates.

**Pass criteria**

| Task | Expect |
|------|--------|
| 02 property | From Monica candidates alone → subject CONFIRMED + board ALL_INCLUSIVE → sufficiency satisfied (0 acquisition steps ideal) |
| 01 package | Outcomes move off all-UNKNOWN when price+identity candidates present; may still need navigation |

If 02 fails offline with the candidate set that clearly contains name+board, the bug is interpretation prioritization, not packaging.
If 01 fails only because name and price are in different candidates, revisit same-entity binding *then*.
