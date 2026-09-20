# Framework boundary — what code owns vs what the LLM owns

**Purpose:** prevent regression into domain hardcoding (travel, GPU, marketplace, …).  
If a future change puts `board_type`, `visible_price`, `offer_state`, or similar **fixed enums** into the runtime, it violates this boundary.

Last updated: 2026-09-16 (Architecture freeze P0 — hard-fail isolation).

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
unless `--legacy-agent` is set explicitly. Execution with `--legacy-agent`
must log a visible `[LEGACY PATH]` line (P0.3).

Do not treat `storage.py` / `candidate_admissibility.py` / `member_role.py`
lexicon gates as the live contract-driven boundary. Those modules belong
to the legacy harvest stack. See `docs/BOUNDARY_AUDIT_FINAL.md`.

---

## Architecture freeze (P0) — 2026-09-16

Locked **before** any further efficiency work (multi-decision batch default,
browser tiers, memory, planner). Goal: production cannot silently degrade
into lab fixtures or a non-frozen contract.

| Rule | Behaviour |
|------|-----------|
| Canonical path | `run_contract_driven_task_v0.py` only for production claims |
| Missing `--contract-dir` / non-dir | **Hard fail**, non-zero exit (`CONTRACT_DIR_MISSING` / `CONTRACT_DIR_REQUIRED`) |
| No contract for task stem | **Hard fail**, non-zero exit (`CONTRACT_MISSING`) |
| `frozen != true` | **Hard fail**, non-zero exit (`CONTRACT_NOT_FROZEN`) — no WARNING-and-continue |
| `frozen_contract is None` without explicit `decisions=` / `allow_lab_fixture` | **RuntimeError** in `run_acquisition_loop` / `run_pipeline_one` (ISOLATE #16) |
| `contract_decision is None` in interpret | Fail-closed **UNKNOWN**; no silent `BOARD_TYPE_CONTRACT` (ISOLATE #17 / P0.2) |
| Multi-decision batch interpret | **Opt-in only** (`batch_decisions=True`); default remains single-decision |
| Legacy | `--legacy-agent` only; prints `[LEGACY PATH]`; not comparable to CD baselines |
| No new layers pre-freeze | No new browser/memory/planner stacks until this P0 checklist is green |

CD-only import graph (P0.4): production modules on the contract-driven path
must not import `agent` / `storage` / `member_role` as runtime dependencies.

### Process rule — raw result quotes (LOCKED)

**Every success or regression claim about a run must quote literally**
`stop_reason`, `outcomes`, and `contract_satisfied` from the run’s raw
`result_*.json` (terminal `grep` / `python -c` on that file).

Do **not** rely on a paraphrase or summary from an earlier chat message.
Motivation: run `20260915T074757Z` was mis-read as UNKNOWN in conversation
while the raw result was `CONTRACT_SATISFIED` / `board_type=ALL_INCLUSIVE`,
which caused a full false “coverage gap” diagnosis (Open #23 downgrade).

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
- **2026-09-17 addendum (`093236Z` abs):** `count_price_like_lines` = **4** (threshold 3) → arXiv **detail** tagged `list_results`. Monica detail fixture = **29**. Density-as-list is not a reliable single-record detector; do not raise the threshold as a silent #27 fix (would also move synthetic list at 3). Re-calibrate on multi-page traces before locking.
- **Live `062211Z` abs `/abs/2609.18128`:** still `surface=list_results`. Fase 2.2 html leaf then packaged Access-Paper chrome (`View PDF` / `HTML (experimental)` / `TeX Source`) instead of the abstract paragraph that is in `step_003_page_text.txt`. Remaining `claim_extracted=NOT_VISIBLE` after a successful preferred-href OPEN is this item, not #24.
- **Recalibration 2026-09-18 (code + offline):** reconstructed those 4 D2c lines as identifier-shaped, not prices: `2609`/`18128` (Cite as + version), DOI `48550`, file size `5,658 KB`. Same class as Monica 7-vs-37 (review scores `8,1` counted as D2c). D2c now rejects bare 4+ digit integers and 1-decimal fractions; T stays **3**. After: abs=1 (filesize only), search=3, synthetic=3, Monica 3-digit prices=10, Flamenco=9. Root start_url (empty path) uses same-host for `same_entity` so a non-dense abs is `live_offer_state`, not `site_marketing`. Offline `evals/surface_threshold/`. **Does not close #10 until live 05.** No html_b2.
- **Live `070449Z` (rebuild `6debab8`):** raw `result_*` `stop_reason=CONTRACT_SATISFIED` `contract_satisfied=true` `claim_extracted=EXTRACTED` `final_url=/abs/2609.18128`. Abs step 3 `surface=live_offer_state` `packager_source=blank_block`; c3 is the abstract paragraph. Search step 2 stayed `list_results`. **This trigger is live-proven.** Threshold value still provisional (not locked across all page types). #26 bind seen, unbind/switch not.

### #19 — outcomes persistence across acquisition steps (provisional)

- **Problem:** each step re-interpreted outcomes from the *current* page only; final result used `last_pipe` only. A confirming label (e.g. `board_type=ALL_INCLUSIVE` on steps 1–2) was silently lost when a later page did not repeat the evidence (`NOT_STATED` / `UNKNOWN` on step 3) — run `20260831T063112Z`.  
- **Fix direction (code, not LLM memory):** `_merge_outcomes` keeps the strongest confirming outcome per `decision_id`. Weak labels (`UNKNOWN`, `NOT_STATED`) never overwrite a confirming value. A later *different confirming* label overwrites (newest concrete observation wins on conflict).  
- **Provisional:** “contradiction wins” and the weak-label set are tested on the 01/02 patterns only — not locked across diverse contracts. Revisit if contracts introduce graded confidence or multi-valued decisions.  
- (Numbered #19 to avoid collision with ground-rules **#11 claim order**.)
- **Origin of `NOT_STATED` (2026-09-07 herkomst-check):** the current `_WEAK` set contains the literal string `"NOT_STATED"`, which comes from **LLM contract synthesis** (`board_type` outcomes on `contract_01_web_hotel_package_concrete`), **not** from framework code. `pipeline_offline.aggregate_outcome` only returns code-default `UNKNOWN`; `interpretation.py` only defines `OUTCOME_UNKNOWN`. `NOT_STATED` is therefore a **task-specific workaround**, not a locked framework primitive.  
- **Do not promote** `OUTCOME_NOT_STATED` as a second framework sentinel (that would hardcode contract vocabulary into the runtime).  
- **If a future task synthesizes a different absence label** (`NOT_VISIBLE`, `UNSTATED`, …), generalize: preferred direction is **option B** — *weak = any label that is not in the sufficiency-satisfying set for that `decision_id`* (contract-driven, no fixed strings). That requires `_merge_outcomes` to receive the `frozen_contract` (or the per-decision satisfying outcome set). **Do not implement until a second task actually needs it.**
- **Same problem class — within-step aggregation (2026-09-08 / run `20260908T081349Z` task 06):** `aggregate_outcome()` used pure confidence order across candidate rows. A high-confidence absence label (`NOT_STATED`) on an irrelevant candidate could outrank a medium-confidence contract-satisfying label (`FIGURE_FOUND`) on another candidate that actually contained the evidence. Population text was present in `step_001_candidates.json` (c2) but final `population_figure` stayed `NOT_STATED`.  
- **Fix (code, domain-free):** `aggregate_outcome(..., preferred_outcomes=decision.required_for_eligibility)`. When any row’s outcome is in the sufficiency-satisfying set for that decision, only those rows compete; confidence order applies *within* that pool. If no row is satisfying, fall back to all non-UNKNOWN rows (so pure absence still aggregates to the absence label). No hardcoded `"NOT_STATED"` string. Call site: `run_interpretation` passes `required_for_eligibility` already annotated from the frozen contract by `_decisions_from_frozen_contract`.  
- **Relation to option B:** this is the *within-step* half of the same rule `_merge_outcomes` needs *across steps*. Both prefer “in sufficiency-satisfying set” over “not in set”, without naming absence vocabulary in framework code.
- **Perf — skip already-satisfied decisions (2026-09-13):** once `best_outcomes[decision_id]` holds a label in that decision’s `required_for_eligibility`, later acquisition steps **do not** re-run interpret for that decision (`_decisions_pending_interpretation`). Outcomes remain visible via `best_outcomes` / step merge. **Design trade-off (accepted):** a later page that would *contradict* an earlier satisfying label is not re-checked — same family as “absence must not erase confirm”, inverted for cost. Revisit if multi-source contradiction detection becomes a requirement.
- **Complement — Open #26:** merge persistence is correct *within one bound candidate*. A concrete reject (`NOT_RELEVANT`) must not survive a later preferred-item bind/unbind; that is scope reset, not a change to `_WEAK`.

### #20 — interpret cost scales with n_decisions (measured pattern, not a bug)

- **Observation (2026-09-08 generality mini-batch):** wall time is dominated by **interpretation LLM calls**, not by number of sites visited. Rough pattern:
  - ~2 decisions (travel 01/02) → ~8–16 calls/step
  - ~5 decisions (wiki 06) → ~16–22 calls/step
  - ~7–8 decisions (arxiv 05, coolblue 03) → ~38–50 calls/step → 5–8 min/step on local models
- **Mechanism (pre-Fase B):** each step ran interpret over (candidates/units × decision_ids).
- **Fase B (2026-09-14):** multi-decision batch implemented (`interpret_observation_multi` / `SYSTEM_PROMPT_MULTI`). `aggregate_outcome` unchanged.
- **Offline oracle parity:** deterministic mock LLM — outcomes identical single vs multi; call count ≈ ÷ n_decisions.
- **Live (2026-09-14):** task **06** OK (26→15 calls, contract satisfied); task **02 REGRESSIE** — `board_type=UNKNOWN` all steps (was `ALL_INCLUSIVE` / `CONTRACT_SATISFIED` under single). Default **reverted to `batch_decisions=False`**. Batch remains available via explicit parameter only. Root cause was later reclassified (see retest 2026-09-16 + Open #22).
- **Retest post-#22 (2026-09-16, `--batch-decisions`, default still False):**
  - **02 ×5:** all `stop_reason=CONTRACT_SATISFIED`, `contract_satisfied=true`, `board_type=ALL_INCLUSIVE`; `llm_calls_total=3` each (single baseline same day: **6**). Runs: `20260916T062828Z`, `…T063117Z`, `…T063301Z`, `…T063406Z`, `…T063503Z`.
  - **06 ×3:** all `CONTRACT_SATISFIED`, `population_figure=FIGURE_FOUND`; `llm_calls_total=15` each. Runs: `20260916T063703Z`, `…T064138Z`, `…T064738Z`.
  - **01 ×1:** `MAX_ACQUISITION_STEPS`, `contract_satisfied=false` (gaps `price_scope=NO_PRICE`, `party_size=NOT_SPECIFIED` — same class as single-decision 01, not a batch correctness regression); `llm_calls_total=34` vs prior single ~**137** (`20260914T124822Z`). Run: `20260916T065415Z`.
- **Definitive verdict (2026-09-16, Fase B closed):** hypothesis supported — 2026-09-14 task-02 batch failure aligned with pre-#22 fail-open/coverage confusion, not inherent multi-decision model failure on this stack.
  - **Default remains `batch_decisions=False`** (explicit `--batch-decisions` required).
  - **Opt-in recommended when `n_decisions >= 4`** for lower interpret cost (log tip only in `run_contract_driven_task_v0.py` — never auto-enabled).
  - Confirmed live: **02** (3 decisions, control) batch 5/5 correct at 3 calls vs single 6; **06** (5 decisions) batch 3/3 correct at 15 calls; **01** (10 decisions) batch still unsatisfied on price/party gaps (not a batch regression) at **34** calls vs single ~**137**.
  - Not a global default: more non-travel + longer-horizon parity still desirable before any policy stronger than a tip.
- **Token trade-off:** larger prompt per call; fewer calls → usually lower total tokens when parity holds.
- **Observability:** `llm_calls_total`, `n_decisions`, `llm_calls_per_decision`; traces may set `batch_decisions`; CLI logs `batch_decisions=True|False` and, when `n_decisions >= 4` and batch is off, a non-binding Tip line pointing at this open item.

### #22 — entity-binding in aggregate_outcome (provisional; code in place)

- **Evidence (offline):** `fase_d_binding_20260915T073132Z.json` (task 02 Monica detail):
  - 1a (title+Fly&Go+reviews+**Abora**) → `board_type=ALL_INCLUSIVE` only from Abora carousel claim
  - 1b (without Abora) → `UNKNOWN`
  - 1c (Abora only) → `ALL_INCLUSIVE`
  - Pre-#22 live PASS could be fail-open on cross-entity board text.
- **Fix (code, domain-free):** track structural `subject_candidate_ref` from the claim/candidate that confirmed `subject_instance` (`candidate_id`, `block_index`, `item_link_href`, `scope`). For other decisions, `aggregate_outcome(..., require_subject_binding=True)` only accepts rows bound by same `candidate_id`, nearby `block_index` (cluster K provisional), or identical `item_link` href; otherwise **UNKNOWN** (fail-closed). Title/page_title anchors use `earliest_block_index`.
- **Post-#22 baseline (happy path):** when subject-bound hero board text is in top candidates, task 02 stops correctly with `board_type=ALL_INCLUSIVE` — not via carousel.
  - Example: `20260915T074757Z` and stability batch 20260915T1610–1627Z (see #23).
- **Interaction with Fase B (2026-09-16):** after #22, live `--batch-decisions` on task 02 was **5/5** `CONTRACT_SATISFIED` / `board_type=ALL_INCLUSIVE` (see Open #20 retest). Supports treating the earlier batch “02 UNKNOWN” episode as pre-binding / diagnosis noise, not permanent multi-decision incompatibility.
- **If `board_type=UNKNOWN` after #22:** may be honest fail-closed (no subject-bound board evidence) — verify with raw `result_*.json` + **same-run** saved candidates before calling it a packaging regression.
- **Not locked:** exact cluster K; path-segment heuristics beyond exact href equality.

### #23 — hero/title board coverage on detail pages (DOWNGRADED — 2026-09-15)

- **Status:** **not a confirmed gap after the #22 fix.** Do not treat “02 UNKNOWN = coverage failure” as established fact.
- **How the earlier “coverage gap” claim arose (corrected):**
  1. **Pre-#22 runs** where `board_type=ALL_INCLUSIVE` looked like success but could be **cross-entity false PASS** (carousel). Those mixed “missing hero in top-K” with “wrong evidence accepted.”
  2. **Read error on run `20260915T074757Z`:** treated as UNKNOWN during Fase E; saved result was actually `CONTRACT_SATISFIED`, `board_type=ALL_INCLUSIVE`, Aparthotel in **saved** `step_000_candidates` (c0).
  3. Some earlier artifact comparisons mixed **different runs** (page_text vs units from different captures).
- **Stability after #22 + bi-first rank (2026-09-15):** **9/9** campaign reports for task 02 → `CONTRACT_SATISFIED`, `ok=true`. Sample greps (161312Z, 162204Z, 162745Z): outcomes `subject_instance=CONFIRMED`, `detail_link=VALID_DETAIL_PAGE`, `board_type=ALL_INCLUSIVE`; Aparthotel in saved candidates **True**; `acquisition_steps=0`. Duration ~41–99s; `llm_calls_total` 5–8 (~1.7–2.7 per decision).
- **What remains possible (not measured as a bug):** occasional layout/carousel captures where hero is absent from top-K and binding correctly leaves UNKNOWN. Residual risk only.
- **Re-open rule:** only reopen as an active defect with a **new** live 02 trace where:
  - `stop_reason` / `outcomes` are grepped from the **raw** `result_*.json` of **that** run, and
  - **saved** `step_000_candidate_units.json` / `step_000_candidates.json` of **the same run** lack subject hero board text.
- **Not in scope:** no gate change, no rank change — not justified by post-#22 stability data.
- **Process:** any future “regression” claim starts with a two-line raw result grep before a diagnosis round.

### #21 — search-field preference (superseded in part by Fase G capability)

- **Original symptom:** non-travel tasks (arxiv 05, coolblue 03) under-used visible search controls; CLICK_TEXT on “Zoeken” timed out on Coolblue.
- **Original hypothesis:** planner bias “prefer observed search field when task names a specific entity”.
- **2026-09-16 Fase G (implemented):** root cause was a **capability gap**, not missing preference:
  - Affordance layer never exported text-like `<input>`/`<textarea>` → new kind `input_field` (structural metadata only, no lexicon).
  - Action enum had no fill → new class `FILL_AND_SUBMIT`; **`query_text` is free LLM text** (code does not copy from gaps).
  - Anti-loop fingerprint includes `(target, query_text)`.
- **Live proof (task 05, 20260916T170647Z):** LLM chose FILL unaided; `query_text="large language model agents tool use 2024"` → 232 arXiv hits. Preference bias **not required** once inputs are visible and fill is executable.
- **Still open under #21 / follow-ons:** list_results → abs href not in affordances (see Open #24). Coolblue CLICK_TEXT: input_field did not self-solve `text=Zoeken` timeout (icon submit, empty innerText). Generic fallback (`7863753`): after visible-text locators miss, click the unique `input_field` whose accessible name token-boundary-matches the click text (`_label_matches_text`). No site selector, no search lexicon. Negative: unrelated failed clicks do not bind a random input. **Live `103711Z`:** `stop_reason=CONTRACT_SATISFIED`; planner used FILL_AND_SUBMIT `Zoeken naar...` (`q=rtx 4070`), not CLICK_TEXT — fallback is the vangnet when that click still happens.

### #24 — list_results item hrefs not in affordances (post-FILL bottleneck)

- **Symptom (task 05 after successful FILL):** LLM proposes `OPEN_URL` to `https://arxiv.org/abs/…` derived from candidate_unit text; code rejects `href_not_in_affordances`. List affordances show short labels (`arXiv:NNNN`, `pdf`, authors) but not full abs links. Interpret on list surface leaves `title/claim/url=NOT_VISIBLE`.
- **Diagnosed 2026-09-17 (offline, real artifacts of run `20260916T170647Z`, no new live run) — split into two distinct sub-findings:**

**#24a — word-boundary item_link mis-binding (CLOSED, fixed 2026-09-17)**
- `candidate_units._link_for_block` (+ the link-anchor→block pass) matched labels via raw substring containment. `"submit" in "submitted 24 march, 2026…"` → the unit containing the AdaTIR paper was bound to the unrelated global `Submit` (`/user/create`) link.
- Fix: `_label_matches_text` requires a non-alphanumeric boundary on both sides — structural token check, no lexicon. Applied at **both** duplicated match sites (lesson from bug #2: fix everywhere the same logic is duplicated).
- Regression-tested against the accepted-good `evals/candidate_offline/fixtures_from_traces/manifest.json` (01/02/synthetic) — item_link bindings unchanged. New fixture: `evals/candidate_units_link_binding/`.
- **This alone does not close #24** — see #24b.

**#24b — chunking/representation gap on blank-line-less list pages (OPEN)**
- Root cause: this page renders its entire 50-result list as **one** blank-line block (no blank line between `<li>` cards in flattened `page_text`). Fixed 8-line chunking then straddles paper boundaries. Combined with `browser_list_affordances`'s de-dupe-by-visible-text (only the *first* occurrence of a repeated label like `"pdf"` is captured), later chunks whose own link was never captured fall back to matching a **different paper's** `"pdf"` link — wrong-entity binding, not absence of binding.
- **Attempted and reverted (2026-09-17):** href path-tail disambiguation (prefer a candidate whose href identifier segment also appears in the block text; else `None`). Regressed the known-good `02_monica_detail` fixture (dropped real `"Prijzen & boeken"` / `"Bekijk deze Fly & Go vakantie"` bindings in favor of a duplicated-but-harmless `"Costa Calma"` breadcrumb link). Reverted in full — do not reintroduce without a design that distinguishes "exact duplicate href" from "generic label, different hrefs."
- **This is a representation problem, not a matching-algorithm problem** — same class `structural_observer.py`'s HTML arm (`extract_candidates_via_html` / `html_b2`, see `CANDIDATE_LAYER.md` §12) was built for, never wired into the live path. **Recommended next step:** measure the HTML arm on a live-captured list-results page (arXiv search or similar) offline, before any further text-heuristic attempt on `candidate_units.py`.
- Also flagged, not yet measured: `browser_list_affordances` text-based de-dupe may under-collect repeated CTA labels on other list pages too (e.g. task 01 "Bekijk vakantie" repeated per card) — needs its own isolated offline measurement, out of scope for this fix.
- **Status-check 2026-09-17 (offline, existing 05 artifacts; no new live run):** **still active after #25/#27.** Not a 111714Z miss. Search `list_results` steps in `083112Z` / `093236Z` / `102344Z` / `111714Z` still show one ~90–111-line blank-line block, `page_ids≈18–19` vs `cand_ids=1`, a single affordance `text="pdf"`, and 8-line chunks that straddle papers. `111714Z` `step_002_candidates.json` c3 evidence is ClinAgent `2609.13860` bound to `pdf` href `2609.19059` (first card). Contract PASS used unique `arXiv:NNNN` abs OPEN + #27 wrap, not per-card packaging. Fetched search HTML: 50× `li.arxiv-result`, titles in `<p class="list-title">`, **1** `h1–h4` on the page — **`html_b2` (heading+price NCA) is the wrong arm for this shape;** leaf `html` (`li`) is the candidate. Do not wire `html_b2` as the #24b fix without that measurement. PDF `Download is starting` is Open #28 (not this item).
- **Fase 1 (2026-09-17, code + offline):** `browser_list_affordances` JS `push()` identity is now `(kind, text, href, name, id)` plus cross-kind `TH|text|href` — **not** text-only `T|text`. Same visible label with distinct hrefs all survive. Exact `(text, href)` duplicates still collapse. Python mirror: `affordance_identity_accepts` / `filter_affordances_by_identity`. Offline `evals/affordance_identity/test_affordance_identity_offline_v0.py`: reconstructed `111714Z`/`153607Z` search (19 paper-ids) → **19 unique pdf hrefs** (legacy rule: 1); 01/02/06 counts identical. **Does not close #24b** (list still one blank-line block). **Fase 2** (leaf `extract_candidates_via_html` additive on `list_results`) only if a Fase-1 live retest is insufficient. No live 05 in this slice.
- **Live `162616Z` (Fase 1 retest, rebuild `cc1871e`):** `stop_reason=CONTRACT_SATISFIED` `final_url=/abs/2609.17632`. Search `step_002_affordances.json`: **3** `"pdf"` hrefs (`19059`/`18736`/`18591`) vs 1 before. After SCROLL: **8** pdf hrefs. **#28 live:** `download.kept_page=true` on `OPEN_URL` `/pdf/2609.19059`. **#24b not closed:** `step_002_candidates.json` c3 still ClinAgent `2609.13860` bound to first-card pdf `2609.19059`; PASS via unique `arXiv:2609.17632` abs OPEN. `action_key=OPEN_URL|pdf|/search` is still text-only.
- **Fase 2.1 (2026-09-17, plumbing):** `_snapshot` keeps `page.content()` as `html` (cap 400k); traces write `step_NNN_page.html`. `extract_candidates` unchanged. Offline `evals/html_leaf_list/test_html_plumbing_offline_v0.py`.
- **Fase 2.2 (2026-09-17, leaf html additive on `list_results`):** live `extract_candidates(..., html=)` calls `extract_candidates_via_html` **not** `html_b2`. Gate: `surface=list_results` and ≥3 repeating cardish siblings under a list-ish parent (`repeating_only=True`). Then select from those leaf cards (Open #6 top-K) instead of 8-line blank-line chunks. 01/02 fixtures byte-identical with vs without HTML (01 sketch has only 2 review listitems; 02 is `live_detail`). Reconstructed 19-card `ol.results > li.result`: selected ids `2609.19059`/`18736`/`18591` with matching `/abs/` hrefs; old text path still mismatches ClinAgent `13860`→pdf `19059`.
- **Live `171515Z` (rebuild `26e89af`):** `stop_reason=MAX_ACQUISITION_STEPS` `contract_satisfied=false` only `claim_extracted=NOT_VISIBLE`. **Leaf arm live:** `step_002_candidates.json` `packager_source=html_structure`, per-paper cards `2609.18445`/`18128`/`17698` with matching `/abs/` hrefs. `step_NNN_page.html` written. Planner `OPEN_URL` `https://arxiv.org/abs/2609.13860` (c0 preferred_item, self-consistent) → `href_not_in_affordances`: href not in the `max_items=60` list. `filter_safe_affordances` boosts preferred items already in that list; it does not inject missing preferred hrefs. **#24b representation is live-visible; remaining fail is the original #24 allowlist/cap.** #26 no scope event.
- **Allowlist slice (2026-09-18, code + offline):** `acquisition_decide` OPEN_URL allowlist is now `observed_open_hrefs(safe, preferred_item_links)` — planner-safe affordance hrefs ∪ `primary_action.href` of every candidate shown this step (text/html/ax). Invented URLs still `code_reject href_not_in_affordances`. Offline `evals/preferred_href_allowlist/`: 171515Z abs accepted; invented URL rejected; 01/02 extra_vs_safe=0; 06 extra_vs_full_aff=0. **Does not close #24 until live 05.** No new extraction. Not html_b2.
- **Live `062211Z` (rebuild `41d5fc7`):** list OPEN_URL `https://arxiv.org/abs/2609.18128` `source=llm` (c2 `primary_action`; href **absent** from `step_002_affordances.json`) → navigated, `candidate_scope event=bind path=/abs/2609.18128`. **No `href_not_in_affordances`.** Raw `result_*`: `stop_reason=MAX_ACQUISITION_STEPS` `contract_satisfied=false` only `claim_extracted=NOT_VISIBLE` `final_url=/abs/2609.18128v1`. Remaining gap is Open #10 (abs tagged `list_results` → html leaf chrome cards), not the allowlist. **#24 allowlist live-proven.** Do not close #24b/#10/#26 on this run.
- **Coolblue list→detail (2026-09-18, offline then live 3×):** live pre-fix repeats `110505Z`/`114603Z`/`123057Z` all `MAX_ACQUISITION_STEPS` `detail_link=NO_URL`. Not a miss of #10 (surface already `list_results`) and not the 05 allowlist (no product href on candidates). (A `06f7f00`) `_snapshot` 400k cap counted `<script>`/`<style>`/`<head>` — `html_chars=699128`; `prepare_html_for_snapshot` strips those *then* keeps `<body>` *then* caps. (B `ef3b066`) pick max `n × (D2c + text-link)`; replace text only if itemish (price **or** href+digit-runs+≥2 lines). (C `64a4f88`) `inject_preferred_action_affordances` before `panel_option` cap. **Live 3× rebuild `3a3407bb`:** `174311Z`/`183956Z`/`190223Z` all `stop_reason=CONTRACT_SATISFIED` `contract_satisfied=true`. Step 1 after FILL `q=rtx 4070`: `packager_source=html_structure`, `primary_action.href` = `/nl/product/947851/asus-rog-strix…` / `969894/hp-victus…` / `948809/hp-victus…` (not Language/Account). Raw affordances still 47 `panel_option` + 0 `/product/` hrefs; replay `filter_safe` injects the three product links first. **0 OPEN_URL in all three loops.** `final_url` remains `/nl/zoeken?query=…`. Planner FILLed again (`videokaart` / `Super`) because list cards are laptops. Interpret set `detail_link=CONCRETE_PRODUCT_PAGE` on `list_results`. **Does not close #24b** (no list→detail navigation). Not html_b2. Not vision.

### #25 — refine search after current-page object rejection (code in place; live retest pending user OK)

- **Symptom (task 05, run `20260917T072448Z`, raw loop):** after `OPEN_URL` to `/abs/2609.19059`, current-page `subject_instance=NOT_RELEVANT`. Next actions were `CLICK_TEXT Related Papers` → `OPEN_URL HTML` → `CLICK_TEXT Back to Abstract` — all on the same rejected paper. Never a new `FILL_AND_SUBMIT`. Final: `stop_reason=MAX_ACQUISITION_STEPS` `contract_satisfied=false` gaps `subject_instance=NOT_RELEVANT` `claim_extracted=NOT_VISIBLE`.
- **Cause:** gaps already carried `observed=NOT_RELEVANT` / `result=FAIL` into `acquisition_decide`, but the planner system prompt preferred staying on the current entity (tabs / preferred_item). FILL was described only as “when gaps suggest missing search results.”
- **Fix (2026-09-17):** if *current-page* outcome (not merged `best_outcomes`) is `NOT_RELEVANT` or `REJECTED` for a still-FAIL gap, **and** this run already saw `surface=list_results`, the planner prompt inverts: do not deepen this record; you MAY `FILL_AND_SUBMIT` with a **new** LLM-formulated `query_text` (code never writes the query). No input_field → use a listed affordance to reach search; no invented URLs. Absence labels (`NOT_VISIBLE` / `UNKNOWN`) do **not** trigger this.
- **Anti-loop:** existing `action_fingerprint` includes `query_text`; identical FILL on the same field stays `no_progress_repeat_blocked`.
- **Offline:** `evals/refine_search_after_reject/test_refine_search_offline_v0.py` green. Live taak 05: only after explicit user OK + `docker compose build`.
- **Live `20260917T083112Z` (user):** #25 held — after abs `NOT_RELEVANT`, `OPEN_URL Search` then new FILL queries. Contract still false because merge kept `NOT_RELEVANT` (Open #26).

### #26 — candidate-scoped outcome reset on item switch / unbind **and** unbound-list search-round reset

Two **separate** reset paths. Neither makes the other redundant:

1. **Bound `candidate_path` (#22-style unbind — already shipped).** Trigger: preferred-item bind / switch / leave-path / FILL while `active_candidate_path is not None`. Reset: **drop** `best_outcomes` with `step >= candidate_bound_step` (`_reset_post_bind_outcomes`). Live bind seen (`062211Z`/`070449Z`); unbind/switch still rare.
2. **Unbound list-interpretation (this slice).** Trigger: successful `FILL_AND_SUBMIT` whose normalized `query_text` **differs** from the previous successful FILL in the same run (same `q=` signal as the anti-loop fingerprint). First FILL: no-op. Reset: **weaken** entries with `step >= last_fill_result_step` to `UNKNOWN` **without deleting the key** (`apply_fill_query_round_reset`). `_merge_outcomes` is unchanged (confirming still beats later UNKNOWN).

Coolblue `183956Z`/`190223Z`: laptop list set `detail_link=CONCRETE_PRODUCT_PAGE` with **no bind** (0× OPEN_URL). Path (1) did nothing (`active_candidate_path is None`). Path (2) is the hole: refine FILL `q=rtx 4070 videokaart` left that confirming label in `best_outcomes`; Open #19 then `skip_satisfied=['detail_link', …]` on the empty result page.

- **Symptom (`20260917T083112Z`):** #25 correctly left the rejected paper; `best_outcomes.subject_instance` stayed `NOT_RELEVANT` because `_merge_outcomes` treats any non-`UNKNOWN`/`NOT_STATED` label as persistent. Later list `UNKNOWN` does not overwrite. Mixing risk: title from paper A + `RELEVANT` from paper B.
- **No existing cross-step entity key.** `#22 subject_candidate_ref` is intra-page only. `same_entity_path` is vs `start_url` (breaks 02 Fly & Go / arxiv root).
- **Fix path (1):** `apply_candidate_scope_after_action` after a successful navigation.
  - **Bind** only if `target_href` ∈ that step’s `preferred_item_links` and path left the current page, from `list_results` (first bind) or onto a different bound path (switch). First list→detail with *satisfying* labels does **not** reset (#19 / taak 01).
  - **Unbind** on `FILL_AND_SUBMIT` **when already bound**, or leaving the bound path without a preferred-item bind (e.g. OPEN Search). Same-record deepening (`/abs/id` → `/html/id…` via last-segment prefix) does not unbind.
  - **Reset:** drop `best_outcomes` with `step >= candidate_bound_step`; keep pre-bind (e.g. `source_site`). No `subject_instance` special-case — any required decision with a concrete non-satisfying outcome is “instance FAIL”.
- **Fix path (2) (2026-09-19):** `apply_fill_query_round_reset` after path (1) on a successful FILL. Loop keeps `last_fill_query_text` + `last_fill_result_step` (no `search_round_id` on candidates; `c0`/`block_index` recycle per page). No decision_id lexicon. Empty/chrome new pool: weakened keys stay `UNKNOWN` so sufficiency still sees a gap.
- **01/02 offline:** tab same-path no-op; Fly & Go from `live_detail` without list-bind no-op; list `ALL_INCLUSIVE` → detail bind without wipe. Path (2) dead (0 FILL in 01/02/06 loops) — fingerprints unchanged.
- **Offline:** `evals/candidate_scope_reset/test_candidate_scope_offline_v0.py` — plus FILL-2 `NOT_RELEVANT`→`UNKNOWN`; FILL-1-only no wipe; Coolblue laptop-pool weaken keeping step-0 shop labels; keys remain on empty-pool reset.
- **Live `20260917T093236Z` (rebuild, `batch_decisions=False`):** `contract_satisfied=false` `gaps_n=1` only `claim_extracted=NOT_VISIBLE`; `subject_instance=RELEVANT` (083112Z: `NOT_RELEVANT` on the same abs — LLM label variance). One `candidate_scope event=bind` on `/abs/2609.19059v1` at step 6; **no unbind/switch**. First list→abs OPEN succeeded (href in affordances) but did **not** bind: `preferred_item_links` were chrome (`Submit`/`Advanced Search`) — #24b. Homepage `NOT_RELEVANT` overwritten by later concrete `RELEVANT` (#19), not by scope reset. **#26 not live-proven — do not close.** Remaining gap was Open #27 (abstract line dropped), not merge.

- **Live `20260917T102344Z`:** still **no** `candidate_scope` bind/unbind/switch. Do not force another 05-run hoping for abs-reject. Offline tests remain the #26 proof. Keep OPEN until an unbind/switch event is observed or the item is explicitly deferred. PDF-download and #24b are later slices.
- **Live path (2) `20260919T061149Z` (rebuild `23028a0`):** raw `result_03_web_product_gpu_20260919T061149Z.json`: `stop_reason=CONTRACT_SATISFIED` `contract_satisfied=true` `subject_instance=RTX_4070` `detail_link=CONCRETE_PRODUCT_PAGE` `final_url=https://www.coolblue.be/nl/zoeken?query=nvidia+rtx+4070` `acquisition_steps=5`. Loop: 0× `OPEN_URL`. Three `search_round=search_round_reset` (q=`rtx 4070 videokaart` / `rtx 4070 super` / `nvidia rtx 4070`). After first reset, step 2 `detail_link=NO_URL` `skip_satisfied=['price_scope']` (no longer `detail_link`). SATISFIED returned on the **same** nvidia-query list at step 5 (no FILL between 4 and 5 — same round, not the hole).
- **Live path (1)+(2) `20260919T064948Z`:** raw `result_03_web_product_gpu_20260919T064948Z.json`: `stop_reason=MAX_ACQUISITION_STEPS` `contract_satisfied=false` `subject_instance=OTHER_GPU` `detail_link=CONCRETE_PRODUCT_PAGE` `study_design=UNKNOWN` `final_url=https://www.coolblue.be/nl/zoeken/producttype:videokaarten?query=videokaart` `acquisition_steps=6`. Unbound reset on refine `q=rtx 4070 super videokaart`; then `OPEN_URL` `Bekijk alle categorieën` `event=bind path=/nl/ons-assortiment`; later FILL `q=videokaart` `event=unbind` `search_round=search_round_reset`. **Do not close #26** (03-run1 still list-SATISFIED; no product OPEN).
- **Live 05 `20260919T072546Z` (same image):** raw `result_05_web_literature_abstract_20260919T072546Z.json`: `stop_reason=CONTRACT_SATISFIED` `contract_satisfied=true` `claim_extracted=EXTRACTED` `final_url=https://arxiv.org/abs/2609.20625` `acquisition_steps=3`. One FILL (first FILL = path-2 no-op). `event=bind path=/abs/2609.20625`. Homepage `NOT_RELEVANT` then Search/FILL/OPEN abs — **not** #25 abs-reject→FILL-retry. Reset did not break the 05 happy path. Do not treat this as #25 re-proof.
- **Offline #25 under path 2 (no new live; reconstruct `083112Z`):** loop order is path 1 then path 2 (`live_offer_state_slice`). Bind uses post-#24b preferred abs href (083112Z artifact preferred links were chrome). **Canonical** (abs `NOT_RELEVANT` at step 3): path 1 `unbind` **drops** `subject_instance` / `access_status` / `recency` / `year_venue_extracted`; path 2 `search_round_reset` does **not** resurrect `subject_instance`; step-0 `source_site=ARXIV` survives path 2; step-2 search-pool keys weaken. **Exact merge** from raw `result_05_…083112Z.json` `steps_contract_flags`: homepage `subject_instance=NOT_RELEVANT` stays `step=0` because `_merge_outcomes` does not bump step on the same concrete string at abs step 3 → unbind (`step>=3`) and path 2 (`step>=2`) **leave** it. Abs-only labels (`access_status=OPEN_ACCESS` `recency=IN_RANGE` `year_venue_extracted=EXTRACTED`, all step 3) still drop. This is merge-step, not path 2 double-reset. **No `_merge_outcomes` change without design.** #26 stays OPEN.

### #27 — long innerText paragraphs dropped from units (wrap + observation-cap closed; live `111714Z` CONTRACT_SATISFIED)

- **Symptom (`20260917T093236Z` step 003):** abstract present in `step_003_page_text.txt` as one **1524-char** line; `claim_extracted=NOT_VISIBLE`. `_skip_line_structural` skipped `len>240` and split the blank-line block, so the paragraph never entered a unit. Title survived in the 8-line prefix chunk.
- **Not a surface-only bug:** even if abs were tagged `live_detail`, `len(selected)==3` chrome candidates skip the `page_text_to_observations` safety net (`len(selected) < 2`). `page_text_to_observations` also skipped `len>240`.
- **Fix (structural):** wrap long lines into 240-char windows as their own block; keep high-char chunks without requiring digit-density or `item_link`; after action-first rank, **append** at most one long-text unit/candidate (do not drop nav top-K).
- **01/02:** fixtures also contain huge lines (already dropped pre-fix). Offline: top-3 item_link hrefs unchanged.
- **Offline:** `evals/long_line_units/test_long_line_units_offline_v0.py`. Live 05 only after user OK + `docker compose build`.
- **Live `20260917T102344Z` (rebuild, `batch_decisions=False`):** wrap+splice **did** produce abs `c3` = full AdaTIR abstract (`identity_hints=[]`, `primary_action=null`, `block_index=1`). **Interpret never saw it:** `live_offer_state_slice` called `candidates_to_observations(selected, max_candidates=3)` so c3 was dropped. `step_005_claims.json` `claim_preview` is title+c0+c1+c2 only (`candidate_claim_n=4`). Same cap on HTML step 6. Offline test hid this (`max_candidates=8`). Not LLM; not empty `identity_hints`; not #22 (subject skipped this step → no subject_ref).
- **Fix (observation-cap mismatch, 2026-09-17):** option (a) — live call is now `obs = candidates_to_observations(selected)` (no independent recap). Open #6 budget stays on `extract_candidates(max_candidates=3, max_units=6)`; #27 splice may make `len(selected)=4`. Option (b) (hardcode the same 3) would still drop c3. `candidates_to_observations` default is `max_candidates=None` → all of `selected`. Offline: `evals/long_line_units/test_long_line_units_offline_v0.py` reconstructs 102344Z (c3 in observations); old recap=3 drops c3; 01/02/06 first-3 claim texts unchanged. **This closes the #27 observation-cap follow-up.**
- **Live `20260917T111714Z` (rebuild `1f0557e`, `batch_decisions=False`):** `stop_reason=CONTRACT_SATISFIED` `claim_extracted=EXTRACTED`. Abs `step_006_claims.json` `candidate_claim_n=5`; `claim_preview` includes spliced c3 abstract (`Large language model (LLM) agents augmented by tools…`). **#27 contract-closed for this gap.** **#26 stays OPEN** (no scope event). #24b still open; PDF-download catch is Open #28.

### #28 — navigation that starts a file download (code in place; live retest pending)

- **Symptom:** `OPEN_URL` to an observed `/pdf/…` href (`111714Z` `https://arxiv.org/pdf/2609.19059`, also `102344Z`) → Playwright `Page.goto: Download is starting` → `error` + `soft_fail`. The loop already kept the list page; the step looked like a failed navigation.
- **Not #24b:** the *wrong* pdf href (first `"pdf"` de-dupe) is still Open #24b. This item is only the engine treating a download as a crashed goto.
- **Fix (structural):** listen for Playwright `download` on `goto`/`click`; match the engine message `Download is starting` (not a URL/file-type lexicon). Cancel the download (no PDF parse). Snapshot the **current** document (`download=True`, `error=None`). Acquisition: `ok` if page text remains; `download_kept_page` log; action_key still blocked so the planner tries another affordance (abs / HTML).
- **Not in scope:** reading PDF bytes as contract evidence.
- **Offline:** `evals/download_navigation/test_download_navigation_offline_v0.py` — live error string detected; timeout is not a download; execute OPEN_URL download is `ok` not `error`. Live 05 only after user OK + `docker compose build`.

### #29 — dead surface: code terminal before interpret (provisional char budget)

- **Symptom:** TUI `111126Z` fetch OK, `affordances=[]`, 1 unit, 190 chars → 6× LLM STOP rejected while gaps remain → `MAX_ACQUISITION_STEPS` + interpret on injected task-entity claim.
- **Trigger (structural, no lexicon):** `fetch_ok` AND `affordances_count==0` AND `candidate_units_count<=1` AND `text_chars < DEAD_SURFACE_TEXT_CHARS_MAX` (400, **provisional**, same class as Open #6 / #10). Stop `DEAD_SURFACE_NO_CONTENT` before `_pipeline_on_obs`.
- **Not bol:** `131049Z` has 3 global links, 2 units, 1093 chars — stretching the predicate to catch bol collides with the 2–3 unit negative. **Open #30 (2a)** owns that rest class.
- **Offline:** `evals/dead_surface/test_dead_surface_offline_v0.py`. Live TUI/bol only after user OK + `docker compose build`.
- **Entity-as-claim (separate):** `page_text_to_observations` no longer adds `candidate_id` as `candidate_claim`. Task text is not page evidence. `entity` remains on `contract_meta` / observation `candidate_id`. Offline: `evals/entity_claim/test_entity_not_claim_offline_v0.py`.

### #30 — dead surface 2a: zero same-host http(s) affordances (provisional unit cap)

- **Symptom:** bol `131049Z` fetch OK, 3 global links (mailto + other hosts), 2 units, 1093 chars → 6× LLM STOP → `MAX_ACQUISITION_STEPS`. FIX 1 (#29) does not match.
- **Trigger (structural, no lexicon, not 2b status tokens):** `fetch_ok` AND NOT `#29 is_dead_surface` AND `same_host_http_affordance_count==0` AND `candidate_units_count <= 2` (provisional). Stop `DEAD_SURFACE_NO_SAME_HOST_CONTENT` before interpret. Host equality = `urlparse.netloc` after `urljoin`; mailto/tel/other host do not count.
- **Boundary (accepted):** contact page, 2 units, only mailto/tel = 2a-dead. This loop cannot OPEN_URL on-host. False-positive class: those two units already hold the answer (never interpreted). Escape: 3+ units, or ≥1 same-host http(s) href.
- **Negatives:** 06 `064738Z` 60 aff / 33 same-host http. 01/02/03/05 + marktplaats/SS/wiki-BXL not 2a. TUI stays `#29` (`DEAD_SURFACE_NO_CONTENT`), not 2a.
- **Offline:** `evals/dead_surface/test_dead_surface_same_host_offline_v0.py`. Live bol only after user OK.
- **Not 2b:** digit tokens 403/404/429 left undiscussed; do not add without a separate decision.

### #31 — blocking overlay dismiss after repeated timeout (ARIA dialog)

- **Symptom:** 2dehands `140350Z` FILL timeout. Playwright: `<div role="dialog" aria-modal="true" id="sp_message_container_*">` intercepts pointer events (Sourcepoint iframe inside). Every click/fill on that page fails, not only search.
- **Trigger:** ≥2 CLICK/FILL timeouts on the **same URL-path** with **different** `action_fingerprint`s (anti-loop keys). First timeout never dismisses (Coolblue Zoeken is one miss + related-input fallback).
- **Detect:** visible `[role="dialog"]` or `[aria-modal="true"]`. No cookie/consent/host lexicon. Existing `COOKIE_SELECTORS` unused on this path.
- **Dismiss (chosen):** first `button` / `[role=button]` in DOM order inside the dialog. **Rejected:** shortest visible text (length-as-meaning / "OK" guess). Cross-origin iframe, no same-origin button → `hide_blocking_dialog` (cannot click into the iframe).
- **Negatives:** 01/02/03/05/06 page HTML has no `sp_message_*` dialog; first-timeout gate is False. Icon-search fixture (Zoeken timeout class) has 0 overlays.
- **Offline:** `evals/overlay_dismiss/test_overlay_dismiss_offline_v0.py`. Live 2dehands only after user OK.

### #32 — HTML leaf replace drops D2c text units (claims-vs-units)

- **Symptom:** wiki `165815Z` step 3. `step_003_candidate_units.json` u0 has `Bevolkingsdichtheid 198.674 (01/01/2026)`. `step_003_claims.json` `claim_preview` is Atomium / Manneken Pis / Belgische Revolutie. Planner STOP cites u0; interpret stays `population_figure=UNKNOWN`. Surface=`list_results` (Open #10 T=3 on infobox digits).
- **Not rank:** text-arm `rank_candidates` keeps u0 first (`block_index=0`, digit_run=11). **Not #27 recap:** claims n=4 = page title + 3 HTML cards; `candidates_to_observations` has no second cap.
- **Mechanism:** Open #24b HTML leaf replace on `list_results`. Landmark `<li>` clusters win `html_leaf_should_replace_text` via href+digit_runs (1830/1958 are not D2c). Exclusive `select_top_candidates(html)` drops the text pool before interpret. Same *class* as #27 (two packagers, exclusive budget), different gate.
- **Fix:** after HTML replace, splice at most one text candidate whose **unrepresented** `line_is_price_like` lines (glyph ∨ D2c, not bare digit_run) are ≥ 3 (same T as #10, **provisional**). "165 miljard" on the Atomium card is D2c but must not block splice. Priced HTML lists (Coolblue) already contain the D2c lines → no extra unit. arXiv pagination 100/200 is 2 hits → no splice.
- **Negatives:** 01/02/03/05/06 text-arm fingerprints unchanged (`html=""`). Recorded 03 HTML (D2c on cards) and 05 HTML (no extra unit) do not grow. No lexicon (`bevolking` etc.).
- **Offline:** `evals/claims_vs_units/test_claims_vs_units_offline_v0.py`. Live wiki only after user OK.
- **Not closed:** Open #10 T=3 still tags the wiki article as `list_results`. This item is only the replace/splice, not the surface classifier.

---

## Hardcoded (framework) — allowed

These are domain-agnostic and may live in code permanently:

| Mechanism | Role |
|-----------|------|
| Task intake (`task.md`) | Input unit |
| Contract meta-schema | Shape: subject, decisions/claims, outcomes include UNKNOWN, sufficiency block |
| Contract synthesis loop | CD0 → CD1/CD2 refine → freeze (passes, not travel rules) |
| Observe / extract affordances | Browser, FS, text — mechanical |
| Action enum + execute | OPEN_URL, CLICK_TEXT, CLICK_SELECTOR, FILL_AND_SUBMIT, SCROLL, WAIT, STOP, OPEN_FILE — closed enum; targets from observed affordances only; FILL query_text is free LLM text |
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
