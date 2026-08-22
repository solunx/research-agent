# Methodology — how this agent learns and researches

This document is the **mental model**: one simple picture of process steps.
Implementation details live in code; experiment history lives in `LEARNING_LOG.md`.

---

## 1. Two run kinds (strict separation)

```
┌─────────────────────┐         ┌─────────────────────┐
│  RECON (learning)   │         │  RESEARCH (delivery)│
│  --run-kind recon   │         │  --run-kind research│
├─────────────────────┤         ├─────────────────────┤
│ Learn HOW hosts     │  ──►    │ Answer the USER task│
│ work (capability)   │ memory  │ using memory first  │
│                     │         │                     │
│ NO shortlist        │         │ shortlist + report  │
│ NO ranking          │         │ honest constraints  │
│ Goal = interface    │         │ Goal = verified     │
│ intelligence        │         │ candidates          │
└─────────────────────┘         └─────────────────────┘
         │                                │
         └──────── global memory ─────────┘
              navigation · semantics · harvest
```

- **Recon** optimizes for **learnable structure**, not finishing a booking.
- **Research** executes recipes and verifies claims. Runtime **blocks** `add_to_shortlist` in recon.

---

## 2. Host capability model (three layers)

Weak research yields often mean: navigation OK, semantics/harvest weak.

| Layer | Question | Examples stored |
|--------|----------|-----------------|
| **Navigation** | How do I reach a useful search/list surface? | preferred_channel, path hints, failed tiers |
| **Semantics** | What does each field/param *mean*? | rewrites, ignored keys, “count looks like date” |
| **Harvest** | Where are names, prices, links on the page? | price_hints signal, extract hints |

```
HOST MEMORY
├── navigation
├── semantics
└── harvest
```

Recon success ≠ “found a deal”.  
Recon success = enough of the three layers to **replay cheaply** on the next research task.

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

## 4. Research: execute, don’t rediscover

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

- Tier 3 (Browser Use) is **not** the default research path.
- Structural fail (broken param encoding, ignored critical filter) ≠ empty inventory.
- Empty inventory after a *correct* search is a valid research outcome.

**Future:** optional inline recon burst on `needs_recon` (still no shortlist), then one research retry.

---

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
