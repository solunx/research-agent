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
  page → package_candidate_units → candidates_from_units → interpret / open primary_action
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from candidate_units import (
    package_candidate_units,
    unit_claim_preview,
    unit_item_link_targets,
    units_to_observations,
)


@dataclass
class Candidate:
    """
    Domain-agnostic candidate object.

    identity_hints: short strings that appear to name or locate the object
                    (titles, bold lines, repeated proper-ish tokens) — not enums.
    evidence:       ordered text fragments bound to this candidate.
    primary_action: optional {text, href} to open/inspect further.
    """

    candidate_id: str
    identity_hints: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    primary_action: dict[str, str] | None = None
    source_url: str = ""
    surface: str = ""
    density_hits: int = 0
    packager_source: str = ""  # blank_block | link_anchor | affordance_only
    block_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def evidence_blob(self, *, max_chars: int = 500) -> str:
        """Single string for LLM interpretation of this candidate only."""
        parts = list(self.identity_hints) + list(self.evidence)
        # de-dupe preserving order
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
        blob = " | ".join(ordered)
        return blob[:max_chars]

    def has_action(self) -> bool:
        if not self.primary_action:
            return False
        return bool(
            (self.primary_action.get("href") or "").strip()
            or (self.primary_action.get("text") or "").strip()
        )


def _identity_hints_from_texts(texts: list[str], *, max_hints: int = 3) -> list[str]:
    """
    Structural identity hints only: prefer short non-numeric lines at the
    start of a unit (typical card title / name). No domain vocabulary.
    """
    hints: list[str] = []
    for t in texts:
        s = (t or "").strip()
        if not s or len(s) < 3:
            continue
        # skip pure price / pure date-ish short tokens as identity
        if s.replace(",", "").replace(".", "").replace(" ", "").isdigit():
            continue
        if len(s) > 80:
            continue
        hints.append(s[:80])
        if len(hints) >= max_hints:
            break
    return hints


def candidate_from_unit(
    unit: dict[str, Any],
    *,
    source_url: str = "",
    surface: str = "",
) -> Candidate:
    """Promote one packaged unit into a Candidate."""
    texts = [str(t).strip() for t in (unit.get("texts") or []) if str(t).strip()]
    link = unit.get("item_link") or {}
    primary = None
    if link.get("text") or link.get("href"):
        primary = {
            "text": str(link.get("text") or "")[:120],
            "href": str(link.get("href") or "")[:400],
        }
    uid = str(unit.get("unit_id") or "u?")
    return Candidate(
        candidate_id=uid,
        identity_hints=_identity_hints_from_texts(texts),
        evidence=texts,
        primary_action=primary,
        source_url=source_url or "",
        surface=surface or "",
        density_hits=int(unit.get("density_hits") or 0),
        packager_source=str(unit.get("source") or ""),
        block_index=unit.get("block_index"),
    )


def candidates_from_units(
    units: list[dict[str, Any]],
    *,
    source_url: str = "",
    surface: str = "",
    max_candidates: int = 8,
) -> list[Candidate]:
    out: list[Candidate] = []
    for u in units[:max_candidates]:
        out.append(candidate_from_unit(u, source_url=source_url, surface=surface))
    # stable ids u0.. after rank already applied by packager
    for i, c in enumerate(out):
        c.candidate_id = f"c{i}"
    return out


def extract_candidates(
    *,
    text: str,
    affordances: list[dict[str, Any]] | None = None,
    page_url: str = "",
    surface: str = "",
    max_candidates: int = 8,
) -> list[Candidate]:
    """
    Full structural path: page text + affordances → units → candidates.
    No LLM. No domain rules.
    """
    units = package_candidate_units(
        text=text or "",
        affordances=affordances or [],
        page_url=page_url or "",
        max_units=max_candidates,
    )
    return candidates_from_units(
        units,
        source_url=page_url or "",
        surface=surface or "",
        max_candidates=max_candidates,
    )


def rank_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """
    Prefer candidates with a primary action and higher density.
    Purely structural — no domain scoring.
    """

    def key(c: Candidate) -> tuple:
        return (
            0 if c.has_action() else 1,
            -c.density_hits,
            -len(c.evidence),
        )

    return sorted(candidates, key=key)


def candidates_to_observations(
    candidates: list[Candidate],
    *,
    max_candidates: int = 6,
) -> list[dict[str, Any]]:
    """
    Emit observation records bound by candidate_id (Observation Contract).
    One multi-line candidate_claim per candidate + optional navigation obs.
    """
    # reuse unit observation shape via synthetic units
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
        ev_n = len(c.evidence)
        act = ""
        if c.primary_action:
            act = f" → {c.primary_action.get('text') or c.primary_action.get('href')}"
        lines.append(
            f"[{c.candidate_id}] dens={c.density_hits} ev={ev_n} | {idh}{act}"
        )
    return lines


def candidates_to_jsonable(candidates: list[Candidate]) -> list[dict[str, Any]]:
    return [c.to_dict() for c in candidates]


# Re-export packager helpers for scripts that only import candidates
__all__ = [
    "Candidate",
    "candidate_from_unit",
    "candidates_from_units",
    "extract_candidates",
    "rank_candidates",
    "candidates_to_observations",
    "candidates_preview",
    "candidates_to_jsonable",
    "package_candidate_units",
    "unit_claim_preview",
    "unit_item_link_targets",
]
