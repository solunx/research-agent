# Architecture Journey — Local Research Agent

**Purpose:** Durable record of *why* the architecture looks the way it does.  
Read this before changing harvest, admissibility, contracts, or LLM wiring.

**Last major update:** 2026-08-26 (grounding ablation A0–A5 + candidate≠eligibility).

---

## 1. Starting problem

We wanted a **generic research agent**: given `task.md`, retrieve evidence from the web (and later other sources), and produce a grounded answer/shortlist — without hardcoding “hotel”, “all-inclusive”, or site-specific scrapers into the core.

Early reality (Aug 2026):

- Ollama context crashes on long single chats → external notes + shortlist + planned phases.
- Playwright deep-links work when recipes exist; Browser Use is slow last resort.
- Host memory (tactics/recipes/URL patterns) is global; run content stays per run.
- **Finding information ≠ having rankable candidates.** Harvest saw prices and names; shortlist often stayed empty or filled with noise.

---

## 2. Ground rule (LOCKED — do not re-litigate casually)

### Formal boundary

```text
CODE may DESCRIBE   →  mechanical / structural facts
LLM  may INTERPRET  →  meaning, role, relevance under the task
CODE may ENFORCE    →  schema, provenance, contract, eligibility, policy
```

Or:

| Owner | Question it is allowed to answer |
|-------|----------------------------------|
| **Code** | What is physically/structurally there? (text, DOM, links, neighbors, channels, HTTP status, URL change, missing field) |
| **LLM** | What does it mean? (candidate? chrome? offer? board type? study design? relevant?) |
| **Code** | What are we allowed to conclude/do given normalized results? (PASS/FAIL/UNKNOWN, eligibility AND, rankable) |

### Anti-patterns (repeat rabbit holes — stop)

1. **“Code filters obvious semantic garbage first, then LLM.”**  
   Determining that something is “garbage” (CTA vs offer vs destination vs amenity) *is* semantic. Code cannot generically know it is uncertain. Default: **LLM interprets; code does not pre-classify meaning.**

2. **“Code first; LLM only when code is uncertain.”**  
   Code often cannot know it is uncertain. Prefer: **LLM for meaning unless we have *empirically proven* a decision is safely deterministic** (e.g. HTTP 404, no DOM mutation, empty text node).

3. **Growing `admissibility.py` / phrase lists / hotel classifiers in core.**  
   Experimental baselines only — not product architecture.

4. **Treating structure as a candidate classifier.**  
   Structure is **grounding context for the LLM** (hierarchy, repetition, proximity, provenance, channels) — not the answer to “is this a candidate?”

### What code *is* allowed to do before the LLM

Observe and package facts **without interpreting role/relevance**:

- text, tag, href, bbox/position, siblings/neighbors, repeated pattern flags  
- channel labels from *provenance rules already proven* (e.g. URL query → `search_context`, not “this hotel is all-inclusive”)  
- pure state: 404, navigation delta, missing required schema field  

Then: grounded LLM → typed result → code validates/enforces.

### What belongs in code (mechanics)

- Parsers / DOM / page structure / neighbors / channels (`candidate_claim` vs `search_context`)
- Contract meta-schema validation (enums must include `UNKNOWN`)
- Deterministic comparison: `outcome ∈ required → PASS else FAIL`; `UNKNOWN → not eligible`
- Progress / control loops that observe state deltas, not “useful click” heuristics alone

---

## 3. Chronological learning path

### Phase A — Browser & host memory (Frontier / T1–T3)

| Learning | Decision |
|----------|----------|
| Transport knowledge must not be rediscovered every task | Global `memory/site_*` |
| Easy booking recon ≠ usable research | Recipes need navigation **+ semantics + harvest** |
| Notes had deals but shortlist=0 | Harvest invariant / promotion path (later refined) |

### Phase B — Observation ≠ candidate

| Learning | Decision |
|----------|----------|
| Auto-promoting every € creates noise (destinations, chrome) | `observations.jsonl` vs shortlist; entity_score / marketing_penalty |
| Search URL `meal=all-inclusive` is **not** a claim about a hotel card | **Evidence channels** (`search_context` ≠ `candidate_claim`) |
| “Harvest better regex” keeps pulling us into travel vertical | Stop vertical tuning; structure + channels first |

### Phase C — Contract, interpretation, eligibility

| Learning | Decision |
|----------|----------|
| Fixed ontologies (`TARGET_OFFER`, `AMENITY`) are hidden verticals | **Task-specific Research Contract** (meta-schema fixed, content from LLM) |
| LLM can discover decisions (`board_type`, `detail_link`, …) from task + surfaces | Contract Discovery v0 |
| Generic executor can run a contract it never hard-coded | Decision Executor (no `if board_type`) |
| Raw text + pattern lists still smuggle semantics into code | **Interpretation LLM** → normalized outcomes → dumb gate |
| Same interpretation+gate works on **literature** study_design | Strong support for meaning-outside-core |
| Multi-decision AND eligibility works (packages + literature) | Fail-closed UNKNOWN blocks eligibility |

### Phase D — Wiring real harvest → interpretation

| Learning | Decision |
|----------|----------|
| Real `raw_evidence` contains card literals (“Enkel kamer”, flights) | Observation builder from raw_evidence |
| Vertical slice: URL all-inclusive + card “Enkel kamer” → not eligible | Safety path proven |
| Fixture positive AI-card → eligible | Positive path proven |
| Batch of 10 candidates: no cross-talk | Isolation OK on fixtures |

### Phase E — Candidate admissibility & selection campaign

| Learning | Decision |
|----------|----------|
| Structural admissibility rejects marketing/chrome well; long hotel titles often UNKNOWN/NOT | Structure alone is **not** a universal candidate classifier |
| Ablation: raw_evidence helps little vs aggressive word-count heuristics | Don’t dig a bigger heuristic hole |
| **S0 structural**: strong on web/code/lit; weak on documents | Structure = context provider |
| **S2 LLM raw**: web **R=0** (hotel name alone → reject) | Context/neighbors are mandatory |
| **S3 LLM grounded**: **R=1.0 / P=1.0** on all four pilot domains | Best hypothesis for candidate selection |
| **S5 hybrid**: cost savings but inherits aggressive prefilter (docs R=0.5) | Aggressive *semantic* prefilter is an anti-pattern; structure is context only |
| Pilot n is small (4–8 units/domain) | S3 is best *on this pilot*, not proven universal |

### Phase F — Grounding ablation (A0–A5) + candidate ≠ eligibility

| Learning | Decision |
|----------|----------|
| **A4 (task+text only): web R=0** | LLM used task as **completeness checklist** → rejected bare hotel titles |
| A5 (full grounding): R=1.0 / P=1.0 on pilots | Neighbors + provenance make *role* clear; recover titles |
| A0–A2 weak on code precision (`format_price` FP) | Task still needed as **relevance filter**, not completeness gate |
| A3 provenance strong on pilot | Path/url is powerful grounding — still not a semantic classifier in code |
| Structure alone ≠ candidate answer | Confirms ground rule §2.4 |

**Locked distinction:**

```text
CANDIDATE_UNIT       "Could this be a useful evidence unit for the task?"
                     Incomplete is OK → ADMISSIBLE

ELIGIBILITY_COMPLETE "Are hard task constraints already proven on this unit?"
                     Missing fields → NOT / UNKNOWN
```

These must **never** share one prompt/step. Mixing them caused A4.

### Phase G — Current architecture hypothesis (2026-08-26)

```text
TASK
  → [LLM] Contract Discovery (what to decide / require)
  → Capabilities (web/pdf/…) produce STRUCTURAL observations + provenance
       (describe only — no “is this a candidate?”)
  → [LLM] CANDIDATE_UNIT (grounded; incomplete OK)
  → [LLM] interpretation of claims → normalized outcomes
  → [CODE] ELIGIBILITY / ranking / report mechanics (enforce)
```

**Not pursued as product direction:** universal `admissibility.py` with more phrase rules;
“obvious chrome” filters that smuggle meaning into code; task-as-completeness in the
candidate step.

---

## 4. High-level process schema

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                         USER / TASK.md                                   │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ F0  FRONTIER / HOST SELECTION                                            │
│   T1 Memory (recipes, tactics, URL patterns)                             │
│   T2 Cheap web/fetch                                                     │
│   T3 Browser (Playwright default; Browser Use optional)                  │
│   Control: progress = state/obs/evidence delta (not “clicks”)            │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ F1  PAGE → STRUCTURE (code / capability)                                 │
│   page_role (list|detail|landing|unknown)                                │
│   members / cards / paragraphs / tables                                  │
│   neighbors, element_type, URLs, provenance                              │
│   channels: candidate_claim | search_context | navigation | page_chrome  │
│   NO semantic “is this the answer?” here                                 │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
          ┌─────────────────────┴─────────────────────┐
          ▼                                           ▼
┌──────────────────────────┐            ┌──────────────────────────────┐
│ F2a CONTRACT DISCOVERY   │            │ F2b CANDIDATE SELECTION      │
│ (LLM, schema-constrained)│            │ (grounded LLM S3 hypothesis) │
│                          │            │                              │
│ CD0 task-only            │            │ structural units + task +    │
│ CD1 task+samples one-shot│            │ neighbors → ADMISSIBLE /     │
│ CD2 provisional→refine   │            │ NOT / UNKNOWN                │
│                          │            │                              │
│ → subject, decisions,    │            │ No semantic prefilter in     │
│   outcomes, sufficiency  │            │ code; structure = grounding  │
└────────────┬─────────────┘            └──────────────┬───────────────┘
             │                                         │
             └─────────────────┬───────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ F3  INTERPRETATION (LLM)                                                 │
│   claim text + decision_id + allowed outcomes                            │
│   → normalized outcome (e.g. ROOM_ONLY, RCT, UNKNOWN)                    │
│   channel filter: search_context must not feed board claims              │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ F4  DETERMINISTIC CORE (code)                                            │
│   Decision executor / gates: PASS | FAIL | UNKNOWN | SPEC_GAP            │
│   Eligibility = AND over required decisions                              │
│   Rankable only if eligible + provenance OK                              │
│   Critic ranks rankable only; report from notes/shortlist                │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ F5  FEEDBACK / GAPS                                                      │
│   blocking UNKNOWN → more retrieval / refine contract / stop             │
│   host needs_recon → memory flag                                         │
│   LLM errors → PARTIAL_SUCCESS if shortlist survives                     │
└─────────────────────────────────────────────────────────────────────────┘
```

### Nested loops (do not conflate)

| Loop | Question | Owner |
|------|----------|--------|
| **Browser control** | Did this action change state / information? | Code |
| **Contract discovery** | What must we decide for this task? | LLM + fixed meta-schema |
| **Candidate selection** | Could this unit be evidence for the task? (incomplete OK) | Grounded LLM + **CANDIDATE_UNIT** prompt |
| **Interpretation** | What does this claim mean under decision X? | LLM |
| **Eligibility** | Do normalized outcomes satisfy the required set? | Code (not the candidate prompt) |
| **Host learning** | How does this site’s interface work? | Memory + recon |

---

## 5. Experiment map (what we measured)

| Campaign | Question | Main result |
|----------|----------|-------------|
| Interpretation single/multi | Can LLM normalize claims without domain code? | Yes (packages + literature) |
| Vertical slice ± batch | Real/fixture evidence → eligibility chain? | Safety + positive paths work |
| Admissibility recall/ablation | Can structure alone keep hotels, drop chrome? | Chrome yes; long titles / docs weak |
| **Candidate selection pilot** | Structural vs raw LLM vs grounded LLM vs hybrid? | **S3 best**; S2 web fails; structure weak on docs |
| **Grounding ablation A0–A5** | Which context does candidate LLM need? | **A4 web R=0** (task as completeness); **A5** recovers |
| **Candidate vs Eligibility** | Split prompt questions? | **Δ=+1.0 web/lit**; code/docs Δ=0 |
| **Offline pipeline v0** | Chain layers end-to-end offline? | **batch 10/10 match, 0 leaks** |
| **Pipeline from real run** | Same chain on harvest observations? | **0 leaks; eligible_n=0 (no AI card claims)** |
| **Positive evidence trace** *(next)* | Where is AI evidence lost A–F? | Design locked |

---

## 6. Choices for the *next* tests (from 2026-08-26)

We are **not** optimizing board synonyms or hotel heuristics further.

**Grounding ablation (20260826T080416Z_full) — key answer:**

- Task without local card evidence makes the LLM demand completeness → false negatives on web titles.
- **Candidate ≠ eligibility** must be explicit in prompts and pipeline stages.
- Full grounding (A5) works on this pilot; provenance (A3) is surprisingly strong; structure alone is not enough for semantics.

**Contract Discovery pilot (20260826T072909Z) — answered enough to proceed:**

| Mode | val_ok | avg decisions | llm_calls | Notes |
|------|--------|---------------|-----------|--------|
| CD0 task-only | 1.0 | 6.5 | 1 | Usable provisional; sparse signals (warnings OK); subject often `unknown_subject` |
| CD1 one-shot | 1.0 | 7.5 | 1 | Richest sample-grounded `missing_to_solve`; evidence_signals filled |
| CD2 provisional→refine | 1.0 | 7.0 | 2 | Jaccard 0.89 (packages) / 1.0 (lit); refine *grounds* subject + gaps; may add 1 decision |

**Takeaway:** CD0 is a valid start; samples (CD1/CD2) ground gaps in real surfaces; refine is stable (does not thrash decision ids). Not “hours” — pilot ≈ 6 LLM jobs, ~7–8 minutes wall time.

**Next scientific question (immediate):**

> When should the agent **refine** the contract (CD2) vs freeze after CD1, and how do we wire discovery → execution without re-introducing semantic filters in code?

Modes measured:

| Mode | Inputs | Hypothesis |
|------|--------|------------|
| **CD0** | task only | Cheap provisional model of the task |
| **CD1** | task + surface samples, one shot | Current default style |
| **CD2** | CD0 then refine with samples | Better blockers / fewer hallucinations / clearer decisions |

Metrics: schema validation, explains-zero-rankable (when run data exists), decision coverage, stability CD0→CD2, LLM calls/tokens/latency.

Then: context ablation on S3 (drop neighbors / element_type / provenance).  
Only later: larger oracles, capability modules, live wiring.

---

## 7. Explicit non-goals (avoid rabbitholes)

- Universal code classifier of “what is a candidate” across web/PDF/PPT/Drive  
- Travel-specific outcome enums in core Python  
- Treating search filters as per-offer evidence  
- Averaging metrics across domains to hide domain failure  
- Live agent changes before offline GO on contract-discovery modes  

---

## 8. Related docs

| File | Role |
|------|------|
| `METHODOLOGY.md` | Operating methodology |
| `LEARNING_LOG.md` | Dated experiment entries |
| `DECISION_CONTRACT_DISCOVERY.md` | Contract discovery v0 |
| `DECISION_INTERPRETATION.md` | Interpretation layer |
| `OBSERVATION_CONTRACT.md` | Observation / channel contract |
| `ARCHITECTURE_MEMORY.md` | Host memory loop |

---

## 9. One-sentence summary

We moved from “smarter harvest and admissibility rules” to **structure as grounding, contracts as task-specific semantic specs, LLM for judgment, code for fail-closed mechanics** — and the candidate-selection pilot showed that **grounding (neighbors/context) is not optional** for LLM candidate decisions on the web.

---

## Evidence scopes (2026-08-26)

Booking sites often separate **list price** from **offer-complete** evidence:

```text
search list "vanaf €849"
   ≠
detail "All Inclusive - Aparthotel"
   ≠
price calculation after party/dates/board selected
```

| Scope | Meaning |
|-------|---------|
| search_list | Weak / incomplete; filters may be search_context only |
| detail_page | Hotel/package page may state board + flight + sample price |
| booking_state | Selected offer just before book — strongest price/board binding |

Pipeline remains fail-closed on UNKNOWN. Missing board/price-scope → evidence acquisition (browse/select), not inventing from URL meal=.

## Evidence acquisition loop (2026-08-27)

```text
CONTRACT.required
       │
       ▼
OBSERVE (page | file | sheet) + LIST_AFFORDANCES
       │
       ▼
CANDIDATE → INTERPRET → CODE eligibility
       │
       ├── all required PASS → STOP / REPORT
       │
       └── gaps (UNKNOWN|FAIL)
              │
              ▼
       ACQUISITION_DECIDE (LLM, enum-only, targets ⊆ affordances)
              │
              ▼
       CODE execute (or reject hallucinated targets)
              │
              ▼
       re-OBSERVE  (max steps; never irreversible commit)
```

**Cross-domain intent:** same loop for package sites, marketplaces, GPU configurators, literature folders, spreadsheets — only the **observer** changes; acquisition enum + gap logic stay shared.

## Trace / observability layer (2026-08-27)

`TraceSession` is a **forensic observer**, not a controller:

- Append-only `events.jsonl` (phases: task_start, observe, affordances, gaps, llm_call, code_policy, action, interpret, eligibility, acquisition, stop)
- Artifacts: full affordance lists, claim previews, truncated page text, LLM I/O
- Human `audit.md` + machine `summary.json` (url_sequence, affordance_flags, acquisition_decisions)

Wired into `run_acquisition_loop` via optional `trace=` and batch via `trace_root=`. Campaign slice defaults to `--trace` (disable with `--no-trace`). Flush-between-jobs remains for VRAM between entities.

Purpose: multi-task night runs + post-mortem of LLM acquisition choices (same-entity price tab vs marketing scope) without changing agent policy.

## Contract synthesis + FREEZE (2026-08-27)

Step 1 of the generic path (before sufficiency gate):

```text
task.md
  → synthesize_and_freeze_contract
       Pass 0  provisional (task only)
       gap-check (LLM)
       Pass 1+ refine / gap_revise
       FREEZE when ready_to_solve structural gaps are closed
  → frozen contract (claims + sufficiency as *data*)
```

- Entry: `contract_discovery.synthesize_and_freeze_contract` / `synthesize_contract_from_task_path`
- Batch: `scripts/run_contract_synthesis_batch_v0.py --tasks-dir tasks/batch_v0 [--llm]`
- Fallback: `heuristic_contract_generic` (domain-agnostic). Packages heuristic is fixture-only.
- Boundary: `docs/FRAMEWORK_BOUNDARY.md` — no board_type / offer_state runtime enums.

## Contract-driven execution (2026-08-27 → 28)

```text
task.md → frozen contract → acquisition loop
  → interpret (even if CU NOT_ADMISSIBLE, when claims exist)
  → outcomes → code sufficiency gate
  → gaps? → acquisition_decide → execute → anti-repeat
```

- Runner: `scripts/run_contract_driven_task_v0.py`
- **STOP authority:** code sufficiency only; LLM STOP rejected while gaps remain
- **Anti-repeat:** `action_key` blocked after one use (UI toggle ≠ progress)
- 01 vs 02 proved different contracts → different “done” without domain ifs

**Still open (ordered):** affordance panel options → identity interpret → list-surface provenance → 8-task batch.

Details: `LEARNING_LOG.md` (2026-08-28), `FRAMEWORK_BOUNDARY.md`.
