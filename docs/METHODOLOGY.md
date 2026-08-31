# Methodology — how this agent learns and retrieves

This document is the **mental model**: one simple picture of process steps.
Implementation details live in code; experiment history lives in `LEARNING_LOG.md`.

**Framework vs LLM content:** see `FRAMEWORK_BOUNDARY.md`.  
Code owns mechanism (observe, actions, provenance, sufficiency gate, trace).  
LLM owns contract *content* per `task.md` (which claims, required, what counts as enough evidence).  
Do **not** promote travel/GPU/marketplace field names into the runtime as fixed enums.

**Naming:** the whole system is the **research agent**. Inside it, web work splits into:

| Name | CLI | Role |
|------|-----|------|
| **Recon** | `--run-kind recon` | Learn *how* hosts work |
| **Retrieval** | `--run-kind retrieval` (alias: `research`) | Fetch & structure evidence for a task |

Reasoning / critic / report sit *above* retrieval. Do not call the delivery web phase “research” in new docs — that word means the whole agent.

---

## 1. Two run kinds (strict separation)

```
┌─────────────────────┐         ┌─────────────────────┐
│  RECON (learning)   │         │  RETRIEVAL (delivery)│
│  --run-kind recon   │         │  --run-kind retrieval│
├─────────────────────┤         ├─────────────────────┤
│ Learn HOW hosts     │  ──►    │ Answer the USER task │
│ work (capability)   │ memory  │ using memory first   │
│                     │         │                      │
│ NO shortlist        │         │ shortlist + report   │
│ NO ranking          │         │ honest constraints   │
│ Goal = interface    │         │ Goal = verified      │
│ intelligence        │         │ candidates           │
└─────────────────────┘         └─────────────────────┘
         │                                │
         └──────── global memory ─────────┘
              navigation · semantics · harvest
```

- **Recon** optimizes for **learnable structure**, not finishing a booking.
- **Retrieval** executes recipes and verifies claims. Runtime **blocks** `add_to_shortlist` in recon.
- Legacy alias: `--run-kind research` → same as `retrieval`.

---

## 2. Host capability model (three layers)

Weak research yields often mean: navigation OK, semantics/harvest weak.

| Layer | Question | Examples stored |
|--------|----------|-----------------|
| **Navigation** | How do I reach a useful search/list surface? | preferred_channel, path hints, failed tiers |
| **Semantics** | What does each field/param *mean*? | rewrites, ignored keys, “count looks like date” |
| **Harvest** | Can we extract *relational* evidence? | `price_signals` (discovery only), `relationships_extractable` (unknown\|partial\|ok\|failed), success/fail counts |

```
HOST MEMORY
├── navigation
├── semantics
└── harvest
    ├── price_signals          ← discovery only
    ├── relationships_extractable
    └── success_count / failure_count
```

Recon success ≠ “found a deal”.  
Recon success = enough of the three layers to **replay cheaply** on the next research task.  
**`price_signals=true` does not imply relationships are extractable.**

---

## 3. Recon: probe style (not “easy booking”)

Prefer **several small probes** over one full form flow:

1. Can destination change the URL / results?
2. Date encoding and stay-length semantics?
3. Pax: which params (or UI only)?
4. Meal/filter: URL vs UI vs ignored?
5. Final URL after open vs requested?
6. Results list: names + prices visible?
7. Which params are silently dropped?

**Stop per host** when navigation + key semantics + a harvest signal are known, or budgets hit.  
**Never** checkout / payment. List page (+ optional one detail) is enough.

Dev helper: `tasks/recon_*.md` may list hosts. Core logic stays domain-agnostic.

---

## 4. Retrieval: execute, don’t rediscover

```
Memory-first deep-link / preferred channel
        │
        ▼
Cheap verify (fetch or browser_open)
        │
   ┌────┴────┐
 success   structural fail
        │         │
   harvest     note needs_recon
   shortlist   next host / later recon
```

- Tier 3 (Browser Use) is **not** the default retrieval path.
- Structural fail (broken param encoding, ignored critical filter) ≠ empty inventory.
- Empty inventory after a *correct* search is a valid retrieval outcome.
- URL rewrite by the site is usually **normal app routing / defaults**, not “bot detection”.

**Future:** optional inline recon burst on `needs_recon` (still no shortlist), then one retrieval retry.

---

## 4b. Retrieval evidence contract (code-first)

```
Discovery signals (price_hints, raw text)
        ↓
PageState          match + page_role + usable_for_task
        ↓
Structure          primary_subject + groups + members
        ↓
Minimal Awareness  adequate | partial | insufficient
        ↓ usable?  role≠landing?  awareness≠insufficient?
   no → observations only
   yes↓
Structure-first evidence units (group members / primary subject)
        ↓  scope classification (primary|group|related|chrome|element)
Evidence buffer → evidence.jsonl + shortlist layer=evidence
        ↓  ConstraintResults (matched/unmatched/unknown)
Eligibility policy (eligible | ineligible | uncertain)
        ↓  rankable only if eligible AND scope∈{primary,group} AND layer≠evidence-only
Ranked candidates (report shortlist)
```

**Hard separations**

| Object | Answers |
|--------|---------|
| **PageState** | Where is the site relative to the request? What *kind* of surface (`page_role`)? |
| **Structure** | What subjects/groups exist on this surface (containment, not taxonomy)? |
| **Minimal Awareness** | Do we have *enough* signals to evaluate constraints without inventing facts? |
| **Evidence** | What does the page claim about a subject (entity + value_role + **scope**)? |
| **ConstraintResult** | Facts vs task hard criteria (matched / unmatched / unknown) |
| **Eligibility** | Policy over ConstraintResults + scope + page usable — may this enter ranking? |
| **RankedCandidate** | Eligible evidence only; report ranks this set |

### Minimal Awareness Context (MinAC)

**Not** “maximum awareness” (DOM + AX + OCR + layout always).  
**Yes** the *minimum* set of structural signals so the agent can answer the user task honestly.

| Dimension | Meaning |
|-----------|---------|
| `page_usable` | Query state matches task enough to trust values |
| `subject_identity` | At least one structure member or primary_subject |
| `primary_values` | At least one primary amount signal |
| `entity_value_link` | At least one paired entity↔value observation |

```
awareness.status:
  adequate      usable + subject + values + link
  partial       usable, some signals, gaps remain
  insufficient  not usable, or no subject and no values, or landing
```

- `insufficient` → observations only (`skipped_reason=awareness_insufficient`).
- Perception cascade (DOM → AX → screenshot/OCR) is a **future cost ladder**, not the default. Current MinAC is filled from Playwright text/DOM harvest.
- Memory may hypothesise *how* to obtain these dimensions cheaply; only current PageState says *what is true now*.

### PageState schema
```
{
  requested_url, observed_url,
  match: full | partial | mismatch | unknown,
  page_role: unknown | landing | list | detail,
  usable_for_task: bool,
  mismatches: [...],
  semantic_flags: [...],
  structure: {
    primary_subject: { id, label, kind: "unknown" } | null,
    groups: [ { id, member_count, sample_labels, sample_values, members } ],
    members: [ { id, entity, value, entity_score, confidence, ... } ],
    member_count: int,
    method: "eav_cluster_structure"
  },
  awareness: {
    status: adequate | partial | insufficient,
    have: [...], gaps: [...], method: "minimal"
  },
  provenance: { method, ... }
}
```
- `page_role` is structural (path/query/title heuristics). **unknown is valid.**
- `landing` → observations only (no evidence-buffer promote).
- `detail` → prefer scope=`primary`; low-score neighbors → `related` (not top-level).
- `list` → scope=`group`; **evidence units = structure members**, not free-floating EAVs.
- `structure.kind` stays **`unknown`** — promotion must never require `kind==hotel|product`.
- Mismatch / `usable_for_task=false` / `awareness=insufficient` → observations only.

### Evidence scope
```
primary   main subject on a detail surface
group     offer-level row on a list surface
related   secondary subject on detail (similar items) — not top-level
chrome    UI / amenity / marketing copy next to prices — observations only
element   line-item / SKU under an offer — observations only
```

### Evidence schema
```
{
  observed: {
    entity, value, value_role, scope,
    confidence, confidence_breakdown: { entity, value, relationship, state, overall },
    entity_score, marketing_penalty, source_url, raw_evidence
  },
  verified: {},
  unknown: [...],
  page_state_ref: { match, usable_for_task, page_role },
  provenance: { source_url, extraction_method, raw_evidence }
}
```

### Dataflow layers (iter 2)
| Store | Content |
|-------|---------|
| `observations.jsonl` | Raw EAV signals (all scopes) |
| `evidence.jsonl` | Gated evidence rows (primary/group) awaiting constraints |
| `shortlist.json` | Mixed buffer; rows carry `layer=evidence\|candidate` |
| Ranked view | `filter_rankable_shortlist` — eligibility + scope + layer gates |

### ConstraintResult vs Eligibility
- **ConstraintResult** = factual match status.
- **Eligibility** = policy gate (`eligible` | `ineligible` | `uncertain`).
- Runtime harvest always: `layer=evidence`, `eligibility=ineligible`, `rankable=false`.
- LLM `add_to_shortlist` → `layer=candidate`; eligibility from ConstraintResults via policy — **not** a free-form LLM “is this a candidate?” decision.
- Default ineligible: observed_only, chrome/related/element scope, landing page_role, mismatch page.

### Harvest capability subscores (host memory)
```
harvest:
  has_price_signals: bool
  relationships_extractable: unknown | partial | ok | failed
  success_count / failure_count
```
- `price_signals=true` ≠ relationships extractable.

### Invariants
- Harvest reconstructs structural entity↔attribute↔value links — **not** vertical product detection.
- chrome / related / element → never top-level ranked candidates.
- Auto-harvest never sets `rankable=true`.
- **No product-vertical word lists.**
- Inline recon: memory only; clear `needs_recon` only without severe param rewrite.

## 4c. Progress-aware control (agent control loop)

Harvest and PageState are not enough if the agent keeps clicking the same surface.

```
ACTION
  → OBSERVATION
  → deltas:
      state_changed          URL / page surface
      observation_delta      new information (first harvest on URL key,
                             param mismatch discovered, empty inventory)
      evidence_added
      constraint_improved
      candidate_added
  → had_progress?
       yes → streak = 0
       no  → streak += 1 (or += 2 if repeated same tool+surface)
  → streak ≥ max_zero_progress_per_host
  → session host abandon
       needs_recon only if host never yielded evidence this session
       else interaction_blocked (list already useful; stop clicking)
```

**Principles (A′)**
- Progress = **state / information delta**, not side-effects.
- **`memory_updated` is not progress** (derived from events, not a progress signal).
- Diminishing returns: repeated same `(tool, url_key)` with no delta costs extra toward abandon.
- Classic no-op (same URL + no new price_hints) remains.
- Config: `limits.max_zero_progress_per_host` (default = `max_browser_noops_per_host`).
- Metadata: `progress_events`, `progress_hits`, `progress_ratio`.

## 4d. Page structure + member admissibility + structure-first evidence

```
PageState.structure
  primary_subject: { id, label, kind: "unknown" } | null
  groups: [ { id, member_count, sample_labels[], sample_values[], members[] } ]
  members: [ admissible members only ]
  rejected_members: [ { entity, value, reject_reason, features } ]
  admissibility_stats: { accept, reject_cta, reject_geo_nav, ... }
  candidate_count: int
```

### Four epistemic questions (keep separate)

| Layer | Question |
|-------|----------|
| **Candidate unit** | Could this fragment be a useful evidence unit for the task? (incomplete OK) |
| **MinAC** | Do we know *enough* about the surface / unit? |
| **Constraints / interpretation** | What does the evidence mean under each decision? |
| **Eligibility** | Do normalized outcomes satisfy the required set? → ranked shortlist |

**Candidate ≠ eligibility (2026-08-26, grounding ablation A4):**  
Never ask the candidate LLM “are all task fields already proven on this unit?”. That is eligibility.  
Task in the candidate step is a **relevance filter**, not a completeness checklist.  
See `ARCHITECTURE_JOURNEY.md` § Phase F and `LEARNING_LOG.md` grounding ablation entry.

Legacy “member admissibility” ≠ MinAC. A clear room-only offer can be a **candidate unit** even if the user asked all-inclusive — constraints then FAIL. Never fold task constraints into MinAC or candidate selection.

### Admissibility (legacy experimental baseline — not product default)

> **Ground rule (2026-08-26):** Code may *describe* structure; the LLM may *interpret* role/relevance; code may *enforce* schema/eligibility.  
> Classifying CTA vs offer vs destination is **semantic** — do not grow deterministic phrase/feature classifiers as the long-term path. Prefer grounded LLM **CANDIDATE_UNIT** selection (S3 / A5-style context). See `ARCHITECTURE_JOURNEY.md` §2.

Historical deterministic path (kept for ablation only):

```
candidate members (entity + primary value)
        ↓
assess_member_admissibility → features + reject_reason | accept
        ↓
structure.members = accepted only
```

Features were experimental (`looks_like_cta`, `geo_signal`, …). Prefer structure as **grounding context** for LLM, not as a meaning filter.

**Structure-first promote (still valid for observation packaging):** evidence buffer gets literal members + channels; ranking never keys on vertical `kind`.

## 5. Web capability ladder (per host)

```
  Tier 0   Memory (navigation + semantics + harvest)
                │ miss or stale
                ▼
  Tier 1   HTTP fetch / search
                │ fail / empty / 403
                ▼
  Tier 2   Playwright deep-link + limited clicks
                │ complex UI only (prefer in recon)
                ▼
  Tier 3   Browser Use (last resort, narrow instruction)
```

**Guards:** memory-first open, param-warning strip, soft mismatch, empty-inventory cap, no-op/consent, **progress-aware abandon**, shortlist honesty.

---

## 6. What is stored where

| Layer | Where | Cross-task? |
|--------|--------|-------------|
| Run evidence | `runs/<id>/` | No |
| Host capability | `memory/site_recipes.json` (+ tactics, url_patterns) | **Yes** |
| Operator view | `host_learnings.md` | Snapshot |

---

## 7. One-liners

- **Recon:** “What is the structural interface of this site, and how do I reach extractable results cheaply?”
- **Research:** “Given that model, answer *this* task with verified candidates.”
- **Candidate step:** “Could this unit matter for the task?” (incomplete OK).
- **Eligibility step:** “Do normalized outcomes satisfy the contract?” (code).
- **Offline pipeline (2026-08-26):** observation → CANDIDATE_UNIT → interpretation → code eligibility.
  Measure each stage separately; never collapse into one “works/doesn’t” score.

---

## Candidate extraction before interpretation (2026-08-28)

**Method rule:** when a page may contain multiple parallel items (list results, search hits, comparison tables), do **not** treat the page as one bag of claims. Extract **Candidates** first (structural packaging), then interpret candidate-bound evidence under the frozen contract.

Offline verification is mandatory for changes to packaging/candidate shape:

```bash
python scripts/run_candidate_extraction_offline_v0.py \
  --manifest evals/candidate_offline/fixtures_from_traces/manifest.json \
  --outdir ./evals/candidate_offline
```

Live contract-driven runs remain the integration test *after* offline GO. See `docs/CANDIDATE_LAYER.md`.


---

## 8. MinAC as a principle (not only a recon checklist)

**Minimal Awareness Context** is the general rule: *what is the cheapest signal that lets this consumer safely proceed?* Escalate only when that signal is insufficient.

Today MinAC is written for recon/retrieve (page_usable, subject_identity, primary_values, entity_value_link). The same *principle* applies on other axes:

| Axis | Cheap → expensive | Consumer examples |
|------|-------------------|-------------------|
| **Access** (Tier 0–3) | memory → HTTP → Playwright → browser-use | reach a usable page |
| **Representation** (F1) | light HTML tags → AX tree → AX+viewport vision | structure for CD samples *and* candidates |
| **Memory compression** (future) | structured JSON facts + raw pointers → free-text summary | survive long multi-step work without drift |

**Consumer-relative MinAC:** Contract Discovery and candidate extraction do **not** need the same richness (Agent-E: different DOM forms for interaction vs summarization). Prefer:

```text
MinAC(consumer, signal) → adequate | partial | insufficient + missing_dims
```

Escalation triggers must stay **structural** (token size, presence of semantic tags/roles, empty containers) — never domain `if site == …`.

**Perception ladder (aligned with existing note in §4b):**

```text
R0  semantic HTML / light DOM tags     (cheapest)
R1  computed AX tree                   (moderate)
R2  AX + selective viewport screenshot (expensive; supporting signal, not default primary)
```

Same rule as host tiers: cheapest first; escalate on MinAC insufficient. Literature is mixed on whether vision always helps — **measure**, do not assume. Offline A/B: `scripts/run_representation_ab_offline_v0.py`.

Do not implement R1/R2 as live default until offline metrics justify the cost.
