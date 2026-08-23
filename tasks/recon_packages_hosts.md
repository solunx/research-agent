# Recon targets (learning only — not a research delivery)

Use with:

```bash
docker compose run --rm research-agent python agent.py --planned \
  --run-kind recon \
  --task tasks/recon_packages_hosts.md \
  --browser-backend playwright
```

## Goal of this run

Build a **host capability model** (not a vacation shortlist):

1. **Navigation** — how to reach search/list (channel, path)
2. **Semantics** — what params/fields mean (rewrites, ignored keys, encodings)
3. **Harvest** — whether results show names + prices (and roughly how)

Optimize for **learnable structure at low cost**.  
Success can mean: “we understand the interface” even with **zero** bookable deals.

**Do not** `add_to_shortlist`. **Do not** rank products for a user. **Do not** go to checkout.

## Hosts to probe (dev list)

1. nl.lastminute.com / lastminute.be — package search surface  
2. sunweb.be — all-inclusive search surface  
3. corendon.be — package search surface  

(This file is a **dev helper**. Production recon should take hosts from flags / primary sources of a research task — no domain logic in core code.)

## Probe approach (generic)

Prefer **several small probes** over one “complete easy booking”:

1. Open a deep-link / search URL (not bare homepage if patterns exist).
2. Change **one** dimension when possible (destination *or* dates *or* pax *or* meal-like filter).
3. Compare **requested URL vs final URL** after load.
4. Note ignored / rewritten params (especially occupancy vs date-like keys).
5. Confirm a **results list** can show names + price signals (broader values OK for learning).
6. Optional: one detail page — stop before booking.
7. Stop per host when navigation + key semantics + harvest signal are clear, or empty/no-op budgets hit.

## Output

`RESEARCH_COMPLETE` with a **per-host mechanism summary** only:

- navigation: channel / paths  
- semantics: param findings  
- harvest: price/name signals or “not observed”  
- failures / needs human setup  

## After recon

```bash
docker compose run --rm research-agent python agent.py --planned \
  --run-kind research \
  --task tasks/compare_packages_dec2026.md \
  --browser-backend playwright
```

Research should reuse global memory without rediscovering the same host from scratch.
