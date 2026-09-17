# Session state — lees dit elke sessie (niet LEARNING_LOG / BOUNDARY_AUDIT_FINAL)

**Canoniek pad:** `scripts/run_contract_driven_task_v0.py` → frozen contract → candidates → interpret → code STOP. Regel: code = structuur, LLM = betekenis. Live Docker/GPU: zie `docs/AGENT_RULES.md`.
**Stabiel:** taak 02 9/9 `CONTRACT_SATISFIED`; Fase G FILL_AND_SUBMIT; entity-binding (#22); #24a woordgrens (`0084f11`); batch_decisions opt-in.
**Laatste commit:** `5b9960a` — docs: #27 live `102344Z` — interpret zag spliced c3 niet (`max_candidates=3`). `claim_extracted=NOT_VISIBLE`. **#26 OPEN** (geen scope-event; geen extra 05-run). Docker: altijd `docker compose build` vóór run.

**Open (top 3):**
1. **#27 follow-up** — observation-cap 3 vs spliced 4e candidate (gediagnosticeerd, geen fix nog). Niet LLM, niet identity_hints, niet #22.
2. **#26** — unbind/switch live nooit gezien (`083112Z` hypothese; `093236Z`/`102344Z` geen event). Offline groen. Open laten.
3. **#24b / PDF-download** — later; `Download is starting` op `/pdf/…` + verkeerde `"pdf"`-href.

Volledige docs alleen bij audit/verificatie: `FRAMEWORK_BOUNDARY.md` Open items, `HANDOVER.md`, `CANDIDATE_LAYER.md` LOCKED, `LEARNING_LOG.md` 2026-09-17, `BOUNDARY_AUDIT_FINAL.md`.
