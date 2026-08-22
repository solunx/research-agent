# Doel (A/B browser-backend test)

Vind **concrete all-inclusive (of volpension) pakket-deals** (vlucht + hotel) voor **3 personen** in **december 2026**, vertrek bij voorkeur **Zaventem (BRU)** of Charleroi, budget **max €1000 p.p.**

Dit is een **korte vergelijkingstaak**: liever 3–8 sterke kandidaten dan een exhaustieve marktanalyse.

# Constraints

- 3 volwassenen
- Periode: december 2026 (concrete data of “december 2026” filter)
- Budget: ≤ €1000 per persoon (vlucht + hotel, all-in)
- Vertrek: BRU of Charleroi (andere BE/FR-luchthavens alleen als makkelijk beschikbaar)

# Harde criteria (moeten in shortlist eerlijk afgevinkt)

- Pakket: vlucht + hotel
- All-inclusive of volpension (of expliciet “niet bevestigd” als de pagina het niet zegt)
- Prijs zichtbaar op de aanbieder-pagina
- Boekings-/detail-link

# Nice-to-haves (niet blokkeren)

- ≥ 4 sterren of goede reviews
- Zee/strand, zwembad, wellness

# Primaire bronnen (alleen deze in fase 1)

1. **nl.lastminute.com** (of lastminute.be) — pakket / vakanties  
2. **sunweb.be** — all-inclusive  
3. Optioneel als tijd over: **corendon.be**

Geen brede Google-hotelzoektocht. Geen losse vluchten.

# Aanpak / funnel

1. Werk **per site**: open de pakket-zoekflow, zet filters (3 personen, december 2026, all-in als mogelijk).
2. Haal **zichtbare** deals: hotelnaam + prijs + link.
3. Direct `add_to_shortlist` met eerlijke `constraints_check` (matched / unmatched / unknown).
4. Als een site filters negeert of datums herschrijft: noteer dat en ga naar de volgende site — niet eindeloos forms proberen.
5. Stop wanneer je 3–8 shortlist-items hebt of de primaire sites structureel falen.

# Output

- Shortlist 3–8 kandidaten (of minder met duidelijke beperkingen)
- Per item: prijs, link, match_status, wat niet geverifieerd is
- Geen verzonnen hotels

# Experiment-notitie (voor de mens, niet voor de agent)

Zelfde task, twee runs:

```bash
# A — huidige Playwright-tools
docker compose run --rm research-agent python agent.py --planned \
  --task tasks/compare_packages_dec2026.md --browser-backend playwright

# B — Browser Use als browser-executor
docker compose run --rm research-agent python agent.py --planned \
  --task tasks/compare_packages_dec2026.md --browser-backend browser_use
```

Vergelijk: `shortlist_count`, `useful_action_ratio`, `constraint_mismatches`, runtime, eerlijkheid van het rapport.
