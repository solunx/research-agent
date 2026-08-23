# Learning log — experiments, results, decisions

Living log of what we tried, what worked, what we abandoned.  
High-level process: see `METHODOLOGY.md`.

Format per entry: **date → hypothesis → result → decision**.

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
