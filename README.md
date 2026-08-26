# Local Research Agent

General-purpose local research agent (Ollama + tools + Docker).

## How it works (start here)

- **[docs/METHODOLOGY.md](docs/METHODOLOGY.md)** — recon vs **retrieval**; **navigation · semantics · harvest**
- **[docs/LEARNING_LOG.md](docs/LEARNING_LOG.md)** — what we tested, what worked, what we abandoned
- **[docs/DECISION_CONTRACT_DISCOVERY.md](docs/DECISION_CONTRACT_DISCOVERY.md)** — Contract Discovery v0 (task-specific research contract)
- **[docs/DECISION_CONTRACT_EXECUTION.md](docs/DECISION_CONTRACT_EXECUTION.md)**
- **[docs/DECISION_INTERPRETATION.md](docs/DECISION_INTERPRETATION.md)** — Interpretation v0 (raw → normalized outcome → dumb gate) — Contract Execution v0.1 (generic decision executor)

```bash
# Learning only (no shortlist) — probes interface structure, not deals
docker compose run --rm research-agent python agent.py --planned \
  --run-kind recon --task tasks/recon_packages_hosts.md --browser-backend playwright

# Task delivery / web retrieval (default) — memory first
docker compose run --rm research-agent python agent.py --planned \
  --run-kind retrieval --task tasks/compare_packages_dec2026.md --browser-backend playwright
# alias: --run-kind research
```

**Recon** learns how hosts work. **Retrieval** gathers evidence for the user task (whole system = *research agent*).  
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
docker compose run --rm research-agent python agent.py --task tasks/example_vakantie.md
# optional flush architecture:
docker compose run --rm research-agent python agent.py --planned --task tasks/example_vakantie.md
```

Smoke browser:

```bash
docker compose run --rm research-agent python scripts/smoke_browser.py https://example.com
```

Inspect learnings:

```bash
cat memory/site_tactics.json
cat memory/site_recipes.json
cat memory/events.jsonl | tail
# after a run:
cat runs/<run_id>/host_learnings.md
```

### Browser Use (optional backend)

```bash
docker compose build   # installs browser-use from requirements.txt
docker compose run --rm research-agent python agent.py --planned \
  --task tasks/compare_packages_dec2026.md --browser-backend browser_use
```

## Config highlights

See `config.yaml`: `timeout_seconds`, `memory.*`, `safety.require_docker`.
