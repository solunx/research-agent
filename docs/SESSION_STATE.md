# Session state — lees dit elke sessie (niet LEARNING_LOG / BOUNDARY_AUDIT_FINAL)

**Canoniek pad:** `scripts/run_contract_driven_task_v0.py` → frozen contract → candidates → interpret → code STOP. Regel: code = structuur, LLM = betekenis. Live Docker/GPU: zie `docs/AGENT_RULES.md`.

**Snapshot 2026-09-20.** Laatste live: tmux `live_33_31`, image `sha256:4785cb0d…`, marktplaats **3/3** `CONTRACT_SATISFIED`. Waarom-naslag: `MECHANISM_NOTES.md`. Item-detail: `FRAMEWORK_BOUNDARY.md`. Architectuur/testdiscipline: `HANDOVER.md`.

---

## Register #22–#33

| # | Kort | Status | Restant / niet doen |
|---|------|--------|---------------------|
| **#22** | Entity-binding, fail-closed | **stabiel** (code + live 02 9/9). Cluster K provisional | Geen lexicon-binding. `#33` hergebruikt dit **niet** als evidence-bus (same-record exempt + subject-ref blijft detail) |
| **#23** | Hero-board coverage | **downgraded** — geen gap na #22 | Alleen heropenen met ruwe `result_*.json` + same-run candidates |
| **#24a** | `Submit` ⊂ `Submitted` | **gesloten** `0084f11` | — |
| **#24** | OPEN_URL-allowlist = aff ∪ shown `primary_action.href` | **gesloten** live `062211Z` OPEN abs `source=llm` | Verzonnen URL blijft `href_not_in_affordances` |
| **#24b** | Leaf-HTML op `list_results` | **open** — representatie live (`171515Z` per-paper `/abs/`) | Coolblue nog **0×** product-`/product/` OPEN. **Niet** `html_b2` |
| **#25** | FILL na current-page `NOT_RELEVANT` | **gesloten** live `083112Z` | Contract bleef false door merge → **#26**, niet #25 |
| **#26** | Twee reset-paden (bound unbind + unbound FILL-round) | **open — niet sluiten** | Pad 2 live `061149Z`/`064948Z`. Exacte `083112Z`-merge houdt homepage-`NOT_RELEVANT` op `step=0`. **Geen** `_merge_outcomes`-fix zonder overleg. `live_33_31` bind=0 (homepage `live_detail`) |
| **#27** | Long innerText wrap + geen recap | **gesloten** live `111714Z` `claim_extracted=EXTRACTED` | Tweede cap op observations is regressie |
| **#28** | Download = stay-on-page | **gesloten** live `162616Z` `download.kept_page=true` | Geen PDF-parse |
| **#29** | Dead surface, 0 aff, ≤1 unit, &lt;400 chars | **gesloten** middag S1 TUI **3×** `DEAD_SURFACE_NO_CONTENT` | Char-budget provisional (zelfde klasse als #6/#10) |
| **#30** | Dead surface 2a, 0 same-host http | **gesloten** voor de trigger: S2 bol **1×** `DEAD_SURFACE_NO_SAME_HOST_CONTENT` | **2×** `FETCH_FAILED_OR_EMPTY` (Page.goto 60s) — infra, niet 2a. Geen 2b (403/404) zonder apart besluit |
| **#31** | Overlay-dismiss (2e timeout, zelfde path, ander fp) + type/click hide-retry | **gesloten** als ontwerp+code | ARIA-vangnet: 1e Coolblue-Zoeken-Timeout is **geen** dismiss. Hide-retry op `browser_type`/`browser_click`. `live_33_31` FILL zonder Timeout; overlay_dismiss unused |
| **#32** | HTML-replace splice (D2c/glyph, max 1) | **gesloten** middag S4 wiki **3×** `population_figure=FIGURE_FOUND` | **#10** T=3 tagt wiki-artikel nog als `list_results` — dat is niet deze splice |
| **#33** | List-card → detail, extra kanaal, one-shot | **gesloten** optie B | `consume_prior_list_card_into_observations` zet pending=False (alleen eerste interpret na OPEN). Live `163011Z` inject zichtbaar; 105757Z city-carry = **offline**. Clear bij #26 unbind |

---

## Overige open (niet #22-familie)

| # | Status | Eén regel |
|---|--------|-----------|
| **#4** | open, meting | Chrome-cluster stats ná #1–#5; oude probe was predicaat-gefilterd |
| **#6** | provisional | `max_candidates=3` / `max_units=6` — budgetknop, geen theorema |
| **#10** | **open** | Abs-trigger live-bewezen (`070449Z` `live_offer_state`). **T=3 niet locken** over paginatypes. Wiki-artikel blijft `list_results` |
| **#19** | provisional | `_merge_outcomes` + skip-satisfied. `NOT_STATED` is contractvocabulaire, geen framework-sentinel. Complement van #26 |
| **#20** | Fase B dicht als policy | Default `batch_decisions=False`; opt-in `--batch-decisions` (tip bij n≥4) |
| **#21** | grotendeels superseded | Fase G `input_field`+FILL. Rest: click→related-input fallback (`7863753`, live FILL `103711Z`) |
| **Taak 03** | open gedrag | A+B+C op zoeklijst. Post-#26: `061149Z` SATISFIED **0× OPEN_URL**; `064948Z` OPEN categorieën, geen `/product/` |
| **Path B** | geïnventariseerd, niet gefixt | Interpret-prompt bevat contractvraag + outcome-enum (`MECHANISM_NOTES` §14) |

---

## Stabiel (niet opnieuw diagnosticeren)

Taak **02** 9/9 `CONTRACT_SATISFIED` (stap 0). Fase G FILL. Entity-binding (#22). `batch_decisions` opt-in. Taak **05** na #10 **5/5** `CONTRACT_SATISFIED` `claim_extracted=EXTRACTED` (`070449Z` `/abs/2609.18128`; `073200Z` zelfde; `075144Z` `/abs/2609.13860`; `081459Z` `/abs/2609.18128`; `072546Z` `/abs/2609.20625`). Wiki middag S4 3/3 `FIGURE_FOUND`. Marktplaats `live_33_31` 3/3 SATISFIED.

---

## Campagnes

| Campagne | Resultaat | Actie |
|----------|-----------|--------|
| `campaign1_generaliteit_20260919T111126Z` | 18 runs, **0/18** SATISFIED, 5 CIRCUIT_BREAK | **Niet herstarten** |
| Middag-queue 2026-09-20 (6 tmux) | S1 TUI #29; S2 bol #30+FETCH; S3 marktplaats overlay/#33-diagnose; S4 wiki #32; S5 `--trace-interpret`; S6 SS upstream 405 | Klaar. QUEUE_DONE `2026-09-20T13:52:19Z` |
| `live_33_31_20260920T160944Z` | marktplaats **3/3** SATISFIED (`BRUSSELS` postcode / `ANTWERP` listing+inject / `ANTWERP` zoeklijst) | Klaar |

Circuit: n=3, zelfde `stop_reason`+first-gap. Campagne-infra: `scripts/run_task_campaign_tmux_v0.sh` — niet starten zonder N + taken-lijst + tmux-sessienaam in **dat** bericht.

---

## Open (top 3) — werkvolgorde

1. **#26** — niet sluiten; geen merge-fix zonder overleg.
2. **#10** — T=3 provisionally; wiki-surface is dit item, niet #32.
3. **#24b / taak 03** — leaf-HTML live; nog geen Coolblue product-OPEN. Niet `html_b2`.

**Hard verboden zonder overleg:** `html_b2`; derde exclusive `return pool_X` zonder splice (`MECHANISM_NOTES` §17); `_WEAK` oprekken i.p.v. #26; overlay-dismiss op **elke** Timeout.

Volledige docs alleen bij audit/verificatie: `MECHANISM_NOTES.md`, `FRAMEWORK_BOUNDARY.md`, `HANDOVER.md`, `CANDIDATE_LAYER.md` LOCKED, `LEARNING_LOG.md`, `BOUNDARY_AUDIT_FINAL.md`.
