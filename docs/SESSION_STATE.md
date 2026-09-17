# Session state — lees dit elke sessie (niet LEARNING_LOG / BOUNDARY_AUDIT_FINAL)

**Canoniek pad:** `scripts/run_contract_driven_task_v0.py` → frozen contract → candidates → interpret → code STOP. Regel: code = structuur, LLM = betekenis. Live Docker/GPU: zie `docs/AGENT_RULES.md`.
**Stabiel:** taak 02 9/9 `CONTRACT_SATISFIED`; Fase G FILL_AND_SUBMIT; entity-binding (#22); #24a woordgrens (`0084f11`); batch_decisions opt-in.
**Laatste commit:** zie git HEAD na Open #25 (refine-search na reject). Live 05 `20260917T072448Z` (vers image): `stop_reason=MAX_ACQUISITION_STEPS` `contract_satisfied=false` gaps `subject_instance=NOT_RELEVANT` `claim_extracted=NOT_VISIBLE`. Docker: altijd `docker compose build` vóór run.

**Open (top 3):**
1. **#24b** — lijstpagina = 1 blank-line-blok + affordance-dedupe `"pdf"`; HTML-arm meten, geen tekstheuristiek.
2. **Taak 03 Coolblue** — geen `input_field` in traces; `CLICK_TEXT Zoeken` no-progress.
3. **#25 live retest** — refine-search na `NOT_RELEVANT` staat in code + offline groen; live taak 05 alleen na expliciete user-OK.

Volledige docs alleen bij audit/verificatie: `FRAMEWORK_BOUNDARY.md` Open items, `HANDOVER.md`, `CANDIDATE_LAYER.md` LOCKED, `LEARNING_LOG.md` 2026-09-17, `BOUNDARY_AUDIT_FINAL.md`.
