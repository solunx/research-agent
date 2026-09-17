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
1. `docs/FRAMEWORK_BOUNDARY.md` — regel uit §3 + Open items (het relevante item, niet alles)
2. `docs/CANDIDATE_LAYER.md` LOCKED-schema — als je candidates/units aanraakt
3. Dit document §5 (gefixte bugs) — als je een “nieuw” defect denkt te vinden
4. `docs/LEARNING_LOG.md` / `docs/BOUNDARY_AUDIT_FINAL.md` — alleen als SESSION_STATE of de taak daar expliciet naar wijst; nooit als default-inlees

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

**Meta-les, zelf ook een keer fout gegaan:** een van de externe reviewers (mij, Claude) las ooit een run-resultaat verkeerd en rapporteerde een fictieve regressie, wat tot een halve dag onnodige diagnose leidde. **Daarom deze procesregel, dwing 'm af:**

> **Elke bewering over een run-resultaat (geslaagd/gefaald/regressie) moet vergezeld gaan van een letterlijk citaat van `stop_reason`/`outcomes`/`contract_satisfied` uit het ruwe `result_*.json`-bestand. Nooit een parafrase, nooit uit geheugen.**

## 6. Huidige status (16 september 2026)

**Werkt, herhaaldelijk bevestigd stabiel:**
- Taak 02 (hotel, detailpagina): 9/9 succesvolle runs, `CONTRACT_SATISFIED` op stap 0
- Taak 06 (Wikipedia): stabiel, inclusief batch-decisions-modus
- Entity-binding (#22): hard bevestigd via offline A/B met echte LLM
- Architecture-freeze P0: hard-fail bij ontbrekend/niet-bevroren contract, guards op lab-fallbacks, legacy-pad geïsoleerd en gelabeld — alle negatieve tests slagen
- Zoekcapaciteit (Fase G): taak 05 (arXiv) — LLM formuleert zoekquery, code vult in, 232 resultaten opgehaald

**Net gevonden, nog open (zie Fase H-prompt hierboven/in laatste conversatie):**
- Na een succesvolle zoekopdracht kan de agent nog niet doorklikken naar een individueel resultaat — de link staat wel in de candidate-data maar niet in de affordance-lijst die `OPEN_URL` mag gebruiken
- **2026-09-17 update (Fase H, offline diagnose van Open #24):** twee losse oorzaken gevonden. (a) een woordgrens-bug in `candidate_units._link_for_block` (`"submit"` matchte per ongeluk binnen `"submitted 24 march..."`) — **gefixt en getest**, geen regressie op taak 01/02. (b) een dieperliggend representatieprobleem: deze pagina rendert de hele resultatenlijst als ÉÉN blank-line-blok (geen scheiding tussen kaarten), waardoor vaste 8-regel-chunking entiteiten doorsnijdt, gecombineerd met een de-dupe-by-tekst in `browser_list_affordances` die herhaalde generieke labels (`"pdf"`) maar één keer vastlegt. Een disambiguatiepoging (href-padsegment-matching) werd getest tegen de bekende-goede fixtures en **teruggedraaid** — die brak taak 02 (`Prijzen & boeken` verdween). Zie `FRAMEWORK_BOUNDARY.md` Open #24b en `LEARNING_LOG.md` 2026-09-17 voor het volledige citaat-onderbouwde verslag. **Aanbevolen volgende stap: de al gebouwde maar nooit ingehaakte HTML-observer (`structural_observer.py`) offline meten op een lijstpagina — geen nieuwe tekstheuristiek meer op `candidate_units.py` proberen.**

**Bewust nog niet opgelost, met reden (zie FRAMEWORK_BOUNDARY.md Open items):**
- Open #4: welke minimale structurele stat-set een LLM nodig heeft om "chrome" te herkennen — nog niet gevalideerd, kleine n
- Open #6: `max_candidates`-budget is provisional, niet gevalideerd over diverse paginatypes
- Open #10: taalneutrale surface-detector-drempel, herijking nog niet afgerond
- Open #19/#22-vervolg: `NOT_STATED` als "zwak" label is een contract-specifieke workaround, geen generiek mechanisme — als een toekomstige taak een ander afwezigheidslabel gebruikt (`NOT_VISIBLE`, `UNSTATED`), moet dit generieker (richting: contract-gedreven sufficiency-set, geen vaste strings)
- Taak 03 (Coolblue GPU): zoekknop-klik faalt op een fragiele tekst-locator (`text=Zoeken`) — apart probleem van de zoekcapaciteit zelf, nog niet gefixt
- Efficiëntie: `batch_decisions=True` is bewezen veilig en veel goedkoper (tot 7x minder LLM-calls) maar blijft bewust **opt-in**, geen default

## 7. Belangrijkste bestanden, met rol

| Bestand | Rol |
|---|---|
| `scripts/run_contract_driven_task_v0.py` | Canoniek entry point |
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

Open **#26** live retest taak 05 (candidate-scope reset na reject/unbind) — alleen na expliciete user-OK + `docker compose build`. **Niet #24b eerst:** als merge een stale `NOT_RELEVANT` vasthoudt, kan betere lijst-extractie alsnog `contract_satisfied=false` geven. Daarna: **#24b** HTML-observer; taak 03 Coolblue; generaliteit 04/08.