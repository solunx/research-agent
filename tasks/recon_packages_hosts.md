# Recon targets (learning only — not a research delivery)

Use with:

```bash
docker compose run --rm research-agent python agent.py --planned \
  --run-kind recon \
  --task tasks/recon_packages_hosts.md \
  --browser-backend playwright
```

## Goal of this run

Discover **how** these hosts work (search URL shapes, query param names/semantics,
cookie walls, empty vs non-empty inventory). Store that in global memory.

**Do not** build a vacation shortlist. **Do not** rank hotels for a user.

## Hosts to probe (primary)

1. nl.lastminute.com / lastminute.be — package / vacation search
2. sunweb.be — all-inclusive search
3. corendon.be — package search

## Learning approach (generic)

1. Prefer deep-link / search URLs over bare homepages when patterns exist.
2. First successful results page matters more than strict filters: use simpler
   combinations if needed so a list page appears (learning, not the final task).
3. Note which params the site rewrites or ignores.
4. Stop per host after a working pattern is clear OR empty-inventory budget is hit.
5. Output RESEARCH_COMPLETE with a per-host mechanism summary only.

## After recon

Run the real task with `--run-kind research` (default) so recipes/param_warnings
from this run are reused without rediscovery.
