# Framework boundary — what code owns vs what the LLM owns

**Purpose:** prevent regression into domain hardcoding (travel, GPU, marketplace, …).  
If a future change puts `board_type`, `visible_price`, `offer_state`, or similar **fixed enums** into the runtime, it violates this boundary.

Last updated: 2026-08-29 (ground rules from BOUNDARY_AUDIT_FINAL MOVE/ISOLATE/BROADEN).

---

## One-line rule

> **Code owns the mechanism. The LLM owns the content of the contract for each task.**

---

## Canonical entry point (LOCKED — 2026-08-29)

`agent.py` is the **legacy pre-contract-driven path** (last substantive
touch 2026-08-20 / mtime 2026-08-23). It is **deprecated** as the
recommended and default way to run the agent (2026-08-29). It is not
deleted in this step.

**Canonical production path:** `scripts/run_contract_driven_task_v0.py`
(`task.md` → frozen contract → `run_acquisition_loop` → code sufficiency STOP).

Batch default: `scripts/run_task_batch_campaign_v0.py` must use that path
unless `--legacy-agent` is set explicitly.

Do not treat `storage.py` / `candidate_admissibility.py` / `member_role.py`
lexicon gates as the live contract-driven boundary. Those modules belong
to the legacy harvest stack. See `docs/BOUNDARY_AUDIT_FINAL.md`.

---

## Ground rules — structure vs interpretation (LOCKED positions — 2026-08-29)

Source: `docs/BOUNDARY_AUDIT_FINAL.md` + ground-rules discussion (MOVE #1–#13, ISOLATE, irreversible BROADEN).  
These rules constrain **contract-driven** production code. Legacy `agent.py` / `storage.py` harvest lexicons are out of scope for repair (deprecated entry).

### Principle

| Code may record | LLM may decide |
|-----------------|----------------|
| Position, nesting, sibling/window, exact duplicate counts, link href/path depth/scope | “Is this chrome / noise / marketing?” |
| Currency **glyphs** (`€$£…`) and **digit runs** (incl. locale decimal/thousand separators as character classes, not language words) | “Is this price evidence for a contract claim?” |
| Bound text windows, affordance lists, provenance tags | Meaning of fragments under the **frozen contract** |
| Stable FIFO order over eligible claims; `max_llm_per_decision` budget | Which outcome enum applies |
| Irreversible **action** block (multi-lingual commit/pay/book patterns) | — (not an evidence classifier) |

**Never in production code (contract-driven path):** word-lists or regexes that classify *relevance* using language content such as `vanaf`, `p.p.`, `from`, hotel/board tokens, or chrome phrase lists (`_CHROME_HINT`, lodging title tokens, `_claim_priority` board/flight boosts).

---

### Candidate / unit layer (MOVE #1–#9, #12)

**#1 — repeat / chrome signal**  
- Code may expose `repeat_count` (how often the **exact same** normalized string appears elsewhere on the page) as a **bare integer**.  
- **No** code-side threshold (`> N` ⇒ chrome). The LLM interprets repetition.

**#2 — price-like structural signals**  
- Code may flag lines/units with **currency glyphs** and/or **digit runs**, including **locale decimal and thousand separators** as structural character patterns (not words like “vanaf” / “from”).  
- Code does **not** assert “this is a price”; the LLM maps signals to contract claims.

**#3 — what is passed to the LLM**  
- **Pass through** candidate/unit text; do **not** drop “chrome-looking” lines via semantic filters before the LLM.  
- **Only** allowed pre-LLM text reduction: remove **byte-identical** duplicate lines already present elsewhere on the **same page** (exact duplicate detection — not fuzzy/semantic dedupe).

**#5 — ranking / select**  
- No `is_chrome: bool` gate for inclusion.  
- Rank/select only on structural facts (e.g. glyph/digit density counts, `has_primary_action`, evidence length, bare `repeat_count`).

**#8 — itemish links (MECHANICAL)**  
- Itemish = structural only: non-empty href, path depth, scope, not `#` / `javascript:`.  
- **No** lexicon drop on link text. Short/generic labels are passed through as `{text, href, path_depth, scope}`.

**#9 — unit packaging**  
- Clustering remains structural (blank-line / link-anchor / sibling windows).  
- No role labels from domain lexicons.

**#11 — claim order (MECHANICAL)**  
- Eligible claims (channel allowed, not provenance-blocked): **stable FIFO** (document order).  
- **No** lexical boost (`vlucht`, board words, …).  
- `max_llm_per_decision` remains a code budget.

**#12 — `_CU_SYSTEM` (candidate-unit prompt)**  
- System text must stay **task-agnostic**: decide ADMISSIBLE | NOT_ADMISSIBLE | UNKNOWN **relative to USER TASK** in the payload.  
- **Allowed:** one **neutral** structural example that uses only abstract terms (e.g. *named fragment*, *supporting evidence*) — **no** concrete domain nouns such as “product”, “price”, “hotel”, “package” in the example itself.  
- Domain meaning comes from `task` + unit text + neighbors in the **user** payload, not from hardcoded system exemplars.

---

### Interpretation prompts (MOVE #13)

**#13 — `interpretation.SYSTEM_PROMPT` (MECHANICAL)**  
- System prompt: map observation → **one of the allowed outcomes supplied in the contract decision**; prefer UNKNOWN; no outside knowledge.  
- **No** hardcoded domain disambiguation (e.g. occupancy vs meal-plan `ROOM_ONLY`) in the system string.  
- Such distinctions belong in **frozen contract** `definitions` / `notes` for that task.

---

### Surface / provenance detector (MOVE #10 — principle locked, threshold open)

- Marketing / `site_marketing` hard-block via provenance tags remains a **framework** mechanism (see table above).  
- The **detector** that feeds density for `list_results` vs other tags must be **language-neutral** (glyph / digit-run style from #2), **not** `_PRICE_LINE`-style word lists (`vanaf`, `p.p.`, `from`, …).  
- **Do not** copy the old threshold `price_hits >= 3` one-to-one onto a glyph/digit counter without re-calibration: on fixture pages, lexicon hits and glyph/digit hits diverge sharply (e.g. Monica detail: PRICE_LINE hits **7** vs glyph/digit hits **37**). Blind reuse of `3` is a **regression risk**.  
- Threshold value: **not locked** here — see *Open items*.

---

### Lab fixtures — hard isolation (ISOLATE #14–#15, MECHANICAL)

**#14 — `PACKAGES_DECISIONS`**  
- Canonical entry (`run_contract_driven_task_v0`, batch without `--legacy-agent`) **must not** fall back to `PACKAGES_DECISIONS` when `frozen_contract is None`.  
- Require frozen contract; otherwise fail closed (raise / non-zero exit).  
- Offline experiments that need the packages fixture must opt in **explicitly** (dedicated flag or script) — never a silent default inside the acquisition loop.

**#15 — `BOARD_TYPE_CONTRACT` fallback**  
- `interpret_observation` on the production path **must not** silently substitute `BOARD_TYPE_CONTRACT` when `contract_decision is None`.  
- Fail closed (UNKNOWN without board default, or raise in the CD pipeline). Experiment scripts load that contract **explicitly**.

---

### Irreversible block — multi-lingual coverage (OK-framework-exception BROADEN #16–#18)

Still **framework-allowed** (safety: block commit/pay/book actions — not evidence relevance).

Expand patterns beyond NL/EN (illustrative set; exact regex is an implementation detail, not site names):

| Lang | Example commit/pay patterns (non-exhaustive) |
|------|-----------------------------------------------|
| DE | jetzt buchen, zahlungspflichtig bestellen, zur kasse, bestellung abschicken, bezahlen |
| FR | réserver maintenant, payer maintenant, passer commande, valider le paiement |
| ES | reservar ahora, pagar ahora, finalizar compra, realizar pedido |
| IT | prenota ora, acquista ora, procedi al pagamento, conferma ordine |

Do **not** block informational controls that only navigate to price/detail surfaces.  
`filter_safe_affordances` and action validation continue to use the same mechanism with the broader pattern set.

---

### Implementation note — density signals in the allowed table

Where the “Hardcoded (framework)” table still mentions density signals with word-shaped examples (`from`, etc.), read that as **legacy wording**. Authoritative rule is **#2** above: glyphs + digit runs (+ locale separators), not language words.

---

## Open items (do not drop in later sessions)

These are **explicitly unlocked**; they depend on implementing the locked rules first.

### #4 — MinAC stats for “chrome cluster?” (measurement order)

- Offline probe on 2026-08-29 used candidates **already filtered** by the lexicon chrome path → **chrome_rate = 0**, so A/B/C stat-sets were non-informative.  
- **Dependency:** re-measure **only after** #1–#5 are implemented (no `is_chrome` pre-filter; pass-through + bare `repeat_count` + structural density).  
- Until then: prefer a **minimal** stat payload (`n_lines`, `max_repeat`, structural density count) without locking a classifier.

### #6 — top-K truncation under token budget

- Directional floor: keep **K ≥ number of identity-bearing non-chrome units** on the page (on n=3 fixtures, loss started at K < 2…3).  
- **Not locked** to a fixed K; not validated across diverse page types.  
- Any production default K is a provisional budget knob, not a boundary theorem.

### #10 — surface density threshold after language-neutral detector

- Principle locked: glyph/digit (or equivalent structural) detector; no `vanaf`/`p.p.` lexicon.  
- **Threshold not locked.** Do not assume old `>= 3` transfers.  
- Evidence of divergence: Monica detail fixture PRICE_LINE hits **7** vs glyph/digit hits **37**.  
- Re-calibrate on multi-page / multi-surface traces (with `same_entity_path`) before locking a number.

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
| **Candidate-unit packaging** | Structural clustering of co-occurring page lines + local item links into bound units (`candidate_units.py`). Blank-line blocks, link anchors, density = currency **glyphs** + **digit runs** (locale separators OK). **No** language words (`vanaf`/`from`/…), **no** hotel/board/SKU field names in the packager |
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


### Representation arms (F1) — framework mechanism

Allowed as code mechanism: extract structure from text / HTML / AX tree into
Candidates. Forbidden: domain offer enums inside structural_observer. HTML arm may
use tag/role/class-*shape* only (card|item|list|article), not product vocabulary.


### Externalized plan over continuous context

Framework may (and should) keep authoritative state **outside** the LLM context: frozen contracts, traces, sufficiency results, host memory files, raw source pointers. Framework must **not** rely on an ever-growing chat transcript as the sole plan store for long work.

### Memory compression is not free

Summaries written by the LLM are *hypotheses*, not truth. Code-owned verification against raw evidence (or structured extract fields) remains the authority for STOP / report claims. Recursive free-text summarize-then-summarize is a known drift risk — treat as experimental, measure fact retention, prefer structured extracts + source URIs.
