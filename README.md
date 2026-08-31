# Local Research Agent

General-purpose local research agent (Ollama + tools + Docker).

## How it works (start here)

- **[docs/METHODOLOGY.md](docs/METHODOLOGY.md)** — recon vs **retrieval**; **navigation · semantics · harvest**
- **[docs/LEARNING_LOG.md](docs/LEARNING_LOG.md)** — what we tested, what worked, what we abandoned
- **[docs/DECISION_CONTRACT_DISCOVERY.md](docs/DECISION_CONTRACT_DISCOVERY.md)** — Contract Discovery v0 (task-specific research contract)
- **[docs/DECISION_CONTRACT_EXECUTION.md](docs/DECISION_CONTRACT_EXECUTION.md)**
- **[docs/DECISION_INTERPRETATION.md](docs/DECISION_INTERPRETATION.md)** — Interpretation v0 (raw → normalized outcome → dumb gate) — Contract Execution v0.1 (generic decision executor)

## Quick start (canonieke productiepad)

Contract-driven: `task.md` → frozen contract → acquisition loop → code sufficiency STOP.  
Zie `docs/FRAMEWORK_BOUNDARY.md`. **Niet** `agent.py` — dat is legacy (onderaan).

```bash
# 1) Contract synthesis (eenmalig per task-set, of opnieuw bij task-wijziging)
docker compose run --rm research-agent \
  python scripts/run_contract_synthesis_batch_v0.py \
  --tasks-dir tasks/batch_v0 \
  --outdir ./evals/contract_synthesis \
  --llm --max-passes 3

# 2) Live run (01 + 02 smoke)
docker compose run --rm research-agent \
  python scripts/run_contract_driven_task_v0.py \
  --tasks 01_web_hotel_package_concrete,02_web_hotel_property_only \
  --tasks-dir tasks/batch_v0 \
  --contract-dir evals/contract_synthesis/<synthesis_run> \
  --llm --outdir ./evals/contract_driven

# 3) Batch (default = contract-driven; vereist --contract-dir)
docker compose run --rm research-agent \
  python scripts/run_task_batch_campaign_v0.py \
  --tasks-dir tasks/batch_v0 \
  --contract-dir evals/contract_synthesis/<synthesis_run> \
  --outdir ./evals/task_batch \
  --llm --flush-between-jobs
```

**Recon** (legacy agent) leert hoe hosts werken; **contract-driven retrieval** verzamelt bewijs t.o.v. een frozen contract.  
`tasks/recon_*.md` files are **dev helpers**; core logic stays domain-agnostic.

## Phases implemented

### Stability
- LLM timeout default **480s** (long reports)
- Forced report from **notes only** (not full chat history)
- Tool duration logging in CLI
- `llm.py` defaults match `config.yaml` (`qwen3.8:27b`)

### Evidence outside context
- `runs/<id>/notes.jsonl` – compact observations per tool
- `runs/<id>/research_state.json|md` – progress snapshot

### Self-learning host capability (global, cross-task)
- `memory/site_tactics.json` – preferred tool / tier outcomes
- `memory/site_recipes.json` – channels + **navigation / semantics / harvest** (`price_signals`, `relationships_extractable`, counts) + `needs_recon` + `human_setup_needed`
- `memory/site_url_patterns.json` – deep-link/param shapes
- `memory/general_strategies.json` – pattern rules (incl. recon probe tactics)
- `memory/events.jsonl` – success/fail log
- Injected into system prompt at run start
- **Host knowledge is shared across all tasks** (never re-discover the same failure)
- Run ends with `runs/<id>/host_learnings.md` (capability scores / human setup)
- 403/blocked → recorded → next run prefers cheaper successful channel

### Generic (no travel hardcoding)
- Prompts and tool descriptions are domain-agnostic
- Escalation: cheap fetch first, browser on failure
- Search query soft-guardrail (keyword-length, not domain rules)

### Planner / executor / critic (optional)
- `--planned`: split task into ≤5 independent sub-tasks, **fresh LLM context per sub-task** (flush), shared `notes.jsonl`, final synthesis from notes only
- Default remains single-session (same as before)

### Safety / web policy
- Refuses host run if `/.dockerenv` missing (`safety.require_docker`)
- Override: `ALLOW_HOST_RUN=1` or `require_docker: false`
- **Honest browser**: no anti-detect / webdriver cloaking (Playwright may be recognized as automation)
- **CAPTCHA / bot-wall**: `policy_stop` → host abandoned for the session (no bypass)
- **`web_policy`**: rolling per-host rate limits + cooldown after 403/429/CAPTCHA (`memory/domain_policy.json`)
- **PageState** (`match` + `page_role`: landing|list|detail|unknown) + **eligibility** policy
- **Page structure**: `primary_subject` (`kind=unknown`) + `groups` + `members` from EAV clusters
- **Member admissibility** (before MinAC): may this object be an evidence unit? Features + reject_reason (`reject_cta`, `reject_geo_nav`, …); only accepted members enter structure
- **Minimal Awareness Context (MinAC)**: only the signals needed for honest constraint evaluation (`adequate` / `partial` / `insufficient`) — not maximum multi-modal capture
- **Structure-first promote**: evidence units = *admissible* structure members; free-floating chrome EAVs stay out
- **Evidence scope**: primary|group|related|chrome|element — chrome/related/element never rankable
- **Layers**: observations → evidence buffer → ranked candidates (only when eligible)
- Harvest: structural entity↔value; multi-confidence; no product-vertical word lists
- Host harvest subscore: `price_signals` ≠ `relationships_extractable`
- **Progress-aware control (A′)**: state/observation/evidence/candidate/constraint deltas; `memory_updated` ≠ progress; repeated same surface costs extra; `needs_recon` only if no evidence this session

## Run

```bash
docker compose build
```

Canonieke live-entry: `scripts/run_contract_driven_task_v0.py` (zie Quick start).

Smoke browser:

```bash
docker compose run --rm research-agent python scripts/smoke_browser.py https://example.com
```

Inspect learnings:

```bash
cat memory/site_tactics.json
cat memory/site_recipes.json
cat memory/events.jsonl | tail
```

## Config highlights

See `config.yaml`: `timeout_seconds`, `memory.*`, `safety.require_docker`.

## Architecture docs (read order for reviews)

1. `docs/FRAMEWORK_BOUNDARY.md` — what code may hardcode vs LLM contract content
2. `docs/CANDIDATE_LAYER.md` — intermediate page object model (2026-08-28)
3. `docs/ARCHITECTURE_JOURNEY.md` — why the system evolved this way
4. `docs/LEARNING_LOG.md` — dated experiments and outcomes
5. `docs/METHODOLOGY.md` — recon vs retrieval, host memory, method rules
6. `docs/DECISION_CONTRACT_DISCOVERY.md` / `DECISION_CONTRACT_EXECUTION.md` — contract path

### Offline candidate probe (no LLM / no browser)

```bash
python scripts/run_candidate_extraction_offline_v0.py \
  --manifest evals/candidate_offline/fixtures_from_traces/manifest.json \
  --outdir ./evals/candidate_offline
```

## Legacy (pre-contract-driven, wordt uitgefaseerd)

`agent.py` is het pre-contract-driven retrieval-pad (laatste inhoudelijke touch ~2026-08-20/23).  
Het is **niet** het aanbevolen productiepad. Boundary-audit 2026-08-29: dit pad loopt via `storage.py` / `candidate_admissibility.py` / `member_role.py` (lexicon-gates). Niet repareren — uitfaseren.

Alleen voor vergelijking met oude `runs/`-artifacts of `--legacy-agent` batches:

```bash
# Learning only (no shortlist) — probes interface structure
docker compose run --rm research-agent python agent.py --planned \
  --run-kind recon --task tasks/recon_packages_hosts.md --browser-backend playwright

# Task delivery / web retrieval (legacy)
docker compose run --rm research-agent python agent.py --planned \
  --run-kind retrieval --task tasks/compare_packages_dec2026.md --browser-backend playwright

docker compose run --rm research-agent python agent.py --task tasks/example_vakantie.md
docker compose run --rm research-agent python agent.py --planned --task tasks/example_vakantie.md

# Browser Use backend (legacy agent only)
docker compose run --rm research-agent python agent.py --planned \
  --task tasks/compare_packages_dec2026.md --browser-backend browser_use

# Batch via legacy agent (expliciete vlag vereist)
docker compose run --rm research-agent \
  python scripts/run_task_batch_campaign_v0.py \
  --legacy-agent \
  --tasks-dir tasks/batch_v0 \
  --outdir ./evals/task_batch
```

`tasks/recon_*.md` blijven dev helpers. Core logic blijft domain-agnostic; criteria komen uit het frozen contract, niet uit `agent.py`.

