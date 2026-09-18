"""
Reconstruct Coolblue search-list shape from run 20260918T110505Z.

Live observe: html_chars=699128; disk artifact 200k still inside a <style>
in <head> (no <body>). page_text had three product cards (ASUS ROG / two
HP VICTUS) with 1.649,- / 1.499,- / 1.349,-. Affordances were 47
panel_option filters and 4 nav hrefs.

This fixture is structural, not a byte-copy of the unsaved 699k DOM:
giant non-content head + chrome repeating widgets + a 3-card result list.
No site lexicon is required to parse it.
"""
from __future__ import annotations

# Measured 110505Z step 1: body never reached the 400k naive cap.
HEAD_STYLE_CHARS = 420_000
NAIVE_CAP = 400_000

ASUS_TITLE = "ASUS ROG Strix G614JIR-N4139W AZERTY"
VICTUS_A_TITLE = "HP VICTUS 16-s1044nb Azerty"
VICTUS_B_TITLE = "HP VICTUS 16-r1054nb Azerty"
ASUS_HREF = "https://www.coolblue.be/nl/laptops/asus-rog-strix-g614jir"
VICTUS_A_HREF = "https://www.coolblue.be/nl/laptops/hp-victus-16-s1044nb"
VICTUS_B_HREF = "https://www.coolblue.be/nl/laptops/hp-victus-16-r1054nb"

PAGE_TEXT = """Coolblue home
Account
Verlanglijstje
3 resultaten voor 'RTX 4070'
ASUS ROG Strix G614JIR-N4139W AZERTY
2 reviews
Krachtig genoeg voor gaming | Intel Core i9 - 16 GB - 1 TB SSD - RTX 4070
1.649,-
Morgen geleverd
Vergelijk dit product
HP VICTUS 16-s1044nb Azerty
0 reviews
Krachtig genoeg voor gaming en streaming | AMD Ryzen 7 | 16 GB | 1 TB SSD | RTX 4070
1.499,-
Morgen geleverd
Vergelijk dit product
HP VICTUS 16-r1054nb Azerty
0 reviews
Krachtig genoeg voor gaming | Intel Core i7 - 16 GB - 1 TB SSD - RTX 4070
1.349,-
Tijdelijk uitverkocht
"""

NAV_AFFORDANCES = [
    {"kind": "link", "text": "Coolblue home", "href": "https://www.coolblue.be/nl", "scope": "local"},
    {"kind": "link", "text": "Account", "href": "https://www.coolblue.be/nl/inloggen", "scope": "local"},
    {"kind": "link", "text": "Verlanglijstje", "href": "https://www.coolblue.be/nl/verlanglijstje", "scope": "local"},
    {"kind": "link", "text": "Bekijk alle categorieën", "href": "https://www.coolblue.be/nl/ons-assortiment", "scope": "local"},
]

FILTER_AFFORDANCES = [
    {"kind": "panel_option", "text": label, "href": "", "scope": "local", "role": "label"}
    for label in (
        "ASUS (1)",
        "HP (2)",
        "Blauw (1)",
        "Grijs (1)",
        "Zwart (1)",
        "AMD Ryzen 7 (1)",
        "Intel Core i7 (1)",
        "Intel Core i9 (1)",
        "1 TB (2)",
        "2 TB (1)",
        "Gaming (3)",
        "Relevantie",
        "Best beoordeeld",
        "Prijs laag - hoog",
    )
]


def filter_heavy_affordances() -> list[dict]:
    """~60-item cap shape: many panel_options, nav links last."""
    extra = [
        {"kind": "panel_option", "text": f"Filter {i}", "href": "", "scope": "local"}
        for i in range(40)
    ]
    return FILTER_AFFORDANCES + extra + NAV_AFFORDANCES


def reconstruct_110505Z_search_html(*, huge_head: bool = True) -> str:
    """Header chrome ul + filter labels + 3 product <li class=result> cards."""
    pad = ("x{}" * (HEAD_STYLE_CHARS // 3)) if huge_head else ""
    filters = "".join(f"<li class='option'>{a['text']}</li>" for a in FILTER_AFFORDANCES[:8])
    cards = f"""
    <li class="result product">
      <a href="{ASUS_HREF}">{ASUS_TITLE}</a>
      <p>Krachtig genoeg voor gaming | Intel Core i9</p>
      <p>1.649,-</p>
    </li>
    <li class="result product">
      <a href="{VICTUS_A_HREF}">{VICTUS_A_TITLE}</a>
      <p>Krachtig genoeg voor gaming en streaming | AMD Ryzen 7</p>
      <p>1.499,-</p>
    </li>
    <li class="result product">
      <a href="{VICTUS_B_HREF}">{VICTUS_B_TITLE}</a>
      <p>Krachtig genoeg voor gaming | Intel Core i7</p>
      <p>1.349,-</p>
    </li>
    """
    return f"""<!DOCTYPE html><html lang="nl"><head>
<meta charset="utf-8"/><title>RTX 4070 resultaten</title>
<style>{pad}</style>
<script>window.__cb=1;</script>
</head><body>
<ul class="header-nav">
  <li><a href="https://www.coolblue.be/en/switchlanguage">English (EN)</a></li>
  <li><a href="https://www.coolblue.be/nl/inloggen">Account</a></li>
  <li><a href="https://www.coolblue.be/nl/verlanglijstje">Verlanglijstje</a></li>
</ul>
<ul class="filters">{filters}</ul>
<ul class="results product-list">{cards}</ul>
</body></html>"""
