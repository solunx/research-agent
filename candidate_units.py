"""
Generic candidate-unit packaging from page text + affordances.

Framework-only: no domain vocabulary (no hotel / board / flight / SKU enums).
Clustering is structural:
  - blank-line separated blocks
  - local links with non-trivial href as anchors
  - short windows of consecutive body lines around anchors / dense blocks

Each unit keeps co-occurring lines bound together so interpretation sees
one evidence cluster instead of isolated fragments.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


# Structural density only (FRAMEWORK_BOUNDARY #2): currency glyphs + digit runs.
# No language words (vanaf / from / p.p. / per …). Locale decimal/thousand seps allowed
# as character classes inside digit runs.
_CURRENCY_GLYPH = re.compile(r"[€$£¥]")
# Digit run: 2+ digits, optional groups with . or , as separators (structural, not lexical).
_DIGIT_RUN = re.compile(r"\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?|\d{2,}")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _skip_line_structural(line: str) -> bool:
    """Empty / tiny / extreme length only — no lexicon chrome filter (#3, #8)."""
    t = (line or "").strip()
    if not t or len(t) < 2:
        return True
    if len(t) > 240:
        return True
    return False


def _currency_glyph_count(texts: list[str]) -> int:
    return sum(len(_CURRENCY_GLYPH.findall(t or "")) for t in texts)


def _digit_run_count(texts: list[str]) -> int:
    return sum(len(_DIGIT_RUN.findall(t or "")) for t in texts)


def currency_glyph_count(texts: list[str]) -> int:
    """Public structural density helper (FRAMEWORK_BOUNDARY #2)."""
    return _currency_glyph_count(texts)


def digit_run_count(texts: list[str]) -> int:
    """Public structural density helper (FRAMEWORK_BOUNDARY #2)."""
    return _digit_run_count(texts)


def has_structural_price_signal(text: str) -> bool:
    """True if line/blob has currency glyph or digit run — no language words."""
    t = text or ""
    return bool(_CURRENCY_GLYPH.search(t) or _DIGIT_RUN.search(t))


# Date-like numeric groups with 2+ separators (DD/MM/YYYY, YYYY-MM-DD) — structural, not lexical.
_DATE_LIKE = re.compile(r"(?<!\d)\d{1,4}\s*[/\-]\s*\d{1,2}\s*[/\-]\s*\d{1,4}(?!\d)")


def line_has_price_form_d2c(text: str) -> bool:
    """
    D2c price-form digit signal (price-shape sub-experiment, 2026-08-29).

    True when a digit run looks money-shaped:
      - not part of a multi-separator date pattern
      - not a bare year 19xx/20xx
      - not a 1–2 digit score without further magnitude
      - magnitude: >=3 digits OR decimal with 2+ chars after separator
    No language words (vanaf/from/p.p.).
    """
    cleaned = _DATE_LIKE.sub(" ", text or "")
    for m in re.finditer(r"(?<!\d)(\d{1,6})([.,]\d{1,3})?(?!\d)", cleaned):
        num, dec = m.group(1), m.group(2)
        if re.fullmatch(r"(?:19|20)\d{2}", num) and not dec:
            continue
        if len(num) <= 2 and not dec:
            continue
        if len(num) >= 3 or (dec and len(dec) >= 2):
            return True
    return False


def line_is_price_like(text: str) -> bool:
    """glyph OR D2c — Fase-3 surface detector (replaces language-specific _PRICE_LINE)."""
    t = text or ""
    if _CURRENCY_GLYPH.search(t):
        return True
    return line_has_price_form_d2c(t)


def count_price_like_lines(text: str) -> int:
    """Count non-empty lines that pass line_is_price_like."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return sum(1 for ln in lines if line_is_price_like(ln))


def _path_depth(href: str) -> int:
    try:
        p = urlparse(href or "")
        parts = [x for x in (p.path or "").split("/") if x]
        return len(parts)
    except Exception:
        return 0


def _is_itemish_link(a: dict[str, Any], *, page_url: str = "") -> bool:
    """
    Structural: local (or unknown) scope, non-empty href, path has substance,
    not pure '#' / javascript, not irreversible-looking.
    """
    href = str(a.get("href") or "").strip()
    text = str(a.get("text") or "").strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return False
    scope = str(a.get("scope") or "unknown")
    if scope == "global":
        # global marketing/home rarely a single item unit
        return False
    depth = _path_depth(href)
    if depth < 1:
        return False
    # Link text is passed through (#8); no lexicon chrome drop on label.
    if _skip_line_structural(text) and not href:
        return False
    try:
        page_path = urlparse(page_url or "").path.rstrip("/")
        href_path = urlparse(href).path.rstrip("/")
        # Prefer links that leave the exact current path (item detail) or deepen it
        if href_path and page_path and href_path == page_path and "tab=" not in href:
            return False
    except Exception:
        pass
    return True


def _blank_line_blocks(raw_text: str) -> list[list[str]]:
    """Split on blank lines into non-empty line groups."""
    blocks: list[list[str]] = []
    cur: list[str] = []
    for ln in (raw_text or "").splitlines():
        if not ln.strip():
            if cur:
                blocks.append(cur)
                cur = []
            continue
        t = ln.strip()
        if _skip_line_structural(t):
            # structural skip only (empty/tiny/huge) — does not break on word lists
            if cur:
                blocks.append(cur)
                cur = []
            continue
        cur.append(t)
    if cur:
        blocks.append(cur)
    return blocks


def _window_around(lines: list[str], idx: int, radius: int = 3) -> list[str]:
    lo = max(0, idx - radius)
    hi = min(len(lines), idx + radius + 1)
    return lines[lo:hi]


def package_candidate_units(
    *,
    text: str,
    affordances: list[dict[str, Any]] | None = None,
    page_url: str = "",
    max_units: int = 8,
    max_lines_per_unit: int = 8,
) -> list[dict[str, Any]]:
    """
    Build structural candidate units from page text + local item-ish links.

    Returns list of:
      {
        unit_id, texts, item_link: {text, href}|None,
        line_span, currency_glyph_count, digit_run_count, source
      }

    Priority:
      1) blank-line blocks (natural card boundaries)
      2) link anchors not yet covered (clipped to their blank block)
    """
    aff = affordances or []
    blocks = _blank_line_blocks(text or "")
    item_links = [a for a in aff if _is_itemish_link(a, page_url=page_url)]
    item_links.sort(key=lambda a: -_path_depth(str(a.get("href") or "")))

    units: list[dict[str, Any]] = []
    used_block_idxs: set[int] = set()

    def _link_for_block(block: list[str]) -> dict[str, str] | None:
        for a in item_links:
            lab = _norm(str(a.get("text") or ""))
            if not lab:
                continue
            if any(lab in _norm(t) or _norm(t) in lab for t in block):
                return {
                    "text": str(a.get("text") or "")[:120],
                    "href": str(a.get("href") or "")[:400],
                }
        return None

    def _density_fields(texts: list[str]) -> dict[str, int]:
        return {
            "currency_glyph_count": _currency_glyph_count(texts),
            "digit_run_count": _digit_run_count(texts),
        }

    # 1) Dense blank-line blocks first (preserve card boundaries).
    # Oversized blocks are chunked (not truncated-and-discarded): a block
    # longer than max_lines_per_unit is split into consecutive windows so
    # content past the old cutoff still reaches a unit, instead of being
    # silently dropped. Purely structural (fixed-size windows on line
    # position) — no repeat/threshold judgment on which lines "matter".
    for bi, block in enumerate(blocks):
        if len(units) >= max_units:
            break
        if len(block) < 2:
            continue
        chunks = [
            block[i : i + max_lines_per_unit]
            for i in range(0, len(block), max_lines_per_unit)
        ] or [block]
        for ci, chunk in enumerate(chunks):
            if len(units) >= max_units:
                break
            if len(chunk) < 2 and len(chunks) > 1:
                # tiny tail chunk: merge into previous unit instead of a
                # near-empty extra unit
                if units and units[-1].get("block_index") == bi:
                    prev = units[-1]
                    merged = (prev["texts"] + chunk)[:max_lines_per_unit]
                    prev["texts"] = merged
                    prev.update(_density_fields(merged))
                continue
            dens_f = _density_fields(chunk)
            linked = _link_for_block(chunk)
            structural = dens_f["currency_glyph_count"] + dens_f["digit_run_count"]
            if structural < 1 and not linked:
                continue
            units.append(
                {
                    "unit_id": f"u{len(units)}",
                    "texts": chunk,
                    "item_link": linked,
                    "line_span": None,
                    **dens_f,
                    "source": "blank_block",
                    "block_index": bi,
                }
            )
        used_block_idxs.add(bi)

    # 2) Link anchors not yet covered
    for a in item_links:
        if len(units) >= max_units:
            break
        label = str(a.get("text") or "").strip()
        href = str(a.get("href") or "").strip()
        if not label:
            continue
        if any(
            (u.get("item_link") or {}).get("href") == href
            or _norm((u.get("item_link") or {}).get("text") or "") == _norm(label)
            for u in units
        ):
            continue
        found_block = None
        found_bi = None
        for bi, block in enumerate(blocks):
            if bi in used_block_idxs:
                continue
            if any(_norm(label) in _norm(t) or _norm(t) in _norm(label) for t in block):
                found_block = block
                found_bi = bi
                break
        if found_block is None:
            dens_f = _density_fields([label])
            units.append(
                {
                    "unit_id": f"u{len(units)}",
                    "texts": [label][:max_lines_per_unit],
                    "item_link": {"text": label[:120], "href": href[:400]},
                    "line_span": None,
                    **dens_f,
                    "source": "affordance_only",
                }
            )
            continue
        texts = found_block[:max_lines_per_unit]
        dens_f = _density_fields(texts)
        units.append(
            {
                "unit_id": f"u{len(units)}",
                "texts": texts,
                "item_link": {"text": label[:120], "href": href[:400]},
                "line_span": None,
                **dens_f,
                "source": "link_anchor",
                "block_index": found_bi,
            }
        )
        if found_bi is not None:
            used_block_idxs.add(found_bi)

    def _rank(u: dict[str, Any]) -> tuple:
        structural = int(u.get("currency_glyph_count") or 0) + int(
            u.get("digit_run_count") or 0
        )
        return (
            0 if u.get("item_link") else 1,
            -structural,
            -len(u.get("texts") or []),
        )

    units.sort(key=_rank)
    for i, u in enumerate(units[:max_units]):
        u["unit_id"] = f"u{i}"
    return units[:max_units]


def units_to_observations(
    units: list[dict[str, Any]],
    *,
    page_url: str = "",
    surface: str = "list_results",
    max_units: int = 6,
) -> list[dict[str, Any]]:
    """
    Emit candidate_claim observations bound by unit_id.

    Each unit becomes ONE multi-line claim (joined) so interpretation sees
    co-occurring facts, plus optional navigation obs for item_link.
    """
    obs: list[dict[str, Any]] = []
    oid = 0
    for u in units[:max_units]:
        uid = str(u.get("unit_id") or f"u{oid}")
        texts = [str(t).strip() for t in (u.get("texts") or []) if str(t).strip()]
        if not texts:
            continue
        joined = " | ".join(t[:160] for t in texts)[:500]
        obs.append(
            {
                "observation_id": f"unit-{oid}",
                "candidate_id": uid,
                "text": joined,
                "channel": "candidate_claim",
                "scope": "unit",
                "provenance": {
                    "origin": "candidate_unit_package",
                    "source_url": page_url,
                    "surface": surface,
                    "unit_id": uid,
                    "unit_source": u.get("source"),
                    "currency_glyph_count": u.get("currency_glyph_count"),
                    "digit_run_count": u.get("digit_run_count"),
                },
            }
        )
        oid += 1
        link = u.get("item_link") or {}
        href = str(link.get("href") or "").strip()
        if href:
            obs.append(
                {
                    "observation_id": f"unit-nav-{oid}",
                    "candidate_id": uid,
                    "text": href[:300],
                    "channel": "navigation",
                    "scope": "unit",
                    "provenance": {
                        "origin": "candidate_unit_link",
                        "source_url": href,
                        "surface": surface,
                        "unit_id": uid,
                        "link_text": str(link.get("text") or "")[:120],
                    },
                }
            )
            oid += 1
    return obs


def unit_item_link_targets(units: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Deduped item links for acquisition preference (text + href)."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for u in units:
        link = u.get("item_link") or {}
        text = str(link.get("text") or "").strip()
        href = str(link.get("href") or "").strip()
        if not text and not href:
            continue
        key = f"{_norm(text)}|{href.lower()}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"text": text[:120], "href": href[:400]})
    return out


def unit_claim_preview(units: list[dict[str, Any]], *, max_units: int = 6) -> list[str]:
    """Human/LLM-readable bound previews for traces and planner."""
    prev: list[str] = []
    for u in units[:max_units]:
        texts = [str(t).strip() for t in (u.get("texts") or []) if str(t).strip()]
        link = u.get("item_link") or {}
        head = " | ".join(texts[:5])[:200]
        if link.get("text") or link.get("href"):
            head = f"{head} → {link.get('text') or link.get('href')}"
        prev.append(f"[{u.get('unit_id')}] {head}")
    return prev
