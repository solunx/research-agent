zie eerst AGENT_RULES.md

# Handover — Local Research Agent

**Doel van dit document:** naslag voor architectuur, gefixte bugs en testdiscipline. **Elke sessie:** lees `docs/AGENT_RULES.md` + `docs/SESSION_STATE.md` (kort). Lees dit bestand, `LEARNING_LOG.md` en `BOUNDARY_AUDIT_FINAL.md` **niet** volledig opnieuw — alleen wanneer de taak verificatie tegen de audit, een historische bug, of een Open-item-wijziging vereist.

---

## 1. Wat dit project is

Een **generieke, contract-driven web-research-agent**, lokaal draaiend (Docker + Ollama, model `qwen3.8:27b`, RTX 3090). Doel: een taakomschrijving (`task.md`) krijgen, zelfstandig een website onderzoeken, en met bewijs een contract van vereiste beslissingen (`decisions`) invullen tot het geheel voldoet (`sufficiency`).

**Niet** een travel-specifieke scraper — expliciet ontworpen om te werken op willekeurige domeinen (hotels, GPU's, marktplaatsen, wikipedia-feiten, wetenschappelijke papers).

## 2. Kernarchitectuur (lees dit vóór je code leest)

```
task.md
  → Contract Discovery (LLM leest enkel de taak, bedenkt een checklist
     van decisions + hun toegestane outcomes; geen browser)
  → bevroren contract (frozen=true, NIET meer wijzigbaar tijdens run)
  → Contract-driven acquisition loop:
       observe pagina → structural_observer/candidate_units/candidates
       → interpretation (LLM, per candidate × decision)
       → aggregate_outcome (combineert candidate-antwoorden)
       → best_outcomes (code-geheugen, persistent over stappen)
       → sufficiency check (CODE beslist STOP, nooit de LLM)
       → volgende actie (OPEN_URL/CLICK_TEXT/FILL_AND_SUBMIT/...)
  → resultaat (outcomes-dict + stop_reason)
```

**Canoniek entry point:** `scripts/run_contract_driven_task_v0.py`.
**Legacy, gedeprecieerd, NIET gebruiken:** `agent.py`, `storage.py`, `candidate_admissibility.py`, `member_role.py` — alleen bereikbaar via een expliciete `--legacy-agent`-vlag, bewust geïsoleerd (zie §5).

## 3. De belangrijkste, harde regel van dit hele project

> **Code bepaalt structurele feiten (positie, herhaling, aanwezigheid van een link, tekenklasse). De LLM interpreteert betekenis (is dit relevant, is dit hetzelfde onderwerp, wat zegt deze tekst).**

Concreet verboden in code: woordenlijsten voor domeinconcepten (geen `"hotel"`, `"board_type"`-synoniemen, geen `"zoeken"/"search"`-lexicon), hardgecodeerde drempels die een classificatiebeslissing verhullen, taalspecifieke patronen zonder brede dekking.

Dit is niet een stijlvoorkeur — het is met een zes rondes durende, formele audit afgedwongen (`docs/BOUNDARY_AUDIT_FINAL.md`). Elke keer dat deze regel werd overtreden, ontstond een verborgen bug die weken later pas werd gevonden. **Bij twijfel: vraag je af "zou dit antwoord veranderen zonder taal- of domeinkennis, puur op basis van positie/structuur?" Zo nee: hoort bij de LLM.**

## 4. Leesvolgorde

**Elke sessie (kort):** `docs/AGENT_RULES.md` → `docs/SESSION_STATE.md`.

**Alleen bij bouwen / boundary-wijziging / audit-verificatie:**
1. `docs/MECHANISM_NOTES.md` — waarom merge/binding/surface/FILL/reset zo gebouwd zijn (refactors)
2. `docs/FRAMEWORK_BOUNDARY.md` — regel uit §3 + Open items (het relevante item, niet alles)
3. `docs/CANDIDATE_LAYER.md` LOCKED-schema — als je candidates/units aanraakt
4. Dit document §5 (gefixte bugs) — als je een “nieuw” defect denkt te vinden
5. `docs/LEARNING_LOG.md` / `docs/BOUNDARY_AUDIT_FINAL.md` — alleen als SESSION_STATE of de taak daar expliciet naar wijst; nooit als default-inlees

## 5. Complete lijst van gevonden en gefixte bugs (NIET opnieuw diagnosticeren)

| # | Bug | Fix | Les |
|---|-----|-----|-----|
| 1 | Tekstblok afgekapt op 8 regels, rest weggegooid | Chunking i.p.v. truncate | Nooit stil data laten vallen bij een budgetlimiet |
| 2 | Cijferdichte blokken verdrongen identity in ranking (2x, op twee plekken in code) | `block_index` als tie-break vóór density | Twee losse rank-functies bestaan (`candidate_units._rank`, `candidates.rank_candidates`) — fixes moeten op BEIDE toegepast worden |
| 3 | Hardcoded `max_candidates=6, max_units=16` overschreef provisional defaults | Teruggezet naar 3/6 + collect-then-cap | Check altijd de daadwerkelijke caller-parameters, niet enkel de functie-default |
| 4 | Interpretatie-LLM kreeg nooit de pagina-URL, kon "is dit de juiste pagina"-vragen niet beantwoorden | `page_context` toegevoegd aan interpretatie-payload | Provenance-data bestond al, werd stilzwijgend niet doorgegeven |
| 5 | Outcomes verdwenen tussen acquisitiestappen (`NOT_STATED` op stap 3 wiste `ALL_INCLUSIVE` van stap 1) | `_merge_outcomes`: non-UNKNOWN blijft behouden tenzij expliciete tegenspraak | Elke stap herberekende alles opnieuw, geen cumulatief geheugen |
| 6 | `aggregate_outcome` liet een candidate over EEN ANDERE entiteit (carrousel-widget van ander hotel) een contract-bevredigend antwoord geven — **fail-open, niet fail-closed** | Entity-binding: bewijs moet structureel gekoppeld zijn aan de candidate die `subject_instance` bevestigde | **Belangrijkste bug van het traject.** Een groene testuitslag bewijst niet dat de grounding correct is — check altijd WAAR het bewijs vandaan kwam |
| 7 | `_claim_priority` had nog hardcoded travel-lexicon lang nadat dit als MOVE gemarkeerd was in de audit | Puur FIFO op list-index | Documentatie "DONE" ≠ code daadwerkelijk aangepast — verifieer met citaat |
| 8 | Multi-decision batching gaf `board_type=UNKNOWN` op alle stappen | Bleek NIET aan modelbelasting te liggen (offline A/B toonde pariteit) maar aan bug #6, die toen nog niet gefixt was | Falsifieer hypotheses met een geïsoleerd experiment vóór je een architectuurbeslissing baseert op een enkel live resultaat |
| 9 | Geen actieklasse om tekst in te typen — agent kon niet zoeken, enkel klikken | `input_field`-affordance-type + `FILL_AND_SUBMIT`-actie, LLM formuleert querytekst vrij, code voert uit | Ontbrekende capability, geen datalek — eerste van dit type gevonden |
| 10 | `Submit` bond aan `Submitted …` in arXiv-units (`#24a`) | `_label_matches_text` woordgrens (niet-alfanumeriek aan beide kanten), geen lexicon. `0084f11` | Substring-containment is geen token-match — zelfde les als bug #2: fix op elke gedupliceerde match-site |
| 11 | Na `subject_instance=NOT_RELEVANT` bleef de planner op dezelfde paper (`#25`) | Planner-hint: current-page reject + `list_results` gezien → mag nieuwe `FILL_AND_SUBMIT` (`query_text` blijft LLM). `7556f64`. Live `083112Z` | Gaps waren al zichtbaar; de system prompt dwong “blijf op dit object” |
| 12 | Merge hield `NOT_RELEVANT` vast na item-wissel (`#26` pad 1, bound) | `apply_candidate_scope_after_action`: bind alleen `preferred_item_links`; unbind FILL / leave-path **als gebonden**. `cae4402`. Live bind `062211Z`/`070449Z`. Pad 1 verwijdert post-bind keys | `_merge_outcomes` is correct binnen één bound candidate; reset is scope, geen zwakke-label-hack |
| 13 | Abstractparagraaf als één innerText-regel >240 chars verdween (`#27`) | Wrap i.p.v. drop (`d9e8000`) + niet recappen vóór interpret (`1f0557e`). Live `111714Z` `CONTRACT_SATISFIED` | Budgetlimiet mag nooit stil data laten vallen (bug #1 opnieuw) |
| 14 | `Page.goto: Download is starting` op `/pdf/…` crashte de stap (`#28`) | Playwright `download`-event: `cancel()`, blijf op huidige pagina, `soft_fail`. `fb4b177` | Navigatie≠parse; PDF-tekst als bewijs is een andere capability |
| 15 | Lijstkaarten: één `"pdf"`-href + blank-line-blok; daarna abs-href niet in affordance-allowlist (`#24b`/`#24`) | Fase 1 `(text,href)`-identity `cc1871e`; Fase 2.2 leaf-html op `list_results` `26e89af`; OPEN_URL-allowlist = safe aff ∪ shown `primary_action.href` `41d5fc7`. Live `171515Z` leaf-cards; `062211Z` OPEN abs `source=llm` | Representatie eerst; allowlist daarna. Niet `html_b2`. LLM mag geen verzonnen URL |
| 16 | Abs-pagina `price_hits=4` → ten onrechte `list_results` → html-leaf pakte PDF/HTML/TeX (`#10`) | D2c weigert kale 4+ digit identifiers en 1-decimaal; T=3; root-start = same-host → `live_offer_state`. `6debab8`. Live `070449Z` `CONTRACT_SATISFIED` `claim_extracted=EXTRACTED` | Drempel 3 was van de lexicon-detector; identifier-runs zijn geen prijzen (Monica 7-vs-37, zelfde klasse) |
| 17 | Taak 03: `CLICK_TEXT Zoeken` timeout op aria-only icon-button (`text=Zoeken`); daarna categorie-browse | Na timeout: unieke `input_field` waarvan accessible name token-boundary-matcht met click-text (`_label_matches_text`); klik/focus die field, geen verzonnen query. Geen lexicon, geen index-nabijheid. `evals/click_related_input/` | input_field-capaciteit loste de klik niet vanzelf op; fallback alleen bij aantoonbare naamrelatie (negatief: `Computers & tablets` / `NietBestaand` pakt search niet) |
| 18 | Coolblue list HTML: 400k-cap telde `<script>`/`<style>`/`<head>` mee → body-kaarten vielen buiten de snapshot (`110505Z` `html_chars=699128`) | `prepare_html_for_snapshot`: strip non-content, houd `<body>`, *dan* cap. `06f7f00`. `evals/html_cap_body/` | Cap op ruwe `page.content()` is geen content-budget |
| 19 | Leaf `repeating_only` nam de eerste repeating group (header-widgets) i.p.v. productkaarten; niet-lege HTML verving de text-arm blind | Cluster-score = n × (D2c + text-link); `html_leaf_should_replace_text` (prijs OF href+digit-runs+≥2 regels). `ef3b066`. `evals/html_leaf_list/` | Eerste cluster ≠ item-cluster; chrome-HTML mag text niet verdringen. arXiv heeft geen € — tie-break is niet prijs-only |
| 20 | Product-`primary_action` verdronk in `panel_option`-filters (47 filters, 4 nav hrefs, geen product-URL in cap) | `inject_preferred_action_affordances` vóór cap; zelfde bron als #24 allowlist. Geen `/product/`-lexicon. `64a4f88`. `evals/preferred_href_allowlist/` | Allowlist accepteert een href die de planner nooit ziet; inject maakt hem zichtbaar |
| 21 | Unbound lijst-interpret zette `detail_link=CONCRETE_PRODUCT_PAGE`; refine FILL andere query liet die confirming label plakken (`#26` pad 2; `183956Z`/`190223Z`) | `apply_fill_query_round_reset`: andere FILL-`query_text` → weaken `step>=last_fill_result_step` naar `UNKNOWN`, keys blijven. `_merge_outcomes` ongewijzigd. Pad 1 (bound unbind) blijft apart. `23028a0`. Live `search_round_reset` `061149Z`/`064948Z`; unbind `064948Z`. `evals/candidate_scope_reset/` | Twee reset-paden: bound path vs unbound search-round. Eén maakt de ander niet overbodig. #26 niet sluiten |

**Meta-les, zelf ook een keer fout gegaan:** een van de externe reviewers (mij, Claude) las ooit een run-resultaat verkeerd en rapporteerde een fictieve regressie, wat tot een halve dag onnodige diagnose leidde. **Daarom deze procesregel, dwing 'm af:**

> **Elke bewering over een run-resultaat (geslaagd/gefaald/regressie) moet vergezeld gaan van een letterlijk citaat van `stop_reason`/`outcomes`/`contract_satisfied` uit het ruwe `result_*.json`-bestand. Nooit een parafrase, nooit uit geheugen.**

## 6. Huidige status (19 september 2026)

**Werkt, herhaaldelijk bevestigd stabiel:**
- Taak 02 (hotel, detailpagina): 9/9 `CONTRACT_SATISFIED` op stap 0
- Taak 06 (Wikipedia): stabiel, inclusief batch-decisions-modus
- Entity-binding (#22): hard bevestigd via offline A/B met echte LLM
- Architecture-freeze P0: hard-fail bij ontbrekend/niet-bevroren contract
- Fase G zoekcapaciteit + §5 #10–#16 (taak 05 list→abs pad). **Na #10: 5/5** live `CONTRACT_SATISFIED` `claim_extracted=EXTRACTED` (`070449Z` `/abs/2609.18128`, `073200Z` zelfde, `075144Z` `/abs/2609.13860`, `081459Z` `/abs/2609.18128`, `072546Z` `/abs/2609.20625`). Niet één paper, niet één run.

**Niet opnieuw diagnosticeren (al in §5):** #24a/#24b/#24 allowlist, #25, #27, #28, #10-trigger op arXiv abs. #26: bound-pad niet herschrijven; unbound FILL-round is een **tweede** pad (niet een vervanging).

**Bewust nog niet opgelost, met reden (zie FRAMEWORK_BOUNDARY.md Open items):**
- Open #4: minimale structurele stat-set voor "chrome" — kleine n, niet gevalideerd
- Open #6: `max_candidates`-budget provisional
- Open #10: **deze abs-trigger live-bewezen** (`070449Z`); T=3 + D2c-tighten blijft provisionally, niet gelockt over alle paginatypes
- Open #26: twee paden. #25-compositie (bind-reject → FILL) offline: canonieke `NOT_RELEVANT` op bind-stap wordt gewist, pad 2 resurrect niet. Exacte `083112Z`-merge: homepage-`NOT_RELEVANT` `step=0` overleeft unbind+pad 2. Geen `_merge_outcomes`-fix zonder overleg. **Niet sluiten**
- Open #19/#22-vervolg: `NOT_STATED` is contract-vocabulaire, geen framework-sentinel
- Taak 03 (Coolblue): click-fallback `7863753`; live FILL `103711Z`. A+B+C `06f7f00`/`ef3b066`/`64a4f88`. Pre-#26 3× `174311Z`/`183956Z`/`190223Z` `CONTRACT_SATISFIED` zonder OPEN. Post-#26: `061149Z` `CONTRACT_SATISFIED` `/zoeken?query=nvidia+rtx+4070` 0× OPEN; `064948Z` `MAX_ACQUISITION_STEPS` OPEN categorieën + unbind, geen `/product/` OPEN. Niet html_b2
- `batch_decisions=True` bewezen goedkoper, blijft **opt-in**
- Niet `html_b2` als #24b-fix (heading+price NCA is de verkeerde vorm voor arXiv `<li>`)

## 7. Belangrijkste bestanden, met rol

| Bestand | Rol |
|---|---|
| `docs/MECHANISM_NOTES.md` | Waarom-naslag (entity-binding, merge, #24–#27, FILL, #25, #26 twee paden, step-stamp-discrepantie) |
| `scripts/run_contract_driven_task_v0.py` | Canoniek entry point |
| `scripts/run_task_campaign_tmux_v0.sh` | Batch-campagne in detached tmux (N×M, circuit breaker, progress-log) |
| `scripts/run_task_campaign_loop_v0.py` | Sequentiële docker-jobs van die campagne |
| `scripts/analyze_campaign_v0.py` | LLM-loze samenvatting + deviant-runs |
| `scripts/run_contract_synthesis_batch_v0.py` | Contract-synthese (Fase 1) |
| `live_offer_state_slice.py` | Hoofdlus: acquisition, outcomes-merge, sufficiency-check per stap |
| `pipeline_offline.py` | `run_interpretation`, `aggregate_outcome`, `_claim_priority`, batch-decisions-logica |
| `interpretation.py` | LLM-prompt-opbouw per candidate/decision, `page_context` |
| `candidates.py` | Candidate-schema, `rank_candidates`, entity-binding |
| `candidate_units.py` | Ruwe paginatekst → units, eigen `_rank`, chunking |
| `evidence_acquisition.py` | Actieklassen (`OPEN_URL`, `CLICK_TEXT`, `FILL_AND_SUBMIT`, ...), anti-loop |
| `browser.py` | Playwright-laag, affordance-extractie (DOM-queries) |
| `sufficiency.py` | Pure functie: outcomes → gaps/STOP-beslissing (geen eigen geheugen) |
| `contract_discovery.py` | Fase 1 LLM-prompts (let op: hier zaten ooit domeinvoorbeelden in prompts, gecontroleerd/gefixt — check bij twijfel) |

## 8. Testdiscipline — volg dit exact, het is hard verdiend

1. **Nooit een hypothese bevestigen met enkel live-gedrag.** Isoleer eerst offline (met echte LLM, niet enkel een oracle-mock waar mogelijk).
2. **Elke "fix" krijgt minstens één negatieve test** (bewijs dat het faalt zoals bedoeld wanneer het moet falen), niet enkel een positieve smoke test.
3. **Geen nieuwe heuristiek zonder meetbaar experiment.** Als je twijfelt tussen twee opties, meet — verzin niet.
4. **Bij "dit lijkt een regressie": eerst het ruwe bestand citeren, dan pas concluderen.**
5. **Klein, gefaseerd, apart commit per stap.** Grote, samengevoegde wijzigingen zijn in dit traject herhaaldelijk de bron van verwarring geweest.

## 9. Wat NU als eerstvolgende stap klaarstaat

Open **#26** niet sluiten (zie `docs/MECHANISM_NOTES.md` §10–§11). Campagne 1 **klaar**. FIX 1 **H-dead-surface** (Open #29): `DEAD_SURFACE_NO_CONTENT` vóór interpret; TUI reconstruct dead, bol niet (3 aff / 2 units / 1093). FIX 2 entity-als-claim volgt apart. Geen live TUI/bol zonder OK. Niet html_b2.