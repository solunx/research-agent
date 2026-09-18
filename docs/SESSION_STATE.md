# Session state — lees dit elke sessie (niet LEARNING_LOG / BOUNDARY_AUDIT_FINAL)

**Canoniek pad:** `scripts/run_contract_driven_task_v0.py` → frozen contract → candidates → interpret → code STOP. Regel: code = structuur, LLM = betekenis. Live Docker/GPU: zie `docs/AGENT_RULES.md`.

**Stabiel (niet opnieuw diagnosticeren):** taak 02 9/9 `CONTRACT_SATISFIED`; Fase G FILL_AND_SUBMIT; entity-binding (#22); batch_decisions opt-in. Plus §5 #10–#16:
- **#24a** `0084f11` woordgrens (`Submit` ≠ `Submitted`)
- **#25** `7556f64` refine FILL na current-page `NOT_RELEVANT` (live `083112Z`)
- **#27** `d9e8000`/`1f0557e` wrap + geen recap; live `111714Z` `CONTRACT_SATISFIED`
- **#28** `fb4b177` download = stay-on-page
- **#24b** `cc1871e`/`26e89af` `(text,href)` + leaf-html op `list_results` (live `171515Z` per-paper `/abs/`)
- **#24** `41d5fc7` OPEN_URL-allowlist = aff ∪ shown `primary_action.href` (live `062211Z` OPEN abs `source=llm`)
- **#10** `6debab8` D2c geen kale identifiers/1-decimaal; abs=`live_offer_state`. Taak 05 na #10 **4/4** `CONTRACT_SATISFIED` `claim_extracted=EXTRACTED`: `070449Z` `/abs/2609.18128`; `073200Z` `/abs/2609.18128`; `075144Z` `/abs/2609.13860`; `081459Z` `/abs/2609.18128`

**Laatste commit:** (taak 03 click-robuustheid, na deze slice). Docker: altijd `docker compose build` vóór live.

**Open (top 3):**
1. **#26** — bind live (`062211Z`/`070449Z`); unbind/switch niet gezien. Code niet herschrijven.
2. **#10** — deze trigger bewezen; T=3 provisionally, niet gelockt over alle paginatypes.
3. **Taak 03 Coolblue** — click-fallback code in (related `input_field` via `_label_matches_text`); live retest. Niet `html_b2`.

Volledige docs alleen bij audit/verificatie: `FRAMEWORK_BOUNDARY.md` Open items, `HANDOVER.md`, `CANDIDATE_LAYER.md` LOCKED, `LEARNING_LOG.md`, `BOUNDARY_AUDIT_FINAL.md`.
