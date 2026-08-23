# Methodology — how this agent learns and retrieves

This document is the **mental model**: one simple picture of process steps.
Implementation details live in code; experiment history lives in `LEARNING_LOG.md`.

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
        ↓ usable_for_task?  /  page_role=landing?
   no → observations only
   yes↓
Structural regions / clusters
        ↓
EAV observations → observations.jsonl
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
| **Evidence** | What does the page claim about a subject (entity + value_role + **scope**)? |
| **ConstraintResult** | Facts vs task hard criteria (matched / unmatched / unknown) |
| **Eligibility** | Policy over ConstraintResults + scope + page usable — may this enter ranking? |
| **RankedCandidate** | Eligible evidence only; report ranks this set |

### PageState schema
```
{
  requested_url, observed_url,
  match: full | partial | mismatch | unknown,
  page_role: unknown | landing | list | detail,
  usable_for_task: bool,
  mismatches: [...],
  semantic_flags: [...],
  provenance: { method, ... }
}
```
- `page_role` is structural (path/query/title heuristics). **unknown is valid.**
- `landing` → observations only (no evidence-buffer promote).
- `detail` → prefer scope=`primary`; low-score neighbors → `related` (not top-level).
- `list` → scope=`group` for offer cards.
- Mismatch / `usable_for_task=false` → observations only.

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

**Guards:** memory-first open, param-warning strip, soft mismatch, empty-inventory cap, no-op/consent, shortlist honesty.

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
