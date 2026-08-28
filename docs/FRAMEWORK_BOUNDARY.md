# Framework boundary — what code owns vs what the LLM owns

**Purpose:** prevent regression into domain hardcoding (travel, GPU, marketplace, …).  
If a future change puts `board_type`, `visible_price`, `offer_state`, or similar **fixed enums** into the runtime, it violates this boundary.

Last updated: 2026-08-28 (candidate layer).

---

## One-line rule

> **Code owns the mechanism. The LLM owns the content of the contract for each task.**

---

## Hardcoded (framework) — allowed

These are domain-agnostic and may live in code permanently:

| Mechanism | Role |
|-----------|------|
| Task intake (`task.md`) | Input unit |
| Contract meta-schema | Shape: subject, decisions/claims, outcomes include UNKNOWN, sufficiency block |
| Contract synthesis loop | CD0 → CD1/CD2 refine → freeze (passes, not travel rules) |
| Observe / extract affordances | Browser, FS, text — mechanical |
| Action enum + execute | OPEN_URL, CLICK_TEXT, SCROLL, WAIT, STOP, … |
| Irreversible block | book/pay/checkout/submit (multi-lingual patterns, not site names) |
| Affordance target enforcement | LLM may only choose observed controls |
| Provenance tags | surface (`live_detail` / `live_offer_state` / `list_results` / `site_marketing`), same_entity_path, acquisition_step — structural, not domain enums. Marketing surfaces hard-blocked; list_results admissible even when path ≠ start_url |
| **Candidate-unit packaging** | Structural clustering of co-occurring page lines + local item links into bound units (`candidate_units.py`). Blank-line blocks, link anchors, density signals (€/$/from shapes only). **No** hotel/board/SKU field names in the packager |
| **Candidate objects** | First-class intermediate model (`candidates.py`): `identity_hints`, `evidence[]`, optional `primary_action`, `source_url`, `surface`. Code builds candidates; LLM interprets them into **contract** outcomes. Offline probe: `scripts/run_candidate_extraction_offline_v0.py`. See `docs/CANDIDATE_LAYER.md` |
| Evidence store + claim status | UNKNOWN / evidence refs |
| **Sufficiency gate** | STOP only when **frozen contract** required claims are satisfied — **code decides STOP**, LLM may only propose |
| TraceSession / flush / job boundaries | Observability and isolation |
| Host memory transport layer | navigation/semantics/harvest sketches — not task criteria |

---

## Not hardcoded — must come from task → contract synthesis

**Never** bake these into the sufficiency engine or acquisition core as fixed fields:

- `board_type`, `package_includes_flight`, `visible_price`, `flight_details`
- `property` / `binding` / `offer_state` as **runtime enums or required layers**
- Site-specific rules (`if corendon`, `always click Prijzen & boeken`)
- Domain taxonomies (meal plans, GPU SKUs, marketplace “seller trust”)

Those strings may appear **inside a frozen contract JSON** for one task because the LLM wrote them for that task. They are **data**, not framework vocabulary.

`property / binding / offer_state` may be used in **human analysis / docs** only — not as code paths.

---

## Contract synthesis (LLM content)

```
task.md
  → Pass 0   provisional (task only)          [CD0]
  → Pass 1+  refine (surfaces and/or gaps)    [CD2 / gap_revise]
  → after each pass: LLM gap-check
       ready_to_freeze?  → FREEZE
       else              → next pass (cap max_passes)
```

Entry points (code):
- `contract_discovery.synthesize_and_freeze_contract(task_text, …)`
- `contract_discovery.synthesize_contract_from_task_path(path, …)`
- batch runner: `scripts/run_contract_synthesis_batch_v0.py`

The frozen contract defines, for **this** task only:

- which claims / decisions exist  
- required vs optional (via `sufficiency.required`)  
- what counts as sufficient evidence (text in the contract — not hidden domain rules in Python)  
- stop criteria (`blocking_unknowns`)  

Verification “hints” in the contract are **contract fields filled by the LLM**, not Python `if price.startswith("vanaf")` rules.

Offline fallback is `heuristic_contract_generic` (shallow, domain-agnostic).  
`heuristic_contract_for_packages` is an **experiment fixture only**, not production ontology.

---

## Runtime sufficiency (code)

```
LLM:  "I think claim X is proven"  → evidence update proposal
CODE: does evidence meet claim X’s requirements from the frozen contract?
CODE: are all required claims satisfied?  → STOP or CONTINUE acquisition
```

The LLM **must not** be the final STOP authority.

Implementation:
- `sufficiency.evaluate_sufficiency(frozen_contract, outcomes, proven_labels=…)`
- `evidence_acquisition.sufficiency_stop` / `gaps_from_frozen_contract`
- Offline probe: `scripts/run_sufficiency_check_v0.py`

Parses `sufficiency.required` as: `decision_id`, `id = OUTCOME`, `id in [A, B]`, or free-text labels.

Acquisition: LLM proposes next action from **observed affordances only**; code validates and executes.

Filesystem (generic): `fs_observer.list_paths` / `inspect_path`; action class `OPEN_FILE` — no domain parsers.

---

## High-level flow (canonical)

```
TASK.md
  → contract synthesis (iterative, LLM content)
  → FREEZE
  → loop:
       observe page
       → extract Candidates (structural; code)
       → interpret Candidates (LLM: bound evidence → contract outcomes)
       → sufficiency gate (CODE vs frozen contract)
       → if insufficient: acquisition (prefer candidate.primary_action / observed affordances)
  → report + TraceSession
  → optional host sketch for later runs
```

Optional later: human API adapters for heavy hosts — still selected as tools/affordances, not `if site == …` in core.

---

## Regression lessons (2026-08-27)

| Lesson | Implication |
|--------|-------------|
| Monica 0-step on one “pakketreis + vlucht” sentence | Current **experiment** outcomes were property-level only; real task text wanted visible price on offer card — **contract should have required that**, not a Monica special-case |
| Costa multi-step local tabs | Gap-driven acquisition works when claims stay UNKNOWN |
| Early-stop on interpret LLM calls | Cost control is framework; claim *meaning* is not |
| Site learning | First visit expensive; memory + optional API for repeats — still generic |
| NOT_ADMISSIBLE blocked interpret → empty outcomes | **Admission ranks units; interpret fills contract outcomes.** Do not skip interpret when candidate_claim observations exist |
| Repeated same CLICK with no URL/text change | **Framework anti-loop:** fingerprint action+target+path; block no-progress repeats — not site-specific ifs |
| UI toggle changes state_sig without research progress (VERTREKPERIODE×3) | **Anti-repeat = block action_key after one attempt**, not only equal signatures |
| LLM acquisition STOP while contract still has gaps | **Code rejects that STOP**; sufficiency gate remains the only “done” authority |
| Page text shows filter options not in affordance list | Affordance extractor surfaces **panel_option** (ARIA/labels/short clickables in expanded surfaces) — no domain lists |
| List/home offer cards → provenance_blocked mass | Provenance must distinguish offer-fragment vs chrome (later step) |

Do **not** “fix Monica” with hardcoded offer-state fields. Fix by **better task→contract** and generic sufficiency.

### STOP authority (hard rule)

```
LLM may propose STOP
     ↓
code: frozen contract satisfied?
     ↓ no → reject STOP, continue (or max steps)
     ↓ yes → CONTRACT_SATISFIED
```

LLM never finalizes a run that still has required gaps.

---


### Candidate layer (2026-08-28)

After multiple correct control-plane fixes (STOP, anti-repeat, panel options, provenance, packaging),
task 01 still failed to *fill* contract outcomes on visible offer text. Task 02 showed a false-negative
`subject_instance` until a better-bound unit appeared. Root issue: **loose claims force post-hoc
reconstruction of object boundaries.**

Framework response: promote structural units into first-class **Candidates** (no domain fields).
Verify offline before more live ranking/surface patches. Do not encode hotel/offer enums into Candidates.

## Checklist before merging code

- [ ] No new fixed decision ids for a vertical in `evidence_acquisition` / sufficiency core  
- [ ] No `if "corendon" in url` (or other host) in acquisition/eligibility  
- [ ] Experiment slices (live_offer PACKAGES_DECISIONS) clearly marked **fixture/experiment**, not production ontology  
- [ ] New tasks = new `task.md` + synthesis, not new Python enums  
- [ ] Trace explains stop via contract claims, not page-type heuristics  

---

## Related docs

- `DECISION_CONTRACT_DISCOVERY.md` — meta-schema, CD0/CD1/CD2  
- `METHODOLOGY.md` — recon vs retrieval, host memory  
- `LEARNING_LOG.md` — dated experiments  
- `ARCHITECTURE_MEMORY.md` — global host transport memory  
