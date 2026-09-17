# Session state — lees dit elke sessie (niet LEARNING_LOG / BOUNDARY_AUDIT_FINAL)

**Canoniek pad:** `scripts/run_contract_driven_task_v0.py` → frozen contract → candidates → interpret → code STOP. Regel: code = structuur, LLM = betekenis. Live Docker/GPU: zie `docs/AGENT_RULES.md`.
**Stabiel:** taak 02 9/9 `CONTRACT_SATISFIED`; Fase G FILL_AND_SUBMIT; entity-binding (#22); #24a woordgrens (`0084f11`); batch_decisions opt-in.
**Laatste commit:** `7556f64` — Open #25. **#26 in tree:** `apply_candidate_scope_after_action` — bind alleen `preferred_item_links`; unbind FILL / leave-path (niet abs→html zelfde last-segment); reset outcomes `step>=bound_step`. Offline `evals/candidate_scope_reset/test_candidate_scope_offline_v0.py` groen. Live 05 `20260917T083112Z`: #25 OK, merge hield `NOT_RELEVANT` vast (= #26). Docker: altijd `docker compose build` vóór run.

**Open (top 3):**
1. **#26 live retest** — scope-reset staat in code + offline groen; live taak 05 alleen na expliciete user-OK + rebuild (vóór #24b: merge kan een correcte nieuwe candidate nog negeren).
2. **#24b** — lijstpagina = 1 blank-line-blok + affordance-dedupe `"pdf"`; HTML-arm meten, geen tekstheuristiek.
3. **Taak 03 Coolblue** — geen `input_field` in traces; `CLICK_TEXT Zoeken` no-progress.

Volledige docs alleen bij audit/verificatie: `FRAMEWORK_BOUNDARY.md` Open items, `HANDOVER.md`, `CANDIDATE_LAYER.md` LOCKED, `LEARNING_LOG.md` 2026-09-17, `BOUNDARY_AUDIT_FINAL.md`.
