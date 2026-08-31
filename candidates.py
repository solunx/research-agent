"""
First-class Candidate model — intermediate abstraction for interpretation.

Framework-only (FRAMEWORK_BOUNDARY ground rules 2026-08-29):
  - No domain fields (board_type, price, airport, SKU).
  - No is_chrome / lexicon density_hits / chrome phrase lists.
  - Structural signals only: currency glyphs, digit runs, exact repeat_count.

Units (candidate_units.py) package text; Candidates are the stable object model:
  page → package_candidate_units → candidates_from_units → select_top
       → interpret / open primary_action
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

from candidate_units import (
    package_candidate_units,
    unit_claim_preview,
    unit_item_link_targets,
    units_to_observations,
)

# Path-shape help/support (URL structure, not body-text chrome lexicon).
_HELP_PATH = re.compile(
    r"/(vragen|faq|help|support|customer|klant|bagage|stoel|incheck|"
    r"cookie|privacy|legal|vacatures|pers|sitemap)(/|$)",
    re.I,
)
_CURRENCY_GLYPH = re.compile(r"[€$£¥]")
_DIGIT_RUN = re.compile(r"\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?|\d{2,}")


@dataclass
class Candidate:
    """
    Domain-agnostic candidate (LOCKED schema — CANDIDATE_LAYER §2).

    identity_hints / evidence: bound text (pass-through after exact dedupe)
    primary_action: structural itemish link only (#8)
    repeat_count: bare page-level exact-line frequency (#1) — no threshold
    currency_glyph_count / digit_run_count: structural density (#2)
    """

    candidate_id: str
    identity_hints: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    primary_action: dict[str, str] | None = None
    source_url: str = ""
    surface: str = ""
    packager_source: str = ""
    block_index: int | None = None
    repeat_count: int = 0
    currency_glyph_count: int = 0
    digit_run_count: int = 0
    n_lines: int | None = None
    max_repeat: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def evidence_blob(self, *, max_chars: int = 500) -> str:
        parts = list(self.identity_hints) + list(self.evidence)
        seen: set[str] = set()
        ordered: list[str] = []
        for p in parts:
            t = (p or "").strip()
            if not t:
                continue
            key = t.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(t)
        return " | ".join(ordered)[:max_chars]

    def has_action(self) -> bool:
        if not self.primary_action:
            return False
        return bool(
            (self.primary_action.get("href") or "").strip()
            or (self.primary_action.get("text") or "").strip()
        )

    def has_substantive_identity(self) -> bool:
        for h in self.identity_hints:
            if _is_substantive_identity_token(h):
                return True
        for t in self.evidence[:4]:
            if _is_substantive_identity_token(t):
                return True
        return False

    def structural_density(self) -> int:
        return int(self.currency_glyph_count) + int(self.digit_run_count)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _is_substantive_identity_token(s: str) -> bool:
    """Structural: multi-token or long alpha line; not pure digits/currency."""
    t = (s or "").strip()
    if not t or len(t) < 4:
        return False
    stripped = t.replace(",", "").replace(".", "").replace(" ", "")
    if stripped.isdigit():
        return False
    if _CURRENCY_GLYPH.search(t) and len(t) < 24 and not any(c.isalpha() for c in t):
        return False
    words = t.split()
    if len(words) >= 2 and any(any(c.isalpha() for c in w) for w in words):
        return True
    if len(t) >= 6 and any(c.isalpha() for c in t):
        return True
    return False


def _identity_hints_from_texts(texts: list[str], *, max_hints: int = 3) -> list[str]:
    hints: list[str] = []
    for t in texts:
        s = (t or "").strip()
        if not s or len(s) < 3:
            continue
        if s.replace(",", "").replace(".", "").replace(" ", "").isdigit():
            continue
        if len(s) > 80:
            continue
        hints.append(s[:80])
        if len(hints) >= max_hints:
            break
    return hints


def _action_is_itemish(action: dict[str, str] | None, *, page_url: str = "") -> bool:
    """Structural itemish: href shape, path depth, not help-path — no text lexicon (#8)."""
    if not action:
        return False
    text = str(action.get("text") or "").strip()
    href = str(action.get("href") or "").strip()
    if not href and not text:
        return False
    if href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return False
    if _HELP_PATH.search(href):
        return False
    try:
        page = urlparse(page_url or "")
        link = urlparse(href)
        if link.netloc and page.netloc and link.netloc != page.netloc:
            return False
        path = (link.path or "").rstrip("/")
        if path in ("", "/") or path.count("/") < 1:
            if "tab=" not in href:
                return False
    except Exception:
        pass
    return True


def _page_line_freq(page_text: str) -> Counter[str]:
    c: Counter[str] = Counter()
    for ln in (page_text or "").splitlines():
        n = _norm(ln)
        if n:
            c[n] += 1
    return c


def _repeat_count_for_texts(texts: list[str], freq: Counter[str]) -> int:
    """Bare max frequency of any evidence line elsewhere on the page (#1)."""
    if not texts or not freq:
        return 0
    return max((freq.get(_norm(t), 1) for t in texts if _norm(t)), default=0)


def _exact_dedupe_lines(texts: list[str]) -> list[str]:
    """Byte-identical (after strip) dedupe within a unit — order preserved (#3)."""
    seen: set[str] = set()
    out: list[str] = []
    for t in texts:
        s = (t or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def candidate_from_unit(
    unit: dict[str, Any],
    *,
    source_url: str = "",
    surface: str = "",
    page_line_freq: Counter[str] | None = None,
) -> Candidate:
    texts = _exact_dedupe_lines(
        [str(t).strip() for t in (unit.get("texts") or []) if str(t).strip()]
    )
    link = unit.get("item_link") or {}
    primary = None
    if link.get("text") or link.get("href"):
        cand_action = {
            "text": str(link.get("text") or "")[:120],
            "href": str(link.get("href") or "")[:400],
        }
        if _action_is_itemish(cand_action, page_url=source_url):
            primary = cand_action

    glyph = int(unit.get("currency_glyph_count") or 0)
    digit = int(unit.get("digit_run_count") or 0)
    if glyph == 0 and digit == 0 and texts:
        glyph = sum(len(_CURRENCY_GLYPH.findall(t)) for t in texts)
        digit = sum(len(_DIGIT_RUN.findall(t)) for t in texts)

    freq = page_line_freq or Counter()
    rep = _repeat_count_for_texts(texts, freq)
    # within-candidate max_repeat
    norm_counts = Counter(_norm(t) for t in texts if _norm(t))
    max_rep_in = max(norm_counts.values()) if norm_counts else 0

    return Candidate(
        candidate_id=str(unit.get("unit_id") or "u?"),
        identity_hints=_identity_hints_from_texts(texts),
        evidence=texts,
        primary_action=primary,
        source_url=source_url or "",
        surface=surface or "",
        packager_source=str(unit.get("source") or ""),
        block_index=unit.get("block_index"),
        repeat_count=int(rep),
        currency_glyph_count=glyph,
        digit_run_count=digit,
        n_lines=len(texts),
        max_repeat=max_rep_in,
    )


def candidates_from_units(
    units: list[dict[str, Any]],
    *,
    source_url: str = "",
    surface: str = "",
    max_candidates: int = 12,
    page_text: str = "",
) -> list[Candidate]:
    """Promote units; quality selection happens in select_top_candidates."""
    freq = _page_line_freq(page_text) if page_text else Counter()
    out: list[Candidate] = []
    for u in units[: max(max_candidates * 2, 16)]:
        out.append(
            candidate_from_unit(
                u, source_url=source_url, surface=surface, page_line_freq=freq
            )
        )
    return out


def rank_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """
    Structural rank only (#5): action, glyphs, identity, position, digits,
    evidence size. No is_chrome key.

    block_index as tie-break before digit_run_count (bugfix 2026-08-30):
    has_substantive_identity() is almost always True for multi-word text, so
    digit_run_count was de-facto the only discriminator — favouring digit-dense
    blocks (review grids, price calendars) over simple name+category content.
    Page position (block_index, earlier = higher on page) is a domain-free
    structural tie-break; no new semantics.
    """

    def key(c: Candidate) -> tuple:
        return (
            0 if c.has_action() else 1,
            -int(c.currency_glyph_count),
            0 if c.has_substantive_identity() else 1,
            int(c.block_index) if c.block_index is not None else 999,
            -int(c.digit_run_count),
            -len(c.evidence),
        )

    return sorted(candidates, key=key)


def _dedupe_candidates_exact(candidates: list[Candidate]) -> list[Candidate]:
    """Drop candidates whose full normalized evidence blob is identical (#3)."""
    seen: set[str] = set()
    out: list[Candidate] = []
    for c in candidates:
        blob = _norm(c.evidence_blob(max_chars=2000))
        if not blob or blob in seen:
            continue
        seen.add(blob)
        out.append(c)
    return out


def select_top_candidates(
    candidates: list[Candidate],
    *,
    max_n: int = 6,
    include_chrome: bool = False,  # noqa: ARG001 — kept for call-site compat; ignored
) -> list[Candidate]:
    """
    Top-K by structural rank. No chrome gate (#5).
    include_chrome is ignored (API compat); all candidates are eligible.
    """
    ranked = rank_candidates(_dedupe_candidates_exact(candidates))
    chosen = ranked[: max(1, max_n)] if ranked else []
    for i, c in enumerate(chosen):
        c.candidate_id = f"c{i}"
    return chosen


def extract_candidates(
    *,
    text: str,
    affordances: list[dict[str, Any]] | None = None,
    page_url: str = "",
    surface: str = "",
    # Open #6 (FRAMEWORK_BOUNDARY.md): provisional budget knob, not validated
    # across diverse page types — not locked. Token-budget floor from post-1a/1b
    # measurement only; raise per caller when needed.
    max_candidates: int = 3,
    max_units: int = 6,
) -> list[Candidate]:
    """
    Full path: page → units → candidates → top-K select.
    Defaults: max_candidates=3 / max_units=6 after post-1a volume measurement
    (PRE-1a ~276 tok; target ≤~550 tok total across 3 fixtures). Callers may raise.
    See FRAMEWORK_BOUNDARY Open item #6 — provisional, not locked.
    """
    units = package_candidate_units(
        text=text or "",
        affordances=affordances or [],
        page_url=page_url or "",
        max_units=max_units,
    )
    raw = candidates_from_units(
        units,
        source_url=page_url or "",
        surface=surface or "",
        max_candidates=max_units,
        page_text=text or "",
    )
    return select_top_candidates(raw, max_n=max_candidates)


def candidates_to_observations(
    candidates: list[Candidate],
    *,
    max_candidates: int = 6,
) -> list[dict[str, Any]]:
    units = []
    for c in candidates[:max_candidates]:
        units.append(
            {
                "unit_id": c.candidate_id,
                "texts": c.evidence or c.identity_hints,
                "item_link": c.primary_action,
                "currency_glyph_count": c.currency_glyph_count,
                "digit_run_count": c.digit_run_count,
                "source": c.packager_source or "candidate",
            }
        )
    return units_to_observations(
        units,
        page_url=candidates[0].source_url if candidates else "",
        surface=candidates[0].surface if candidates else "",
        max_units=max_candidates,
    )


def candidates_preview(candidates: list[Candidate], *, max_n: int = 8) -> list[str]:
    lines: list[str] = []
    for c in candidates[:max_n]:
        idh = " · ".join(c.identity_hints[:2]) if c.identity_hints else "(no identity hint)"
        act = ""
        if c.primary_action:
            act = f" → {c.primary_action.get('text') or c.primary_action.get('href')}"
        ident = " id+" if c.has_substantive_identity() else ""
        lines.append(
            f"[{c.candidate_id}] g={c.currency_glyph_count} d={c.digit_run_count} "
            f"r={c.repeat_count} ev={len(c.evidence)}{ident} | {idh}{act}"
        )
    return lines


def candidates_to_jsonable(candidates: list[Candidate]) -> list[dict[str, Any]]:
    return [c.to_dict() for c in candidates]


__all__ = [
    "Candidate",
    "candidate_from_unit",
    "candidates_from_units",
    "extract_candidates",
    "rank_candidates",
    "select_top_candidates",
    "candidates_to_observations",
    "candidates_preview",
    "candidates_to_jsonable",
    "package_candidate_units",
    "unit_claim_preview",
    "unit_item_link_targets",
]
