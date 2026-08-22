# Host memory & learning loop (global, cross-task)

## Goal

The more you use the agent, the better it gets **at reading the same hosts**, without task-specific hardcoding.

## Two layers

| Layer | Scope | Examples |
|-------|--------|----------|
| **Host transport** | Global (`memory/`) | preferred channel, failed tiers, URL param *names*, `human_setup_needed` |
| **Run content** | Per run (`runs/<id>/`) | shortlist, notes, report, task constraints |

Rule: *transport knowledge is never rediscovered for another task; answer content stays per run.*

## Loop (generic)

1. **Probe** – cheapest channel first (`web_fetch` / known recipe).
2. **Classify** – success channel or failure reason.
3. **Persist** – `site_tactics`, `site_recipes`, `site_url_patterns` (all global).
4. **Reuse** – next task on same host starts from preferred channel.
5. **Invalidate** – on structural fail, update counts; limited re-recon.
6. **Human signal** – if multiple tiers fail → `human_setup_needed` + `runs/.../host_learnings.md`.

## Files

- `memory/site_recipes.json` – channels + human flags  
- `memory/site_tactics.json` – preferred tool / tier outcomes  
- `memory/site_url_patterns.json` – deep-link shapes  
- `runs/<id>/host_learnings.md` – operator summary after every run  

## Operator role

When `host_learnings.md` lists **HUMAN_SETUP** hosts, you can once:

- document a working API endpoint or deep-link template, or  
- add affiliate/API access  

Store it in the same global memory so **every** future task reuses it.

## Not in scope of this layer

- Task-specific criteria (budget, dates, pax values)  
- Shortlist ranking content  
- Inventing affiliate contracts automatically  
