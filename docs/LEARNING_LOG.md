# Learning log — experiments, results, decisions

Living log of what we tried, what worked, what we abandoned.  
High-level process: see `METHODOLOGY.md`.

Format per entry: **date → hypothesis → result → decision**.

---

## 2026-08-28 — Contract-driven 01+02 (execution layer)

| Hypothesis | Result | Decision |
|------------|--------|----------|
| Frozen contract + code sufficiency is the only STOP authority | Task 02: LLM said STOP (“All Inclusive found”) while `subject_instance` still UNKNOWN → run ended unsatisfied | **Reject LLM/soft STOP while gaps remain**; only code terminals (`no_gaps`, `max_steps`, `no_llm`) may end early |
| State-signature anti-loop stops useless repeats | Task 01: 3× `VERTREKPERIODE`; UI toggled open↔close so `no_progress=false` | **Block action_key after one use** (toggle ≠ research progress) |
| Interpret after NOT_ADMISSIBLE yields outcomes | 01: `interpreted=True` but `provenance_blocked_n=248` → all UNKNOWN | Admission fix kept; **provenance/list surface** = later step (not this commit) |
| Same architecture, different tasks → different stop criteria | 01 (8 required) vs 02 (2 required) without Python domain ifs | Keep ladder: contract → sufficiency → evidence → nav; **no Monica/Costa patches** |

**Shipped (this step only):** stop-reject-on-gaps + anti-repeat-by-action-key in `live_offer_state_slice.py` / `evidence_acquisition.py`.

**Next (ordered, one layer at a time):** affordance panel options → identity interpret → list-surface provenance → full 8-task batch.

See also `FRAMEWORK_BOUNDARY.md` regression lessons.

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
