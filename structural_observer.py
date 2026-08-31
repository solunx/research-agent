"""
F1 Structural Observer — representation axis (orthogonal to access tiers).

Access tiers (0–3) answer: how do we reach a page?
This module answers: how do we structure what we see?

Arms for representation A/B experiments
---------------------------------------
  text     — blank-line / link clustering on flattened page text (current default)
  html     — group by DOM leaf structural containers (article, listitem, card-ish)
  html_b2  — mixed-signal nearest-common-ancestor containers (identity + price
             bound at the tightest shared ancestor, not at leaf tags alone)
  ax       — accessibility-tree nodes (optional; requires snapshot fixture)

Neither arm hardcodes domain enums (hotel/board/price vocabulary as policy).
HTML arms use only structural signals: tag/role/class-shape/sibling repetition,
heading vs price-shaped text. No board_type / offer enums.

Hypothesis (METHODOLOGY / Claude challenge)
------------------------------------------
Candidate binding may be a representation problem (solve earlier in F1) rather than
a downstream classification problem (more heuristics in candidates.py).

After first A/B (2026-08-29): leaf-level html improved name+board co-location but
not name+price. Possible confound: we grouped on leaf tags (h2/h3/article) instead
of the card container that holds both. html_b2 isolates that confound.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from candidates import (
    Candidate,
    candidate_from_unit,
    extract_candidates as extract_candidates_text,
    select_top_candidates,
)
from candidate_units import (
    currency_glyph_count,
    digit_run_count,
    has_structural_price_signal,
)

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None  # type: ignore


# Structural class/id tokens — shape only, not product vocabulary
_CARDISH_CLASS = re.compile(
    r"(card|tile|item|result|listing|offer|product|row|entry|media|unit|block)",
    re.I,
)
_LISTISH_CLASS = re.compile(r"(list|results|grid|items|offers|products)", re.I)
_SKIP_TAG = frozenset(
    {
        "script",
        "style",
        "noscript",
        "svg",
        "path",
        "meta",
        "link",
        "template",
    }
)
# Document-root-ish tags: NCA here is too broad to be a single candidate
_ROOTISH = frozenset({"html", "body", "[document]"})
_MAINISH = frozenset({"main", "body", "html"})
# Heading-like structural identity anchors (tag only — no domain vocab)
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4"})


def extract_candidates_via_text(
    *,
    page_text: str,
    affordances: list[dict[str, Any]] | None = None,
    page_url: str = "",
    surface: str = "",
    max_candidates: int = 8,
    apply_quality: bool = True,
) -> list[Candidate]:
    """Arm A: current text clustering path."""
    # extract_candidates always applies select_top_candidates quality path
    cands = extract_candidates_text(
        text=page_text or "",
        affordances=affordances or [],
        page_url=page_url,
        surface=surface,
        max_candidates=max_candidates if apply_quality else max(max_candidates, 16),
    )
    if not apply_quality:
        # still return a bounded list without re-running chrome filters beyond extract
        return cands[:max_candidates]
    return cands


def _visible_text_lines(el) -> list[str]:
    """Extract non-empty text lines from an element, depth-first."""
    lines: list[str] = []
    if el is None:
        return lines
    for s in el.stripped_strings:
        t = re.sub(r"\s+", " ", s).strip()
        if t:
            lines.append(t[:240])
    # de-dupe consecutive
    out: list[str] = []
    prev = ""
    for t in lines:
        if t == prev:
            continue
        out.append(t)
        prev = t
    return out[:24]


def _local_links(el, page_url: str = "") -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    if el is None:
        return links
    for a in el.find_all("a", href=True):
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True))[:120]
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        if page_url and href.startswith("/"):
            href = urljoin(page_url, href)
        links.append({"text": text, "href": href[:400]})
    # de-dupe by href
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for L in links:
        k = L["href"].lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(L)
    return out[:6]


def _is_cardish_element(el) -> bool:
    if el is None or not getattr(el, "name", None):
        return False
    if el.name in _SKIP_TAG:
        return False
    role = (el.get("role") or "").lower()
    if role in ("listitem", "article", "option", "row"):
        return True
    if el.name in ("article", "li"):
        return True
    classes = " ".join(el.get("class") or [])
    el_id = el.get("id") or ""
    if _CARDISH_CLASS.search(classes) or _CARDISH_CLASS.search(el_id):
        return True
    return False


def _is_descendant_of_any(el, ancestors: list[Any]) -> bool:
    for a in ancestors:
        if el is a:
            return True
        try:
            if el in a.descendants:
                return True
        except Exception:
            continue
    return False


def _find_structural_containers(soup) -> list[Any]:
    """
    Collect card-like structural units:

    1) Repeating children under list-ish parents (role=list / ul / results-grid)
    2) Standalone article / cardish blocks that are NOT nested inside (1)

    Both are needed: list pages have repeating items; detail pages often have
    a few sibling cards (identity, price, promo) outside any list.
    """
    containers: list[Any] = []
    seen_ids: set[int] = set()

    def add(el) -> None:
        i = id(el)
        if i in seen_ids:
            return
        if _is_descendant_of_any(el, containers):
            return
        seen_ids.add(i)
        containers.append(el)

    # 1) list-ish parents → cardish children
    parents = []
    parents.extend(soup.find_all(attrs={"role": re.compile(r"^list$", re.I)}))
    parents.extend(soup.find_all(["ul", "ol"]))
    for el in soup.find_all(True):
        classes = " ".join(el.get("class") or [])
        if _LISTISH_CLASS.search(classes):
            parents.append(el)

    for parent in parents:
        kids = [
            c
            for c in parent.find_all(recursive=False)
            if getattr(c, "name", None) and c.name not in _SKIP_TAG
        ]
        cardish_kids = [k for k in kids if _is_cardish_element(k)]
        if len(cardish_kids) >= 2:
            for k in cardish_kids:
                add(k)
            continue
        deeper = [k for k in parent.find_all(True, recursive=True) if _is_cardish_element(k)]
        top: list[Any] = []
        for k in deeper:
            if _is_descendant_of_any(k, top):
                continue
            top.append(k)
        if len(top) >= 2:
            for k in top:
                add(k)

    # 2) Standalone articles / explicit cards (detail pages)
    for el in soup.find_all(["article"]):
        lines = _visible_text_lines(el)
        if len(lines) < 2 or len(lines) > 40:
            continue
        add(el)
    for el in soup.find_all(True):
        if el.name == "article":
            continue
        if not _is_cardish_element(el):
            continue
        lines = _visible_text_lines(el)
        if len(lines) < 2 or len(lines) > 40:
            continue
        add(el)

    return containers


def _element_depth(el) -> int:
    d = 0
    cur = el
    while cur is not None and getattr(cur, "name", None) not in (None, "[document]"):
        d += 1
        cur = getattr(cur, "parent", None)
        if d > 40:
            break
    return d


def _is_too_broad_container(el) -> bool:
    """Reject document/main roots and huge wrappers as candidate boundaries."""
    if el is None:
        return True
    name = (getattr(el, "name", None) or "").lower()
    if name in _ROOTISH or name in _MAINISH:
        return True
    # Many direct structural children ⇒ page-level layout, not one object
    kids = [
        c
        for c in el.find_all(recursive=False)
        if getattr(c, "name", None) and c.name not in _SKIP_TAG
    ]
    cardish = [k for k in kids if _is_cardish_element(k) or k.name in ("article", "section")]
    if len(cardish) >= 3:
        return True
    lines = _visible_text_lines(el)
    if len(lines) > 36:
        return True
    return False


def _find_identity_anchors(soup) -> list[Any]:
    """Heading-like nodes that can anchor an object's identity (structure only)."""
    anchors: list[Any] = []
    for tag in soup.find_all(list(_HEADING_TAGS)):
        text = re.sub(r"\s+", " ", tag.get_text(" ", strip=True))
        if len(text) < 2 or len(text) > 160:
            continue
        anchors.append(tag)
    for el in soup.find_all(attrs={"role": re.compile(r"heading", re.I)}):
        text = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if len(text) < 2:
            continue
        anchors.append(el)
    return anchors


def _find_price_anchors(soup) -> list[Any]:
    """Elements whose visible text contains a price-shaped signal (structure only)."""
    anchors: list[Any] = []
    for el in soup.find_all(["p", "span", "div", "li", "td", "strong", "b"]):
        # Prefer leaf-ish: little nested block structure
        if el.find(["p", "div", "article", "section", "li"]):
            continue
        text = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if not text or not has_structural_price_signal(text):
            continue
        if len(text) > 200:
            continue
        anchors.append(el)
    return anchors


def _nearest_common_ancestor(a, b):
    if a is None or b is None:
        return None
    ancestors_a: set[int] = set()
    cur = a
    while cur is not None:
        ancestors_a.add(id(cur))
        cur = getattr(cur, "parent", None)
    cur = b
    while cur is not None:
        if id(cur) in ancestors_a:
            return cur
        cur = getattr(cur, "parent", None)
    return None


def _dom_distance(a, b) -> int:
    """Rough distance via depths to NCA (smaller = closer)."""
    nca = _nearest_common_ancestor(a, b)
    if nca is None:
        return 10_000
    return (_element_depth(a) - _element_depth(nca)) + (_element_depth(b) - _element_depth(nca))


def _find_mixed_signal_containers(soup) -> list[Any]:
    """
    Arm B2: tightest containers that bind an identity anchor + a nearby price anchor.

    Domain-agnostic: headings + price-shaped text only. If the NCA is page-root /
    main / a multi-card layout wrapper, the pair is rejected (not a single object).
    """
    id_anchors = _find_identity_anchors(soup)
    price_anchors = _find_price_anchors(soup)
    if not id_anchors or not price_anchors:
        return []

    containers: list[Any] = []
    seen: set[int] = set()

    for id_el in id_anchors:
        best_price = None
        best_dist = 10_000
        for p_el in price_anchors:
            # Same node is useless
            if id_el is p_el:
                continue
            dist = _dom_distance(id_el, p_el)
            if dist < best_dist:
                best_dist = dist
                best_price = p_el
        if best_price is None or best_dist > 12:
            continue
        nca = _nearest_common_ancestor(id_el, best_price)
        if nca is None or _is_too_broad_container(nca):
            continue
        i = id(nca)
        if i in seen:
            continue
        # Prefer cardish NCA; still accept article/section/div with mixed signals
        lines = _visible_text_lines(nca)
        if len(lines) < 2:
            continue
        seen.add(i)
        containers.append(nca)

    return containers


def _drop_strict_parent_candidates(cands: list[Candidate]) -> list[Candidate]:
    """
    Generic nesting cleanup (domain-agnostic).

    Drop candidate A when another candidate B is a strict content subset of A
    (A looks like a parent list/wrapper that only repeats children without adding
    its own unique identity). Prevents synthetic parent-duplicate (ul + articles).
    """
    if len(cands) < 2:
        return cands

    def _line_set(c: Candidate) -> set[str]:
        return {ln.strip().lower() for ln in (c.evidence or []) if ln.strip()}

    drop: set[str] = set()
    for i, a in enumerate(cands):
        sa = _line_set(a)
        if len(sa) < 2:
            continue
        for j, b in enumerate(cands):
            if i == j:
                continue
            sb = _line_set(b)
            if not sb:
                continue
            # B's evidence is fully contained in A, and A is strictly larger
            if sb.issubset(sa) and len(sa) > len(sb) + 1:
                # A adds little unique identity beyond B's set
                a_id = {h.strip().lower() for h in (a.identity_hints or []) if h.strip()}
                b_id = {h.strip().lower() for h in (b.identity_hints or []) if h.strip()}
                unique_id = a_id - b_id - sb
                if len(unique_id) == 0:
                    drop.add(a.candidate_id)
                    break
    return [c for c in cands if c.candidate_id not in drop]


def _containers_to_candidates(
    containers: list[Any],
    *,
    page_url: str,
    surface: str,
    source_label: str,
    max_candidates: int,
    apply_quality: bool,
    drop_parents: bool = True,
) -> list[Candidate]:
    units: list[dict[str, Any]] = []
    for idx, el in enumerate(containers):
        texts = _visible_text_lines(el)
        if len(texts) < 1:
            continue
        links = _local_links(el, page_url=page_url)
        item_link = links[0] if links else None
        g = currency_glyph_count(texts)
        d = digit_run_count(texts)
        units.append(
            {
                "unit_id": f"h{idx}",
                "texts": texts[:12],
                "item_link": item_link,
                "currency_glyph_count": g,
                "digit_run_count": d,
                "source": source_label,
                "block_index": idx,
            }
        )

    cands = [
        candidate_from_unit(u, source_url=page_url, surface=surface) for u in units
    ]
    for c in cands:
        c.packager_source = source_label

    if drop_parents:
        cands = _drop_strict_parent_candidates(cands)

    if apply_quality:
        return select_top_candidates(cands, max_n=max_candidates)
    cands.sort(key=lambda c: (-c.structural_density(), -len(c.evidence), c.candidate_id))
    return cands[:max_candidates]


def extract_candidates_via_html(
    *,
    html: str,
    page_url: str = "",
    surface: str = "",
    max_candidates: int = 8,
    apply_quality: bool = False,
    drop_parents: bool = True,
) -> list[Candidate]:
    """
    Arm B (html): leaf-level DOM structural containers → Candidates.

    apply_quality=False by default: the experiment measures structure alone,
    without chrome/density post-filters from candidates.py.
    drop_parents=True applies generic parent-duplicate suppression.
    """
    if not html or not html.strip():
        return []
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 required for HTML structural observer")

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(list(_SKIP_TAG)):
        tag.decompose()

    containers = _find_structural_containers(soup)
    return _containers_to_candidates(
        containers,
        page_url=page_url,
        surface=surface,
        source_label="html_structure",
        max_candidates=max_candidates,
        apply_quality=apply_quality,
        drop_parents=drop_parents,
    )


def extract_candidates_via_html_b2(
    *,
    html: str,
    page_url: str = "",
    surface: str = "",
    max_candidates: int = 8,
    apply_quality: bool = False,
    drop_parents: bool = True,
) -> list[Candidate]:
    """
    Arm B2 (html_b2): mixed-signal nearest-common-ancestor containers.

    Isolates the confound from the first A/B: leaf tags (h2 vs price paragraph)
    vs the tightest ancestor that actually binds identity + price together.

    If identity and price live in sibling cards under <main>, NCA is too broad
    and is rejected — then B2 correctly reports that structure alone does not
    bind those facets (interpret neighbor-window becomes the next hypothesis).
    """
    if not html or not html.strip():
        return []
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 required for HTML structural observer")

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(list(_SKIP_TAG)):
        tag.decompose()

    mixed = _find_mixed_signal_containers(soup)
    leaf = _find_structural_containers(soup)

    leaf_mixed: list[Any] = []
    leaf_identity: list[Any] = []
    for el in leaf:
        texts = _visible_text_lines(el)
        if len(texts) < 1:
            continue
        blob = " ".join(texts)
        has_price = has_structural_price_signal(blob)
        has_heading = any(
            (getattr(h, "name", None) or "").lower() in _HEADING_TAGS
            for h in el.find_all(list(_HEADING_TAGS))
        )
        # Leaf already binds both signals
        if has_price and (has_heading or any(len(t) >= 4 for t in texts[:2])):
            leaf_mixed.append(el)
            continue
        # Identity-only leaf (heading present, no price). Keep when NCA binding
        # failed — otherwise detail pages lose the name/board candidate.
        if has_heading and not has_price and len(texts) >= 2:
            leaf_identity.append(el)

    # Prefer mixed NCA, then leaf-mixed, then identity-only not absorbed
    containers: list[Any] = []
    seen: set[int] = set()
    for el in mixed + leaf_mixed + leaf_identity:
        i = id(el)
        if i in seen:
            continue
        if _is_descendant_of_any(el, containers):
            continue
        seen.add(i)
        containers.append(el)

    return _containers_to_candidates(
        containers,
        page_url=page_url,
        surface=surface,
        source_label="html_b2_nca",
        max_candidates=max_candidates,
        apply_quality=apply_quality,
        drop_parents=drop_parents,
    )


def extract_candidates_via_ax(
    *,
    ax_tree: dict[str, Any] | list[Any] | None,
    page_url: str = "",
    surface: str = "",
    max_candidates: int = 8,
) -> list[Candidate]:
    """
    Arm C: accessibility tree (optional fixture).

    Expects Playwright-like accessibility.snapshot() dict with nested children,
    or a flat list of {role, name, children}.
    """
    if not ax_tree:
        return []

    nodes: list[dict[str, Any]] = []

    def walk(n: Any, depth: int = 0) -> None:
        if not isinstance(n, dict):
            return
        role = str(n.get("role") or "")
        name = str(n.get("name") or "").strip()
        children = n.get("children") or []
        if role in ("listitem", "article", "row", "option", "cell") and name:
            nodes.append({"role": role, "name": name, "depth": depth, "raw": n})
        for ch in children:
            walk(ch, depth + 1)

    if isinstance(ax_tree, list):
        for item in ax_tree:
            walk(item)
    else:
        walk(ax_tree)

    cands: list[Candidate] = []
    for i, node in enumerate(nodes[: max_candidates * 3]):
        name = node["name"]
        lines = [ln.strip() for ln in re.split(r"[\n|•]", name) if ln.strip()]
        if not lines:
            lines = [name]
        c = Candidate(
            candidate_id=f"ax{i}",
            identity_hints=lines[:3],
            evidence=lines[:12],
            primary_action=None,
            source_url=page_url,
            surface=surface,
            currency_glyph_count=currency_glyph_count(lines),
            digit_run_count=digit_run_count(lines),
            packager_source="ax_tree",
            block_index=i,
        )
        cands.append(c)

    cands.sort(key=lambda c: (-c.structural_density(), -len(c.evidence)))
    return cands[:max_candidates]


def candidate_metrics(candidates: list[Candidate]) -> dict[str, Any]:
    """Comparable metrics for A/B reports (no oracle required)."""
    n = len(candidates)
    with_action = sum(1 for c in candidates if c.has_action())
    with_id = sum(1 for c in candidates if c.has_substantive_identity())
    dens = sum(1 for c in candidates if c.structural_density() > 0)
    mean_ev = (sum(len(c.evidence) for c in candidates) / n) if n else 0.0
    mean_dens = (sum(c.structural_density() for c in candidates) / n) if n else 0.0
    # co-location proxy: same candidate has identity-ish AND price-ish
    coloc = 0
    for c in candidates:
        blob = " ".join(c.identity_hints + c.evidence)
        has_price = has_structural_price_signal(blob)
        has_id = c.has_substantive_identity()
        if has_price and has_id:
            coloc += 1
    return {
        "candidate_n": n,
        "with_primary_action": with_action,
        "with_identity": with_id,
        "with_density": dens,
        "identity_price_colocated": coloc,
        "mean_evidence_lines": round(mean_ev, 2),
        "mean_structural_density": round(mean_dens, 2),
        "packager_sources": sorted({c.packager_source for c in candidates}),
    }


def extract_for_arm(
    arm: str,
    *,
    page_text: str = "",
    html: str = "",
    ax_tree: dict | list | None = None,
    affordances: list[dict] | None = None,
    page_url: str = "",
    surface: str = "",
    max_candidates: int = 8,
    apply_quality_on_text: bool = True,
    apply_quality_on_html: bool = False,
) -> list[Candidate]:
    arm = (arm or "text").lower().strip()
    if arm == "text":
        return extract_candidates_via_text(
            page_text=page_text,
            affordances=affordances,
            page_url=page_url,
            surface=surface,
            max_candidates=max_candidates,
            apply_quality=apply_quality_on_text,
        )
    if arm == "html":
        return extract_candidates_via_html(
            html=html,
            page_url=page_url,
            surface=surface,
            max_candidates=max_candidates,
            apply_quality=apply_quality_on_html,
            drop_parents=True,
        )
    if arm in ("html_b2", "html-b2", "b2"):
        return extract_candidates_via_html_b2(
            html=html,
            page_url=page_url,
            surface=surface,
            max_candidates=max_candidates,
            apply_quality=apply_quality_on_html,
            drop_parents=True,
        )
    if arm == "ax":
        return extract_candidates_via_ax(
            ax_tree=ax_tree,
            page_url=page_url,
            surface=surface,
            max_candidates=max_candidates,
        )
    raise ValueError(
        f"unknown representation arm: {arm!r} (expected text|html|html_b2|ax)"
    )
