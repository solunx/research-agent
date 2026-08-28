# Task batch v0 — multi-domain micro-tasks

Natural-language tasks only. **No fixed outcome enums** in these files.

The agent (or future contract-synthesis pass) must derive claims and sufficiency from the text.

| ID | Domain | Intent sketch |
|----|--------|----------------|
| 01 | Web packages | Concrete bookable offer (price + board + flight binding) |
| 02 | Web hotel | Property-only (All Inclusive on detail — stop early OK) |
| 03 | Web retail | GPU product page + VAT price |
| 04 | Marketplace | Second-hand GPU listing |
| 05 | Literature | Paper abstract claim |
| 06 | Wiki | Single fact + citation |
| 07 | Files | xlsx headers if present |
| 08 | Web compare | Two-site price comparison |

## Run

```bash
# All tasks in this folder (agent.py per task, flush between jobs)
docker compose run --rm research-agent \
  python scripts/run_task_batch_campaign_v0.py \
  --tasks-dir tasks/batch_v0 \
  --outdir ./evals/task_batch \
  --llm --flush-between-jobs \
  --max-hours 6 --job-timeout-s 1800

# Subset
docker compose run --rm research-agent \
  python scripts/run_task_batch_campaign_v0.py \
  --tasks-dir tasks/batch_v0 \
  --only 02_web_hotel_property_only,06_web_wiki_fact \
  --outdir ./evals/task_batch --llm --flush-between-jobs
```

## Design note

01 vs 02 is intentional: same host family, **different completeness requirements in the task text**.  
Contract synthesis should yield different required claims — not a hardcoded `offer_state` enum in Python.

See `docs/FRAMEWORK_BOUNDARY.md`.
