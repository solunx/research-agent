"""
Observation Builder v0.2 — WHAT was WHERE. No semantic outcomes.

Notes are OFF by default (include_notes=False).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


CHANNELS = frozenset(
    {"candidate_claim", "search_context", "navigation", "page_chrome", "unknown"}
)


def make_observation(
    *,
    observation_id: str,
    candidate_id: str,
    text: str,
    channel: str,
    scope: str = "unknown",
    origin: str = "unknown",
    source_url: str = "",
    surface: str = "",
) -> dict[str, Any]:
    if channel not in CHANNELS:
        channel = "unknown"
    return {
        "observation_id": observation_id,
        "candidate_id": candidate_id,
        "text": text,
        "channel": channel,
        "scope": scope,
        "provenance": {
            "origin": origin,
            "source_url": source_url,
            "surface": surface,
        },
    }


def observations_from_card_record(rec: dict[str, Any], idx: int = 0) -> list[dict[str, Any]]:
    """
    Build observations from an explicit card/page record (fixture or future harvest).

    Expected optional fields on rec:
      candidate_id, source_url,
      card_texts: list[str]           → candidate_claim / scope=card
      search_query: dict|str          → search_context / scope=search
      chrome_texts: list[str]         → page_chrome / scope=page
      detail_url: str                 → navigation / scope=card or page
    """
    cid = str(rec.get("candidate_id") or rec.get("name") or f"c{idx}")
    base_url = str(rec.get("source_url") or rec.get("url") or "")
    out: list[dict[str, Any]] = []

    for j, t in enumerate(rec.get("card_texts") or []):
        t = str(t).strip()
        if not t:
            continue
        out.append(
            make_observation(
                observation_id=f"{idx}-card-{j}",
                candidate_id=cid,
                text=t,
                channel="candidate_claim",
                scope="card",
                origin="card_fields",
                source_url=base_url,
                surface="card",
            )
        )

    # name / price convenience (shortlist-shaped)
    name = str(rec.get("name") or "").strip()
    price = str(rec.get("price") or "").strip()
    if name and not any(o["text"] == name for o in out):
        out.append(
            make_observation(
                observation_id=f"{idx}-name",
                candidate_id=cid,
                text=name,
                channel="candidate_claim",
                scope="card",
                origin="shortlist",
                source_url=base_url,
                surface="search_card",
            )
        )
    if price:
        out.append(
            make_observation(
                observation_id=f"{idx}-price",
                candidate_id=cid,
                text=price,
                channel="candidate_claim",
                scope="card",
                origin="shortlist",
                source_url=base_url,
                surface="search_card",
            )
        )

    detail = str(rec.get("detail_url") or "").strip()
    if detail:
        out.append(
            make_observation(
                observation_id=f"{idx}-detail",
                candidate_id=cid,
                text=detail,
                channel="navigation",
                scope="card",
                origin="card_fields",
                source_url=detail,
                surface="detail",
            )
        )
    elif base_url:
        out.append(
            make_observation(
                observation_id=f"{idx}-nav",
                candidate_id=cid,
                text=base_url,
                channel="navigation",
                scope="page",
                origin="shortlist",
                source_url=base_url,
                surface="list",
            )
        )

    # search context from explicit field or URL query
    sq = rec.get("search_query")
    if isinstance(sq, dict):
        for k, v in sq.items():
            val = v if isinstance(v, str) else ",".join(str(x) for x in v)
            out.append(
                make_observation(
                    observation_id=f"{idx}-sq-{k}",
                    candidate_id=cid,
                    text=f"{k}={val}",
                    channel="search_context",
                    scope="search",
                    origin="url_query",
                    source_url=base_url,
                    surface="search",
                )
            )
    elif isinstance(sq, str) and sq.strip():
        out.append(
            make_observation(
                observation_id=f"{idx}-sq",
                candidate_id=cid,
                text=sq.strip(),
                channel="search_context",
                scope="search",
                origin="url_query",
                source_url=base_url,
                surface="search",
            )
        )

    if base_url:
        q = parse_qs(urlparse(base_url).query)
        for key in ("meal", "Mealplan", "board", "pension"):
            if key in q:
                val = ",".join(q[key])
                text = f"{key}={val}"
                if not any(o["text"] == text and o["channel"] == "search_context" for o in out):
                    out.append(
                        make_observation(
                            observation_id=f"{idx}-sc-{key}",
                            candidate_id=cid,
                            text=text,
                            channel="search_context",
                            scope="search",
                            origin="url_query",
                            source_url=base_url,
                            surface="list",
                        )
                    )

    for j, t in enumerate(rec.get("chrome_texts") or []):
        t = str(t).strip()
        if not t:
            continue
        out.append(
            make_observation(
                observation_id=f"{idx}-chrome-{j}",
                candidate_id=cid,
                text=t,
                channel="page_chrome",
                scope="page",
                origin="card_fields",
                source_url=base_url,
                surface="chrome",
            )
        )

    return out


def build_from_fixture_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, rec in enumerate(cases):
        out.extend(observations_from_card_record(rec, i))
    return _dedup(out)


def build_from_run_dir(
    run_dir: Path,
    *,
    include_notes: bool = False,
) -> list[dict[str, Any]]:
    """Shortlist (+ optional notes). Notes OFF by default."""
    shortlist_path = run_dir / "shortlist.json"
    data = json.loads(shortlist_path.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else data.get("items") or data.get("shortlist") or []
    out: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        rec = {
            "candidate_id": item.get("name") or item.get("id") or f"c{i}",
            "name": item.get("name"),
            "price": item.get("price"),
            "source_url": item.get("source_url") or item.get("url"),
            "card_texts": item.get("card_texts") or item.get("claims") or [],
            "chrome_texts": item.get("chrome_texts") or [],
            "detail_url": item.get("detail_url"),
        }
        # harvest optional raw fields as card claims (still no semantics)
        for key in ("board_text", "meal_text", "flight_text", "raw_evidence", "observed_raw"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                rec.setdefault("card_texts", [])
                if isinstance(rec["card_texts"], list):
                    rec["card_texts"] = list(rec["card_texts"]) + [val.strip()]
        out.extend(observations_from_card_record(rec, i))

    if include_notes:
        out.extend(_notes_observations(run_dir / "notes.jsonl", [str(x.get("name") or "") for x in items]))

    return _dedup(out)


def _notes_observations(notes_path: Path, candidate_ids: list[str]) -> list[dict[str, Any]]:
    """Legacy notes path — not used in main route. Weak binding; origin=notes."""
    if not notes_path.exists():
        return []
    out: list[dict[str, Any]] = []
    chrome_re = re.compile(r"(Pakket bekijken|Boek nu|3 kleine tassen|Filter|Sorteer)", re.I)
    board_re = re.compile(r"(Enkel kamer|All[- ]?inclusive|Volpension|Ontbijt inbegrepen|Room only)", re.I)
    flight_re = re.compile(r"(vlucht inbegrepen|Flight included|Heen- en terugvlucht)", re.I)
    for i, line in enumerate(notes_path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            text = json.dumps(row, ensure_ascii=False)
        except json.JSONDecodeError:
            text = line
        for cid in candidate_ids:
            if not cid or cid[:10].lower() not in text.lower():
                continue
            for m in board_re.finditer(text):
                out.append(
                    make_observation(
                        observation_id=f"n{i}-b",
                        candidate_id=cid,
                        text=m.group(0),
                        channel="candidate_claim",
                        scope="note",
                        origin="notes",
                    )
                )
            for m in flight_re.finditer(text):
                out.append(
                    make_observation(
                        observation_id=f"n{i}-f",
                        candidate_id=cid,
                        text=m.group(0),
                        channel="candidate_claim",
                        scope="note",
                        origin="notes",
                    )
                )
            for m in chrome_re.finditer(text):
                out.append(
                    make_observation(
                        observation_id=f"n{i}-c",
                        candidate_id=cid,
                        text=m.group(0),
                        channel="page_chrome",
                        scope="page",
                        origin="notes",
                    )
                )
    return out


def _dedup(obs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    uniq: list[dict[str, Any]] = []
    for o in obs:
        key = (o["candidate_id"], o["channel"], o["text"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(o)
    return uniq


# --- harvest observations.jsonl → literal observations (no semantics) ---

# UI / baggage labels: channel only, still no board/flight enums.
_CHROME_LITERALS = frozenset(
    {
        "pakket bekijken",
        "boek nu",
        "boek nu, betaal later",
        "3 kleine tassen per boeking",
        "3 kleine tassen",
        "sorteer",
        "filter",
        "personaliseer je pakket",
    }
)

_SKIP_ENTITIES = frozenset(
    {
        "",
        "pakket bekijken",
        "3 kleine tassen per boeking",
        "personaliseer je pakket",
        "appartement",
        "hotel",
        "landhuis",
    }
)


def split_raw_evidence(raw: str) -> list[str]:
    """Literal split on '|' only. No synonym maps, no outcomes."""
    if not raw or not str(raw).strip():
        return []
    parts = [p.strip() for p in str(raw).split("|")]
    return [p for p in parts if p]


def _is_chrome_literal(text: str) -> bool:
    t = text.strip().lower()
    if t in _CHROME_LITERALS:
        return True
    for c in _CHROME_LITERALS:
        if c in t and len(t) < 80:
            return True
    return False


def _entity_usable(entity: str, entity_score: float, min_score: float) -> bool:
    e = (entity or "").strip()
    if not e:
        return False
    if e.lower() in _SKIP_ENTITIES:
        return False
    if entity_score < min_score:
        return False
    return True


def observations_from_harvest_row(
    row: dict[str, Any],
    idx: int,
    *,
    min_entity_score: float = 0.7,
) -> list[dict[str, Any]]:
    """
    One observations.jsonl row → zero or more Observation dicts.
    Uses entity + raw_evidence + source_url only. No board_type / flight enums.
    """
    entity = str(row.get("entity") or "").strip()
    try:
        score = float(row.get("entity_score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    if not _entity_usable(entity, score, min_entity_score):
        return []

    url = str(row.get("source_url") or row.get("page_url") or "")
    raw = str(row.get("raw_evidence") or "")
    value = str(row.get("value") or "").strip()
    out: list[dict[str, Any]] = []

    # entity name as claim
    out.append(
        make_observation(
            observation_id=f"h{idx}-entity",
            candidate_id=entity,
            text=entity,
            channel="candidate_claim",
            scope="card",
            origin="harvest_entity",
            source_url=url,
            surface="harvest",
        )
    )

    segments = split_raw_evidence(raw)
    for j, seg in enumerate(segments):
        # skip pure price duplicates of value later; still emit segment as claim
        if _is_chrome_literal(seg):
            ch, scope = "page_chrome", "page"
        else:
            ch, scope = "candidate_claim", "card"
        out.append(
            make_observation(
                observation_id=f"h{idx}-seg{j}",
                candidate_id=entity,
                text=seg,
                channel=ch,
                scope=scope,
                origin="raw_evidence",
                source_url=url,
                surface="harvest",
            )
        )

    if value and not any(o["text"] == value for o in out):
        out.append(
            make_observation(
                observation_id=f"h{idx}-val",
                candidate_id=entity,
                text=value,
                channel="candidate_claim",
                scope="card",
                origin="harvest_value",
                source_url=url,
                surface="harvest",
            )
        )

    if url:
        out.append(
            make_observation(
                observation_id=f"h{idx}-nav",
                candidate_id=entity,
                text=url,
                channel="navigation",
                scope="page",
                origin="harvest_url",
                source_url=url,
                surface="list",
            )
        )
        q = parse_qs(urlparse(url).query)
        for key in ("meal", "Mealplan", "board", "pension"):
            if key in q:
                val = ",".join(q[key])
                out.append(
                    make_observation(
                        observation_id=f"h{idx}-sc-{key}",
                        candidate_id=entity,
                        text=f"{key}={val}",
                        channel="search_context",
                        scope="search",
                        origin="url_query",
                        source_url=url,
                        surface="list",
                    )
                )

    return out


def build_from_observations_jsonl(
    path: Path,
    *,
    min_entity_score: float = 0.7,
    prefer_offer_price: bool = True,
) -> list[dict[str, Any]]:
    """
    Load harvest observations.jsonl and emit Observation contract rows.
    Prefer one primary offer_price row per entity when multiple exist.
    """
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if prefer_offer_price:
        by_entity: dict[str, dict[str, Any]] = {}
        for row in rows:
            ent = str(row.get("entity") or "").strip()
            if not ent:
                continue
            attr = str(row.get("attribute") or "")
            prev = by_entity.get(ent)
            if prev is None:
                by_entity[ent] = row
                continue
            # prefer offer_price + higher confidence / entity_score
            def rank(r: dict[str, Any]) -> tuple:
                return (
                    1 if r.get("attribute") == "offer_price" else 0,
                    float(r.get("entity_score") or 0),
                    float(r.get("confidence") or 0),
                    len(str(r.get("raw_evidence") or "")),
                )

            if rank(row) > rank(prev):
                by_entity[ent] = row
        rows = list(by_entity.values())

    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        out.extend(
            observations_from_harvest_row(row, i, min_entity_score=min_entity_score)
        )
    return _dedup(out)


def build_from_run_dir_rich(
    run_dir: Path,
    *,
    include_notes: bool = False,
    include_shortlist: bool = True,
    min_entity_score: float = 0.7,
) -> list[dict[str, Any]]:
    """Preferred run path: observations.jsonl raw_evidence first, optional shortlist merge."""
    out: list[dict[str, Any]] = []
    obs_path = run_dir / "observations.jsonl"
    if obs_path.exists():
        out.extend(
            build_from_observations_jsonl(obs_path, min_entity_score=min_entity_score)
        )
    if include_shortlist and (run_dir / "shortlist.json").exists():
        out.extend(build_from_run_dir(run_dir, include_notes=include_notes))
    elif include_notes:
        out.extend(build_from_run_dir(run_dir, include_notes=True))
    return _dedup(out)
