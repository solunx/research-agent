# Session state — lees dit elke sessie (niet LEARNING_LOG / BOUNDARY_AUDIT_FINAL)

**Canoniek pad:** `scripts/run_contract_driven_task_v0.py` → frozen contract → candidates → interpret → code STOP. Regel: code = structuur, LLM = betekenis. Live Docker/GPU: zie `docs/AGENT_RULES.md`.

**Stabiel (niet opnieuw diagnosticeren):** taak 02 9/9 `CONTRACT_SATISFIED`; Fase G FILL_AND_SUBMIT; entity-binding (#22); batch_decisions opt-in. Plus §5 #10–#16:
- **#24a** `0084f11` woordgrens (`Submit` ≠ `Submitted`)
- **#25** `7556f64` refine FILL na current-page `NOT_RELEVANT` (live `083112Z`)
- **#27** `d9e8000`/`1f0557e` wrap + geen recap; live `111714Z` `CONTRACT_SATISFIED`
- **#28** `fb4b177` download = stay-on-page
- **#24b** `cc1871e`/`26e89af` `(text,href)` + leaf-html op `list_results` (live `171515Z` per-paper `/abs/`)
- **#24** `41d5fc7` OPEN_URL-allowlist = aff ∪ shown `primary_action.href` (live `062211Z` OPEN abs `source=llm`)
- **#10** `6debab8` D2c geen kale identifiers/1-decimaal; abs=`live_offer_state`. Taak 05 na #10 **5/5** `CONTRACT_SATISFIED` `claim_extracted=EXTRACTED`: `070449Z` `/abs/2609.18128`; `073200Z` `/abs/2609.18128`; `075144Z` `/abs/2609.13860`; `081459Z` `/abs/2609.18128`; `072546Z` `/abs/2609.20625`

**Laatste commit:** `23028a0` (#26 unbound FILL-query-round reset). Docker: altijd `docker compose build` vóór live.

**Campagne 1 klaar** (`campaign1_generaliteit_20260919T111126Z`): 18 runs, **0/18** SATISFIED, 5 CIRCUIT_BREAK. **Niet herstarten.**

**H-leak gediagnosticeerd.** FIX 1 **H-dead-surface** shipped (Open #29): `DEAD_SURFACE_NO_CONTENT` vóór interpret. TUI reconstruct dead; bol **niet** (3 aff / 2 units / 1093 chars — predicate niet rekken). 01/02/05/06 golden ongewijzigd. Entity-als-claim = FIX 2. Geen live zonder OK.

**Open (top 3):**
1. **#26** — pad 2 live `061149Z`/`064948Z`. #25 onder pad 2 **offline geverifieerd** (canonieke abs-reject op bind-stap: unbind wist `NOT_RELEVANT`; pad 2 wekt het niet opnieuw). **Niet sluiten:** exacte `083112Z`-merge houdt homepage-`NOT_RELEVANT` op `step=0` (zelfde label op abs bump't de stap niet). Geen merge-fix zonder overleg. 03-run1 nog list-SATISFIED.
2. **#10** — deze trigger bewezen; T=3 provisionally, niet gelockt over alle paginatypes. Campagne: wiki-artikel `Brussel_(stad)` als `list_results`.
3. **Taak 03 Coolblue list→detail** — A+B live op zoeklijst. Post-#26: `061149Z` `CONTRACT_SATISFIED` `final_url=/zoeken?query=nvidia+rtx+4070` **0× OPEN_URL**; `064948Z` `MAX_ACQUISITION_STEPS` `final_url=/zoeken/producttype:videokaarten?query=videokaart` — eerste OPEN (`Bekijk alle categorieën`, bind `/nl/ons-assortiment`), geen product-`/product/` OPEN. #24b niet sluiten. Niet `html_b2`.

Volledige docs alleen bij audit/verificatie: `MECHANISM_NOTES.md` (waarom), `FRAMEWORK_BOUNDARY.md` Open items, `HANDOVER.md`, `CANDIDATE_LAYER.md` LOCKED, `LEARNING_LOG.md`, `BOUNDARY_AUDIT_FINAL.md`. Campagne-infra: `scripts/run_task_campaign_tmux_v0.sh` — niet starten zonder N + taken + sessienaam.
