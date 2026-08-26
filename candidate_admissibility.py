"""
Candidate Admissibility v0 — structural gate only.

Question: does this harvested entity look like a *result / offer row*?
Not: is it a hotel? is it all-inclusive?

Outputs: ADMISSIBLE | NOT_ADMISSIBLE | UNKNOWN

No board/flight enums. No LLM.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

ADMISSIBLE = "ADMISSIBLE"
NOT_ADMISSIBLE = "NOT_ADMISSIBLE"
UNKNOWN = "UNKNOWN"

# Structural: generic type nouns that are labels, not named offers (not board semantics).
_GENERIC_TYPE_LABELS = frozenset(
    {
        "hotel",
        "appartement",
        "landhuis",
        "studio",
        "kamer",
        "room",
        "resort",  # alone, without a proper name — see _looks_named_offer
    }
)

# Structural chrome/nav patterns: short UI phrases (language-agnostic-ish shape heuristics
# plus a tiny fixed set of exact harvest entities that are *page chrome*, not offers).
# Prefer exact entity match over substring to avoid "Hotel X Contact" false negatives later.
_CHROME_EXACT = frozenset(
    {
        "vragen & contact",
        "vragen en contact",
        "personaliseer je pakket",
        "pakket bekijken",
        "boek nu",
        "boek nu, betaal later",
    }
)


def _pipe_segment_count(raw: str) -> int:
    if not raw:
        return 0
    return len([p for p in str(raw).split("|") if p.strip()])


def _looks_named_offer(entity: str) -> bool:
    """Heuristic: has a proper-name shape (capitalized token longer than a type label)."""
    e = (entity or "").strip()
    if not e:
        return False
    # "Name · distance" cards still named
    if "·" in e:
        return True
    tokens = re.findall(r"[A-Za-zÀ-ÿ0-9]{2,}", e)
    if not tokens:
        return False
    # at least one token length >= 4 that is not only a generic type word
    for t in tokens:
        if len(t) >= 4 and t.lower() not in _GENERIC_TYPE_LABELS:
            return True
    return False


# Structural lodging *name tokens* (product-title shape), not meal-plan semantics.
_LODGING_TITLE_TOKENS = frozenset(
    {
        "hotel",
        "resort",
        "apartamentos",
        "apartments",
        "apartment",
        "suite",
        "suites",
        "club",
        "villa",
        "villas",
        "hostel",
        "inn",
        "lodge",
        "palace",
        "riad",
        "riads",
    }
)


def _looks_lodging_title(entity: str) -> bool:
    e = (entity or "").lower()
    if "·" in (entity or ""):
        return True
    tokens = set(re.findall(r"[a-zà-ÿ0-9]{2,}", e))
    return bool(tokens & _LODGING_TITLE_TOKENS)


def structural_features(row: dict[str, Any]) -> dict[str, Any]:
    entity = str(row.get("entity") or "").strip()
    raw = str(row.get("raw_evidence") or "")
    url = str(row.get("source_url") or row.get("page_url") or "")
    try:
        entity_score = float(row.get("entity_score") or 0.0)
    except (TypeError, ValueError):
        entity_score = 0.0
    try:
        marketing_penalty = float(row.get("marketing_penalty") or 0.0)
    except (TypeError, ValueError):
        marketing_penalty = 0.0
    try:
        confidence = float(row.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    attribute = str(row.get("attribute") or "")
    path = urlparse(url).path.lower() if url else ""

    return {
        "entity": entity,
        "entity_len": len(entity),
        "entity_score": entity_score,
        "marketing_penalty": marketing_penalty,
        "confidence": confidence,
        "attribute": attribute,
        "pipe_segments": _pipe_segment_count(raw),
        "raw_len": len(raw),
        "is_line_item": bool(row.get("is_line_item")),
        "cluster_size": int(row.get("cluster_size") or 0),
        "url_path": path,
        "url_is_search_list": "/s/tsx" in path or "search" in path,
        "url_looks_help": any(x in path for x in ("/help", "/contact", "/faq")),
        "named_offer_shape": _looks_named_offer(entity),
        "entity_lower": entity.lower(),
    }


def decide_admissibility(row: dict[str, Any]) -> dict[str, Any]:
    """
    Structure-only decision with explicit reason codes (no meal-plan enums).
    """
    f = structural_features(row)
    reasons: list[str] = []

    # --- hard NOT ---
    if not f["entity"]:
        return {
            "decision": NOT_ADMISSIBLE,
            "reasons": ["empty_entity"],
            "features": f,
        }
    if f["entity_lower"] in _CHROME_EXACT:
        return {
            "decision": NOT_ADMISSIBLE,
            "reasons": ["chrome_exact_entity"],
            "features": f,
        }
    if f["url_looks_help"]:
        return {
            "decision": NOT_ADMISSIBLE,
            "reasons": ["url_help_or_contact"],
            "features": f,
        }
    if f["marketing_penalty"] >= 0.9:
        return {
            "decision": NOT_ADMISSIBLE,
            "reasons": ["marketing_penalty_high"],
            "features": f,
        }
    if f["entity_score"] < 0.35:
        return {
            "decision": NOT_ADMISSIBLE,
            "reasons": ["entity_score_very_low"],
            "features": f,
        }
    # pure type label without name
    if f["entity_lower"] in _GENERIC_TYPE_LABELS and not f["named_offer_shape"]:
        return {
            "decision": NOT_ADMISSIBLE,
            "reasons": ["generic_type_label_only"],
            "features": f,
        }

    word_count = len(f["entity"].split())
    # Card titles with "·" (distance) are structural result cards, not slogans
    has_card_dot = "·" in f["entity"]
    # Slogan / marketing headline shape: many words or question mark
    if "?" in f["entity"] or (word_count >= 6 and not has_card_dot):
        return {
            "decision": NOT_ADMISSIBLE,
            "reasons": ["slogan_or_long_phrase_entity"],
            "features": f,
        }
    if word_count >= 5 and f["pipe_segments"] <= 2 and not has_card_dot:
        return {
            "decision": NOT_ADMISSIBLE,
            "reasons": ["long_phrase_weak_card"],
            "features": f,
        }

    lodging_title = _looks_lodging_title(f["entity"])
    f["lodging_title_shape"] = lodging_title

    # --- ADMISSIBLE: named lodging-title + card-like raw_evidence ---
    offer_like = f["attribute"] in ("offer_price", "amount:primary") or f[
        "attribute"
    ].startswith("offer")
    if (
        lodging_title
        and f["named_offer_shape"]
        and f["entity_score"] >= 0.7
        and f["pipe_segments"] >= 2
        and f["marketing_penalty"] < 0.5
        and offer_like
    ):
        return {
            "decision": ADMISSIBLE,
            "reasons": ["lodging_title", "score_ok", "card_like_raw_evidence"],
            "features": f,
        }

    # Brand-style titles without "Hotel/Resort" token (still short + strong card evidence)
    if (
        not lodging_title
        and f["named_offer_shape"]
        and f["entity_score"] >= 0.85
        and f["pipe_segments"] >= 3
        and word_count <= 3
        and f["marketing_penalty"] < 0.5
        and offer_like
    ):
        return {
            "decision": ADMISSIBLE,
            "reasons": ["short_brand_title", "high_score", "multi_segment_card"],
            "features": f,
        }

    # Destination / place aggregates: named but no lodging-title token → UNKNOWN
    if f["named_offer_shape"] and f["entity_score"] >= 0.7 and f["pipe_segments"] >= 2:
        return {
            "decision": UNKNOWN,
            "reasons": ["place_or_aggregate_not_confirmed_lodging_card"],
            "features": f,
        }

    if f["entity_score"] >= 0.5 and f["named_offer_shape"]:
        return {
            "decision": UNKNOWN,
            "reasons": ["partial_structure"],
            "features": f,
        }

    return {
        "decision": UNKNOWN,
        "reasons": reasons or ["insufficient_structural_signal"],
        "features": f,
    }
