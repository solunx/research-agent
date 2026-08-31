# Boundary audit — canonieke consolidatie

**Document:** `docs/BOUNDARY_AUDIT_FINAL.md`  
**Scope:** statische + empirische boundary-audit (rondes 1–6), inclusief prompt-laag en consistentiechecks.  
**Geen fixes, geen refactorplan** — alleen inventaris en categorisatie.  
**Criterium (ongewijzigd):** voor filter/score/rank/label/accept/reject/groep op tekstfragmenten: zou het antwoord hetzelfde blijven zonder taal- of domeinkennis, puur op positie/nesting/herhaling/link/sibling? **JA → structureel (OK).** **NEE → interpretatie (MOVE/DELETE).** Taal- vs domein-specifiek apart.  
**Productiepad (referentie):** `scripts/run_contract_driven_task_v0.py` → `run_acquisition_loop(..., frozen_contract=...)`.

---

## 1. Samenvatting

De audit scheidt **structurele mechanismen** (framework) van **interpretatie** (LLM / lexicon). Op het **contract-driven** pad zijn de zwaarste boundary-overtredingen geconcentreerd in (1) lexicale chrome/price-signalen in `candidates.py` / `candidate_units.py`, (2) de surface-density detector `_PRICE_LINE` die indirect evidence hard-blocked via provenance, (3) lexicale `_claim_priority` in interpretatie-ranking, en (4) **prompt-strings** die travel/offer-voorbeelden hardcoden (`_CU_SYSTEM`, `interpretation.SYSTEM_PROMPT`).  

Modules die in eerdere rondes veel MOVE-rijen hadden (`storage.py`, `candidate_admissibility.py`, `member_role.py`) blijken **niet** in de contract-driven call-graph en **niet** in empirische traces van die runs — wél deels via legacy `agent.py` → `storage`. Lab-only fault-labels (`E_board_*` / `E_flight_*`) zijn **DELETE**. Fixture-defaults (`PACKAGES_DECISIONS`, `BOARD_TYPE_CONTRACT`-fallback) zijn **ISOLATE**: legitiem voor offline tooling, maar zonder harde guard tegen stilzwijgende fallback. Irreversible-actieblokkade is **OK-as-framework-exception** met incomplete taaldekking (**BROADEN**).  

Kernconclusie: de STOP/contract/sufficiency-kant is grotendeels framework-conform; de resterende schendingen zitten in **pre-interpret lexicons**, **één surface-detector**, en **system-prompts die domeinvoorbeelden leveren in plaats van alleen contract-data**.

---

## 2. Methodenverantwoording

| Methode | Wat |
|--------|-----|
| **Statisch** | Functie-voor-functie lezen in observer, candidates, candidate_units, admissibility, member_role, storage, live_offer/detail slices, evidence_acquisition, web_policy, pipeline_offline, interpretation, contract_discovery heuristics |
| **Grep** | `score`, `rank`, `weight`, `is_chrome`, `merge`, `accept`, `reject`, `threshold`, `vanaf`, `p.p.`, `offer_shape`, `ADMISSIBLE`, `PACKAGES_DECISIONS`, `E_board`, prompt-strings |
| **Call-graph** | Imports/aanroepen vanaf `run_contract_driven_task_v0.py` en parallel `agent.py` |
| **Empirisch** | Trace-artifacts van minstens twee contract-driven runs: `20260828T151029Z` (task 01) en `20260828T153646Z` (task 02) — `loop_*.json`, `result_*.json`, `step_*_candidates.json`, `events.jsonl` |

**Limitatie (expliciet):** empirische bevestiging steunt op **n = 2 travel-runs** (Corendon hotel-tasks). Geen non-travel contract-driven traces in deze audit. Afwezigheid van storage/admissibility-markers in die traces bevestigt de call-graph voor *dit* pad, niet universeel voor elke toekomstige entry point.

---

## 3. Voorafgaande consistentiechecks

### Check 1 — `member_role.py` / `build_member_role_prompt`

**Vraag:** is er een actief live-pad (ook buiten `run_acquisition_loop`)?

| Pad | Bereikbaar? | Bewijs |
|-----|-------------|--------|
| Contract-driven → `run_acquisition_loop` | **Nee** | Geen import; empirie: geen `member_role` / `offer_shape_score` / `TARGET`-rollen in traces 01/02 |
| Legacy live `agent.py` → `storage` | **Ja** | `storage.py:1100–1111` `from member_role import resolve_member_role` → kan `llm_member_role` → `build_member_role_prompt` aanroepen bij UNCERTAIN |

**Correctie op eerdere ronde:** “member_role nergens bereikbaar” was **te sterk**. Precies: **niet op contract-driven**; **wel op legacy `agent.py`-harvest**.

**Verdict prompt (147–163):**  
- T.o.v. **contract-driven productie:** **OK (niet-bereikbaar)** — consistent met deterministic member_role-rijen.  
- T.o.v. **legacy agent-pad:** domeinframing (`accommodation_offer`-default, “destination/region”) blijft een **MOVE-risico** als dat pad nog live gebruikt wordt; in de canonieke tabel hieronder als **OK (niet contract-driven)** met noot, geen dubbele MOVE op het referentiespad.

### Check 2 — `interpretation.py` `BOARD_TYPE_CONTRACT`-fallback

```text
interpretation.py:155
    decision = contract_decision or BOARD_TYPE_CONTRACT["decision"]
```

**Productie-aanroep:**

```text
pipeline_offline.py:540-543
    ir = interpret_observation(
        str(o.get("text") or ""),
        contract_decision=d,  # uit decisions-lijst
        chat_fn=chat_dict,
    )
```

Met frozen contract wordt `d` gezet → fallback normaal niet geraakt. **Harde guard ontbreekt** (geen `assert contract_decision is not None` / raise). Zelfde patroon als `PACKAGES_DECISIONS`.

**Verdict:** **ISOLATE** — lab/default-contract; isolatie is convention + caller, geen enforce.  
**Losse gap:** zie §4.

**Apart:** `SYSTEM_PROMPT` regel 5 (*occupancy vs ROOM_ONLY*) is **MOVE** — die string draait wél op het contract-driven interpret-pad, ongeacht de fallback.

---

## 4. Canonieke bevindingentabel

Categorieën: **MOVE** | **DELETE** | **ISOLATE** | **OK-framework-exception-BROADEN** | **OK**

### A. Op contract-driven pad — MOVE

| # | bestand | regel(s) | citaat (kern) | categorie | bereikbaar CD? | reden | taal? | domein? |
|--|--|--|--|--|--|--|--|--|
| 1 | `candidates.py` | ~45+ | `_CHROME_HINT` regex | MOVE | ja | chrome-classificatie op tekstinhoud | deels | deels |
| 2 | `candidates.py` | ~67–68 | `_PRICEISH_LINE` (`p.p.`/`vanaf`/`from`) | MOVE | ja | price-jargon lexicon | **ja** | nee |
| 3 | `candidates.py` | ~144–186 | match chrome/priceish op regels | MOVE | ja | past lexicon toe | deels | deels |
| 4 | `candidates.py` | ~205–271 | `_candidate_looks_chrome` | MOVE | ja | inhoudelijke chrome-detectie | deels | deels |
| 5 | `candidates.py` | ~305, 335, 366 | `is_chrome` rank/filter | MOVE | ja | selectie op chrome-label | deels | deels |
| 6 | `candidates.py` | ~373–389 | density + non-chrome preferentie | MOVE | ja | hangt af van chrome/density-lexicon | deels | deels |
| 7 | `candidate_units.py` | density/`vanaf`/`p.p.` | price-signalen in packaging | MOVE | ja | lexicale density | **ja** | nee |
| 8 | `candidate_units.py` | chrome op itemish links | `_is_chrome(text)` | MOVE | ja | tekstclassificatie | deels | deels |
| 9 | `candidate_units.py` | overige lexicale unit-signalen | unit-grenzen via jargon | MOVE | ja | niet puur positie/sibling | deels | deels |
| 10 | `live_offer_state_slice.py` | 62–63, 102 | `_PRICE_LINE` + `price_hits` | MOVE | ja | detector voedt surface→evidence-gate | **ja** | nee |
| 11 | `pipeline_offline.py` | ~411–428 | `_claim_priority` (board/flight lexemes) | MOVE | ja | rankt claims op domeinwoorden | **ja** | **ja** |
| 12 | `pipeline_offline.py` | 208–224 | `_CU_SYSTEM` (“hotel name”, “offer card”, “package fragment”) | MOVE | ja | domeinvoorbeelden in system-prompt | nee | **ja** |
| 13 | `interpretation.py` | 100–116 | `SYSTEM_PROMPT` regel 5 occupancy vs `ROOM_ONLY` | MOVE | ja | domeinvoorbeeld in system-prompt | deels | **ja** |

### B. DELETE (lab-only fault-labels)

| # | bestand | regel(s) | citaat (kern) | categorie | bereikbaar CD? | reden | taal? | domein? |
|--|--|--|--|--|--|--|--|--|
| 14 | `live_offer_state_slice.py` | 847–851 | `E_board_*` / `E_flight_*` na `frozen_contract is None` | DELETE | **nee** | dode productielogica; lab fault-enums | nee | **ja** |
| 15 | `live_detail_slice.py` | ~440–442 | zelfde `E_board_*` / `E_flight_*` + `PACKAGES_DECISIONS` | DELETE | **nee** | lab entry only | nee | **ja** |

### C. ISOLATE (lab-fixture, geen stilzwijgende productie-fallback bedoeld)

| # | bestand | regel(s) | citaat (kern) | categorie | bereikbaar CD? | reden | taal? | domein? |
|--|--|--|--|--|--|--|--|--|
| 16 | `pipeline_offline.py` | 39+; live_offer 228–233 | `PACKAGES_DECISIONS` / `decisions or PACKAGES_DECISIONS` | ISOLATE | alleen als `frozen_contract is None` | offline experiments; **geen harde guard** | nee | **ja** |
| 17 | `interpretation.py` | 34–61, 155 | `BOARD_TYPE_CONTRACT` / `contract_decision or BOARD_TYPE_CONTRACT["decision"]` | ISOLATE | fallback alleen bij `None` | experiment-default; **geen harde guard** | deels | **ja** |

### D. OK-framework-exception-BROADEN

| # | bestand | regel(s) | citaat (kern) | categorie | bereikbaar CD? | reden | taal? | domein? |
|--|--|--|--|--|--|--|--|--|
| 18 | `evidence_acquisition.py` | 37–48 | `_IRREVERSIBLE` regex | OK-fw-exc-BROADEN | ja | safety, FRAMEWORK_BOUNDARY allowed; NL/EN onvolledig | **ja** | nee |
| 19 | `evidence_acquisition.py` | 159 | drop irreversible in `filter_safe_affordances` | OK-fw-exc-BROADEN | ja | actieblokkade, geen evidence-label | **ja** | nee |
| 20 | `evidence_acquisition.py` | 423–453 | validate target/href → STOP | OK-fw-exc-BROADEN | ja | idem | **ja** | nee |

### E. OK — structureel of niet op contract-driven pad

| # | bestand | construct | categorie | bereikbaar CD? | reden |
|--|--|--|--|--|--|
| 21–29 | `storage.py` | CTA/offer_body/offer_shape/chrome-regexes (9 constructs) | OK | **nee** | alleen harvest/`agent.py`; niet in CD-traces |
| 30–38 | `candidate_admissibility.py` | lodging/chrome/short_brand/slogan/thresholds (9) | OK | **nee** | offline eval scripts only; empirie zonder reason-codes |
| 39–40 | `member_role.py` | score≥0.55 ACCEPT; reject mapping | OK | **nee** (CD); ja via `agent.py` | deterministic; CD-niet-bereikbaar |
| 41 | `member_role.py` | `build_member_role_prompt` / `llm_member_role` | OK | **nee** (CD); ja via `agent.py` | check 1; geen MOVE op CD-referentiepad |
| 42–44 | `observation_builder.py` | `chrome_re` / `board_re` / `flight_re` | OK | **nee** | offline notes/golden tool |
| 45 | `structural_observer.py` | HTML/priceish offline A/B | OK | **nee** | representation experiment only |
| 46 | `contract_discovery.py` | `heuristic_contract_for_packages` | OK | **nee** | gelabeld experiment fixture; synthesis gebruikt generic |
| 47 | `contract_discovery.py` | `heuristic_contract_generic` | OK | synthesis offline | generieke fallback |
| 48 | `web_policy.py` | bot-wall e.d. | OK | nee in CD-keten | access, geen candidate-boundary |
| 49 | `live_offer_state_slice.py` | `_classify_surface` path/same_entity | OK | ja | structureel URL/nesting; marketing-block is framework |
| 50 | `pipeline_offline.py` | `is_provenance_blocked_for_entity` | OK | ja | framework surface-gate (boundary § provenance) |
| 51 | `pipeline_offline.py` | `aggregate_outcome` skip blocked | OK | ja | structureel t.o.v. tag |
| 52 | `evidence_acquisition.py` | gaps/sufficiency_stop / fingerprint / scope rank | OK | ja | mechanismen, contract-gevoed |
| 53 | `candidates.py` | blank_block packaging / primary_action structureel | OK | ja | positie/link-anchor (lexicon elders MOVE) |
| 54 | `candidate_units.py` | blank-line / link-anchor clustering | OK | ja | structureel |
| 55 | `sufficiency.py` | `evaluate_sufficiency` | OK | ja | code vs frozen contract |
| 56 | `live_detail_slice.py` | `page_text_to_observations` line-split | OK | ja | structureel |
| 57 | `live_offer_state_slice.py` | `force_click_texts` | OK | **nee** | lab hints; CD laat leeg |
| 58 | `pipeline_offline.py` | `channel_allowed` | OK | ja | structureel allowed_channels |
| 59 | `prompts/system.md` | algemene agent-prompt | OK | ander pad | generiek; niet in CU |
| 60 | `evidence_acquisition.py` | acquisition planner system (geen hotel-lijst) | OK | ja | gaps/affordances mechanisch |
| 61 | `decision_executor.py` | offline typed executor | OK | **nee** live CD | experiment module |

*Rijnummering 21–61 groepeert OK-constructs; detailregels uit eerdere 58-som zijn hier samengevoegd waar identiek van categorie — tellingen in §6 zijn leidend.*

---

## 5. Losse bugs/gaps (geen boundary-categorie)

| Gap | Feit | Impact |
|-----|------|--------|
| **Geen harde guard `frozen_contract is None`** | `decisions = decisions or PACKAGES_DECISIONS` zonder assert/raise | Stilzwijgende travel-fixture als iemand `run_acquisition_loop` zonder contract aanroept |
| **Geen harde guard `contract_decision is None`** | `decision = contract_decision or BOARD_TYPE_CONTRACT["decision"]` | Stilzwijgende board_type-experiment-default bij vergeten argument |
| **`_IRREVERSIBLE` taaldekking** | Alleen NL/EN (+ universele tokens) | BROADEN (DE/FR/ES/…); geen MOVE |
| **Legacy `agent.py` + storage/member_role** | Nog live entry met lexicon-paden | Buiten CD-scope; wel risico bij parallel gebruik |

Dit zijn **correctheids-/isolatie-issues**, geen extra MOVE-rijen.

---

## 6. Definitieve eindtelling

| Categorie | Aantal |
|-----------|--------|
| **MOVE** | **13** |
| **DELETE** | **2** |
| **ISOLATE** | **2** |
| **OK-framework-exception-BROADEN** | **3** |
| **OK** | **41** |
| **Totaal** | **61** |

**Rekenpad:**

```text
Eerdere 58-som (na ISOLATE voor #43, DELETE #37+#52):
  MOVE 11 + DELETE 2 + ISOLATE 1 + OK-fw-BROADEN 3 + OK 41 = 58

Toevoegingen laatste aanvulling + checks:
  + _CU_SYSTEM                         MOVE  (+1)
  + interpretation SYSTEM_PROMPT        MOVE  (+1)
  + BOARD_TYPE_CONTRACT fallback       ISOLATE (+1)

Eind:
  MOVE 13 | DELETE 2 | ISOLATE 2 | OK-fw-BROADEN 3 | OK 41
  13+2+2+3+41 = 61
```

**Verificatie:** \(13 + 2 + 2 + 3 + 41 = 61\).

**Empirische steun (n=2 CD-runs):** geen `short_brand_title` / `offer_shape_score` / `member_role` / `E_board` / `package_includes_flight`; wél LLM-`candidate_unit` ADMISSIBLE (andere module) en `candidates.is_chrome`.

---

## 7. Prioriteit per bestand (data voor latere fase)

Gesorteerd op **MOVE + DELETE + ISOLATE** (hoog → laag). Geen refactorplan.

| Prioriteit | bestand | MOVE | DELETE | ISOLATE | OK-fw-BROADEN | Notitie |
|------------|---------|------|--------|---------|---------------|---------|
| 1 | `candidates.py` | 6 | 0 | 0 | 0 | chrome/price lexicon op CD-pad |
| 2 | `candidate_units.py` | 3 | 0 | 0 | 0 | density/chrome op CD-pad |
| 3 | `pipeline_offline.py` | 2 | 0 | 1 | 0 | `_claim_priority`, `_CU_SYSTEM`; PACKAGES ISOLATE |
| 4 | `interpretation.py` | 1 | 0 | 1 | 0 | SYSTEM_PROMPT; BOARD_TYPE ISOLATE |
| 5 | `live_offer_state_slice.py` | 1 | 1 | 0 | 0 | `_PRICE_LINE`; E_board DELETE |
| 6 | `live_detail_slice.py` | 0 | 1 | 0 | 0 | E_board lab |
| 7 | `evidence_acquisition.py` | 0 | 0 | 0 | 3 | irreversible BROADEN only |
| — | `storage.py` / `candidate_admissibility.py` / `member_role.py` | 0* | 0 | 0 | 0 | *0 op CD-pad; legacy agent nog lexicon |
| — | overige (observation_builder, structural_observer, web_policy, …) | 0 | 0 | 0 | 0 | offline of structureel OK |

\* Als `agent.py` opnieuw als primaire live entry telt, stijgt prioriteit van storage/admissibility/member_role sterk — buiten huidige CD-referentie.

---

## 8. Referenties (interne docs)

- `docs/FRAMEWORK_BOUNDARY.md` — irreversible + provenance tags allowed  
- `docs/OBSERVATION_CONTRACT.md` — surface-tag semantiek  
- `docs/CANDIDATE_LAYER.md` — candidate abstractie  
- Empirie: attachments/traces `20260828T151029Z` (01), `20260828T153646Z` (02)

---

*Einde canonieke consolidatie. Volgende fase (niet in dit document): ground rules bijwerken, eval-schema, refactorplan op basis van §6–§7.*
