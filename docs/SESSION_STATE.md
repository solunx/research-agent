# Session state — lees dit elke sessie (niet LEARNING_LOG / BOUNDARY_AUDIT_FINAL)

**Canoniek pad:** `scripts/run_contract_driven_task_v0.py` → frozen contract → candidates → interpret → code STOP. Regel: code = structuur, LLM = betekenis. Live Docker/GPU: zie `docs/AGENT_RULES.md`.
**Stabiel:** taak 02 9/9 `CONTRACT_SATISFIED`; Fase G FILL_AND_SUBMIT; entity-binding (#22); #24a woordgrens (`0084f11`); batch_decisions opt-in.
**Laatste commit:** `d9e8000` — Open #27: wrap innerText-regels `len>240` + append één long-text candidate; offline `evals/long_line_units/test_long_line_units_offline_v0.py`. Live 05 `20260917T093236Z`: `claim_extracted=NOT_VISIBLE` terwijl abstract in page_text stond; `subject_instance=RELEVANT`; #26 niet live bewezen (geen unbind). Docker: altijd `docker compose build` vóór run.

**Open (top 3):**
1. **#27 live retest** — abstract-wrap staat in code + offline groen; live taak 05 alleen na expliciete user-OK + rebuild (verwacht: `claim_extracted` kan EXTRACTED worden als interpret de wrapped paragraph ziet).
2. **#26 live** — unbind/switch-pad nog niet voorgekomen in `093236Z`; niet sluiten.
3. **#24b** — lijstpagina = 1 blank-line-blok + affordance-dedupe `"pdf"`; HTML-arm meten, geen tekstheuristiek.

Volledige docs alleen bij audit/verificatie: `FRAMEWORK_BOUNDARY.md` Open items, `HANDOVER.md`, `CANDIDATE_LAYER.md` LOCKED, `LEARNING_LOG.md` 2026-09-17, `BOUNDARY_AUDIT_FINAL.md`.
