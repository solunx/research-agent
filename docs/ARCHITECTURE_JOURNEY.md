# Architecture Journey — Local Research Agent

**Purpose:** Durable record of *why* the architecture looks the way it does.  
Read this before changing harvest, admissibility, contracts, or LLM wiring.

**Last major update:** 2026-08-26 (after candidate-selection pilot with real LLM).

---

## 1. Starting problem

We wanted a **generic research agent**: given `task.md`, retrieve evidence from the web (and later other sources), and produce a grounded answer/shortlist — without hardcoding “hotel”, “all-inclusive”, or site-specific scrapers into the core.

Early reality (Aug 2026):

- Ollama context crashes on long single chats → external notes + shortlist + planned phases.
- Playwright deep-links work when recipes exist; Browser Use is slow last resort.
- Host memory (tactics/recipes/URL patterns) is global; run content stays per run.
- **Finding information ≠ having rankable candidates.** Harvest saw prices and names; shortlist often stayed empty or filled with noise.

---

## 2. The central insight (locked in)

> **Code owns mechanics, structure, provenance, validation, and fail-closed gates.**  
> **LLM owns meaning: what counts as a candidate, what a phrase means under a task, what decisions the task needs.**

Anything that requires *understanding language in context of the user task* does **not** belong in permanent Python rules for a generic agent.

What *does* belong in code:

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
| **S5 hybrid**: cost savings but inherits aggressive prefilter (docs R=0.5) | Prefilter only for *obvious chrome*, not content types |
| Pilot n is small (4–8 units/domain) | S3 is best *on this pilot*, not proven universal |

### Phase F — Current architecture hypothesis (2026-08-26)

```text
TASK
  → [LLM] provisional Research Contract (what to decide / require)
  → Capabilities (web/pdf/…) produce STRUCTURAL units + provenance
  → [LLM] grounded candidate/evidence selection + contract refine
  → [LLM] interpretation of claims → normalized outcomes
  → [CODE] eligibility / ranking / report mechanics
```

**Not pursued as product direction:** universal `admissibility.py` with more phrase rules.

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
│ (LLM, schema-constrained)│            │ (prefer grounded LLM S3)     │
│                          │            │                              │
│ CD0 task-only            │            │ structural units + task +    │
│ CD1 task+samples one-shot│            │ neighbors → ADMISSIBLE /     │
│ CD2 provisional→refine   │            │ NOT / UNKNOWN                │
│                          │            │                              │
│ → subject, decisions,    │            │ Capabilities may deprioritize│
│   outcomes, sufficiency  │            │ obvious chrome only          │
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
| **Candidate selection** | Is this unit a candidate under the task? | Grounded LLM (hypothesis) |
| **Interpretation** | What does this claim mean under decision X? | LLM |
| **Eligibility** | Do normalized outcomes satisfy required set? | Code |
| **Host learning** | How does this site’s interface work? | Memory + recon |

---

## 5. Experiment map (what we measured)

| Campaign | Question | Main result |
|----------|----------|-------------|
| Interpretation single/multi | Can LLM normalize claims without domain code? | Yes (packages + literature) |
| Vertical slice ± batch | Real/fixture evidence → eligibility chain? | Safety + positive paths work |
| Admissibility recall/ablation | Can structure alone keep hotels, drop chrome? | Chrome yes; long titles / docs weak |
| **Candidate selection pilot** | Structural vs raw LLM vs grounded LLM vs hybrid? | **S3 best**; S2 web fails; structure weak on docs |

---

## 6. Choices for the *next* tests (from 2026-08-26)

We are **not** optimizing board synonyms or hotel heuristics further.

**Next scientific question:**

> Is contract discovery a **one-shot** problem (task±data → final contract), or an **iterative grounding** problem (task → provisional → samples → refine)?

Modes to measure:

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
