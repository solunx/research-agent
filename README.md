# Local Research Agent

General-purpose local research agent (Ollama + tools + Docker).

## Phases implemented

### Stability
- LLM timeout default **480s** (long reports)
- Forced report from **notes only** (not full chat history)
- Tool duration logging in CLI
- `llm.py` defaults match `config.yaml` (`qwen3.8:27b`)

### Evidence outside context
- `runs/<id>/notes.jsonl` – compact observations per tool
- `runs/<id>/research_state.json|md` – progress snapshot

### Self-learning tool routing
- `memory/site_tactics.json` – per-domain preferred tool
- `memory/general_strategies.json` – pattern rules
- `memory/events.jsonl` – success/fail log
- Injected into system prompt at run start
- 403/blocked → recorded → next run prefers `browser_open`

### Generic (no travel hardcoding)
- Prompts and tool descriptions are domain-agnostic
- Escalation: cheap fetch first, browser on failure
- Search query soft-guardrail (keyword-length, not domain rules)

### Planner / executor / critic (optional)
- `--planned`: split task into ≤5 independent sub-tasks, **fresh LLM context per sub-task** (flush), shared `notes.jsonl`, final synthesis from notes only
- Default remains single-session (same as before)

### Safety
- Refuses host run if `/.dockerenv` missing (`safety.require_docker`)
- Override: `ALLOW_HOST_RUN=1` or `require_docker: false`

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
cat memory/events.jsonl | tail
```

## Config highlights

See `config.yaml`: `timeout_seconds`, `memory.*`, `safety.require_docker`.
