# Mechanism notes

Naslag voor **waarom** de acquisitielus zo is gebouwd. Geen changelog
(`LEARNING_LOG.md`) en geen audit-checklist (`FRAMEWORK_BOUNDARY.md`).
Lees dit vóór een refactor van merge, binding, surface, affordances of
FILL. Elke sessie: `AGENT_RULES.md` + `SESSION_STATE.md` eerst.

**Regel die elk mechanisme hier eerbiedigt:** code = structuur (positie,
herhaling, aanwezigheid van een link, tekenklasse). LLM = betekenis.
Geen domeinlexicon in deze triggers.

**Procesregel:** een run-bewering citeert `stop_reason` / `outcomes` /
`contract_satisfied` uit ruwe `result_*.json`. Zie `HANDOVER.md` §5.

---

## 1. Entity-binding (#22) — `require_subject_binding`, fail-closed

### Probleem

`aggregate_outcome` nam de hoogste-confidence niet-UNKNOWN rij, ongeacht
**welke** candidate die schreef. Op een hotel-detailpagina scoorde een
carrousel-widget van een *ander* property `board_type=ALL_INCLUSIVE` voor
Monica. Fail-open: het contract werd groen op bewijs dat structureel niet
aan het subject hing. HANDOVER §5 #6: grounding ≠ groene test.

### Afgewezen

- LLM-vraag “is dit hetzelfde hotel?” in code-aggregatie — betekenis in
  code, audit-verboden.
- Alle candidates mergen (OR over de pagina) — zelfde fail-open.
- Binding alleen op zichtbare naam-string — lexicon / taal.

### Oplossing + trigger

Twee passes: eerst `subject_instance` **zonder** binding → structurele
`subject_candidate_ref` (`candidate_id` / `block_index` / `item_link`).
Daarna overige decisions met `require_subject_binding=True`. Geen bound
rij → `UNKNOWN` (fail-closed), niet de carrousel-label.

**Trigger:** `require_subject_binding and subject_candidate_ref is not None`.
`subject_instance` zelf bindt nooit op zichzelf.

```437:443:pipeline_offline.py
    if require_subject_binding and subject_candidate_ref is not None:
        bound = [r for r in eligible_rows if _is_subject_bound(r, subject_candidate_ref)]
        if bound:
            eligible_rows = bound
        else:
            # Cross-entity-only answers → fail closed (do not use Abora for Monica).
            return "UNKNOWN"
```

Caller: `_finalize_outcomes_with_binding` pass 2.

### Bewijs

Offline A/B `fase_d_binding` `20260915T073132Z` (echte LLM). Live taak 02
9/9 `CONTRACT_SATISFIED` op detail zonder carrousel-lekkage. Tests:
entity-binding evals in `pipeline_offline` / candidate layer.

---

## 2. Outcomes-persistentie (#5, `_merge_outcomes`)

### Probleem

Elke acquisitiestap herberekende outcomes from scratch. Stap 3
`board_type=NOT_STATED` (pagina toont de tekst niet meer) wiste stap 1
`ALL_INCLUSIVE`. HANDOVER §5 #5. Citaat-patroon:
`20260831T063112Z` — latere afwezigheid mag eerder bewijs niet wissen.

### Afgewezen

- Alleen de laatste stap bewaren — precies de bug.
- `NOT_RELEVANT` in `_WEAK` stoppen zodat een reject vanzelf verdampt —
  dat verbreekt “concrete reject is persistent *binnen één candidate*”;
  item-wissel is scope (#26), geen zwakkere merge.
- Recency-only (nieuwste stap wint altijd) — een lege zoekpagina zou
  PRICE/BOARD wissen.

### Oplossing + trigger

Per `decision_id`: `UNKNOWN`/`NOT_STATED`/`""` overschrijven een
confirming label **niet**. Een **andere** concrete string wel (nieuwste
tegenspraak wint). Stap-stempel gaat alleen mee bij write.

**Trigger:** elke interpret-stap na aggregatie, vóór sufficiency.

```246:257:live_offer_state_slice.py
        if outcome in _WEAK:
            # Never overwrite a better (confirming) outcome with weak absence.
            if cur is None:
                best[decision_id] = {"outcome": outcome, "step": step}
            continue
        if (
            cur is None
            or str(cur.get("outcome") or "") in _WEAK
            or cur.get("outcome") != outcome
        ):
            best[decision_id] = {"outcome": outcome, "step": step}
```

Let op: **gelijke** concrete string bump’t `step` **niet**. Dat is
mechanisme 11 (gedocumenteerd, niet gefixt).

### Bewijs

Taak 01: stap-log `board_type=NOT_STATED`, finale
`outcomes.board_type=ALL_INCLUSIVE`. Taak 02: `UNKNOWN` stappen 0–2 →
`ALL_INCLUSIVE` stap 3 blijft tot STOP. LEARNING_LOG 2026-09-07.

---

## 3. Observation-cap-sync (#27)

### Probleem

Een abstract als één innerText-regel >240 tekens werd structureel
geskipt (`_skip_line_structural`). Wrap+splice (`d9e8000`) maakte `c3`
wel, maar live recapte daarna hard `candidates_to_observations(...,
max_candidates=3)` en gooide c3 weg vóór interpret.
`20260917T102344Z`: `claim_extracted=NOT_VISIBLE` terwijl de abstract in
`step_*_page_text.txt` stond. HANDOVER §5 #13; Open #27.

### Afgewezen

- Lange regels blijven droppen — herhaling bug #1 (stille databudget).
- Open #6 optrekken naar 8 als “fix” — budget is een ander item;
  de bug was een **tweede** cap, niet de eerste.
- Recap op 3 hardcoden “om tokens te sparen” — verbergt splice.

### Oplossing + trigger

Live: `obs = candidates_to_observations(selected)` zonder extra cap.
`extract_candidates` blijft Open #6 (3/6) plus hoogstens één long-text
splice. Default `max_candidates=None` = alle `selected`.

**Trigger:** altijd na `extract_candidates` in de acquisition-loop;
geen tweede onafhankelijke top-K.

```770:775:live_offer_state_slice.py
        # Open #6: extract_candidates already applied the provisional budget
        # (max_candidates=3, max_units=6). Open #27 may splice one extra
        # long-text candidate, so len(selected) can be 4. Do not recap here
        # with a hardcoded 3 — that dropped spliced c3 in 20260917T102344Z
        # before interpret ever saw the abstract.
        obs = candidates_to_observations(selected)
```

### Bewijs

Live `20260917T111714Z`: `stop_reason=CONTRACT_SATISFIED`
`claim_extracted=EXTRACTED`. `step_006_claims.json` `candidate_claim_n=5`,
abstract in `claim_preview`. Offline:
`evals/long_line_units/test_long_line_units_offline_v0.py`.

---

## 4. Affordance-dedup `(text, href)` (#24 Fase 1)

### Probleem

Identity was zichtbare **tekst**. Op arXiv-search waren ~19 papers
`text="pdf"` met verschillende hrefs → één affordance. Daarna was de
abs-URL niet in de allowlist. `171515Z` / eerdere 05-runs: één `"pdf"`.

### Afgewezen

- Eerste `"pdf"` houden en de rest verzinnen — LLM mag geen URL
  verzinnen (`href_not_in_affordances`).
- Pad-lexicon `/abs/` of `/pdf/` — domeinregel.
- Helemaal niet dedupen — 60-cap vol chrome-duplicaten.

### Oplossing + trigger

Identity = `(kind, text, href, name, id)` plus cross-kind `(text, href)`.
Zelfde label, andere href → beide blijven. Exacte `(text, href)`-dupes
klappen nog in.

**Trigger:** `browser_list_affordances` JS `push()` en Python
`affordance_identity_accepts` (zelfde regel, twee sites — les bug #2).

```656:662:browser.py
            // Open #24b Fase 1: identity is (kind, text, href, name, id) — not text
            // alone. Repeated labels ("pdf") with distinct hrefs must all survive.
            // Mirrors Python affordance_identity_accepts.
            const key = (kind + '|' + (text || '').toLowerCase() + '|' + hrefN + '|' + (extra && extra.name ? extra.name : '') + '|' + (extra && extra.id ? extra.id : ''));
            if (seen.has(key)) return;
            const textHrefKey = 'TH|' + (text || '').toLowerCase() + '|' + hrefN;
```

### Bewijs

`evals/affordance_identity/test_affordance_identity_offline_v0.py`
(negatief: 19 unieke pdf-hrefs). Live `171515Z` na Fase 2: per-paper
kaarten; Fase 1 alleen was nog niet genoeg voor OPEN.

---

## 5. Leaf-HTML additief op `list_results` + replace-gate (#24 Fase 2 A+B+C)

### Probleem

Plat `page_text` maakte één blank-line-blok dat papers/producten
oversprong. Coolblue `110505Z`: `html_chars=699128`, 400k-cap in
`<head><style>`, candidates = Language/Account. Affordances: 47
`panel_option`, 0 product-hrefs. arXiv: één chunk, `cand_ids=1`.

### Afgewezen

- `html_b2` (heading+price NCA) — arXiv-search heeft **één** `h1–h4`;
  kaarten zijn `<li class="arxiv-result">`. Gemeten, niet geraden.
- Altijd HTML i.p.v. text als `html` niet leeg is — chrome-HTML
  verdringt text (header-widgets).
- Eerste repeating group in DOM-volgorde — Coolblue header wint van
  productkaarten.
- `/product/`-lexicon in de allowlist — verboden.

### Oplossing + trigger

Drie structurele lagen, alleen `surface=list_results`:

| Laag | Wat | Trigger |
|------|-----|---------|
| A | `prepare_html_for_snapshot`: strip non-content, `<body>`, *dan* cap | elke snapshot |
| B | repeating cluster-score `n × (D2c + text-link)`; `html_leaf_should_replace_text` | leaf mag text vervangen iff prijs **of** (href ∧ digit_runs≥2 ∧ regels≥2) |
| C | `inject_preferred_action_affordances` vóór 60-cap | shown `primary_action.href` in de planner-lijst |

OPEN_URL-allowlist = safe aff ∪ diezelfde preferred hrefs (`41d5fc7`).

```329:345:candidates.py
def html_leaf_should_replace_text(cands: list[Candidate]) -> bool:
    """Keep HTML leaf only when at least one card looks itemish.
    Itemish = D2c/glyph price line (Open #10) OR (href + digit runs + ≥2 lines).
    """
    ...
        if href and int(c.digit_run_count or 0) >= 2 and n_lines >= 2:
            return True
```

```145:175:evidence_acquisition.py
def inject_preferred_action_affordances(...):
    """Put candidate primary_action links into the affordance list before cap.
    Same source as observed_open_hrefs / the #24 allowlist.
```

**Trigger B:** `surface=="list_results"` en niet-lege `html`. Andere
surfaces negeren html (additief).

### Bewijs

A: `evals/html_cap_body/` vs `110505Z`. B: live `174311Z`/`183956Z`/
`190223Z` `packager_source=html_structure`, ASUS/VICTUS `/product/`-hrefs
(niet Language/Account). C+allowlist: `062211Z` OPEN
`https://arxiv.org/abs/2609.18128` `source=llm` terwijl href **niet** in
ruwe `step_002_affordances.json` stond. `171515Z` leaf-cards met `/abs/`.
Niet sluiten: 03 blijft vaak interpret-op-lijst zonder product-OPEN.

---

## 6. Surface-classificatie + D2c identifier-uitsluiting (#10)

### Probleem

`list_results` = `price_hits >= T`. Abs-pagina `062211Z`: arXiv-id
`2609.18128` (kale 4+ cijfers) + review-achtige 1-decimalen →
`price_hits=4` → ten onrechte `list_results` → html-leaf pakte
PDF/HTML/TeX-chrome i.p.v. de abstract. `claim_extracted=NOT_VISIBLE`.

### Afgewezen

- Lexicon-prijsdetector (`vanaf`/`from`/`p.p.`) — taal in code.
- T verlagen tot 1 — lists en abs vallen samen.
- Host/path-string “arxiv” → always detail — sitenaam in code.

### Oplossing + trigger

D2c weigert kale 4+ digit integers en 1-decimaalfracties; 3-digit
prijzen zonder glyph blijven (Monica). T=3 **provisionally**. Site-root
start: same-host → `same_entity` → abs wordt `live_offer_state` i.p.v.
marketing.

**Trigger:** `_classify_surface`: `dense_list = count_price_like_lines >= 3`.
`step==0 and same_entity` → `live_detail` (property-pagina-wacht).

```141:143:candidate_units.py
        # Bare 4+ digit integers are identifiers, not displayed prices.
        if not dec and len(num) >= 4:
            continue
```

```116:125:live_offer_state_slice.py
    price_hits = count_price_like_lines(text or "")
    dense_list = price_hits >= _PRICE_LIKE_LIST_THRESHOLD
    if step == 0 and same_entity:
        return "live_detail", True
    if dense_list:
        return "list_results", same_entity
```

T=3 is **niet** gelockt over alle paginatypes (Open #10).

### Bewijs

`evals/surface_threshold/test_surface_threshold_offline_v0.py`
(reconstruct `062211Z`). Live na `6debab8`: `070449Z` / `073200Z` /
`075144Z` / `081459Z` / `072546Z` allemaal `CONTRACT_SATISFIED`
`claim_extracted=EXTRACTED` op `/abs/…`.

---

## 7. `input_field` + `FILL_AND_SUBMIT` (Fase G)

### Probleem

Actie-enum had klikken/openen, geen typen. De agent kon niet zoeken,
alleen navigeren. HANDOVER §5 #9: ontbrekende capability, geen datalek.

### Afgewezen

- Query uit de taaktekst knippen in code — LLM-betekenis.
- `?q=` op de URL plakken zonder observed input — verzonnen control.
- Site-specifieke search-knop.

### Oplossing + trigger

Nieuwe affordance-`kind=input_field` (placeholder/aria/name/id; mag
lege innerText). Actie `FILL_AND_SUBMIT`: `query_text` is **vrije LLM-
tekst**; code matcht alleen het observed field en typt+Enter. Anti-loop
fingerprint bevat `q=` zodat dezelfde box met een andere query mag.

**Trigger (planner mag kiezen):** `kind=input_field` staat in safe
affordances. **Trigger (execute):** `query_text` non-empty en locator uit
het gematchte field. Geen field → `fill_no_input_field_affordance`.

```697:708:evidence_acquisition.py
    # FILL_AND_SUBMIT: target must match an input_field affordance; query_text is
    # free text formulated by the LLM (never auto-copied from gaps by code).
    ...
        if not input_affs:
            return {
                "action_class": "STOP",
                "reason": "fill_no_input_field_affordance",
```

### Bewijs

Live `103711Z` taak 03: `FILL_AND_SUBMIT` `target_text=Zoeken naar...`
`query_text=RTX 4070` `target_id=search`. `stop_reason=CONTRACT_SATISFIED`.
Taak 05: FILL op arXiv-search (`083112Z`, `072546Z`).

---

## 8. Retry met nieuwe query na `NOT_RELEVANT` (#25)

### Probleem

Na OPEN abs `subject_instance=NOT_RELEVANT` bleef de planner op hetzelfde
record (Related Papers / HTML / Back). Gaps toonden de FAIL al.
`20260917T072448Z`: `stop_reason=MAX_ACQUISITION_STEPS`
`subject_instance=NOT_RELEVANT` `claim_extracted=NOT_VISIBLE`. System
prompt zei “blijf bij current entity”.

### Afgewezen

- Code schrijft `query_text` — betekenis.
- Merged `best_outcomes.NOT_RELEVANT` als trigger — homepage-reject zou
  forever FILL’en (daarom current-page only).
- `NOT_VISIBLE` / `UNKNOWN` als reject — afwezigheid ≠ object-reject.

### Oplossing + trigger

Hint iff **current-page** outcome ∈ `{NOT_RELEVANT, REJECTED}` voor een
nog-FAIL gap **én** deze run heeft al `surface=list_results` gezien.
Dan: niet verdiepen; `FILL_AND_SUBMIT` met **nieuwe** LLM-`query_text`
mag. Geen input_field → eerst een listed affordance naar search.

```348:386:evidence_acquisition.py
def object_rejected_on_current_page(...):
    """Uses current-page outcomes, not merged best_outcomes: a homepage
    NOT_RELEVANT must not keep firing after a later page confirms the subject.
    """
...
def should_hint_refine_search(...):
    rejected = object_rejected_on_current_page(current_page_outcomes, gaps)
    if not rejected:
        return None
    if "list_results" not in {str(s or "") for s in (surfaces_seen or [])}:
        return None
```

#25 lost **planner-stuck** op. Dat merge `NOT_RELEVANT` daarna vasthoudt
is #26, niet #25.

### Bewijs

Live `083112Z`: na abs-reject `OPEN_URL Search` daarna FILL
`q=LLM agents tool use`. Contract bleef false door merge (Open #26).
Offline: `evals/refine_search_after_reject/`. Compositie met pad 2:
`evals/candidate_scope_reset/` (canonieke bind-reject wist het label;
exacte 083112Z-merge is mechanisme 11).

---

## 9. Click-robuustheid → related `input_field` (taak 03)

### Probleem

`CLICK_TEXT Zoeken` op Coolblue: knop is aria-only, `locator("text=Zoeken")`
timeout 8000ms, daarna categorie-browse. Fase G `input_field` stond wél
in affordances (`placeholder=Zoeken naar...`, `id=search`) maar loste de
**mis-klik** niet op. `20260916T110052Z` step 0: `execute_error` Timeout.

### Afgewezen

- Eerste zichtbare input — vangt newsletter/account (negatieven).
- `type=search` of nabijheid in de DOM-index — niet universeel, niet
  structureel-uniek.
- Coolblue-`#search`-special case — sitenaam.

### Oplossing + trigger

Na gemiste visible-text locators: unieke `input_field` waarvan accessible
name **token-boundary** matcht (`_label_matches_text`) met de click-text.
Focus/klik dat field; **geen** verzonnen `query_text`. 0 of ≥2 matches →
None. Daarna pas aria-label voor icon-buttons zonder related field.

**Trigger:** `CLICK_TEXT` execute, visible-text locators falen, precies
één related input.

```1015:1027:evidence_acquisition.py
        # 2. Related input_field: token-boundary match into accessible name.
        #    Focus/click that field — do not invent query_text.
        ...
        if loc:
            snap2 = browser_click(loc, max_chars=max_chars)
            if snap2.get("ok"):
                snap2["click_fallback"] = "related_input_field"
```

### Bewijs

Offline `evals/click_related_input/`: Zoeken → `#search`;
`Computers & tablets` / `NietBestaand` → geen fallback. Live `103711Z`
bewijst het FILL-pad, niet deze timeout-fallback (planner koos FILL).
Vangnet blijft voor icon-search.

---

## 10. Twee reset-paden (#26)

`_merge_outcomes` is **correct binnen één bound candidate**. Reset is
scope, geen zwakke-label-hack. Pad 1 en pad 2 lossen **verschillende**
gaten. Eén maakt de ander niet overbodig.

### 10a. Pad 1 — bound unbind/switch

**Probleem.** #25 verliet de rejected paper; merge hield
`subject_instance=NOT_RELEVANT` vast. Latere list-`UNKNOWN` overschrijft
niet. Risico: titel van paper A + `RELEVANT` van paper B. `083112Z`
finaal: `stop_reason=MAX_ACQUISITION_STEPS` `subject_instance=NOT_RELEVANT`.

**Afgewezen.** `_WEAK` uitbreiden met `NOT_RELEVANT` — wis ook een
bewuste reject *op dezelfde pagina*. `same_entity_path` vs `start_url`
als reset — breekt taak 02 Fly & Go / arXiv-root.

**Trigger.** Succesvolle navigatie én `active_candidate_path is not None`:
FILL always unbind; leave-path zonder preferred bind → unbind; preferred
ander path → switch. Bind alleen via `preferred_item_links` vanaf
`list_results` (Search is geen candidate). Same-record deepening
(`/abs/id` → `/html/id`) unbindt niet.

**Reset:** **drop** keys met `step >= candidate_bound_step`; pre-bind
blijft (`source_site`).

```393:397:live_offer_state_slice.py
    if action == "FILL_AND_SUBMIT":
        if active_candidate_path is not None:
            best = _reset_post_bind_outcomes(best, candidate_bound_step)
            return best, None, None, "unbind"
```

**Bewijs.** Live bind `062211Z`/`070449Z`/`072546Z` `path=/abs/…`.
Unbind `064948Z` `event=unbind` na FILL `q=videokaart`. Offline:
`test_unbind_after_reject_like_083112Z`, `test_fill_unbinds_bound_candidate`.

### 10b. Pad 2 — unbound search-round reset

**Probleem.** Nooit gebonden: lijst-interpret zette
`detail_link=CONCRETE_PRODUCT_PAGE`; refine FILL andere query liet die
confirming label plakken (`skip_satisfied` bevatte `detail_link`).
Pad 1 deed niets (`active_candidate_path is None`).
`183956Z`/`190223Z`: `stop_reason=CONTRACT_SATISFIED` terwijl
`final_url` `/zoeken?query=…` bleef, 0× OPEN_URL.

**Afgewezen.** Alleen pad 1 — deelt dit gat niet. `search_round_id` op
candidates — `c0`/`block_index` recyclen per pagina; extra id is geen
structureel feit. Keys deleten i.p.v. weaken — sufficiency ziet de gap
niet meer.

**Trigger.** Succesvolle `FILL_AND_SUBMIT` waarvan genormaliseerde
`query_text` **verschilt** van de vorige succesvolle FILL in deze run.
Eerste FILL: no-op (onthoudt `last_fill_query_text` +
`last_fill_result_step`).

**Reset:** **weaken** `step >= last_fill_result_step` naar `UNKNOWN`,
keys blijven. `_merge_outcomes` ongewijzigd (confirming slaat later
UNKNOWN nog). Loopvolgorde: pad 1 **daarna** pad 2.

```496:503:live_offer_state_slice.py
    if (
        last_fill_query_text is not None
        and prev_q
        and new_q != prev_q
        and last_fill_result_step is not None
    ):
        best = _weaken_outcomes_from_step(best, last_fill_result_step, next_step)
        event = "search_round_reset"
```

**Bewijs.** Live `061149Z`: 3× `search_round_reset`; na eerste reset
stap 2 `detail_link=NO_URL`. `064948Z`: reset + later unbind.
Offline: `test_coolblue_refine_drops_list_pool_keeps_step0`;
01/02/06 trigger-dood (fingerprint ongewijzigd).

#26 **niet sluiten:** 03-run1 nog SATISFIED op zoeklijst; mechanisme 11.

---

## 11. Step-stamp bij herhaalde waarde — GEDOCUMENTEERD, NIET GEFIXT

### Wat het is

`_merge_outcomes` schrijft `step` alleen bij een **nieuwe** concrete
string (of eerste write / weak→concrete). Zelfde label opnieuw →
`step` blijft de **eerste** keer.

Pad 1 drop’t `step >= candidate_bound_step`. Pad 2 weaken’t
`step >= last_fill_result_step`. Een reject die **string-gelijk** is aan
een eerdere (homepage) reject houdt `step=0` en overleeft beide resets.

### Exacte voorwaarde

1. Stap A schrijft `decision_id=X` `outcome=V` (V niet in `_WEAK`) met
   `step=A`.
2. Later, na bind op stap B > A, schrijft interpret opnieuw `X=V`
   (zelfde string, bv. homepage `NOT_RELEVANT` én abs `NOT_RELEVANT`).
3. Merge bump’t `step` niet → blijft A.
4. Unbind/FILL met `candidate_bound_step=B` drop’t alleen `step>=B` →
   `X=V` blijft. Pad 2 met `last_fill_result_step` tussenin wipe’t A
   evenmin als A < die drempel.

Niet: verschillende concrete strings (die winnen wél en bump’en step).
Niet: weak labels (die overschrijven confirming niet).

### Waarom niet stiekem fixen

Een automatische step-bump bij gelijke V verandert de merge-kern
(Open #11 “tegenspraak wint” is al provisional). Het zou homepage- en
abs-reject ononderscheidbaar *in de tijd* maken op een andere manier.
Geen patch zonder ontwerp.

### Citaat + bewijs

```290:295:live_offer_state_slice.py
        if (
            cur is None
            or str(cur.get("outcome") or "") in _WEAK
            or cur.get("outcome") != outcome
        ):
            best[decision_id] = {"outcome": outcome, "step": step}
```

Exacte reconstructie uit
`result_05_web_literature_abstract_20260917T083112Z.json`
`steps_contract_flags`: stap 0 én stap 3 `subject_instance=NOT_RELEVANT`
→ na merge `step=0`. Unbind+pad 2 laten het staan. Abs-only labels op
stap 3 (`access_status=OPEN_ACCESS`, `recency=IN_RANGE`) vallen wél weg.

**Known-current-behavior, geen correctness-test:**
`test_known_current_behavior_not_correctness_083112Z_merge_step_stamp`
bevriest `_fp(after2)` als
`SNAPSHOT_083112Z_AFTER_PATH1_PATH2`. Groen = “gedrag ongewijzigd”,
niet “discrepantie is weg”. Een toekomstige merge-fix **moet** deze
test opzettelijk rood maken en de snapshot herschrijven. Canonieke
abs-reject op `step=3` (homepage op UNKNOWN gezet) **wordt** gewist:
`test_083112Z_canonical_bound_reject_then_fill_path1_then_path2`.

---

## 12. Dead surface — code-terminal vóór interpret (Open #29)

### Probleem

TUI `111126Z` (`result_tui_package_crete_20260919T111126Z.json`):
`stop_reason=MAX_ACQUISITION_STEPS` `contract_satisfied=false`. Fetch
OK, 0 affordances, 1 unit, 190 tekens. LLM koos 6× STOP; code reject'te
die STOP omdat gaps bleven. Interpret draaide tóch. Stap 0
`subject_instance=UNKNOWN`; stappen 1–5 `BOOKABLE_PACKAGE` (via
mechanisme 13: entity-als-claim). HANDOVER / campagne 1: 6 identieke
`stop_reason` + eerste gap tot circuit_break.

Bol `131049Z` is **dezelfde faalklasse in de lus** (6× STOP →
`MAX_ACQUISITION_STEPS`) maar **niet** deze predicate: aff=3, units=2,
`text_chars=1093`. Ontwerp voor die restklasse staat in LEARNING_LOG
2026-09-20 (H-dead-surface-2); niet gebouwd.

### Afgewezen

- Lexicon op `"Access Denied"` / `"IP blocked"` / hostnamen — betekenis
  of sitenaam in code.
- Drempel rekken tot bol (3 global links, 2 units, 1093 tekens) — botst
  met de verplichte 2–3-unit negatieve test (sparse-real / 06 wiki).
- Contractvraag herschrijven — TUI-specifiek; lost de 6×-cyclus niet op.
- LLM STOP honoreren terwijl gaps blijven — dat is juist de reject die
  de lus eindeloos maakte.

### Oplossing + trigger

`is_dead_surface`: `fetch_ok` én `affordances_count==0` én
`candidate_units_count<=1` én `text_chars < DEAD_SURFACE_TEXT_CHARS_MAX`
(400, **provisional**, zelfde klasse als Open #6 max_candidates).
`FETCH_FAILED_OR_EMPTY` blijft eigenaar van `err` / `text_chars<40`.
Bij True: `DEAD_SURFACE_NO_CONTENT` **vóór** `_pipeline_on_obs` /
`page_text_to_observations` — geen interpret, geen entity-claim
safety-net.

**Trigger:** acquisition-loop, na `package_candidate_units`, vóór
`candidates_to_observations`.

```97:112:live_offer_state_slice.py
    if not fetch_ok:
        return False
    try:
        aff_n = int(affordances_count)
        unit_n = int(candidate_units_count)
        n_chars = int(text_chars)
        cap = int(text_chars_max)
    except (TypeError, ValueError):
        return False
    if aff_n != 0:
        return False
    if unit_n > 1:
        return False
    if n_chars < 0 or n_chars >= cap:
        return False
    return True
```

```812:817:live_offer_state_slice.py
        if is_dead_surface(
            fetch_ok=True,
            affordances_count=len(affordances),
            candidate_units_count=len(units),
            text_chars=len(text),
        ):
```

```860:869:live_offer_state_slice.py
            ledger.set_stop(DEAD_SURFACE_STOP_REASON)
            if trace:
                trace.log_stop(DEAD_SURFACE_STOP_REASON)
            print(
                f"[acquisition] step={step} STOP {DEAD_SURFACE_STOP_REASON} "
                f"aff={len(affordances)} units={len(units)} "
                f"text_chars={len(text)} (no interpret)",
                flush=True,
            )
            break
```

Commit `82cae84`. Entity-als-claim is **mechanisme 13**, niet deze
predicate.

### Bewijs

Live-bug `111126Z`: `stop_reason=MAX_ACQUISITION_STEPS`
`outcomes.subject_instance=BOOKABLE_PACKAGE`. Offline reconstruct TUI
= dead; bol `131049Z` = niet dead (cite aff=3 / units=2 / chars=1093).
01 `065415Z` / 02 `062828Z` / 05 `081459Z` / 06 `064738Z` golden
`stop_reason` ongewijzigd. Tests:
`evals/dead_surface/test_dead_surface_offline_v0.py`. Live TUI/bol
retest: **niet** zonder expliciete OK.

---

## 13. Entity-hint is geen `candidate_claim` (H-leak FIX 2)

### Probleem

`extract_entity_hint` = eerste `**bold**` in `task.md`. Die string ging
als observation de interpret in:

`add("candidate_claim", candidate_id, "identity", "entity")`

TUI-taak bold = `"one concrete bookable"`. Interpret las dat als
paginabewijs → `subject_instance=BOOKABLE_PACKAGE` op een Access-Denied
pagina. `111126Z` stappen 1–5. Candidate-unit wees de fragment terecht
af; `interpret_even_if_not_admitted=True` interprette tóch zolang er
`candidate_claim`s waren.

### Afgewezen

- Entity helemaal schrappen uit de run — `contract_meta.entity` en
  observation `candidate_id` zijn logging/identiteit, geen bewijs.
- Alleen TUI-frase blocken — lexicon / taak-specifiek.
- `interpret_even_if_not_admitted=False` als “fix” — dat verandert
  list/home interpret (andere faalklasse); de injectie blijft.
- Mechanisme 12 stretchen tot bol om H-leak te maskeren — bol injecteert
  de entity niet; TUI-H is een observation-kanaal, geen surface-count.

### Oplossing + trigger

Regel verwijderd. `page_text_to_observations` emit’t alleen paginatekst:
titel (`origin=browser_title`) en bodyregels (`origin=browser_inner_text`).
`entity` blijft `candidate_id` op die observations en in `contract_meta`.

**Trigger:** altijd in `page_text_to_observations`; geen
`channel=candidate_claim` waarvan `text` de task-bold is.

```154:157:live_detail_slice.py
    # Task/entity hint is run identity, not page evidence. Do not emit it as
    # candidate_claim (H-leak: TUI "one concrete bookable" → BOOKABLE_PACKAGE).
    if title:
        add("candidate_claim", title, "page_title", "browser_title")
```

Commit `2f030e3`.

### Bewijs

Live-bug `111126Z`: `outcomes.subject_instance=BOOKABLE_PACKAGE` terwijl
de pagina geen bookable package toont. Offline
`evals/entity_claim/test_entity_not_claim_offline_v0.py`: dunne
wiki-achtige tekst + entity=`one concrete bookable` → claim-texts zijn
page lines; frase afwezig; `origin=entity` afwezig.
`evals/h_leak/test_h_leak_offline_v0.py` injectie-assert omgedraaid.
01/02/05/06: `entity` in `contract_meta` blijft; golden `stop_reason`
onaangeroerd. Geen live zonder OK.

---

## 15. Dead surface 2a — 0 same-host http(s) (Open #30)

### Probleem

Bol `131049Z`: `stop_reason=MAX_ACQUISITION_STEPS` `contract_satisfied=false`.
Fetch OK, 3 global links, 2 units, 1093 tekens. Titel `"bol"`. Affordances:
`mailto:customerservice@bol.com`, `https://whatismyip.akamai.com/`,
`https://developers.bol.com/` — geen same-host http(s) t.o.v.
`https://www.bol.com/`. FIX 1 (#29) eist aff==0 ∧ units≤1 ∧ chars<400.

### Afgewezen

- 2b digit-tokens `403`/`404`/`429` — aparte discussie (lexicon vs
  tekenklasse); bol heeft die tokens niet.
- Units≤2 zonder same-host-filter — botst met 06 / sparse-real.
- Sitenaam `bol.com` / string `"blocked"` — lexicon.
- FIX 1 stretchen — TUI-stop_reason zou bol niet onderscheiden.

### Oplossing + trigger

`is_dead_surface_no_same_host`: `fetch_ok` én **niet** #29 én 0 http(s)
affordances met `urlparse(href).netloc == urlparse(final_url).netloc`
én `units <= 2` (provisional). mailto/tel/andere host tellen niet.
Stop `DEAD_SURFACE_NO_SAME_HOST_CONTENT` vóór interpret.

**Contactpagina-grens (aanvaard):** 2 units + alleen mailto = 2a-dead.
Deze lus navigeert via same-host http(s). False-positive: die twee
units bevatten het antwoord al (geen interpret). Escape: 3+ units of
≥1 same-host http-href.

**Trigger:** acquisition-loop na `package_candidate_units`, ná #29-check.

```176:188:live_offer_state_slice.py
    if not fetch_ok:
        return False
    if first_order_dead:
        return False
    try:
        unit_n = int(candidate_units_count)
        cap = int(max_units)
    except (TypeError, ValueError):
        return False
    if unit_n > cap:
        return False
```

```889:901:live_offer_state_slice.py
        dead1 = is_dead_surface(
            fetch_ok=True,
            affordances_count=len(affordances),
            candidate_units_count=len(units),
            text_chars=len(text),
        )
        dead2 = is_dead_surface_no_same_host(
            fetch_ok=True,
            page_url=final_url,
            affordances=affordances,
            candidate_units_count=len(units),
            first_order_dead=dead1,
        )

### Bewijs

Bol reconstruct `131049Z`: 2a True, #29 False. 06 `064738Z`: 60 aff,
33 same-host http, 2a False. TUI blijft #29. 01/02/03/05 + marktplaats /
SS / wiki-BXL: 2a False.
`evals/dead_surface/test_dead_surface_same_host_offline_v0.py`.
Geen live zonder OK.

---

## 16. Overlay-dismiss na herhaalde timeout (Open #31)

### Probleem

2dehands `140350Z`: `FILL_AND_SUBMIT` `q=fiets` daarna `q=2000` daarna
`q=bicycle` — alle drie `Locator.click: Timeout`. Citaat:
`<div role="dialog" aria-modal="true" id="sp_message_container_1494622">`
onderschept pointer events (iframe `sp_message_iframe_*` erin). Niet
alleen zoeken: élke klik/fill op die state.

Bestaande `_hide_consent_overlays` / `COOKIE_SELECTORS` zijn
consent-lexicon en golden **niet** op `browser_type` (FILL klikt de
input zonder die hide-retry).

### Afgewezen

- Kortste zichtbare knoptekst in de modal — lengte als betekenis
  ("OK"/"X"). Giswerk; een taalwissel `NL` kan korter zijn dan Accept.
- `COOKIE_SELECTORS` / `iframe[src*="consent"]` uitbreiden — lexicon.
- Elke timeout → overlay-dismiss — vangt Coolblue Zoeken (geen modal,
  fragiele locator).
- Alleen Escape — Sourcepoint negeert dat vaak; niet meetbaar offline
  op deze fixture.

### Gekozen optie

**Eerste knop in DOM-volgorde** binnen `[role=dialog]` / `aria-modal=true`.
ARIA-structuur, geen woordenlijst. Cross-origin iframe zonder
same-origin knop: `hide_blocking_dialog` op de dialog-node (enige
structurele actie die pointer-events teruggeeft).

**Trigger:** tweede timeout op dezelfde URL-path met een **ander**
`action_fingerprint`. Eerste timeout doet niets.

```31:43:overlay_dismiss.py
def overlay_dismiss_should_run(
    *,
    prior_timeout_fps: list[str] | None,
    current_fp: str,
) -> bool:
    """True after ≥1 earlier timeout fingerprint on this page, different target.

    Reuses action_fingerprint keys. First failure never dismisses (Coolblue
    Zoeken is one timeout, then a different fallback — must not fire here).
    """
```

```160:175:overlay_dismiss.py
    buttons = list(ov.get("buttons") or [])
    if buttons:
        first = buttons[0]
        return {
            "method": "first_button",
            "overlay_id": ov.get("id") or "",
            "overlay_role": ov.get("role") or "",
            "aria_modal": ov.get("aria_modal") or "",
            "n_buttons": len(buttons),
            "n_iframes": int(ov.get("n_iframes") or 0),
            "first_button_text": first.get("text") or first.get("aria_label") or "",
            "click_selector": (
                '[role="dialog"], [aria-modal="true"]'
                " >> button, [role='button'], input[type='button'], input[type='submit']"
            ),
        }

### Bewijs

Offline: eerste knop = `"Lees het cookiebeleid volledig"`, niet `"OK"`.
2dehands-fixture: id `sp_message_container_1494622`, method
`hide_blocking_dialog`. Gate: één fingerprint False; twee verschillende
True. 01/02/03/05/06 HTML: 0 `sp_message_*`; first-timeout gate False.
`evals/overlay_dismiss/test_overlay_dismiss_offline_v0.py`. Geen live.

---

## 14. Path B — contractvraag + outcome-enum in de interpret-prompt (NIET GEFIXT)

Audit 2026-09-20. Geen codewijziging. Path A was task-bold als
`candidate_claim` (mechanisme 13). Path B is: **elke** interpret-call
ziet de decision-`question` en de toegestane outcomes naast
`source_text`. Nooit live gefalsifieerd op een rijke pagina; demping
is alleen SYSTEM_PROMPT.

### Probleem

`build_user_prompt` stopt de hele decision (vraag, enum, definitions,
notes) in dezelfde user-JSON als de snippet. Een dunne of irrelevante
claim kan `BOOKABLE_PACKAGE` / `RELEVANT` / `RTX_4070` kiezen omdat de
**vraag** het woord al noemt, niet omdat de snippet het toont.
TUI `111126Z` bewees Path A; Path B bleef een hypothese.

### Afgewezen (deze audit)

- SYSTEM_PROMPT herschrijven — geen meting op rijke pagina.
- Outcome-labels hercoderen — contract-synthese, niet interpret-code.
- Vraag weglaten uit de payload — LLM heeft de vraag nodig; dat is een
  ontwerpkeuze, geen stille patch.

### Wat de prompt echt zegt

Er staat **geen** zin “gebruik ALLEEN de snippet”. De dichtstbijzijnde
regels zijn 4 (UNKNOWN boven gokken) en 6 (geen buitenkennis). “Use
ONLY” in regel 5 geldt de **definitions**, niet de observation.

```100:117:interpretation.py
SYSTEM_PROMPT = """You are a semantic interpretation coprocessor for a research agent.

You receive:
- one decision from a frozen research contract (id, question, allowed outcomes, definitions)
- one raw observation string (website text snippet)

Your job: decide whether the observation is evidence for EXACTLY ONE of the allowed outcomes.

Rules:
1. Output EXACTLY one JSON object. No markdown fences, no commentary outside JSON.
2. Schema:
   {"outcome": "<one of allowed outcomes>", "confidence": "high"|"medium"|"low", "reason": "<short>", "source_text": "<echo input>"}
3. outcome MUST be one of the allowed outcomes list (including UNKNOWN).
4. Prefer UNKNOWN over guessing when the text is ambiguous or only related, not equivalent.
5. Use ONLY the definitions supplied with this decision; do not equate labels that the
   definitions treat as distinct categories.
6. Do not use outside knowledge to invent facts not supported by the snippet.
"""
```

`SYSTEM_PROMPT_MULTI` (batch) heeft dezelfde 4/6/7-regels. Payload:

```169:178:interpretation.py
    payload = {
        "decision": {
            "id": contract_decision.get("id"),
            "question": contract_decision.get("question"),
            "outcomes": contract_decision.get("outcomes"),
            "definitions": contract_decision.get("definitions") or {},
            "notes": contract_decision.get("notes") or [],
        },
        "observation": observation,
    }
```

### Inventaris (01/02/03/05/06 + vijf campagne-contracten)

Tien frozen files, niet negen: batch vijf + campagne vijf. Bronnen:
`20260908T061529Z` (01/02/03/06), `20260916T165744Z` (05),
`20260919T110338Z` (tui/bol/marktplaats/ss/wiki).

**Patroon.** Outcome-labels zijn bijna altijd `SNAKE_CASE`-codes
(`BOOKABLE_PACKAGE`, `PRICE_INCL_VAT`, `FIGURE_FOUND`), geen vrije
Engelse zin. De **vragen** zijn vrije Engels/Nederlands en herhalen het
suggestieve woord. Path B-gevoeligheid zit dus in de vraag (+ proper
nouns in de enum), niet in “leesbare Engelse labels i.p.v. codes”.
Uitzondering: korte Engelse woorden als enum (`RELEVANT`, `VALID`,
`RECENT`, `CONFIRMED`, `OTHER`) — die kunnen ook in irrelevante
paginatekst voorkomen, maar de LLM moet het **exacte** token
uitvoeren; de priming loopt via de vraag.

| Contract | Hoogste Path-B overlap | Waarom |
|----------|------------------------|--------|
| TUI | `subject_instance` Q *bookable package* + `BOOKABLE_PACKAGE`; `destination_confirm`=`CRETE` | Zelfde priming als `111126Z`; `CRETE` staat op elke Kreta-chrome-pagina |
| 01 | `bookable` Q + `BOOKABLE`; `board_type` Q “board type” + `ALL_INCLUSIVE` | Transactioneel woord in vraag én enum |
| 02 | Q “All Inclusive” + `ALL_INCLUSIVE`; property-naam in `subject_instance`-vraag | Label staat letterlijk in de vraag |
| 03 | Q “RTX 4070” + `RTX_4070`; `IN_STOCK` | Productstring op elke Coolblue-lijstkaart |
| 05 | Q “LLM agents” + `RELEVANT`/`NOT_RELEVANT` | `RELEVANT` is gewoon Engels; vraag lekt het onderwerp |
| 06 | Q “Fuerteventura” + `CONFIRMED_ISLAND_ARTICLE` | Eilandnaam in de vraag |
| bol | Q “AirPods Pro” + `CURRENT_MODEL`; `IN_STOCK` | Productnaam in de vraag |
| marktplaats | Q “bicycle” + `CONFIRMED_BICYCLE`; `ANTWERP`/`BRUSSELS` | Stadsnaam-enum op footers |
| SS | Q “retrieval-augmented generation (RAG)” + `CONFIRMED`/`NOT_RAG`; `RECENT`/`VALID` | Onderwerp in de vraag; `VALID` is Engels |
| wiki-BXL | Q “city of Brussels” + `FIGURE_FOUND`; `NL_ARTICLE` | Relatief code-achtige enum; vraag noemt de stad |

`evidence_signals.patterns` (TUI: `"book now"`, `"reserveer"`) zitten
**niet** in `build_user_prompt` — alleen question/outcomes/definitions/notes.

### Trigger (ongewijzigd, niet gefixt)

Elke `interpret_observation` / `_multi`. Geen extra injectie naast deze
payload.

### Bewijs

Offline: `evals/h_leak/test_h_leak_offline_v0.py`
`test_build_user_prompt_does_not_inject_phrase_from_decision` — Path A
frase zit niet in de lege/denied prompt; de **vraag**
`"Is the page a specific bookable package…"` wél. Live Path B op rijke
pagina: **ontbreekt**. Geen fix zonder die meting.

---

## Appendix — campagne-infrastructuur (geen live starten vanuit deze nota)

Losse runs: `AGENT_RULES.md` regels 1–3. Batch: regel 4 (één OK voor N,
taken-lijst, tmux-naam).

| Stuk | Pad |
|------|-----|
| Start (host/node-01) | `scripts/run_task_campaign_tmux_v0.sh` |
| Sequentiële loop | `scripts/run_task_campaign_loop_v0.py` |
| Samenvatting | `scripts/analyze_campaign_v0.py` |

Per-run output blijft `evals/contract_driven/<UTC-stamp>_<taak>/` zoals
`run_contract_driven_task_v0.py` nu schrijft. Campagne-meta
(`campaign_progress.log`, manifest, circuit-breaker) staat onder
`--campaign-dir`.

**Niet** in deze nota: een taken-lijst of N vastleggen. Dat is een
apart bericht.

---

## Appendix — schijfruimte vóór onbewaakte campagne (2026-09-20)

Geen codewijziging. Meting op de host die de traces houdt.

### Probleem

Fase 2 schrijft `step_NNN_page.html` (cap 200k in `trace_session.py`).
`--min-free-gb` default **8** is één check bij **start**, niet per job.
Vraag: is 8 GiB nog realistisch als HTML groter is dan pre-Fase-2
text-only traces?

### Meting (geen live)

```
evals/contract_driven/   53M   (120 run-dirs)
evals/campaigns/         56K   (meta; 52K campaign1)
host df /                1.5T free / 1.8T  (16% used)
```

| | |
|--|--|
| gemiddelde run | 0.39 MB |
| mediaan run | 0.30 MB |
| max run | 1.8 MB (`173006Z` wiki, 7× html) |
| html-files | 121, totaal 15.6 MB |
| runs mét html | 33/120 (oudere dirs pre-Fase 2) |
| gemiddelde `*_page.html` | 126 KiB |
| max html-file | 202 KiB (trace-cap 200k + truncate-comment) |

Worst-case per run: 6 stappen × 200 KiB html ≈ 1.2 MB html + loop/result
≈ **< 2 MB**. Default-marge 8 GiB ≈ 4000 zulke runs. Middag N=3+3 = 6
jobs ≈ **12 MB**. Campagne 1 (18 runs) paste in dezelfde 53M-boom.

### Trigger (bestaand, niet gewijzigd)

```87:94:scripts/run_task_campaign_tmux_v0.sh
# Disk: available KiB on the filesystem that holds --outdir.
avail_kb="$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')"
need_kb=$((MIN_FREE_GB * 1024 * 1024))
if [[ "${avail_kb:-0}" -lt "$need_kb" ]]; then
  echo "DISK STOP: ${avail_kb} KiB free < --min-free-gb ${MIN_FREE_GB} GiB (traces accumulate)." >&2
  exit 3
fi
```

`--min-free-gb` is **ruim**, niet krap. Geen per-job hercheck. HTML-cap
in de trace:

```153:157:trace_session.py
        if html:
            html_art = self.save_artifact(
                f"step_{self._step:03d}_page.html",
                html if len(html) <= 200_000 else html[:200_000] + f"<!-- truncated +{len(html)-200000} -->",
            )
```

### Voorstel (niet implementeren zonder OK)

Marge is **niet** te krap voor een middagcampagne. HTML weglaten is
geen schijfnood. Optioneel, alleen als traces kleiner moeten voor
rsync/backup: `step_*_page.html` bewaren bij **laatste stap** of bij
`stop_reason` ≠ `CONTRACT_SATISFIED` / `DEAD_SURFACE_NO_CONTENT`;
tussentijdse stappen alleen `page_text`. Niet doen vóór de TUI/bol-
hertest — die HTML is juist het bewijs van dead-surface vs bol-block.

Niet voorgesteld: `--min-free-gb` verlagen. 8 GiB mag blijven.

---

## Appendix — middag-queue (NIET STARTEN vanuit deze nota)

Twee hypothesen, **geen** generaliteitscampagne. Reserve T2/T3, E2/E3, C1
staan **niet** op de command line: geen `task.md` onder die stems in
deze tree; alleen meenemen als het start-bericht ze bij naam noemt plus
N en sessienaam (`AGENT_RULES` regel 4).

### 1. TUI dead-surface — N=3

Fix 1 (`82cae84`): TUI Access Denied = aff=0, units=1, 190 tekens →
`DEAD_SURFACE_NO_CONTENT` vóór interpret. Verwacht: drie keer die
`stop_reason`, **niet** `MAX_ACQUISITION_STEPS`, **niet**
`BOOKABLE_PACKAGE` uit Path A. Los van campagne 1.

### 2. bol bekende grens — N=3

FIX 1 vangt bol niet (aff=3, units=2, 1093 tekens). Verwacht: opnieuw
6×-reject → `MAX_ACQUISITION_STEPS` (of `FETCH_FAILED_OR_EMPTY` zoals
`133208Z`). **Dat is geen falen** — bevestiging van de 2a/2b-grens.
Niet als regressie rapporteren.

### 3. Reserve (niet in het plakcommando)

T2/T3, E2/E3, C1 uit de eerdere 15-ideeën-lijst: alleen als het
start-bericht ze expliciet toevoegt. Geen automatische derde sessie.

### Plakcommando's (wacht op `ja, start` + exacte sessienaam)

Twee sequentiële tmux-sessies, overzichtelijker dan één mix (verschillende
verwachte `stop_reason`). Script doet `docker compose build` tenzij
`--skip-build`.

```bash
# SESSIE 1 — alleen ná: "ja, start" met sessienaam middag_tui_dead
# (N=3, taak tui_package_crete, --tasks-dir campaign1)
./scripts/run_task_campaign_tmux_v0.sh \
  --session middag_tui_dead \
  --repeats 3 \
  --tasks tui_package_crete \
  --tasks-dir tasks/campaign1_generaliteit \
  --contract-dirs evals/contract_synthesis/20260919T110338Z_synthesis \
  --max-steps 6 \
  --circuit-n 3
```

```bash
# SESSIE 2 — alleen ná TUI klaar én "ja, start" met sessienaam middag_bol_bound
# --skip-build alleen als image van sessie 1 nog vers is
./scripts/run_task_campaign_tmux_v0.sh \
  --session middag_bol_bound \
  --repeats 3 \
  --tasks bol_airpods_pro \
  --tasks-dir tasks/campaign1_generaliteit \
  --contract-dirs evals/contract_synthesis/20260919T110338Z_synthesis \
  --max-steps 6 \
  --circuit-n 3 \
  --skip-build
```

Eén gecombineerde variant (alleen als het start-bericht **beide** taken
én één sessienaam noemt): `--session middag_tui_bol --repeats 3 --tasks tui_package_crete,bol_airpods_pro` plus dezelfde `--tasks-dir` / `--contract-dirs`. Circuit is per taak; TUI-DEAD stopt bol niet.

Volgen: `tail -f evals/campaigns/<session>_<stamp>/campaign_progress.log`.
Stoppen: `tmux kill-session -t <session>`.

**Dit start niet vanzelf.** Ontbreekt N, taken-lijst of sessienaam in het
start-bericht → niet starten.
