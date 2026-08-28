"""
First-class Candidate model — the missing intermediate abstraction.

Problem this solves
-------------------
Loose claims force the agent to reconstruct "which facts belong together"
via ranking, provenance, surface heuristics, and large LLM prompts.
Humans do the opposite: spot one object, bind nearby evidence, then evaluate.

A Candidate is:
  a recognizable potential entity/offer on a page, with structurally bound
  evidence and an optional primary action to open that candidate further.

Framework-only: no domain fields (no board_type, price, airport, SKU).
Those remain *contract outcomes* produced by interpretation of candidates.

Relationship to candidate_units.py
----------------------------------
Units are the structural packager (blank blocks + link anchors).
Candidates are the stable object model used by interpretation and acquisition:
  page → package_candidate_units → candidates_from_units → quality select
       → interpret / open primary_action

Quality (v1, offline-validated)
-------------------------------
- Drop / downrank chrome candidates (FAQ, nav seasons, pure menu).
- Keep identity-bearing candidates even at density 0.
- primary_action only if structural item-ish (same-host, non-help path).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

from candidate_units import (
    package_candidate_units,
    unit_claim_preview,
    unit_item_link_targets,
    units_to_observations,
)

# --- structural chrome / help patterns (not domain offer vocab) ---
_CHROME_HINT = re.compile(
    r"^(nl|fr|en|de|cookie|privacy|login|registreer|register|newsletter|"
    r"instagram|facebook|twitter|copyright|menu|zoeken|search|home|"
    r"veelgestelde(\s+vragen)?|faq|klantenservice|contact|inloggen|"
    r"online inchecken|stoel\s*/?\s*bagage(\s*reserveren)?|naam wijzigen|"
    r"handbagage(\s+bij\s+\w+)?|"
    r"zomer\s*\d{4}|winterzon|last\s*minutes|verre\s*reizen|zonvakanties|"
    r"all\s*inclusive|vliegtickets|specials|"
    r"foto'?s(\s*&\s*video'?s)?|kaart|beoordelingen|beschrijving|vlucht)$",
    re.I,
)
_HELP_PATH = re.compile(
    r"/(vragen|faq|help|support|customer|klant|bagage|stoel|incheck|"
    r"cookie|privacy|legal|vacatures|pers|sitemap)(/|$)",
    re.I,
)
_DATEISH = re.compile(
    r"^(\d{1,2}\s+\w+\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"\d{1,2}\s+\w+\s+\d{4}\s*\([^)]+\)|"
    r"\d+\s*dagen|\d+\s*nachten)$",
    re.I,
)
_PRICEISH_LINE = re.compile(
    r"(€|\$|£|\bp\.?\s*p\.?\b|\bva\.?\s*\d|\bvanaf\b|\bfrom\b)",
    re.I,
)


@dataclass
class Candidate:
    """
    Domain-agnostic candidate object.

    identity_hints: short strings that appear to name or locate the object
    evidence:       ordered text fragments bound to this candidate
    primary_action: optional {text, href} — only when structurally item-ish
    is_chrome:      structural chrome/nav/help cluster (not for primary interpret)
    """

    candidate_id: str
    identity_hints: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    primary_action: dict[str, str] | None = None
    source_url: str = ""
    surface: str = ""
    density_hits: int = 0
    packager_source: str = ""
    block_index: int | None = None
    is_chrome: bool = False

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
        """
        Identity that is not pure chrome / pure date / pure price token.
        Multi-token or capitalized-ish name lines count.
        """
        for h in self.identity_hints:
            if _is_substantive_identity_token(h):
                return True
        # also scan first evidence lines
        for t in self.evidence[:4]:
            if _is_substantive_identity_token(t):
                return True
        return False


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _is_substantive_identity_token(s: str) -> bool:
    t = (s or "").strip()
    if not t or len(t) < 4:
        return False
    if _CHROME_HINT.match(t):
        return False
    if _DATEISH.match(t):
        return False
    if _PRICEISH_LINE.search(t) and len(t) < 24:
        return False
    if t.replace(",", "").replace(".", "").replace(" ", "").isdigit():
        return False
    # FAQ / support phrases even when multi-word
    low = t.lower()
    if any(
        k in low
        for k in (
            "veelgestelde",
            "faq",
            "inchecken",
            "handbagage",
            "klantenservice",
            "stoel",
            "bagage reserveren",
        )
    ):
        return False
    words = t.split()
    if len(words) >= 2:
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
        # prefer substantive first, but still collect short non-chrome
        if _CHROME_HINT.match(s):
            continue
        hints.append(s[:80])
        if len(hints) >= max_hints:
            break
    return hints


def _action_is_itemish(action: dict[str, str] | None, *, page_url: str = "") -> bool:
    """
    Structural: reject help/FAQ/global support paths and pure chrome labels.
    Same-host preferred; tab deep-links on same path allowed.
    """
    if not action:
        return False
    text = str(action.get("text") or "").strip()
    href = str(action.get("href") or "").strip()
    if not href and not text:
        return False
    if _CHROME_HINT.match(text):
        return False
    if href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return False
    if _HELP_PATH.search(href):
        return False
    try:
        page = urlparse(page_url or "")
        link = urlparse(href)
        if link.netloc and page.netloc and link.netloc != page.netloc:
            # off-host rarely primary item action for this page's candidates
            return False
        # shallow marketing roots
        path = (link.path or "").rstrip("/")
        if path in ("", "/") or path.count("/") < 1:
            if "tab=" not in href:
                return False
    except Exception:
        pass
    return True


def _candidate_looks_chrome(c: Candidate) -> bool:
    """
    Structural chrome cluster: low density, no substantive identity,
    and evidence dominated by nav/season/FAQ tokens.
    """
    if c.density_hits >= 2:
        return False
    texts = list(c.identity_hints) + list(c.evidence)
    if not texts:
        return True
    chrome_n = 0
    for t in texts:
        nt = _norm(t)
        if _CHROME_HINT.match(t) or _CHROME_HINT.match(nt):
            chrome_n += 1
            continue
        if len(t) <= 24 and _CHROME_HINT.search(nt):
            chrome_n += 1
    ratio = chrome_n / max(1, len(texts))
    # FAQ / nav only
    if ratio >= 0.5 and c.density_hits == 0:
        # allow through if clear multi-token place/entity name present
        if c.has_substantive_identity() and any(
            len(x.split()) >= 2 and not _CHROME_HINT.match(x) for x in texts
        ):
            # still chrome if ALL substantive lines are review "Over X:" only
            if not any(
                _DATEISH.match(x) for x in texts[:1]
            ) and ratio < 0.85:
                pass  # fall through to other checks
            else:
                return True
        else:
            return True
    # pure review-date blocks: start with date + "Over X:" without density
    if c.density_hits == 0 and texts:
        if _DATEISH.match(texts[0]) and any(
            _norm(x).startswith("over ") for x in texts[1:3]
        ):
            return True
    # single-tab affordance-only noise
    if (
        c.density_hits == 0
        and len(texts) <= 2
        and all(_CHROME_HINT.match(t) or len(t) < 20 for t in texts)
    ):
        return True
    return False


def candidate_from_unit(
    unit: dict[str, Any],
    *,
    source_url: str = "",
    surface: str = "",
) -> Candidate:
    texts = [str(t).strip() for t in (unit.get("texts") or []) if str(t).strip()]
    link = unit.get("item_link") or {}
    primary = None
    if link.get("text") or link.get("href"):
        cand_action = {
            "text": str(link.get("text") or "")[:120],
            "href": str(link.get("href") or "")[:400],
        }
        if _action_is_itemish(cand_action, page_url=source_url):
            primary = cand_action
        # else leave None — better no action than help/FAQ
    c = Candidate(
        candidate_id=str(unit.get("unit_id") or "u?"),
        identity_hints=_identity_hints_from_texts(texts),
        evidence=texts,
        primary_action=primary,
        source_url=source_url or "",
        surface=surface or "",
        density_hits=int(unit.get("density_hits") or 0),
        packager_source=str(unit.get("source") or ""),
        block_index=unit.get("block_index"),
    )
    c.is_chrome = _candidate_looks_chrome(c)
    return c


def candidates_from_units(
    units: list[dict[str, Any]],
    *,
    source_url: str = "",
    surface: str = "",
    max_candidates: int = 12,
) -> list[Candidate]:
    """Promote all units; quality selection happens in select_top_candidates."""
    out: list[Candidate] = []
    for u in units[: max(max_candidates * 2, 16)]:
        out.append(candidate_from_unit(u, source_url=source_url, surface=surface))
    return out


def rank_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """
    Rank for interpretation priority:
      1) non-chrome
      2) density
      3) substantive identity (even at dens 0)
      4) has primary_action
      5) evidence size
    """

    def key(c: Candidate) -> tuple:
        return (
            1 if c.is_chrome else 0,
            -c.density_hits,
            0 if c.has_substantive_identity() else 1,
            0 if c.has_action() else 1,
            -len(c.evidence),
        )

    return sorted(candidates, key=key)


def select_top_candidates(
    candidates: list[Candidate],
    *,
    max_n: int = 6,
    include_chrome: bool = False,
) -> list[Candidate]:
    """
    Interpretation set:
      - always prefer non-chrome ranked list
      - guarantee inclusion of high-density candidates
      - guarantee inclusion of substantive-identity candidates (even dens=0)
      - drop pure chrome unless include_chrome
    """
    ranked = rank_candidates(candidates)
    chosen: list[Candidate] = []
    seen: set[int] = set()

    def add(c: Candidate) -> None:
        i = id(c)
        if i in seen:
            return
        if c.is_chrome and not include_chrome:
            return
        seen.add(i)
        chosen.append(c)

    # pass 1: dense non-chrome
    for c in ranked:
        if c.density_hits >= 1 and not c.is_chrome:
            add(c)
        if len(chosen) >= max_n:
            break

    # pass 2: substantive identity (property name + board often dens=0)
    if len(chosen) < max_n:
        for c in ranked:
            if c.has_substantive_identity() and not c.is_chrome:
                add(c)
            if len(chosen) >= max_n:
                break

    # pass 3: fill with remaining non-chrome
    if len(chosen) < max_n:
        for c in ranked:
            if not c.is_chrome:
                add(c)
            if len(chosen) >= max_n:
                break

    # re-id for stable c0.. in selected set
    for i, c in enumerate(chosen):
        c.candidate_id = f"c{i}"
    return chosen


def extract_candidates(
    *,
    text: str,
    affordances: list[dict[str, Any]] | None = None,
    page_url: str = "",
    surface: str = "",
    max_candidates: int = 6,
    max_units: int = 16,
) -> list[Candidate]:
    """
    Full path: page → units → candidates → quality select (top-K).
    No LLM. No domain offer enums.
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
                "density_hits": c.density_hits,
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
        chrome = " chrome" if c.is_chrome else ""
        ident = " id+" if c.has_substantive_identity() else ""
        lines.append(
            f"[{c.candidate_id}] dens={c.density_hits} ev={len(c.evidence)}"
            f"{ident}{chrome} | {idh}{act}"
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
