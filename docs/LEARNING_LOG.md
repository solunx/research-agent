# Learning log — experiments, results, decisions

Living log of what we tried, what worked, what we abandoned.  
High-level process: see `METHODOLOGY.md`.

Format per entry: **date → hypothesis → result → decision**.

---

## 2026-09-16 — Architecture freeze P0 (isolation)

| Hypothesis | Result | Decision |
|------------|--------|----------|
| Non-frozen / missing contract should hard-fail | Neg tests: missing dir → exit 2 `CONTRACT_DIR_MISSING`; empty dir → exit 2 `CONTRACT_MISSING`; `frozen=false` → exit 1 `CONTRACT_NOT_FROZEN` (no acquisition) | **P0.1 locked** in `run_contract_driven_task_v0.py` |
| Lab fixtures must not silent-fallback on CD path | `run_acquisition_loop` / `run_pipeline_one` already raise without decisions; interpret returns UNKNOWN without `BOARD_TYPE_CONTRACT` | **P0.2 confirmed** (ISOLATE #16/#17) |
| Legacy path must be obvious at runtime | `--legacy-agent` prints `[LEGACY PATH]` | **P0.3** |
| CD modules import agent/storage/member_role? | grep on CD graph: **empty** | **P0.4 isolatie OK** |

Process rule locked: quote raw `result_*.json` (`stop_reason` / `outcomes` / `contract_satisfied`) for any success/regression claim (074757Z misread).

See `FRAMEWORK_BOUNDARY.md` § Architecture freeze (P0).

---

## 2026-09-16 — Fase B retest post-#22 (`--batch-decisions`)

| Hypothesis | Result | Decision |
|------------|--------|----------|
| 2026-09-14 task-02 batch UNKNOWN was entity-binding, not multi-decision model failure | **02 ×5** batch: all `CONTRACT_SATISFIED`, `board_type=ALL_INCLUSIVE`, `llm_calls_total=3` (single same-day: 6). **06 ×3** batch: all satisfied, `FIGURE_FOUND`, calls=15. **01 ×1** batch: still unsatisfied (`NO_PRICE` / `NOT_SPECIFIED`) but calls **34** vs ~137 single | Hypothese **supported**. Batch remains **opt-in** (`--batch-decisions`); not global default. Documented under Open #20 + #22 |
| Batch cuts cost on heavy contracts | 01: 34 vs ~137 LLM calls at max_steps=4 | Keep measuring; acquisition gaps (price/party) still dominate 01 success, not interpret mode |

Raw runs: `20260916T062828Z`…`T063503Z` (02), `T063703Z`…`T064738Z` (06), `T065415Z` (01).

---


## 2026-08-28 — Contract-driven 01+02 (execution layer)

| Hypothesis | Result | Decision |
|------------|--------|----------|
| Frozen contract + code sufficiency is the only STOP authority | Task 02: LLM said STOP (“All Inclusive found”) while `subject_instance` still UNKNOWN → run ended unsatisfied | **Reject LLM/soft STOP while gaps remain**; only code terminals (`no_gaps`, `max_steps`, `no_llm`) may end early |
| State-signature anti-loop stops useless repeats | Task 01: 3× `VERTREKPERIODE`; UI toggled open↔close so `no_progress=false` | **Block action_key after one use** (toggle ≠ research progress) |
| Interpret after NOT_ADMISSIBLE yields outcomes | 01: `interpreted=True` but `provenance_blocked_n=248` → all UNKNOWN | Admission fix kept; **provenance/list surface** = later step (not this commit) |
| Same architecture, different tasks → different stop criteria | 01 (8 required) vs 02 (2 required) without Python domain ifs | Keep ladder: contract → sufficiency → evidence → nav; **no Monica/Costa patches** |

**Shipped (this step only):** stop-reject-on-gaps + anti-repeat-by-action-key in `live_offer_state_slice.py` / `evidence_acquisition.py`.

See also `FRAMEWORK_BOUNDARY.md` regression lessons.

---

## 2026-08-28 — Affordance panel options (step C)

| Hypothesis | Result | Decision |
|------------|--------|----------|
| Filter tabs alone enough | 01 opened VERTREKPERIODE; page_text had months; affordances only tabs | Extract **panel_option** generically |
| Hardcode months/airports | Domain leak | ARIA option/menuitem, label+input, short clickables in expanded/listbox/filter-like surfaces |

**Code:** `browser.browser_list_affordances` — `kind=panel_option` after tabs; acquisition `max_items=60`.

**Test:** re-run **01 only**; expect panel options in affordances after filter open (no domain ifs).

---

## 2026-08 — Architecture direction

| Decision | Why |
|----------|-----|
| External notes + shortlist, not one giant chat | Ollama context crashes (500) on long runs |
| Planner / executor / critic (`--planned`) | Flush context per phase |
| Global host memory (not per-task only) | Same site must not be re-learned every task |
| No travel hardcoding in core | Agent must stay general-purpose |
| Browser Use = optional tier 3, not default | Not a magic bullet; slow; timeouts |
| **Host capability = navigation + semantics + harvest** | Transport alone ≠ usable research (2026-08-22 runs) |
| **Recon optimizes for interface learning, not deals** | Easy-booking recon left meal/date/pax semantics weak |
| **Research executes memory; heavy tiers prefer recon** | Production should not rediscover hosts each run |

---

## 2026-08-22 — Capability model update

| Hypothesis | Result | Decision |
|------------|--------|----------|
| Recipes with only path+param *names* are enough | Research still ignored meal filter, 30-night range, Sunweb date snap | Add **semantics** + **harvest** layers to recipes |
| Recon = “simple vacation until results” | Learned navigation; weak semantics/harvest | Recon = **probes** (one dimension at a time); stop at list/detail |
| Literature AWM / Branch-and-Browse | Related (workflow memory) but we need site **capability** model | Keep building thin host OS layer; don’t copy full academic stacks |

**Code shipped:** recipe fields `navigation` / `semantics` / `harvest` / `capability_score` / `needs_recon`; recon prompt rewrite; METHODOLOGY + recon task updated.

---

## 2026-08-22 — Harvest invariant + production stop (P0/P1)

| Hypothesis | Result | Decision |
|------------|--------|----------|
| LLM will call `add_to_shortlist` when it sees name+€ | Research run: notes had Sercotel €698 etc., shortlist=0 | **Runtime harvest invariant** auto-writes `observed_only` candidates |
| Soft nudge alone is enough | Nudge present; still no shortlist | Invariant must not depend on LLM |
| Production may UI-learn pax on Sunweb | 8+ no-ops then abandon | **needs_recon** on no-op abandon; no mini-recon in retrieve |
| Forced report “no hotel names” | False — names were in notes | Auto shortlist + evidence model reduces forced-report lies |

**Code shipped:** `extract_observed_candidates` / `harvest_invariant_from_browser_result` in `storage.py`; agent wires after browser tools (research only); `match_status=observed_only` + `evidence.observed/verified`; production stop marks `needs_recon`.

**Not in this iteration:** VLM / extra Browser Use; full separate recon metrics pipeline (still shared counters, but recon still blocks shortlist).

---

## 2026-08-22 — Observation ≠ candidate (generic EAV)

| Hypothesis | Result | Decision |
|------------|--------|----------|
| Auto-shortlist every € + nearby line | Shortlist=23 noise (discounts, airport deltas) | **observations.jsonl** vs promoted candidates |
| Fix with travel-specific regex | Would hardcode the vertical | Structural **amount_role** + **entity_score** + confidence gate |
| Soft mismatch + keep clicking | Mini-recon on Sunweb | Research: mismatch → needs_recon + host block after one harvest |

**Code shipped:** `extract_eav_observations`, promotion only primary+conf≥0.55; mismatch tags on candidates; useful_actions = promotions only.

---

## 2026-08-22 — Multi-signal candidate gate + rankable runtime (P0)

| Hypothesis | Result | Decision |
|------------|--------|----------|
| Single proper-noun rule enough | Would miss real names; slogans still scored high | **Multi-signal**: entity_score + marketing_penalty + offer-meta chrome + URL depth + pairing confidence |
| Critic filters shortlist junk | Forced report ranked 5 items though 4 were NIET BRUIKBAAR | **Rankable gate before critic**; critic ranks only rankable |
| LLM update overwrites rankable=False | Merge dropped harvest rankable | Sticky rankable=False on shortlist merge |
| useful_ratio optimizes research quality | Misleading | Log **candidate_precision** = rankable/shortlist; status taxonomy PARTIAL_SUCCESS / RUN_FAILED_LLM |

**Code shipped:** `_marketing_penalty`, `_OFFER_META_RE`, `_pairing_confidence`; promote thresholds conf≥0.70 entity≥0.58 mp<0.45; `compute_rankable` + sticky merge; metadata `rankable_count` / `candidate_precision`; status `PARTIAL_SUCCESS` when shortlist survives LLM crash.

**Not in this iteration:** Corendon list-card extract; Task Definition Agent; new browser tiers.

---

## Browser backends (A/B)

| Backend | Finding | Status |
|---------|---------|--------|
| Playwright deep-links | Best yield so far when recipes exist | **Keep as default Tier 2** |
| Browser Use (full agent) | Long timeouts, low yield on package sites; good as last resort only | **Optional; not primary** |
| “Rebuild Browser Use features ourselves” | Distraction | **Abandoned** |

---

## Package-site probes (lastminute / sunweb / corendon)

| Observation | Implication |
|-------------|-------------|
| lastminute deep-links often show **0 results** even with valid param shape | URL mechanics ≠ inventory; need empty-inventory cap |
| Sunweb `Participants[0][0]=3` → rewritten to **date** `1996-08-22` | Param semantics memory + strip on open |
| Sunweb Mealplan codes `AI` / `UA`, not word “all-inclusive” | Recipe should store **value enums** later |
| Corendon `destination=` often **ignored**; filter is UI panel | Deep-link alone insufficient; list harvest / UI filter still needed |
| Consent iframe blocks clicks | Hide overlay + force click; don’t count as no-op |

### Research run (Playwright, ~11 min, shortlist 1)

- Soft mismatch worked on Sunweb; still only 1 strong candidate (Corendon Grand Park Lara).
- Too many empty lastminute opens → low useful_ratio.
- **Decision:** empty-inventory cap + recon/research split.

### Recon run 2026-08-22 (`--run-kind recon`, ~3.5 min)

| Host | Mechanism | Inventory |
|------|-----------|-----------|
| lastminute.be | `/s/tsx` params accepted; origin defaults LON; dates snap | Empty (3 probes) → cap abandon |
| nl.lastminute.com | Same engine; origin AMS ok | Empty |
| sunweb.be | AI/UA codes; date range widens; Participants date bug confirmed | **Populated** (prices) |
| corendon.be | URL stable; destination param ineffective | **Populated** |

- shortlist_count = **0** (correct for recon).
- Report = `RECON_COMPLETE` + host_learnings (correct).
- Phase 2 skipped due to empty shortlist (recon quirk: skip logic is research-oriented — improve later).
- Agent still produced a rich mechanism summary in the LLM turn; critic used host_learnings file.

**Decision:** recon mode is valid. Next: internal recon without hotel-specific task.md; persist richer recipe fields (value codes, ignored params).

---

## Mechanisms tried / status

| Mechanism | Status | Notes |
|-----------|--------|--------|
| Soft constraint mismatch | **Keep** | Soft when prices present |
| Param warnings + strip | **Keep** | Sunweb participants |
| Empty-inventory cap (3) | **Keep** | Stops lastminute thrash |
| Memory-first (no root open) | **Keep** | |
| Cookie dismiss + iframe hide | **Keep / extend** | |
| `--run-kind recon\|research` | **Keep** | Code-enforced shortlist block |
| Harvest & hydrate (list → JSON → agent picks) | **Planned** | Biggest yield lever |
| Schema URL builder | **Later** | Light guards first |
| GUI-VLM one-shot recon | **Later** | Only if Playwright stuck |
| Parallel same-query runs | **Abandoned** | Wasteful for this use case |
| Hardcoding Sunweb/TUI steps in agent | **Rejected** | Task/memory only |

---

## Open follow-ups

1. **Recon without task.md** — `--run-kind recon --hosts h1,h2` or auto from research primary sources.
2. **Recon phase-2 skip** — don’t use “empty shortlist” skip in recon; optional single phase only.
3. **Persist recon findings** beyond url_patterns (ignored params, value enums, inventory_ok flag).
4. **List harvest** on Corendon/Sunweb result pages in research mode.
5. **Ollama 500** — continue shorter tool results + earlier complete; eval metrics later.

---

## How to read this log later

- If a technique is **Abandoned** / **Rejected**, do not reintroduce without new evidence.
- Prefer updating this file after each meaningful run with: metrics (duration, shortlist_count, useful_ratio) + one-line lesson.

## 2026-08-22 — Web policy + harvest quality + honest ranking

### Ethics / safety
- Removed Playwright anti-detect (`AutomationControlled`, `navigator.webdriver` override, fake plugins).
- Browser remains a normal Chromium automation client (Chrome-like UA kept; not stealth).
- CAPTCHA / bot-wall signals → `policy_stop` + host abandoned for the session; no bypass.
- New `web_policy.py`: thin gate before fetch/browser with rolling per-host hourly budgets and cooldown after 403/429/CAPTCHA. State in `memory/domain_policy.json`.

### Harvest / ranking
- Stricter structural entity score (ALL-CAPS labels, distance crumbs, short-token UI lines).
- Promote thresholds: entity_score ≥ 0.55, confidence ≥ 0.62, ≥ 2 tokens.
- `query_state_mismatch` → `rankable=false` (kept for transparency, excluded from ranking).
- Forced report instructed to rank only rankable items; no “meets hard criteria” for partial/unverified AI/pax.

### Not done (intentionally)
- Full robots.txt engine / whitelist-only mode.
- Site-specific product word lists.

---

## 2026-08-23 — Retrieval naming + shortlist purity + harvest gates

### Naming
- Whole system = **research agent**.
- Delivery web phase = **retrieval** (`--run-kind retrieval`; `research` kept as alias).
- Docs/CLI updated so we stop calling the narrow web phase “research”.

### Shortlist purity (generic)
- Query-state mismatch pages → **observations only**, never `add_to_shortlist`.
- Stronger slogan/marketing structural penalty (`!`, guaranteed-shape, promo calendar openers).
- Promote thresholds: entity_score ≥ 0.62, confidence ≥ 0.72, marketing_penalty < 0.30.
- Shortlist = candidate evidence buffer; observations = raw layer.

### Harvest process (unchanged architecture, clearer contract)
- **100% runtime code** (no LLM in extract/promote).
- Pipeline: page text → EAV observations → gated promote → shortlist → critic.
- No product-vertical word lists; structural signals only.
- Next (not in this patch): structure-aware clusters (cards/tables/lists) as extraction strategies; optional small model only on ambiguous pairs.

### Metrics note
- Prefer `rankable_count`, `candidate_precision`, constraints satisfied over raw `useful_action_ratio`.

### Explicitly not done
- Inline auto-recon loop on `needs_recon` during retrieval (still separate `--run-kind recon`).
- Card-first as the only strategy (avoid new false primitive).

---

## 2026-08-23 — Structure-aware harvest + line-item gate + inline recon skeleton

### Harvest
- Cluster lines into local blocks; entity↔price pairing prefers **same cluster**.
- Structural **line-item / SKU** gate (`1 × 2-persoonskamer`, room config) → never top-level shortlist.
- Amenity chrome (`Luchthaventransfer inbegrepen`) demoted as entity.
- EU thousand separators: `€2.328` → 2328 (was misread as 2.328 → noise).

### Inline recon skeleton
- On retrieval structural mismatch: pause host UI → `run_inline_recon_burst` (memory only).
- No shortlist writes; retrieval LLM does not see recon transcript.
- If recon clears `needs_recon`, one deep-link retry allowed.

### Still open
- Location-vs-hotel title disambiguation on list pages.
- Full relationship graph (price vs discount vs nights) beyond cluster pairing.

---

## 2026-08-23 — PageState + eligibility + harvest subscores (post run 10-07-03)

### Run lesson
- Navigation OK; yield limited by **state → relations → eligibility**.
- Sunweb: URL rewrite → needs_recon; inline recon must **not** clear on price_hints alone.
- Corendon: LLM found Grand Park Lara; harvest promoted **“Balkon of terras (zitje)”** as rankable — fixed by eligibility + line-item region gate.
- Memory `harvest=1` from price_signals alone was too optimistic.

### Implemented
- **PageState** (`build_page_state`): match full|partial|mismatch|unknown; `usable_for_task`.
- Mismatch / unusable pages → observations only, no rankable promote.
- **Eligibility**: `observed_only` never rankable; scope element/filter; amenity/parenthetical feature labels blocked.
- Auto-harvest writes `eligibility=ineligible`, `rankable=False`.
- **Inline recon**: clear `needs_recon` only without severe date/occupancy rewrite.
- **Harvest memory**: `relationships_extractable` + success/failure counts; capability score no longer treats price_signals as full harvest.

### Still open
- List-page structure (hotel title vs location vs filter chrome) for higher recall without LLM.
- UI occupancy vs URL adults (Corendon “2 Personen” while URL says 3).
- Multi-confidence fields on evidence (entity/value/relationship/state).

---

## 2026-08-23 — Evidence multi-confidence + harvest subscore feedback loop

### Contract refinement (ChatGPT review → implement)
- Evidence now carries `confidence_breakdown`: entity / value / relationship / state / overall.
  - Keeps overall for legacy thresholds; breakdown supports future critic weighting.
- `page_state_ref` remains on every promoted evidence row.
- Agent → memory: after harvest, set `relationships_extractable` from outcome:
  - promote ≥1 → partial|ok + success
  - `page_state_not_usable` → failed + not success
  - observations only → partial
- `harvest_invariant` always carries `skipped_reason` / `page_state` when relevant so learning sees the gate.

### Docs
- METHODOLOGY §4b expanded to full minimal contract: PageState schema, Evidence schema, ConstraintResult vs Eligibility, harvest capability subscores, invariants.

### Still open
- List-page structure (hotel title vs location vs filter chrome) for higher recall without LLM.
- UI occupancy vs URL adults (Corendon “2 Personen” while URL says 3).
- Critic using confidence_breakdown (optional; thresholds still use overall).

---

## 2026-08-23 — Iter 1+2: page_role + evidence scope + layer dataflow

### Trigger
Run 12-33-37: shortlist=25, rankable=1, precision=0.04. Diagnosis: different semantic objects (destination cards, chrome, related hotels, real offers) shared one buffer — not only a weak extractor.

### Iter 1 — Page role + evidence scope
- `infer_page_role` / `PageState.page_role`: `unknown | landing | list | detail` (structural path/query/title; unknown valid).
- Evidence **scope**: `primary | group | related | chrome | element`.
- chrome / related / element → observations only (no evidence-buffer promote).
- landing → no promote (`skipped_reason=page_role_landing`).
- detail low entity_score → `related` (neighbor cards).

### Iter 2 — Hard dataflow
```
observations → evidence (layer=evidence) → ConstraintResults → eligibility → ranked
```
- `evidence.jsonl` parallel store for gated primary/group rows.
- Harvest always `layer=evidence`, `eligibility=ineligible`, `rankable=false`.
- LLM adds default `layer=candidate`.
- `compute_rankable`: blocks layer=evidence, scope chrome/related/element, landing harvest rows.
- Shortlist prompt shows evidence_layer vs rankable counts.

### Explicitly not in this patch
- value unit/qualifier schema (iter 3)
- depth/control budget (iter 4)
- tighter entity_score / harvest precision (iter 5)
- LLM-as-eligibility-decider (rejected; policy over ConstraintResults)

### Genericity
Harvest still reconstructs entity↔value structure only — no product-vertical word lists. Same contract for any list/detail surface.

## 2026-08-23 — Progress-aware control (opt 1)

### Trigger
Retrieval run 13-24-22 (~11 min): useful list harvested on lastminute.be, then repeated clicks → timeout → host abandon; Sunweb same pattern. Control loop, not harvest, was the operational bottleneck. ChatGPT helicopter view: progress first-class, not fixed click caps; no more page_role taxonomy growth.

### Hypothesis
If each browser action records a **progress delta** (state / evidence / candidate / constraint) and consecutive zero-progress actions abandon the host, runs stop thrashing the same surface after yield is exhausted.

### Shipped
- `_record_progress` / `_maybe_abandon_zero_progress` in `agent.py` (per session).
- Progress event fields: `state_changed`, `evidence_added`, `candidate_added`, `constraint_improved`, `had_progress`, `zero_progress_streak`.
- Config: `limits.max_zero_progress_per_host` (default 2, same scale as no-ops).
- Metadata: `progress_events`, `progress_hits`, `progress_ratio`.
- Tool results expose compact `progress` so the LLM sees stagnation.
- Classic no-op (URL + price_hints) retained; progress is stricter (hints alone without state/evidence do not keep the host open indefinitely).
- Docs: METHODOLOGY §4c, this log entry, README bullet.

### Explicitly not in this patch
- Subject/group containment model (opt 2 / structure)
- Extra page_role values
- Site-specific harvest regex / marketing word lists
- Semantics requested/observed/interpreted object (follow-up)

### Expected test signal
Re-run `compare_packages_dec2026` with playwright: after one successful Mijas list harvest, further clicks with no new evidence should hit zero-progress abandon faster; more budget left for other hosts; `progress_ratio` visible in metadata.

## 2026-08-23 — A′ control refinement + B structure skeleton

### Trigger
ChatGPT review after progress-control run 13-56-14: control and structure are coupled; `memory_updated` is not retrieval progress; need `observation_delta`; stop rule should be diminishing returns (repeated same state/action), not a pure counter; structure (subject+groups) must follow immediately — not more harvest micro-tuning.

### Hypothesis
If progress is defined as state/information deltas (including first-time observations and mismatch discovery) and repeated same-surface actions cost extra, the agent stops when marginal information value is low. Attaching a structural skeleton (primary_subject + groups, kind=unknown) makes those deltas and later eligibility meaningful without verticalising.

### Shipped (A′)
- `_record_progress`: removed `memory_updated`; added `observation_delta`.
- Progress = `state_changed | observation_delta | evidence_added | candidate_added | constraint_improved`.
- Diminishing returns: same `(tool, url_key)` with no delta increments streak by 2.
- `needs_recon` on zero-progress abandon only if host never yielded evidence this session; otherwise `interaction_blocked` (list already useful).
- First harvest per URL key and constraint-mismatch discovery count as observation progress.

### Shipped (B)
- `build_page_structure()` in `storage.py`: `primary_subject { id, label, kind: "unknown" }` + `groups[]`.
- Attached to `PageState.structure` inside harvest; evidence rows get `structure_ref`.
- No new page_role values; kind never gates promotion.

### Explicitly not in this patch
- Semantics requested → observed → interpretation{result,confidence,support}
- Subject_kind inference for location vs offer cards
- Cross-subtask interaction memory (verify-only opens)
- Site-specific extractors

### Expected test signal
Re-run retrieval: progress log shows `obs=+N`; repeated clicks on same list surface abandon faster with weight≥2; hosts that already produced evidence are abandoned without `needs_recon`; `page_state.structure.groups` present on list harvests.

---

## 2026-08-23 — Minimal Awareness Context + structure-first promote

### Trigger
Helicopter review (ChatGPT + internal): “Maximum Awareness” (DOM+AX+OCR always) is the wrong cost model. Latest retrieval run still had list surfaces with observations but weak/empty auto-promote; LLM hand-picked the one rankable candidate. Control (A′) and structure skeleton (B) were necessary but not sufficient — evidence units were still free-floating EAVs.

### Principle shift
**Minimal Awareness Context (MinAC)** replaces any “gather everything” instinct:

- Collect only the structural dimensions needed to evaluate task constraints without inventing facts.
- Dimensions: `page_usable`, `subject_identity`, `primary_values`, `entity_value_link`.
- Status: `adequate` | `partial` | `insufficient`.
- `insufficient` → observations only (same fail-closed family as mismatch / landing).

Perception cascade (DOM → AX → screenshot/OCR) remains a **future escalation ladder**, not the default. Current MinAC is filled from Playwright text harvest.

### Structure-first evidence units
- `structure.members` is the promote source on list/detail (entity already paired with primary value).
- Chrome/amenities that pass isolated entity_score but are not structure members stay out.
- Soft score floors for confirmed members; classic high thresholds remain as fallback only when structure is empty.
- `extraction_method`: `structure_member` vs `eav_cluster`.

### Explicitly not in this patch
- AX tree / OCR / VLM perception backends
- Task-parsed required-observable lists (can layer later on MinAC gaps)
- Vertical kind inference (kind stays `unknown`)
- Site-specific card selectors

### Expected test signal
List harvest on populated hosts: `page_state.awareness.status` ∈ {partial, adequate}; `promoted` tracks structure members; chrome entities no longer dominate shortlist; empty/mismatch hosts still `awareness=insufficient` / observations only.

---

## 2026-08-23 — Member admissibility (iteration A)

### Trigger
Run 22-07-41 after MinAC: structure-first + adequate awareness, but shortlist still held destination cards (Gran Canaria), CTAs (Pakket bekijken), amenities (3 kleine tassen). Case B: entity↔value true → MinAC adequate → false evidence unit.

### Principle
Four separate epistemic questions:
1. **Admissibility** — may this object be evidence at all?
2. **MinAC** — do we know enough?
3. **Constraints** — does it match the request?
4. **Eligibility** — may it rank?

Admissibility is **not** a MinAC dimension. Task constraints stay out of both.

### Shipped
- `assess_member_admissibility()` with features + `reject_reason` codes
- `build_page_structure`: candidates → admissibility → `members` (accepted only) + `rejected_members` + `admissibility_stats`
- Generic signals: CTA shape, unit/amenity, type-label, dest/geo card without property body, schema outlier vs cohort
- No AX/OCR/LLM; no host routing; no new harvest score layer

### Explicitly not in this patch
- Frontier host switch on constraint-unmatched
- Perception cascade
- LLM on uncertain members

### Expected test signal
Same retrieval task: Gran Canaria / Pakket bekijken / Personaliseer / Appartement / amenity lines in `rejected_members` with reason codes; hotel-shaped rows in `members`; higher candidate_precision; MinAC still adequate on real offer lists.

---

## 2026-08-24 — MEMBER_ROLE experiment v0 (isolated)

### Why
Iteratie A (admissibility) reduced geo/CTA noise but remaining Case-B and vertical enums
(`TARGET_OFFER`) are not generic. Architecture direction: code driver + typed LLM only
on UNCERTAIN.

### Shipped
- `docs/DECISION_MEMBER_ROLE.md` — structural roles TARGET|NAVIGATION|ACTION|FRAGMENT|CHROME|UNKNOWN
- `evals/member_role_golden.jsonl` — 20 labeled members from runs
- `member_role.py` — deterministic-first → optional LLM (`MEMBER_ROLE_LLM=1`) → fail-closed UNKNOWN
- `build_page_structure` wires resolve_member_role + telemetry

### Golden (deterministic only)
accuracy 19/20 (0.95). Miss: "Mijas Costa·…·Bekijk op kaart" accepted as TARGET (chrome glued into entity string).

### Enable LLM path
`MEMBER_ROLE_LLM=1` plus inject chat_fn in resolve (not wired to Ollama in harvest path yet — next small step).

---

## 2026-08-24 — Contract Discovery v0 (isolated, no pipeline change)

### Why
Run `2026-08-24T08-01-36`: rankable=0, candidate_precision=0.0, but admissibility/member_role
correctly rejected geo/CTA noise and accepted hotel-shaped TARGET rows. Bottleneck is no longer
harvest chrome — it is **task-specific semantics** (board_type, detail_link, price_scope) and
eligibility. Fixed MEMBER_ROLE ontology is still vertical bias for non-shopping tasks.

### Architecture shift (agreed)
- Meta-schema fixed in code; LLM fills content only
- Contract Discovery → (later) FREEZE → typed decision execution
- MEMBER_ROLE remains a feature layer, not the permanent ontology
- Success criterion: contract **explains** zero-rankable (names missing decisions)

### Shipped
- `contract_discovery.py` — schema, validate, surface selection, discover, gap analysis
- `scripts/run_contract_discovery_v0.py` — CLI + fixture
- `docs/DECISION_CONTRACT_DISCOVERY.md`

### Not shipped
- Live pipeline wiring, FREEZE loop, SPEC_GAP auto-patch, multi-host convergence

### How to test on host
```bash
python scripts/run_contract_discovery_v0.py --fixture
python scripts/run_contract_discovery_v0.py \
  --run-dir runs/2026-08-24T08-01-36_compare_packages_dec2026
# optional:
python scripts/run_contract_discovery_v0.py --run-dir PATH --llm
```

---

## 2026-08-24 — Contract Execution v0.1 (generic decision executor)

### Hypothesis
LLM/heuristic contract supplies evidence_signals; domain-agnostic executor emits
PASS|FAIL|UNKNOWN|SPEC_GAP without `if decision_id == ...`.

### Shipped
- `contract_discovery.py` schema **0.2** + `evidence_signals` validation + heuristic signals
- `decision_executor.py` — generic pattern match, item-local evidence, optional LLM on UNKNOWN
- `scripts/run_contract_execution_v0.py`
- `evals/decision_oracle_packages_v0.jsonl` (14 cells)
- `docs/DECISION_CONTRACT_EXECUTION.md`

### Fixture GO metrics
- oracle_accuracy **1.0**, false_pass **0**, blocker_recall **1.0**, spec_gap_rate **0**
- board_type ROOM_ONLY on "Enkel kamer"; detail_link ABSENT on `/s/tsx`; Gran Canaria NOT_TARGET

### Not shipped
Live agent wiring, FREEZE, contract patch, rankable policy.

---

## 2026-08-24 — Evidence channels v0.2 / contract schema 0.3

### Lesson from LLM execution run
false_pass: Gran Canaria board_type=ALL_INCLUSIVE because `meal=all-inclusive`
lived in source_url, merged into one evidence blob.

### Change
- `build_evidence_channels()` splits candidate_claims / search_context / navigation / page_context
- signals may set `evidence_channels`; default = candidate_claims only
- discovery prompt + heuristic schema 0.3 require channel discipline
- oracle soft-align ABSENT ↔ SEARCH_LIST_ONLY

### GO still offline
false_pass=0 is the gate before second domain or live wiring.

---

## 2026-08-24 — Interpretation v0

### Shift
evidence_signals proved generic execution is possible but encode meaning as
patterns. Product direction: Interpretation LLM → normalized outcome; code only
gates outcomes against the contract.

### Shipped
- `interpretation.py` — interpret_observation + execute_normalized
- `evals/interpretation_board_type_golden.jsonl`
- `scripts/run_interpretation_v0.py`
- `docs/DECISION_INTERPRETATION.md`

### Next
`--llm` golden run → if GO, same binary on a literature snippet set (no core change).

---

## 2026-08-25 — Observation provenance v0.2

- Contract: `docs/OBSERVATION_CONTRACT.md` (text/channel/scope/provenance; no outcomes).
- Builder: `observation_builder.py` — notes **off** by default; card_texts / url_query / chrome explicit.
- Fixture test: `scripts/run_observation_provenance_v0.py` + `evals/observation_provenance_fixture_v0.json`.
- Result: **GO=True** — card vs search_context vs chrome separated; no cross-candidate leak; no semantic fill.
- Next: map existing run artifacts → card_texts if present; one vertical slice.

## 2026-08-25 — raw_evidence → observations

- Extended `observation_builder.py`: `split_raw_evidence`, `observations_from_harvest_row`,
  `build_from_observations_jsonl`, `build_from_run_dir_rich`.
- Literal `|` split only; chrome literals → page_chrome; URL meal= → search_context.
- Script: `scripts/run_observation_raw_evidence_v0.py`.
- On pasted harvest JSONL: GO=True, Sercotel gets "Enkel kamer" + flight text as candidate_claim.
- Notes still off. No semantic outcomes in builder.

## 2026-08-25 — Vertical slice v0

- `scripts/run_vertical_slice_v0.py`: harvest observations → builder → interpret_observation
  (board_type + package_includes_flight) → AND eligibility.
- Channel filter: only candidate_claim for those decisions; meal= search_context excluded.
- Primary case: Sercotel (Enkel kamer + flight text) → expect not eligible under required AI.
- Dry-run GO (UNKNOWN fail-closed + search_context not fed). Full GO needs `--llm`.

---

## 2026-08-25/26 — Candidate selection campaign (structural vs LLM)

**Hypothesis:** Compare S0 structural, S1 heuristics, S2 LLM-raw, S3 LLM-grounded, S5 hybrid for *candidate selection* across web/literature/code/documents pilots.

| Method | Avg R (4 domains) | Notes |
|--------|-------------------|--------|
| S3 grounded | **1.0** | Neighbors/element_type/provenance matter |
| S0 structural | 0.875 | Weak on documents |
| S5 hybrid | 0.875 | Loses docs recall to aggressive long-phrase prefilter |
| S1 heuristics | 0.75 | Long-phrase harms content units |
| S2 raw | 0.625 | **Web R=0** — hotel name alone insufficient |

**Decisions:**
- Treat structure as **context provider**, not universal candidate classifier.
- Do not expand phrase-based admissibility as product architecture.
- Prefer **grounded LLM (S3)** as selection hypothesis.
- **Do not** add semantic “obvious chrome” prefilters in code (see ground rule).
- Next science: **Contract Discovery modes CD0/CD1/CD2**.

**Code:** `candidate_selection/`, `scripts/run_candidate_selection_*.py`; results under `evals/candidate_campaign/`.

---

## 2026-08-26 — Ground rule locked + CD pilot complete

### Ground rule (docs/ARCHITECTURE_JOURNEY.md §2)

```text
CODE describes  |  LLM interprets  |  CODE enforces
```

Anti-pattern: “code removes obvious semantic garbage before LLM.” That *is* interpretation. Mechanical facts only in code; meaning only via LLM unless proven deterministic (404, empty field, no DOM delta).

### Contract Discovery pilot `20260826T072909Z_pilot`

| Mode | packages | literature | jaccard (CD2) |
|------|----------|------------|---------------|
| CD0 | 8 dec, ~39s, sparse signals | 5 dec, ~33s, sparse signals | — |
| CD1 | 9 dec, ~85s, full signals + surface gaps | 6 dec, ~85s | — |
| CD2 | 9 dec, ~124s, +filter_reliability | 5 dec, ~88s | 0.89 / **1.0** |

- **6/6 jobs DONE**, validation_ok=1.0 all modes (after normalize + soft validation).
- Wall time **~7–8 min**, not hours (1–2 LLM calls × 6 jobs).
- CD0: valid provisional *without* samples; `missing_to_solve` is hypothesis-level.
- CD1: best **sample-grounded** explanation of zero-rankable (Enkel kamer vs meal=filter; placebo vs standard care).
- CD2: **stable decision ids**; refine mainly names subject + adds sample-driven gaps/decisions; not a full rewrite.
- CD0 literature vs packages heuristic cross-jaccard=0 is expected (domain-wrong baseline comparison).

**Not learned yet:** freeze policy (when to stop refining); live wiring discovery→execution.

**Scripts:** `run_contract_discovery_mode_v0.py`, `run_contract_discovery_campaign_v0.py`.

---

## 2026-08-26 — Grounding ablation campaign v0 (results)

**Hypothesis:** which context (task / neighbors / structure / provenance) does
candidate interpretation need?

**Run:** `evals/grounding_ablation/20260826T080416Z_full` — **24/24 DONE**, flush on.

| Variant | Web R | Lit R | Code P | Docs | Note |
|---------|------:|------:|-------:|------|------|
| A0 text only | 1.0 | 1.0 | 0.67 | ok | Code: `format_price` FP without task |
| A1 +neighbors | 1.0 | 1.0 | 0.67 | ok | Same code FP |
| A2 +structure | 1.0 | 1.0 | 0.67 | weaker | Structure ≠ semantic classifier |
| A3 +provenance | 1.0 | 1.0 | **1.0** | ok | Path/url strong grounding |
| **A4 task+text** | **0.0** | **0.5** | 1.0 | ok | **Critical failure** |
| **A5 full** | **1.0** | **1.0** | **1.0** | ok | Best overall |

**Core finding (A4):**

```text
task + bare hotel title  →  NOT_ADMISSIBLE
```

The LLM treated the task as a **completeness checklist** (“no price/board/flight visible → reject”)
instead of a **relevance filter**. That confuses:

```text
CANDIDATE:   "could this be a useful evidence unit?"
ELIGIBILITY: "are hard constraints already proven?"
```

A5 recovers because neighbors/provenance show card body (price, board, flight) —
and because the unit’s *role* becomes clear.

**Other lessons:**
- Task is still needed for **precision** on code (auth vs `format_price`).
- Provenance alone is a strong signal on this pilot (not claimed universal).
- Structure remains grounding, not a universal candidate classifier.
- Small n (4–8/domain) → directional evidence, not production claim.

**Decision:** next experiment isolates the **prompt question** (candidate vs eligibility),
not more board/hotel heuristics.

**Scripts:** `run_grounding_ablation_*.py` · **Module:** `candidate_selection/grounding_ablation.py`

---

## 2026-08-26 — Next: Candidate vs Eligibility prompt-split v0

**Hypothesis:** If the LLM is asked the **CANDIDATE_UNIT** question explicitly
(incomplete OK), web RELEVANT titles recover under `G_task_text` and `G_full`,
while code precision stays high. **ELIGIBILITY_COMPLETE** should stay strict
(low relevant_recall on incomplete units).

| Factor | Values |
|--------|--------|
| Decision mode | `CANDIDATE_UNIT` vs `ELIGIBILITY_COMPLETE` |
| Grounding | `G_task_text` (A4-shaped) · `G_full` (A5-shaped) |
| Datasets | web_travel, literature, code, documents |

**Primary metric:** per-domain `relevant_recall` and  
`delta = CU_relevant_recall − ELIG_relevant_recall`  
(expect large positive delta on web under `G_task_text`).

**GO (scientific, not averaged):**
- web + `G_task_text`: delta > 0.5 and CU relevant_recall ≥ 0.75
- code + `G_full`: CU precision stays high (task still filters off-topic)

**Isolation:** same as ablation (subprocess, keep_alive=0, optional flush).

**Scripts:** `run_candidate_vs_eligibility_experiment_v0.py`,  
`run_candidate_vs_eligibility_campaign_v0.py`  
**Module:** `candidate_selection/candidate_vs_eligibility.py`

```bash
# smoke offline
python scripts/run_candidate_vs_eligibility_campaign_v0.py --campaign smoke \
  --outdir ./evals/candidate_vs_eligibility

# full LLM (2 modes × 2 groundings × 4 domains = 16 jobs)
python scripts/run_candidate_vs_eligibility_campaign_v0.py --campaign full --llm \
  --outdir ./evals/candidate_vs_eligibility --max-hours 6 --flush-between-jobs
```

---

## 2026-08-26 — Candidate vs Eligibility campaign (results)

**Run:** `evals/candidate_vs_eligibility/20260826T104655Z_full` — **16/16 DONE**.

| Domain | CU relevant_R | ELIG relevant_R | Δ |
|--------|-------------:|----------------:|--:|
| **web** | **1.0** | **0.0** | **+1.0** |
| **literature** | **1.0** | **0.0** | **+1.0** |
| code | 1.0 | 1.0 | 0 |
| documents | 1.0 | 1.0 | 0 |

**GO criteria met:** web Δ=+1.0 with CU≥0.75; code CU precision=1.0.

**Causal example (web G_task_text):**
```text
"Grand Park Lara All Inclusive Resort"
  CANDIDATE_UNIT      → ADMISSIBLE  (hotel name can be evidence unit; incomplete OK)
  ELIGIBILITY_COMPLETE → NOT/UNKNOWN (price/party/dates not on this fragment)
```

**Lessons locked:**
1. A4 failure was the **wrong question**, not “too little text”.
2. Candidate and eligibility are **empirically different operations** — never one LLM step.
3. Code/docs Δ=0 is expected: self-contained units satisfy both questions.
4. Literature CU P≈0.67 (keywords FP) is acceptable residual; do **not** harden candidate back into eligibility.
5. Product eligibility remains **code** on normalized outcomes; ELIGIBILITY_COMPLETE mode was diagnostic only.

**Decision:** stop further isolated candidate/eligibility prompt experiments.
**Next:** offline end-to-end pipeline (observation → CANDIDATE_UNIT → interpretation → code eligibility) with staged metrics.

---

## 2026-08-26 — Next: Offline pipeline v0

**Hypothesis:** chaining proven layers yields correct eligibility on package fixtures
without domain heuristics in code.

```text
fixture / observations
  → CANDIDATE_UNIT (LLM, optional gate)
  → INTERPRETATION (LLM, candidate_claim only)
  → ELIGIBILITY (code AND)
  → staged metrics
```

**GO:** positive AI-card eligible; Sercotel/breakfast not; search_context never boards AI; no marketing eligible.

**Scripts:** `run_pipeline_offline_experiment_v0.py`, `run_pipeline_offline_campaign_v0.py`
**Module:** `pipeline_offline.py`

---

## 2026-08-26 — Offline pipeline pilot (results)

**Run:** `evals/pipeline_offline/20260826T114225Z_pilot` — 2/2 DONE.

| Fixture | n | match_rate | pos | neg | search_leaks | GO |
|---------|---|------------|-----|-----|--------------|-----|
| batch | 10 | **1.0** | 2/2 | 8/8 | **0** | True |
| positive (pre-fix) | 3 | n/a (missing oracle labels) | — | — | 0 | True* |

**Causal chains verified:** Grand Park / Blue Bay → eligible; Sercotel (Enkel kamer + meal= URL) → not eligible, board UNKNOWN, search_context skipped; marketing CU=NOT_ADMISSIBLE.

**Lesson:** full semantic chain works on controlled fixtures. Next risk is **real harvest observations**, not more board synonyms.

**Fixes applied after pilot:**
- `vertical_slice_positive_fixture_v0.jsonl` now has `expected_eligible` / `expected_role`
- `go_no_go(..., require_oracle=True)` invalidates empty-oracle scored runs
- `run_pipeline_from_run_v0.py` + campaign `--campaign from_run`

```bash
python scripts/run_pipeline_offline_campaign_v0.py --campaign from_run --llm \
  --run-dir runs/2026-08-24T08-01-36_compare_packages_dec2026 \
  --outdir ./evals/pipeline_offline --flush-between-jobs --max-hours 6
```

---

## 2026-08-26 — Pipeline from real run (results)

**Run:** `evals/pipeline_offline/20260826T123947Z_from_run`  
**Source:** `runs/2026-08-24T08-01-36_compare_packages_dec2026` (360 observations → 15 candidates)

| Metric | Value |
|--------|-------|
| CU admitted | 11/15 (73%) |
| **eligible_n** | **0/15** |
| Oracle negatives | 3/3 correct not-eligible |
| search_context → board leaks | **0** |
| LLM calls | 169 |

**What held:** full semantic chain on messy harvest is **fail-closed and leak-free**.  
Hotels can be ADMISSIBLE while board stays UNKNOWN → not eligible. Chrome often NOT_ADMISSIBLE.

**What failed (by design):** zero rankable packages — harvested **card text** had no trustworthy ALL_INCLUSIVE claim (mostly `Enkel kamer`, destinations, marketing slogans). URL `meal=all-inclusive` correctly stayed search_context.

**Architectural localization:** bottleneck is **observation / evidence acquisition** (retrieval page coverage and/or extractor binding), **not** candidate/interpretation/eligibility code.

**Do not fix with:** board synonyms, URL→board, admissibility heuristics.

**Next:** Positive Evidence Trace v0 — for 1–3 hand-verified AI offers, mark PRESENT/ABSENT at stages A–F (site → raw harvest → observation → CU → interp → eligibility).

---

## 2026-08-26 — Positive Evidence Trace v0 (Test A/B built)

| Decision | Why |
|----------|-----|
| **List/card price ≠ offer evidence** | Sites show “vanaf” prices before date/board/party selection; claiming budget/board from list alone is unsafe |
| **Evidence scopes** | `detail_page` (direct AI text) vs `booking_state` / offer selection vs `search_list` incomplete |
| **Ultra AI** | LLM maps “Ultra All Inclusive” → `ALL_INCLUSIVE` under contract; no Python synonym table |
| **Trace A→F** | Localize loss: site → retrieval → page/state → observation → CU/interp → eligibility |

**Fixtures shipped**

- `evals/detail_evidence_fixture_v0.jsonl` — Costa Calma, Monica Beach, IVI Mare (simulated **successful** detail harvest)
- `evals/offer_state_fixture_v0.jsonl` — Playa Park **selected** AI offer vs hotel-level options only vs vague list price vs Sercotel Enkel kamer
- `evals/positive_evidence_trace_oracle_v0.jsonl` — hand-verified URLs (unchanged)

**Code shipped**

- `positive_evidence_trace.py` — stage D literal checks + fault localization + pipeline reuse
- `scripts/run_positive_evidence_trace_v0.py`
- `scripts/run_positive_evidence_trace_campaign_v0.py` — smoke / detail / offer_state / full

**What this test proves / does not prove**

| Proves (when LLM GO on detail fixture) | Does **not** prove |
|----------------------------------------|--------------------|
| If observations contain board+flight literals, D→F can yield eligible | Live retrieval opened those detail pages |
| Incomplete list / unselected hotel options stay not eligible | Agent navigates to price-calculation state |
| search_context still cannot sole-source board | Production memory/deep URL already does this |

**Still required after offline GO:** controlled live harvest of the oracle `detail_url`s (and later booking-state stop-before-book) into a run-dir, then same pipeline — that is stages **B/C**.

**Ground rule reminder:** Code describes surfaces/state; LLM judges “complete offer vs incomplete list”; code enforces eligibility. No “obvious garbage” semantic prefilter in core.

---

## 2026-08-26 — Live detail slice + Run Ledger v0 (built)

After fixture evidence-trace GO (detail + offer_state, 7/7 fault=none):

| Built | Role |
|-------|------|
| `run_ledger.py` | Side-branch telemetry: actions, observations, decisions, stop_reason — no live self-train |
| `live_detail_slice.py` | OPEN oracle `detail_url` → literal page lines → frozen CU/interp/eligibility → A–F with **LIVE** B/C |
| `scripts/run_live_detail_slice_v0.py` | CLI presets: costa_monica, primary_detail, ivi |
| `scripts/run_live_detail_campaign_v0.py` | smoke / pilot / primary / full |

**Hypothesis under test:** real Corendon/Sunweb detail pages contain board+flight literals that the proven D–F chain can consume.

**Not in this slice:** free multi-step booking-state navigation (Playa Park price calculation) — next after detail GO.

**stop_reason examples:** `ALL_REQUIRED_OUTCOMES_PROVEN`, `EVIDENCE_UNAVAILABLE_BOARD`, `FETCH_FAILED_OR_EMPTY`, `BOT_WALL_OR_POLICY`.

---

## 2026-08-27 — Evidence acquisition + live offer-state slice (built)

### Ground rule (reaffirmed)

- Code **observes** structure, affordances, provenance; enforces enums, max depth, irreversible blocks.
- LLM **interprets** meaning (board/flight/…) and may **propose** next action only from **observed** affordances.
- **No** core hardcoding of “on Corendon click Prijzen & boeken” as product policy.
- Lab presets may pass `force_click_texts` as **experiment parameters** only (visible labels under test).

### Why

Live detail pilot: Monica could reach eligible; Costa often `E_flight_UNKNOWN` on first detail state. Human inspection showed richer flight/price/board in **price-calculation / selected offer** UI. Need gap-driven deeper exploration without vertical scrapers.

### Shipped

| Module | Role |
|--------|------|
| `evidence_acquisition.py` | `gaps_from_eligibility`, safe affordances, enum `ACTION_CLASSES`, `acquisition_decide` (LLM or fail-closed), `execute_acquisition_action` |
| `browser.browser_list_affordances` | Visible links/buttons/tabs only (structural) |
| `live_offer_state_slice.py` | OPEN → observe → CU/interp/elig → while gaps: decide → act → re-observe |
| `scripts/run_acquisition_unit_v0.py` | Offline unit tests (no browser) |
| `scripts/run_live_offer_state_slice_v0.py` | Presets: monica_lab, costa_lab, monica_llm, costa_llm, both_lab |
| `scripts/run_live_offer_state_campaign_v0.py` | smoke / lab / llm / full |

### Action enum (closed)

`STOP | OPEN_URL | CLICK_TEXT | CLICK_SELECTOR | SCROLL | WAIT | OPEN_FILE`

`OPEN_FILE` reserved for future FS/xlsx observers; browser path fail-closes.

Irreversible text blocked generically (`Reis boeken`, `Buy now`, checkout, …). **“Prijzen & boeken”** is not treated as irreversible (information UI, not commit).

### Test commands

```bash
# Offline units (always first)
python scripts/run_acquisition_unit_v0.py --out ./evals/live_offer/acquisition_unit_v0.json

# Lab: forced click queue + LLM interpretation (proves deeper state → pipeline)
docker compose run --rm research-agent python scripts/run_live_offer_state_campaign_v0.py \
  --campaign lab --llm --outdir ./evals/live_offer \
  --flush-between-jobs --max-hours 3 --job-timeout-s 7200

# Pure LLM acquisition (no force list) — genericity test
docker compose run --rm research-agent python scripts/run_live_offer_state_campaign_v0.py \
  --campaign llm --llm --outdir ./evals/live_offer \
  --flush-between-jobs --max-hours 3 --job-timeout-s 7200
```

### What success means

| Lab GO | LLM campaign GO |
|--------|-----------------|
| When force path reaches price UI, D–F can use richer literals | Acquisition planner picks observed affordances and improves gaps without site rules in core |

### Not done yet

- FS / xlsx / literature folder observers using same acquisition API
- Wiring into main `agent.py` control loop
- Free multi-site night task + final report schema

---

## 2026-08-27 — Lab + LLM campaign results + TraceSession wired

### Lab campaign (`20260827T080151Z_lab`)

| Job | steps | stop | fault |
|-----|-------|------|-------|
| monica_lab | 0 | ALL_REQUIRED_OUTCOMES_PROVEN | none |
| costa_lab | 1 (force `Prijzen & boeken`) | ALL_REQUIRED_OUTCOMES_PROVEN | none |

Monica: detail page already has board + flight literals → eligible without acquisition.
Costa: step-0 `package_includes_flight=UNKNOWN`; after price-tab surface → `FLIGHT_INCLUDED`.

### LLM campaign (`20260827T064948Z_llm`)

Both monica_llm and costa_llm reported GO / fault=none (durations ~12–39 min). Full affordance + acquisition decisions need TraceSession for post-mortem (why any path chose marketing vs price-tab).

### Design read

Lab results **do not change** TraceSession contract:
- Full affordance lists + `has_prijzen_boeken` flags already anticipated
- URL sequence + surface tag (`live_detail` vs `live_offer_state`) already in provenance
- Acquisition decision + code_policy reject already logged

Trace is the tool to diagnose future LLM wrong-surface choices, not a redesign.

### Shipped this step

| Piece | Role |
|-------|------|
| `trace_session.py` | Already present: events.jsonl, artifacts, audit.md/json, summary |
| `live_offer_state_slice.run_acquisition_loop` | Optional `trace: TraceSession` — observe / affordances / gaps / interpret / eligibility / acquisition / action / stop |
| `run_acquisition_batch(..., trace_root=)` | One TraceSession dir per entity under `trace_root/<entity>/` |
| `run_live_offer_state_slice_v0.py` | `--trace` default on; `--no-trace` to disable; writes `<out>_traces/` |

### How to read a trace

```text
evals/live_offer/<job>_traces/<Entity>/
  meta.json
  events.jsonl          # ordered phases
  artifacts/step_NNN_affordances.json
  artifacts/step_NNN_claims.json
  artifacts/step_NNN_page_text.txt
  audit.md              # human timeline
  summary.json          # url_sequence, affordance_flags, acquisition_decisions
```

Key forensic questions for Costa LLM vs lab:
1. Did step-0 affordances include `Prijzen & boeken`? (`has_prijzen_boeken`)
2. What `action_class` + `target_text` did acquisition choose?
3. Final URL still same-entity tab, or global marketing path (`/voordelen`)?
4. Evidence for `FLIGHT_INCLUDED` bound to which surface/URL?

### Next runs

```bash
# Traced lab (default --trace)
docker compose run --rm research-agent python scripts/run_live_offer_state_campaign_v0.py \
  --campaign lab --llm --outdir ./evals/live_offer \
  --flush-between-jobs --max-hours 3 --job-timeout-s 7200

# Traced pure LLM
docker compose run --rm research-agent python scripts/run_live_offer_state_campaign_v0.py \
  --campaign llm --llm --outdir ./evals/live_offer \
  --flush-between-jobs --max-hours 3 --job-timeout-s 7200
```


## 2026-08-27 — LLM campaign diagnosis + affordance/scope fix

### Campaign result (traced)
- Monica LLM: 0-step GO — detail already had strong `pakketreis met vlucht + deze accommodatie`.
- Costa LLM: 1-step GO — but **false-positive scope**: chose global `ALL INCLUSIVE` → `/vakanties/all-inclusive`, then accepted marketing literals as `FLIGHT_INCLUDED`.

### Root causes (trace-proven)
1. **Affordance extraction**: global `<a>` filled max_items before tabs/buttons; `has_prijzen_boeken=false` while page text contained the tab.
2. **Acquisition**: LLM only saw global menu → chose marketing path.
3. **Provenance**: eligibility accepted cross-entity marketing surface as candidate proof.

### Fix shipped (generic, no Corendon if)
| Change | Module |
|--------|--------|
| Affordance priority: tabs → buttons → local links → global | `browser.browser_list_affordances` |
| `scope` tag: local / global / unknown | same |
| `filter_safe_affordances` ranks local/tab first | `evidence_acquisition` |
| Planner prompt: prefer scope=local | `acquisition_decide` |
| Trace: n_local, n_global, n_tab, local_sample | `trace_session` |
| Surface tag `site_marketing` when URL leaves entity path | `live_offer_state_slice` |

### Expected after re-test
```
Monica: detail → STOP (unchanged)
Costa:  detail → flight UNKNOWN → sees local "Prijzen & boeken" → CLICK → offer state → STOP
```
without site-specific hardcoding.

### Still open
- Hard provenance reject (marketing evidence cannot PASS candidate decisions)
- decision_context artifact per acquisition step
- 5 multi-domain tasks after Costa/Monica regression GO

## 2026-08-27 — Safety + Evidence Integrity (V0.1)

Post successful Costa local-tab run + Monica 0-step.

### Shipped
1. **Hard provenance guard** (`pipeline_offline`)
   - `is_provenance_blocked_for_entity`: surface in {site_marketing, site_wide, global_marketing} OR same_entity_path=False → blocked
   - Blocked claims never sent to interpret LLM; cannot contribute to aggregate PASS
   - Unit: `marketing_only_stays_unknown`, `aggregate_ignores_blocked`

2. **Irreversible expanded** (`evidence_acquisition`)
   - Added: Start boeking/booking, Confirm payment/booking/order, Bevestig betaling/boeking, proceed to checkout
   - Still safe: "Prijzen & boeken", "Vlucht"

3. **Interpret cost control**
   - Priority sort of claims (boardish/flightish first)
   - `max_llm_per_decision=8` + early-stop on high-confidence required outcome
   - Expected wall-time drop: ~12min/page → ~1–2min on local Ollama

4. **Trace decision-context + timing**
   - acquisition events carry known/unknown/actions_sample
   - interpret events: llm_calls, duration_s, provenance_blocked_n
   - timing phase: interpret_llm_s vs wall_total_s
   - audit.md shows both

### Runtime diagnosis (from Monica events)
- Browser OPEN+OBSERVE: ~5.6s
- Interpret: ~737s (30 claims × 2 decisions × local LLM)
- Bottleneck is interpretation fan-out, not navigation.
- Early-stop + priority should cut this by ~5–10×.

### Next after re-test
- 5 multi-domain tasks (vakantie / GPU / 2dehands / literatuur / xlsx)
- Then night campaign with flush-between-jobs

## 2026-08-27 — Sufficiency is contract-driven (not page richness)

### Hypothesis challenge
Monica 0-step GO looked “correct” under fixed experiment outcomes (`ALL_INCLUSIVE` + `FLIGHT_INCLUDED`). Human review: detail still only shows *vanaf*-price and a Fly&Go tip sentence; concrete bookable offer needs availability / price-calc surface. Costa only reached that surface because flight stayed UNKNOWN.

### Decision
- **Not** a Monica special-case fix.
- **Not** hardcoding `property` / `binding` / `offer_state` or `visible_price` / `flight_details` as runtime enums.
- **Yes**: task → LLM contract synthesis defines claims + verification + required set; **code** sufficiency gate decides STOP.
- Experiment fixtures (`PACKAGES_DECISIONS` in live_offer slice) remain **vertical experiment only**, not production ontology.

### Boundary doc
See `docs/FRAMEWORK_BOUNDARY.md` — checklist to avoid sliding back into domain hardcoding.

### Direction
Broaden with many small `task.md` files in batches (web + marketplace + literature + files). Observability across tasks teaches architecture more than further Corendon-only loops. Frequent hosts may later get human API adapters; agent still learns sketches in recon for cheap replay.

## 2026-08-27 — Task batch campaign v0

- `tasks/batch_v0/*.md` — micro-tasks across domains (no fixed outcome enums in files beyond natural language).
- `scripts/run_task_batch_campaign_v0.py` — one job per task.md, flush, timeout, campaign report + traces path.
- Goal: surface contract gaps and premature-stop failures generically.

## 2026-08-27 — Contract synthesis freeze + sufficiency mismatch (02)

### Observation
LLM frozen contracts for batch_v0: 8/8 frozen. Contract **01** (package) uses machine-checkable `sufficiency.required` (`subject_instance = YES`, `price_scope in […]`, …). Contract **02** (property-only) put **prose sentences** in `sufficiency.required`, so outcomes `board_type=ALL_INCLUSIVE` did not satisfy the gate (label_missing).

### Learning
- Gate + 01 behaviour is correct: board alone ≠ package contract.
- 02 failure was representation, not architecture: required must reference **decision ids / outcomes**, not free text.
- Do **not** map prose labels with Python heuristics.
- Fix synthesis prompts (rule 9/10): required only `id` | `id = OUTCOME` | `id in [A,B]`.
- Execution wiring: `run_acquisition_loop(..., frozen_contract=)` → `gaps_from_frozen_contract` + `sufficiency_stop` for STOP (no match_status / shortlist shortcuts).

### Next
Re-synthesize contracts with updated prompts; re-run batch with frozen contracts passed into the loop; read traces for premature vs correct stop.

## 2026-08-28 — Provenance E + soft-fail (list/results admissible)

### Context
After panel_option affordances (C), task 01 reached `/kerstvakantie` with concrete offer cards
(board, price, departure visible). All outcomes stayed UNKNOWN because every observation after
leaving the start path was tagged `site_marketing` + `same_entity_path=False` → hard-blocked
(`provenance_blocked_n=248`). One failed Playwright click on "Zoeken" ended the run with
`ACQUISITION_ACTION_FAILED`.

### Shipped
1. **Surface taxonomy** (`live_offer_state_slice._classify_surface`)
   - `live_detail` / `live_offer_state` / `list_results` / `site_marketing`
   - `list_results` when page has multi-item price-like density (generic €/$/p.p./from/va patterns)
   - `site_marketing` only when path left start entity **and** no dense item evidence
   - No host- or site-specific path strings

2. **Provenance gate** (`pipeline_offline.is_provenance_blocked_for_entity`)
   - Blocks only explicit marketing/chrome surfaces
   - **No longer** hard-blocks solely on `same_entity_path=False`
   - Rationale: root-start / abstract-entity tasks always leave the start path; list cards
     remain the correct evidence surface for "find one bookable …"

3. **Soft-fail on action** (`live_offer_state_slice`)
   - Failed click → block action_key, keep prior page text/url, continue
   - Does **not** terminal-stop the run; max-steps / contract gaps still end the loop

### Still framework (not domain)
- No Corendon/month/hotel ifs
- Contract content still LLM-owned; gate still code-owned

### Expect on 01 re-run
- `surface=list_results` on kerstvakantie / search lists
- `provenance_blocked_n` much lower than 248
- At least some decision outcomes ≠ UNKNOWN when offer text is present
- Failed "Zoeken" does not alone yield `ACQUISITION_ACTION_FAILED`

---

## 2026-08-28 — Candidate-unit packaging + item-link acquisition bias

### Problem (post E / soft-fail)
Provenance no longer blocked list evidence (`prov_blocked=0`), and some outcomes
moved (e.g. `board_type=ALL_INCLUSIVE`, `price_scope=PRICE_NOT_VISIBLE`). But
most package-level decisions stayed UNKNOWN because interpretation still saw
**isolated line claims**:
  "Grand Park Lara"
  "Ultra All Inclusive"
  "vanaf Brussel"
  "va 547 p.p."
A human binds these as one offer; the agent did not.

Also: acquisition kept preferring search/filter controls over concrete item links
even when units were visible.

### Shipped (framework only)
1. **`candidate_units.py`**
   - `package_candidate_units(text, affordances, page_url)` → units with
     `texts`, optional `item_link`, `density_hits`, `source`
   - Clustering: blank-line blocks first (card boundaries), then link anchors
     clipped to their block
   - Density signal: currency / from / p.p. shapes only — **no** domain enums
   - `units_to_observations` emits **one multi-line claim per unit** so
     interpretation sees co-occurring facts
   - `unit_item_link_targets` for acquisition preference

2. **Acquisition loop** (`live_offer_state_slice`)
   - On `list_results`: prefer unit-bound observations over flat line ranking
   - On detail surfaces: keep line observations; units supplemental
   - Trace artifacts: `step_XXX_candidate_units.json`, unit_preview in claims

3. **Planner bias** (`evidence_acquisition`)
   - `filter_safe_affordances(..., preferred_item_links=)` marks matching
     local links `preferred_item=true` and ranks them first
   - `acquisition_decide` receives `candidate_units` + `preferred_item_links`
     and is instructed to prefer opening a concrete unit when gaps remain

### Boundary
- No Corendon / hotel / board / flight strings in packager or ranking
- Contract decision ids remain LLM-owned data
- Packaging is a **mechanism** (binding), not a domain ontology

### Expect on 01 re-run
- `units=N item_links=M` on list steps
- claim_preview shows `[u0] … | … | … → link`
- At least one acquisition step may OPEN/CLICK a preferred item link
- Outcomes for co-occurring facts (airport/date/board/price) more likely
  non-UNKNOWN when unit text contains them
- 02 still CONTRACT_SATISFIED in 0 steps (detail path unchanged)

### Still open
- Interpretation still one-decision-at-a-time; unit text helps binding but
  cost (LLM calls) remains high on large contracts
- Prefer deeper DOM card structure later if blank-line clustering fails on
  some sites (still structural, not domain)

## 2026-08-28 — Candidate layer (stop rabbit-hole of local fixes)

### Trigger

After packaging + item-link bias, task 01 reached price/offer surfaces with visible facts but outcomes stayed partially UNKNOWN / wrong surface labels. Task 02 remained CONTRACT_SATISFIED but sometimes needed an extra same-entity tab click because step-0 interpretation set `subject_instance=NOT_CONFIRMED` despite literal property name + board on the page — until a better-bound unit appeared.

User + external review: successive fixes (STOP, anti-repeat, panels, provenance, packaging) each unlocked the *next* layer of the same underlying issue: **no stable “one object on the page” model.**

### Decision (scientific order)

1. Define Candidate as framework object (no domain fields).
2. Offline extraction only — prove coherent candidates from page_text + affordances.
3. Only then wire interpret-over-candidates + primary_action acquisition.
4. Do **not** stack more surface/ranking patches as the main track.

### Shipped

| Artifact | Role |
|----------|------|
| `candidates.py` | `Candidate` dataclass, `extract_candidates`, rank, observations |
| `scripts/run_candidate_extraction_offline_v0.py` | Offline campaign runner |
| `evals/candidate_offline/fixtures_from_traces/` | Synthetic multi-offer + Monica detail + Flamenco price-surface |
| `docs/CANDIDATE_LAYER.md` | Definition, boundary, offline protocol |
| Updates | `FRAMEWORK_BOUNDARY.md`, `ARCHITECTURE_JOURNEY.md`, this log |

### Offline smoke (same day)

```text
synthetic_multi_offer_list  → 3 candidates, each identity + primary_action + density
02_monica_detail            → candidates extracted; dense price block + chrome units present
01_flamenco_price_surface   → dense price candidate + primary_action; chrome still mixed
```

Synthetic pass proves structural multi-card separation. Real pages still emit chrome candidates — ranking/filtering by density+action is intentional and domain-agnostic; further live interpret should use **top-K by rank**, not all units equally.

### Explicit non-goals this step

- Live acquisition rewrite
- 8-task batch
- Domain outcome fields on Candidate
- Raising max steps as substitute for binding

### Next (only after offline review accepted)

1. Interpretation consumes candidate evidence blobs (top-K), not 30+ unranked lines.
2. Acquisition decide prefers candidate.primary_action when gaps remain.
3. Re-run contract-driven 01 + 02; expect fewer UNKNOWNs when facts are on-page.
4. Then full batch regression.

## 2026-08-28 — Candidate quality v1 (offline)

### Goal
Reduce chrome, keep identity-bearing candidates, stricter primary_action — still offline only.

### Changes (`candidates.py`)
- `is_chrome` structural flag (nav/FAQ/season/review-date blocks)
- `primary_action` only if item-ish (reject help paths, chrome labels, off-host)
- `select_top_candidates`: dense first, then substantive identity (even dens=0), drop chrome
- Ranking no longer prefers “any action” over identity

### Offline results (manifest)

| Fixture | Before (raw top-8) | After quality select |
|---------|--------------------|----------------------|
| synthetic multi-offer | 3 clean cards | 3 clean cards (unchanged GO) |
| 02 Monica detail | 8 incl. FAQ, seasons, reviews | **4**: price block + Prijzen&boeken; disclaimer; Fly&Go tip; breadcrumb+name+board |
| 01 Flamenco price | 8 incl. FAQ, reviews, seasons | **4**: price block + action; entity path; periods; score block |

Chrome menu (ZOMER/LAST MINUTES), FAQ, review-date blocks largely removed.
Property identity line (`SBH Monica Beach` / `Flamenco…` + board) retained via identity pass despite dens=0.

### Remaining gaps (honest)
- Price facts and hotel name still **separate candidates** (not one merged object).
- Score/review aggregate can still appear (dens=0, multi-line).
- Merging identity+offer on same-entity pages is a **later** generic problem — not fixed by domain ifs.

### Next
Offline accepted for “usable top-K set” → wire interpret over selected candidates + prefer primary_action in acquisition → live 01/02.


## 2026-08-28 — Interpret over candidates (wiring)

### Decision
Do not merge candidates yet. Feed top-K quality-selected candidates into interpretation.

### Shipped
- `live_offer_state_slice`: observations from `extract_candidates` → `candidates_to_observations` (all surfaces); preferred_item_links from candidate.primary_action; trace `step_*_candidates.json`
- `scripts/run_interpret_candidates_offline_v0.py`: offline interpret + sufficiency vs frozen contract
- Docs: CANDIDATE_LAYER §11

### Test order
1. Offline interpret on Monica candidates + contract_02 (no browser)
2. Live contract-driven 01+02
3. Only if data shows split-binding failure → same-entity merge research


## 2026-08-28 — Representation A/B experiment (F1)

### Trigger
Claude Sonnet challenge + rabbit-hole recognition: polishing candidates.py heuristics
may be solving the wrong problem. Structure may need to be preserved upstream.

### Decision
Stop candidate-polish; run offline A/B: text clustering vs HTML structural containers.
DOM/AX is a representation axis (F1), orthogonal to access tiers 0–3.

### Shipped
- `structural_observer.py` — text / html / ax arms + metrics
- `scripts/run_representation_ab_offline_v0.py`
- HTML fixtures: synthetic_list, 02_detail, 01_price_surface
- manifest includes `html` paths

### First run (directional, n=3)
- Synthetic: both arms recover 3 offer cards with actions (html briefly double-counts parent)
- Monica HTML arm: separates **identity+board** (`SBH Monica Beach · All Inclusive`) from price card — coloc of name+board without merge heuristics
- Text arm still splits name vs price across candidates on real-ish pages

### Not yet
- Live-captured HTML from Playwright
- AX arm fixtures
- Wiring HTML observer into live acquisition path
- Multi-domain held-out


## 2026-08-29 — Long-horizon / local-LLM horizon notes (roadmap only)

### Source
Architecture challenge with Claude Sonnet (Anthropic research multi-agent, MemGPT/Letta, local VRAM constraints). Documented so future work does not re-litigate the same choices.

### Agreements locked as direction
1. **Bounded parallel workers + external plan** beat one long continuous session.
2. **Roaster** (human → sharp task.md) = same ambiguity-before-cost rule as Contract Discovery.
3. **Citation/verification against raw sources** is a separate concern from “the lead agent remembers.”
4. **MinAC principle** generalizes to representation and memory compression (consumer-relative).
5. **Local 7B–32B**: compensate with structured I/O and source pointers; do not assume free-text summary chains preserve essentials.

### Explicit non-goals for the next engineering slice
- Full multi-day autonomous single-thread research
- Default vision-primary observation
- Building orchestrator/roaster before F1 representation experiment results and non-travel live evidence

### Pointers
- `docs/ARCHITECTURE_JOURNEY.md` — Long-horizon research (future horizon)
- `docs/METHODOLOGY.md` §8 — MinAC as principle + representation ladder
- `docs/FRAMEWORK_BOUNDARY.md` — externalized plan / memory compression


## 2026-08-29 — Representation A/B + arm B2 (mixed-signal NCA)

### Context
First A/B (text vs leaf-html) was PARTIAL: html improved name+board identity, not
name+price co-location. Claude challenge: possible confound — we grouped on leaf
tags (h2/h3/article), not the card container that binds both signals.

### What we built
- Arm **html_b2**: nearest common ancestor of heading-anchor + nearby price-shaped
  node; reject body/main/multi-card wrappers
- Generic **parent-duplicate** filter (strict content-subset parents dropped)
- Applied to both `html` and `html_b2`
- Docs: CANDIDATE_LAYER §12 updated

### How to run
```bash
docker compose run --rm research-agent \
  python scripts/run_representation_ab_offline_v0.py \
  --manifest evals/candidate_offline/fixtures_from_traces/manifest.json \
  --arms text,html,html_b2 \
  --outdir ./evals/representation_ab
```

### Expected directional signals (sketches, n=3)
| Fixture | html_b2 expectation |
|---------|---------------------|
| synthetic | 3 cards, parent-dupe gone, coloc=3 |
| Monica / Flamenco | identity + price as **separate** candidates if NCA is main; coloc still 1 |

If sibling identity/price cards remain split under B2 → representation is not the
binding solution for detail-page facets; next measured step is interpret
neighbor-window (no merge heuristic, no live 01 rerun on sketches).

### Explicit non-goals this slice
- Automatic same-entity merge
- Chrome filter changes (out of extraction scope)
- Live HTML capture (P1b, after B2 reading)
- AX arm until B/B2 exhausted

## 2026-09-07 — Outcomes persistence live + 01/02 baseline

### Campaign
`evals/contract_driven/` runs `20260907T110322Z` (01) and `20260907T113643Z` (02).

| Task | stop | satisfied | duration | notes |
|------|------|-----------|----------|-------|
| 01 package concrete | MAX_ACQUISITION_STEPS | false | ~2001s | 2 gaps left |
| 02 property only | CONTRACT_SATISFIED | true | ~394s | 3 acquisition steps |

### Outcomes persistence (Open #19) — confirmed
Task 01 step 3 raw `board_type: NOT_STATED` (Grand Park Lara page no longer shows board text);
**final** `outcomes.board_type: ALL_INCLUSIVE` from earlier steps. Step log stays honest; end state keeps strongest confirming label. Same mechanism: task 02 `board_type` UNKNOWN steps 0–2 → ALL_INCLUSIVE step 3 → final PASS.

### Task 01 remaining gaps (not architecture bugs)
- **date_scope = OUT_OF_RANGE:** LLM chose “Kerstvakantie 2026” then opened offer dated **03 jan 2027** (`…030127…` in URL). Site holiday window spans into January; agent did not re-filter to calendar December before OPEN. Planning/verification weakness within 3 steps.
- **traveller_count = UNKNOWN:** “Wijzig Reisgezelschap” was visible in affordances early but never selected under max_steps=3. Strategy/budget, not data loss.

Other decisions on 01 **PASS:** package_exists, price_scope, board_type (persisted), flight_inclusion, departure_airport, bookable_surface.

### Task 02 path
Not 0-step: identity confirmed early; board evidence dominated by **carousel other hotels** on detail page → LLM correctly avoided attributing Abora “All Inclusive” to Monica → tried Beschrijving / Verzorging → Fly & Go page finally had “All Inclusive - Aparthotel” / Verzorging blocks bound to Monica → CONTRACT_SATISFIED. Shows gap-driven navigation + interpret caution, not a false early STOP.

### NOT_STATED herkomst (no code change)
Literal in `_WEAK` is **contract-synthesis vocabulary**, not `OUTCOME_*` framework default. Documented under FRAMEWORK_BOUNDARY Open #19 with preferred future direction: weak = non-satisfying set from frozen contract (option B). Implement only when a second task needs it.

### Next measurement
Cross-domain contract-driven mini-batch (non-travel web tasks 03/05/06 first) after (re)synthesis of frozen contracts. FS task 07 needs separate path (no start_url). Do not keep patching Corendon until that baseline exists.

## 2026-09-08 — First non-travel generality mini-batch (03/05/06)

### Campaign
Synthesis `20260908T061529Z_synthesis` (8/8 FROZEN). Contract-driven run on
`06_web_wiki_fact`, `05_web_literature_abstract`, `03_web_product_gpu`
(contract-dir = synthesis **folder**, not the campaign_report JSON).

### Results (directional)
| Task | Domain | stop | satisfied | Dominant cost driver |
|------|--------|------|-----------|----------------------|
| 06 wiki fact | Wikipedia | CONTRACT_SATISFIED | true | ~5 decisions; STOP-gate correctly rejected premature LLM soft-STOP while gaps=1 |
| 05 literature abstract | arXiv | not satisfied (max steps / search strategy) | false | ~8 decisions; stayed on search/category surfaces; little deep-page evidence |
| 03 product GPU | Coolblue | not satisfied | false | ~7 decisions; category crawl; explicit `Zoeken` click timeout |

### What this proves
- **Core loop is not travel-only:** contract → candidates → interpret → code STOP works on Wikipedia (06). Premature LLM STOP was rejected while gaps remained — same authority model as 01/02.
- **01/02 fixes did not regress:** candidate budget (cands≈3, units≈6), ranking, outcomes path remained stable on these runs.
- **New failure class (not old bugs):** open-domain **search strategy** — planner prefers menu/category links over using a visible search field; no recovery after search-control timeout.

### Cost scaling (first quantitative visibility)
Time was **not** spent visiting many sites. Most wall time is interpret LLM calls:

| Task | ~# decisions | ~LLM calls / step | ~time / step |
|------|--------------|-------------------|--------------|
| travel 01/02 (baseline) | 2 | 8–16 | lower |
| 06 wiki | 5 | 16–22 | ~90–135s |
| 05 arxiv | 8 | 42–50 | ~330–390s |
| 03 coolblue | 7 | 38–44 | ~430–470s |

Pattern: cost ≈ f(n_decisions × candidates/units per step). Hidden while all tests used 2-decision travel contracts.

### Observability added (no behaviour change)
- `llm_calls_total`, `n_decisions`, `llm_calls_per_decision` on loop result, task result JSON, campaign report, and DONE log line.
- Documented as FRAMEWORK_BOUNDARY Open **#20**.

### Search preference — hypothesis only (Open #21)
Do **not** implement “always prefer search field” yet. Re-test on tasks **04** (marketplace) and **08** (compare two prices). If the same pattern repeats, design a **generic** affordance bias (search control present + specific entity in task → prefer fill/submit search) with offline measurement first — never site-specific selectors.

### Explicit non-actions this slice
- No acquisition-policy code change
- No contract thinning to reduce cost
- No Corendon-specific patches
- Task 07 (xlsx) still out of web start_url path

## 2026-09-15 — Fase D entity-binding leak (task 02)

Offline A/B (`fase_d_binding_20260915T073132Z`): live PASS `board_type=ALL_INCLUSIVE` depended entirely on the **Abora Continental** carousel claim (other hotel). Removing that claim → `UNKNOWN`. Root cause: `aggregate_outcome` had no subject/entity binding — any high-confidence contract-satisfying label from any candidate won.

**Fix:** Open #22 — structural subject_candidate_ref + fail-closed unbound rows. Expected live effect on 02: fewer false PASS until hero board is in subject-bound candidates.


## 2026-09-15 — Post-#22 live: 02 fail-closed (desired) + Fase E coverage diagnosis

### Binding fix live outcome
- **02:** `board_type=UNKNOWN` across steps, `MAX_ACQUISITION_STEPS` — **expected** after #22. Carousel Abora is no longer accepted for Monica. Not a regression.
- **06:** still `CONTRACT_SATISFIED` / `population_figure=FIGURE_FOUND` — binding does not harm same-entity evidence.

Document for later sessions: **UNKNOWN on 02 after #22 = honest coverage gap**, not "agent broke."

### Fase E — why hero board never sticks in top-K (diagnosis only, no fix)

| Question | Finding |
|----------|---------|
| Does raw page contain hero board? | **Yes** — e.g. `SBH Monica Beach` + `All Inclusive - Aparthotel` near top of `step_000_page_text.txt`. |
| Is there a unit with low block_index that includes Aparthotel? | **Offline** on attached text+affordances: **yes** (large bi=0 block chunked; one 8-line window includes title+board+times). **Live** step_000 units/candidates across 054Z / 602Z / 070819Z / 3× reruns: **no** Aparthotel in top-6/3. |
| Ranking loss vs extraction miss? | **Both possible.** Gate `structural < 1 and not linked → drop` can omit a pure title/board window without digits/link text. Live tops are item_link-heavy distant blocks (Fly&Go bi≈2, carousel bi≈79). Dual rank: units prefer early `block_index`; `extract_candidates` prefers **action/glyphs** then position — carousel-friendly. |
| Same as 01 homepage chrome-prefix? | **Related class, different mechanism.** Homepage was collect early-stop before cards (fixed by collect-then-cap). Monica detail is **one merged chrome+hero block + chunk/gate + dual rank under max_units=6 / max_candidates=3**. block_index-before-density in units helped other fixtures; it does **not** guarantee hero survival on this live path. |

**Root-cause statement (provisional):** coverage gap is **packaging/selection under budget on detail pages where subject board co-occurs with chrome in an early mega-block**, not absence of text and not binding. Open **#23**. No code change until offline experiment isolates gate vs rank vs live/docker text drift.

## 2026-09-15 — Open #23 downgraded + task-02 stability (9/9 SUCCESS)

### Correction of earlier Fase E narrative
- Run **074757Z** was misread as UNKNOWN; raw result: `CONTRACT_SATISFIED`, Aparthotel in saved candidates, step 0.
- Pre-#22 “coverage gap” mixed false-PASS (carousel) with packaging; not proven as a post-#22 defect.
- Docker container confirmed bi-first `_rank` (commit 7927859); stale-image hypothesis for current tree rejected.

### Stability batch (same contract, current code)
All campaign reports grepped: **CONTRACT_SATISFIED / ok=true** for `02_web_hotel_property_only`:

| created_at | duration_s | llm_calls | calls/dec |
|------------|------------|-----------|-----------|
| 20260915T161056Z | 72.41 | 6 | 2.0 |
| 20260915T161209Z | 61.78 | 6 | 2.0 |
| 20260915T161312Z | 42.46 | 5 | 1.67 |
| 20260915T161936Z | 47.48 | 5 | 1.67 |
| 20260915T162024Z | 99.44 | 8 | 2.67 |
| 20260915T162204Z | 45.68 | 5 | 1.67 |
| 20260915T162617Z | 45.65 | 5 | 1.67 |
| 20260915T162703Z | 41.14 | 5 | 1.67 |
| 20260915T162745Z | 55.46 | 6 | 2.0 |

Spot-check outcomes (161312Z, 162204Z, 162745Z + loop 162617/162703/162745):  
`subject_instance=CONFIRMED`, `detail_link=VALID_DETAIL_PAGE`, `board_type=ALL_INCLUSIVE`, Aparthotel in saved candidates **True**, `acquisition_steps=0`.

**9/9 SUCCESS on step 0.** No rank/gate fix needed. Open #23 downgraded in FRAMEWORK_BOUNDARY.md.

### Process rule locked
Any future regression claim: grep `stop_reason` / `outcomes` from raw `result_*.json` **before** a diagnosis round.

## 2026-09-16 — Fase G: search strategy (input_field + FILL_AND_SUBMIT)

### Diagnosis (pre-implement)
Tasks **03** (Coolblue) and **05** (arXiv) failed post-#22 with `MAX_ACQUISITION_STEPS` while search controls were visible. Root cause was **not** entity-binding:

| Path | Status pre-G |
|------|----------------|
| Affordance collection (`browser_list_affordances`) | Text-like `<input>` / `<textarea>` **never** queried — only submit/button inputs + labels for checkbox/radio |
| Candidates / page_text | `body` inner_text; placeholders not systematically extracted |
| Action enum | No TYPE/FILL — only OPEN_URL, CLICK_TEXT, … |
| LLM behaviour | Chose "Zoeken"/Search via CLICK_TEXT; could not type a query |

Conclusion: **capability gap** (inputs invisible + no fill action), not a binding regression.

### Implementation (structural, no lexicon)
1. **`input_field` affordance** (`browser.py`): DOM query for text-like inputs/textarea; metadata `tag`, `type`, `name`, `id`, `placeholder`, `aria_label`. Bucket after buttons, before links.
2. **`FILL_AND_SUBMIT`** (`evidence_acquisition.py`): closed action class. **`query_text` is free LLM text** in the action proposal schema — code never auto-copies from contract gaps. Locator built only from observed structural metadata (id/name/placeholder).
3. **Anti-loop:** `action_fingerprint` includes `(target_id|name, query_text)` so the same query on the same field is blocked after one no-progress attempt; a **refined** query remains allowed.
4. Offline tests: `evals/fill_and_submit/test_fill_offline_v0.py` (+ local HTML fixture) — decide, fingerprint, filter metadata, Playwright fill — all green in Docker.

### Live proof (task 05, frozen contract `20260916T165744Z`)
Run `20260916T170647Z`:

| Step | Action | Evidence |
|------|--------|----------|
| 0 | CLICK_TEXT `Search` | Homepage → search UI |
| 1 | **FILL_AND_SUBMIT** | `query_text="large language model agents tool use 2024"`, `target_id=arxiv-search-input` |
| 2 | Observe | `final_url=…/search/?query=large+language+model+agents+tool+use+2024…`, **232 results**, surface=`list_results` |

Letterlijke query uit trace; anti-repeat key blocked after one use. **Fase G search gap is closed on arXiv.**

### What did *not* close (next bottleneck — not Fase G scope)
After results loaded, LLM proposed `OPEN_URL` → `https://arxiv.org/abs/2601.14696` (from unit text). Code correctly rejected: **`href_not_in_affordances`**. Affordances on the list page include short labels (`arXiv:2608.06909`, `pdf`, author names) but not the full abs hrefs the planner invented. Interpretation on list surface still left `title/claim/url=NOT_VISIBLE`. Stop: `MAX_ACQUISITION_STEPS`, `contract_satisfied=false`.

That is a **list→detail navigation / affordance coverage** issue (and list interpret binding), separate from typing a query.

### Task 03 note
Coolblue click-robustness (`text=Zoeken` timeout) remains a **separate** problem: it sits *before* the search field is reliably reachable. FILL_AND_SUBMIT does not fix fragile CLICK_TEXT locators.

### Explicit non-actions this slice
- No planner hard-bias “always prefer search” (Open #21 preference hypothesis not required once capability exists — LLM chose FILL unaided on 05)
- No Coolblue-specific selectors
- No list-results OPEN_URL relaxation without a structural affordance fix

## 2026-09-17 — Fase H diagnosis: Open #24 root cause + word-boundary item_link bugfix (shipped) + deeper chunking issue (found, NOT fixed)

### Goal
Start the Fase H roadmap item: diagnose Open #24 (`list_results` item hrefs not in
affordances, task 05) offline using the real saved trace of run `20260916T170647Z`
(`step_002_*` artifacts) before touching any code — per testdiscipline.

### Diagnosis (offline, real artifacts, no new live run)
Grepped `step_002_affordances.json`: `arxiv.org/abs/*` links ARE present as `kind=link`
structural affordances — but only for **4 of 50** results on the page
(`2608.06909`, `2606.05711`, `2605.28359`, `2603.23802`). The paper the LLM wanted
(`arXiv:2601.14696`, "AdaTIR") never appears in the affordance list at all.

Two independent, distinct root causes found (all with citation, no paraphrase):

1. **Word-boundary bug in `candidate_units._link_for_block` / the link-anchor pass**
   (BUG, fixed this session). Label/text matching used raw substring containment
   (`lab in norm(t)`). `step_002_candidate_units.json` showed the unit containing
   `AdaTIR` / `arXiv:2601.14696` bound to `item_link = {"text": "Submit", "href":
   ".../user/create"}` — a completely unrelated global nav link — because
   `"submit" in "submitted 24 march, 2026; originally announced march 2026."`
   is true. This is a structural token-boundary defect, not a domain/language rule
   (same audit class as MOVE items — but this one was never lexical to begin with,
   just an unguarded substring check).

2. **Deeper, NOT fixed: chunking/representation gap on this page shape** (found,
   documented, deliberately not patched). The entire 50-result list on this arXiv
   search page renders as **one single blank-line block** (no blank line separates
   `<li>` result cards in the flattened `page_text`). `package_candidate_units`
   then slices that one block into fixed 8-line chunks, which straddle paper
   boundaries (a chunk can end mid-paper-A and start mid-paper-B). Separately,
   `browser_list_affordances`'s JS-side de-dupe-by-visible-text
   (`browser.py` `push()`, `textKey` dedupe) means a generic repeated label like
   `"pdf"` is captured **once** for the whole page (first paper only); every other
   chunk that also contains the literal substring `"pdf"` (true of nearly every
   result, via `"[pdf, ps, other]"`) falls back to matching that one surviving
   `"pdf"` link — silently binding to a **different, wrong paper's** pdf href.

### Fix shipped (small, tested, non-regressive)
`_label_matches_text(a, b)`: require a non-alphanumeric boundary (or string edge)
on both sides of the shorter string inside the longer one — a mechanical
token-boundary check, no word lists, no language content. Applied at **both**
match sites inside `package_candidate_units` (block→link pass and the
link-anchor→block pass) — lesson from HANDOVER bug #2 applied: when the same
matching logic is duplicated, fix both call sites, not just the one you found
first.

New offline regression: `evals/candidate_units_link_binding/test_link_binding_offline_v0.py`,
fixtures = real `step_002_page_text.txt` / `step_002_affordances.json` copied
verbatim from run `20260916T170647Z`. Covers: the fixed false-positive
(Submit/Submitted), a positive control that a *legitimate* exact-word "Submit"
match on the real top-nav chrome block still works (fix must not become too
strict), and a frozen-hash check against the existing accepted-good
`evals/candidate_offline/fixtures_from_traces/manifest.json` (01/02/synthetic) —
item_link bindings on those fixtures are byte-identical before/after this change.

### Attempted, measured, and reverted: href-segment disambiguation
Tried extending `_link_for_block` to disambiguate when a label matches more
than one item_link (to fix case #2 above): prefer a candidate whose href's own
path-tail identifier also appears verbatim in the block text; else return
`None` instead of guessing (same fail-closed principle as entity-binding /
Open #22). **Regression on the known-good manifest**: on `02_monica_detail`,
this caused `"Prijzen & boeken"` and `"Bekijk deze Fly & Go vakantie"` — real,
distinctive action links — to be replaced by repeated `"Costa Calma"` bindings
(a literally-duplicated breadcrumb link on the same page, previously correctly
out-prioritized by path-depth ordering). Root cause of the regression: treating
"same label appears in >1 candidate" as inherently ambiguous does not distinguish
*harmless exact duplicates of the same href* (breadcrumb repeated in header/
footer) from *genuinely different hrefs sharing a generic label* (per-paper
"pdf"). Reverted in full (both call sites) rather than ship a heuristic that
passed on the new fixture but broke the old one — testdiscipline rule "no new
heuristic without a measurable experiment," and the experiment said no.

### Verdict / next step (do not re-attempt as a text patch)
Root cause of #2 is a **representation gap**, not a matching-algorithm gap: this
page shape (no blank lines between list items) breaks the blank-line + fixed-
chunk packaging assumption entirely. This is the exact failure class
`structural_observer.py` (`extract_candidates_via_html` / `html_b2`, see
`CANDIDATE_LAYER.md` §12) was built to address but which was never wired into
the live acquisition path ("Wiring HTML observer into live acquisition path" —
listed as "Not yet" since 2026-08-28). **Recommendation for next Open #24
session:** measure the HTML arm on a live-captured arXiv search-results page
(list of `<li>`/`<dt>`/`<dd>` result records) offline before any further text-
heuristic attempt; do not spend another cycle patching `candidate_units.py`
text matching for this specific failure mode.

### FRAMEWORK_BOUNDARY Open #24 — updated
Split into two sub-findings (see doc): 24a (word-boundary matching — CLOSED,
shipped) and 24b (chunking/representation gap on blank-line-less list pages,
compounded by affordance-capture de-dupe — OPEN, HTML-arm investigation is the
recommended next step, not a text patch).

### Explicit non-actions this slice
- No live re-run of task 05 yet (the shipped fix does not by itself close Open
  #24 end-to-end; a live retest would still hit case #2 on this specific page)
- No change to `browser_list_affordances` de-dupe-by-text behaviour (needs its
  own isolated measurement — may affect other tasks, e.g. task 01 "Bekijk
  vakantie" CTAs repeated per card)
- No wiring of `structural_observer` HTML arm into the live path yet (next step,
  not this slice)

## 2026-09-17 — Refine search after subject rejection (Open #25; follow-up of `20260917T072448Z`)

### Citaat oud (raw `loop_05_web_literature_abstract_20260917T072448Z.json`)
- step 3 `url=https://arxiv.org/abs/2609.19059` `subject_instance=NOT_RELEVANT` → `CLICK_TEXT Related Papers`
- step 4 same abs URL → `OPEN_URL HTML (experimental)`
- step 5 `/html/2609.19059v1` → `CLICK_TEXT Back to Abstract`
- Final `result_*.json`: `stop_reason=MAX_ACQUISITION_STEPS` `contract_satisfied=false` outcomes `subject_instance=NOT_RELEVANT` `claim_extracted=NOT_VISIBLE` (plus extracted title/url/recency/access).

### Diagnose (code, no new live run)
`acquisition_decide` already passed `gaps` with `observed`/`result=FAIL`. The LLM *could* see NOT_RELEVANT. The system prompt still said prefer local tabs / preferred_item / stay on current entity, and mentioned FILL only “when gaps suggest missing search results.” So the planner stayed on the rejected paper.

### Fix
- `object_rejected_on_current_page` / `should_hint_refine_search`: current-page outcome in `{NOT_RELEVANT, REJECTED}` **and** a FAIL gap **and** `list_results` already in `surfaces_seen`. Not merged `best_outcomes` (homepage NOT_RELEVANT must not keep firing). Absence (`NOT_VISIBLE`) does not trigger.
- Planner prompt then: do not deepen this record; MAY `FILL_AND_SUBMIT` with a **new** LLM `query_text`. Code does not generate the query. Same fingerprint anti-loop as Fase G.
- Loop passes `current_page_outcomes=pipe["outcomes"]` and unique `surfaces_seen`.

### Offline
`python3 evals/refine_search_after_reject/test_refine_search_offline_v0.py` — all passed: hint on, refined FILL accepted, identical query still `no_progress_repeat_blocked`, no-hint when only `NOT_VISIBLE`. Existing FILL tests still pass.

### Niet gedaan
Live taak 05 retest — alleen na expliciete toestemming + `docker compose build research-agent` (code zit in het image).

## 2026-09-17 — Open #26 candidate-scope reset (vóór #24b)

### Citaat oud (`20260917T083112Z` result + loop)
`stop_reason=MAX_ACQUISITION_STEPS` `contract_satisfied=false` `subject_instance=NOT_RELEVANT`.
Stap 3 `/abs/2609.19059` NOT_RELEVANT → `OPEN_URL Search` (reden: rejected) → FILL nieuwe queries. #25 OK. Merge hield NOT_RELEVANT vast (`_WEAK` = UNKNOWN/NOT_STATED only).

### Regel
Bind via `preferred_item_links` + path-leave vanaf `list_results` of switch naar ander item-path. Unbind bij FILL of verlaten van bound path (niet abs→html zelfde last-segment). Reset `best_outcomes` met `step >= bound_step`. Geen decision_id-hardcode.

### Offline
`evals/candidate_scope_reset/test_candidate_scope_offline_v0.py` — unbind 083112Z, FILL unbind, 02 tab, 02 Fly&Go, 01 list→detail keep ALL_INCLUSIVE, switch A→B, html deepening.

### Niet gedaan
Live 05 — alleen na user-OK + `docker compose build`.

## 2026-09-17 — Live #26 retest `20260917T093236Z` (niet gesloten)

### Config
Rebuild `--no-cache`, `batch_decisions=False`, zelfde frozen contract, `--max-steps 6`. Apples-to-apples vs `083112Z`.

### Citaat raw `result_05_web_literature_abstract_20260917T093236Z.json`
`stop_reason=MAX_ACQUISITION_STEPS` `contract_satisfied=false` `gaps_n=1` alleen `claim_extracted=NOT_VISIBLE`.
PASS: `subject_instance=RELEVANT` `access_status=OPEN_ACCESS` `recency=IN_RANGE` `title_extracted=EXTRACTED` `url_extracted=EXTRACTED`.
`final_url=https://arxiv.org/abs/2609.19059v1` `llm_calls_total=156` (083112Z: 216).

### Lus (loop + terminal)
- Stap 0 homepage `NOT_RELEVANT` (geen bound paper) → Search → FILL `large language model agents tool use`.
- Stap 2 lijst `OPEN_URL https://arxiv.org/abs/2609.19059` — href **zat** in affordances (niet het #24 `href_not_in_affordances` pad).
- Stap 3–5 zelfde abs: LLM `subject_instance=RELEVANT` (083112Z: **NOT_RELEVANT** op dit abs — labelvariant, geen codebewijs).
- `CLICK_TEXT View PDF` `soft_fail`: locator `text=View PDF` is onzichtbare `a.mobile-submission-download`.
- Enige scope-event: `candidate_scope event=bind path=/abs/2609.19059v1 bound_step=6`. **Geen unbind/switch.**

### Waarom #26 niet live bewezen
Het ontwerp-faalpad (bound reject → leave → merge houdt `NOT_RELEVANT` vast t.o.v. later `UNKNOWN`) is niet voorgekomen.
- Eerste list→abs bond **niet**: `preferred_item_links` op `/search` waren chrome (`Submit`→`/user/create`, `Advanced Search`) — top-3 candidates = header (#24b).
- Bind op v1 is same-record deepening; `from_list` was true omdat abs `surface=list_results` is (`_classify_surface` via price-like digit density: **4** hits, drempel 3 — Open #10).
- Homepage-`NOT_RELEVANT` verdween via #19 (later concreet `RELEVANT`), niet via scope-reset.
Stap-log `outcomes=` is `pipe` (huidige pagina), niet `best_outcomes`.

### Resterende contract-gap (niet merge)
`step_003_page_text.txt` bevat de MIRAGE-abstractparagraaf. `claim_extracted` bleef `NOT_VISIBLE` omdat die regel **nooit in een unit zat**. Zie Open #27.

## 2026-09-17 — Open #27 long innerText lines dropped (claim_extracted gap)

### Citaat / meting (offline, echte artifacts `093236Z` step 003)
- 70 non-empty regels; **1** regel `len=1524` begint met `Multimodal large language model (MLLM) agents`.
- `_skip_line_structural` behandelde `len>240` als skip-and-split → abstract verdween; title overleefde in de 8-regel prefix-chunk (`title_extracted=EXTRACTED`).
- `extract_candidates` top-3: Submit `/user/create`, view email, View PDF — geen abstract.
- 01/02 fixtures hebben ook huge lines (max 832–837) die al gedropped werden; top-3 item_link hrefs mogen niet herschikken.

### Regel (structureel, geen lexicon)
- Wrap `len>240` in vensters van 240 als **eigen blok** (niet droppen, niet aan chrome-chunk plakken).
- 1-regel / digit-loze chunks behouden als tot char-count ≥ 240.
- Na action-first rank: append hoogstens **één** long-text unit/candidate als die ontbreekt (nav top-K blijft).

### Offline
`evals/long_line_units/test_long_line_units_offline_v0.py` — abstract in units + observations; short-only pagina verzint geen paragraaf; 01/02/synthetic top-3 hrefs ongewijzigd. Regressie #24a/#25/#26 groen.

### Niet gedaan
- Live 05 hertest — alleen na user-OK + `docker compose build`.
- Surface-tag abs=`list_results` (Open #10) niet “gefixed” in deze slice: monica detail heeft price_hits=29; drempel ophogen lost abs=4 niet zuiver op en zou 01-lijsten raken.
- #24b HTML-observer; #26 unbind-pad nog ongetest live.
- View PDF mobile-locator.

## 2026-09-17 — Live #27 retest `20260917T102344Z` + claim_extracted diagnose (geen fix)

### Config / raw result
Rebuild, `batch_decisions=False`. `result_…102344Z.json`: `stop_reason=MAX_ACQUISITION_STEPS` `contract_satisfied=false` alleen `claim_extracted=NOT_VISIBLE`. PASS: RELEVANT / OPEN_ACCESS / IN_RANGE / title+url EXTRACTED. `final_url=/html/2601.14696v1` `llm_calls_total=197`. Stap 0 `cands=4 units=7` (splice in image).

### #26
Geen `candidate_scope` in deze run. **Blijft OPEN.** Geen geforceerde herhaalronde (beide recente 05-runs waren RELEVANT, niet het reject→leave-pad). Offline `test_candidate_scope_offline_v0.py` blijft het bewijs.

### PDF / #24b (niet deze slice)
`OPEN_URL` target=`pdf` href=`https://arxiv.org/pdf/2608.06909` → `Page.goto: Download is starting` soft_fail. Unit toonde AdaTIR `2601.14696`; href was een andere paper. Later OPEN abs + HTML experimental.

### c3 citaat (`trace/artifacts/step_005_candidates.json`)
- **Wel:** `candidate_id=c3`, `evidence` = 6 wrap-vensters van het AdaTIR-abstract (begint `Tool-Integrated Reasoning (TIR) has significantly enhanced…`), `block_index=1`, `packager_source=blank_block`, `digit_run_count=5`, `n_lines=6`. Preview: `id+ | (no identity hint)`.
- **Niet:** `identity_hints=[]`, `primary_action=null`. (Title zit in **c0** `block_index=0`.)

### (1) identity_hints — niet de oorzaak
`_identity_hints_from_texts` slaat regels `len>80` over → wrapped 240-char vensters geven nooit hints. **Toeval t.o.v. deze failure.**
- `interpret_observation` krijgt alleen `source_text`; geen identity_hints-gate.
- `_claim_priority`: FIFO `list_index`, optioneel kortere snippets eerst; geen identity.
- `aggregate_outcome` / `_is_subject_bound`: `candidate_id` / `block_index` / `item_link_href` only. Lege hints sluiten c3 niet uit.

### (2) #22 + wrap-split — niet de failure die gebeurde
Contractvraag (`contract_05_…json`): “Can a one-sentence main claim or conclusion be extracted from the abstract or intro?” — **geen** extra entity-binding-eis in de vraagtekst. Binding is framework (#22), intra-page.
c0 `block_index=0` vs c3 `block_index=1` → `|Δ|=1 ≤ cluster K=8`; zelfde `item_link` ontbreekt (c3 heeft geen action). **Als beide geïnterpreteerd waren en subject_ref=c0, zou c3 wél bound zijn.**
Stap 5: `skip_satisfied` bevat `subject_instance` → `pending_decisions` zonder subject → `_finalize_outcomes_with_binding` zet `subject_ref=None` → `require_subject_binding=False` voor claim. Wrap “identity meelopen” is dus **niet** wat deze run brak.

### Root cause (categorie: structureel/packaging, niet LLM)
`#27` splice zet c3 in `selected` (artifact). Live call:

`live_offer_state_slice.py`: `obs = candidates_to_observations(selected, max_candidates=3)`

c3 is de 4e candidate → **geen observation**. `step_005_claims.json` `claim_preview` = title + c0 chrome + c1 cite + c2 View PDF. Geen abstractparagraaf. `candidate_claim_n=4`. Zelfde cap op HTML stap 6 (`claim_preview` eindigt op `"to | 97.6"`, niet c3).
Offline test `test_long_line_units_offline_v0.py` gebruikte `max_candidates=8` en verborg dit.

**Niet categorie 3:** het model heeft c3 niet gelabeld; het heeft c3 niet gekregen.
**Niet categorie 1.** Categorie 2-familie (packaging), concrete mechaniek = observation-cap vs splice — niet identity-context in wrap-chunks.

### Niet gedaan (op diagnose-moment)
Geen codefix. PDF/#24b onaangeroerd. #26 geen extra live-run.

## 2026-09-17 — #27 follow-up: observation-cap mismatch (code + offline)

### Root cause (bevestigd)
Oud: `live_offer_state_slice.py` `obs = candidates_to_observations(selected, max_candidates=3)`.
`extract_candidates(..., max_candidates=3, max_units=6)` + Open #27 splice mag `len(selected)=4` (c3 = abstract). Tweede cap gooide c3 weg vóór interpret.

### Fix — optie (a), kleinste ingreep die Open #6 respecteert
Nieuw: `obs = candidates_to_observations(selected)` — geen onafhankelijke recap.
`candidates_to_observations` default `max_candidates=None` → `cap = len(candidates)`.
Optie (b) (hardcode hetzelfde 3) zou c3 **nog steeds** droppen; Open #6 zit al op `extract_candidates`. Comment bij de call verwijst naar #6/#27/`102344Z`.

### Offline
- Negatief: frozen 102344Z 4 candidates, recap=3 → c3 **niet** in observations.
- Verplicht: zelfde 4, synced cap → c3-tekst `Tool-Integrated Reasoning (TIR) has significantly enhanced…` **wel** in observations (`candidate_id=c3`).
- Harness: live-budget 3/6 (niet meer `max_candidates=8` als enige pad); apart wide-budget=8.
- 01/02/06: first-3 `candidate_claim` teksten identiek vóór/na; extra 4e observation = spliced long-text (zelfde klasse als 05 c3, geen herschikking van de oorspronkelijke 3).

### Open
**#26 blijft OPEN** (ongerelateerd; geen unbind/switch in 093236Z/102344Z). PDF/#24b later.

## 2026-09-17 — Live #27 cap-sync retest `20260917T111714Z`

Rebuild na `1f0557e`, `batch_decisions=False`. Raw `result_05_web_literature_abstract_20260917T111714Z.json`: `stop_reason=CONTRACT_SATISFIED` `contract_satisfied=true` `claim_extracted=EXTRACTED`. Overige required: RELEVANT / OPEN_ACCESS / IN_RANGE / title+url EXTRACTED. `final_url=/abs/2609.18128` `llm_calls_total=156`.

Stap 6 `step_006_claims.json`: `candidate_claim_n=5` (was 4 in 102344Z). `claim_preview` eindigt op c3-abstract: `Large language model (LLM) agents augmented by tools can automate… We present ContrAgent…`. Candidates: c0 chrome, c1 cite, c2 browse, c3 `(no identity hint)` = wrap. Interpret zag c3.

PDF `Download is starting` opnieuw (`/pdf/2609.19059`) — #24b, niet deze slice. Geen `candidate_scope` event — **#26 blijft OPEN**.

## 2026-09-17 — #24b status-check (offline, bestaande 05-artifacts)

### Vraag
Komt “lijst = één blank-line-blok” nog voor na #25/#27, of miste `111714Z` het toevallig?

### Citaat — nog actief
`111714Z` `step_002_page_text.txt` (search, `surface=list_results`): geen blanco regel tussen kaarten:

```
arXiv:2609.19059  [pdf, ps, other]
…
Comments: Accepted by ACM MM 2026
arXiv:2609.18736  [pdf, ps, other]
```

`_blank_line_blocks`: **5** blokken, max **92** regels, **19** paper-ids op de pagina, **1** in top-candidates. `step_002_affordances.json`: precies **één** `"text": "pdf"` → `https://arxiv.org/pdf/2609.19059`. `step_002_candidates.json` c3 evidence = ClinAgent `arXiv:2609.13860`, `primary_action` = diezelfde first-card pdf `2609.19059`.

Zelfde patroon op search-stappen van `083112Z` / `093236Z` / `102344Z` (max-blok 92–111; pdf-mismatch). `111714Z` `CONTRACT_SATISFIED` via `OPEN_URL` `arXiv:2609.18128` (uniek label wél in affordances) + #27 op de abs-pagina — **omzeiling, geen fix**.

### html_b2 niet gewired deze slice
Publieke search-HTML (geen LLM): **50×** `li.arxiv-result`, titel in `<p class="list-title">`, **1** heading-tag op de hele pagina. `html_b2` = heading+price NCA → geen per-paper split. Kandidaat-arm = leaf `html` (`li`). Live pad slaat geen HTML op. 01/02-negatieven blijven verplicht zodra een HTML-arm wél live gaat.

### PDF (scope, geen code)
`Page.goto: Download is starting` op `/pdf/…` is generiek Playwright (navigatie triggert download). Loop **soft_failt al** en blijft op de lijst. Verkeerde pdf-href is #24b-dedupe, niet de download-exception. Abs/HTML-experimental volstaan voor taak 05. Kleine fix: download-event vangen i.p.v. goto-exception. PDF-tekst als bewijs = grotere capability, niet nodig voor huidig contract.

## 2026-09-17 — Open #28 PDF/download catch (code + offline)

### Citaat oud (`111714Z` loop)
`execute_error`: `Page.goto: Download is starting` navigating to `https://arxiv.org/pdf/2609.19059` → `soft_fail`, lijstpagina behouden.

### Fix
`browser._run_keeping_download`: Playwright `download`-event + message `Download is starting`. Geen URL-/`.pdf`-lexicon. Download `cancel()` (geen parse). Snapshot van de **huidige** pagina, `download=True`, `error=None`. `OPEN_URL`/`CLICK` blijven `ok` als paginatekst >40. Loop: `download_kept_page`, action_key geblokkeerd, volgende affordance. Timeout blijft een echte error.

### Offline
`evals/download_navigation/test_download_navigation_offline_v0.py` groen (live error-string; timeout-negatief; execute-download is `ok`). Playwright HTTP-fixture SKIP op deze host (geen playwright).

### Niet
Geen PDF-tekst als bewijs. #24b (één `"pdf"`-affordance / verkeerde href) ongemoeid. Geen live 05 zonder user-OK.

## 2026-09-17 — Open #24b Fase 1: affordance-identity `(text, href)`

### Citaat oud (`browser.py` JS `push()`, live 111714Z/153607Z)
```
const key = (kind + '|' + (text || '').toLowerCase() + '|' + (extra && extra.name ? extra.name : '') + '|' + (extra && extra.id ? extra.id : '')).slice(0, 200);
if (seen.has(key)) return;
const textKey = 'T|' + (text || '').toLowerCase();
if (!isInput && text && seen.has(textKey) && kind !== 'tab') return;
seen.add(key);
if (text) seen.add(textKey);
```
`111714Z`/`153607Z` `step_002_affordances.json`: precies **één** `"text": "pdf"` → `https://arxiv.org/pdf/2609.19059`. `step_002_page_text.txt`: **19** `arXiv:NNNN [pdf, …]`-kaarten.

### Citaat nieuw
Identity = `(kind, text, href, name, id)` + cross-kind `TH|text|href`. Geen lexicon. Exacte `(text, href)`-duplicaten blijven samenvallen.

### Offline
`evals/affordance_identity/test_affordance_identity_offline_v0.py`: reconstructie 19 paper-ids → legacy **1** pdf, nieuw **19** unieke pdf-hrefs. Negatief: zelfde `(text, href)` twee keer → 1. Regressie 01/02/06: saved counts + HTML-anchors identiek (01 n=49/14, 02 n=44/17, 06 n=60).

### Niet
Sluit #24b niet (lijst is nog één blank-line-blok). **Geen Fase 2** (`extract_candidates_via_html`) tot een Fase-1 live-hertest onvoldoende blijkt. Geen live 05 zonder user-OK.

## 2026-09-17 — Open #24b Fase 2.1: raw-HTML plumbing (geen candidate-wijziging)

### Citaat oud
`browser._snapshot` gaf alleen `url/title/text`. Live pad bewaarde geen DOM. `extract_candidates_via_html` bestond maar had geen input.

### Citaat nieuw
`_snapshot` zet `html` + `html_chars` via `page.content()` (cap 400k). Ontbrekende `content()` → `html=""`. Trace: `step_NNN_page.html`. Acquisition houdt `html` naast `text` bij navigatie.

### Offline
`evals/html_leaf_list/test_html_plumbing_offline_v0.py` groen. 01/02/06 extract-fingerprint ongewijzigd (html nog niet gewired).

### Niet
Geen `extract_candidates_via_html` in de live extract. Geen html_b2.





