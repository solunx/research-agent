"""
Generic Decision Executor v0.2 — offline experiment (evidence channels).

Hypothesis
----------
Given a Research Contract decision (evidence_signals + optional evidence_channels)
and a *channel-structured* observation bundle, a domain-agnostic executor emits:

  PASS | FAIL | UNKNOWN | SPEC_GAP

without any `if decision_id == ...` branches.

v0.2 change: evidence is not one text blob. Each signal declares which channels
it may read (candidate_claims, search_context, navigation, page_context).
Default when evidence_channels omitted: candidate_claims only (fail-closed —
search URL filters must not silently become candidate claims).

No live agent wiring.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse, unquote

OUTCOME_UNKNOWN = "UNKNOWN"
VALID_RESULTS = frozenset({"PASS", "FAIL", "UNKNOWN", "SPEC_GAP"})
VALID_POLARITY = frozenset({"supports", "contradicts"})

# Fixed small channel vocabulary (code-owned labels; meaning from contract).
EVIDENCE_CHANNELS = (
    "candidate_claims",  # name, price, raw card text, entity-local claims
    "search_context",    # query params / filter state (meal=, dateFrom=)
    "navigation",        # URL path shape (list vs detail)
    "page_context",      # page_role and light chrome — rarely for hard criteria
)
DEFAULT_SIGNAL_CHANNELS = ("candidate_claims",)

ChatFn = Callable[[list[dict[str, Any]]], dict[str, Any]]


@dataclass
class StageResult:
    decision_id: str
    result: str  # PASS | FAIL | UNKNOWN | SPEC_GAP
    outcome: str | None = None
    reason: str = ""
    source: str = "deterministic"  # deterministic | llm | none
    matched_patterns: list[str] = field(default_factory=list)
    matched_channels: list[str] = field(default_factory=list)
    item_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Evidence channels (generic, from shortlist / page_state rows)
# ---------------------------------------------------------------------------

def _join(parts: list[str]) -> str:
    return " | ".join(p for p in parts if p and str(p).strip())


def _query_blob(url: str) -> str:
    """Decode query string into searchable text (search_context only)."""
    if not url:
        return ""
    try:
        q = urlparse(url).query
        if not q:
            return ""
        pairs = []
        for k, vals in parse_qs(q, keep_blank_values=True).items():
            for v in vals:
                pairs.append(f"{k}={unquote(v)}")
        return " ".join(pairs)
    except Exception:
        return ""


def _path_blob(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlparse(url)
        return f"{p.path or ''} {p.query or ''}".strip()
    except Exception:
        return url


def build_evidence_channels(item: dict[str, Any]) -> dict[str, str]:
    """
    Split item fields into provenance channels (casefolded at match time).

    candidate_claims: identity + card/raw text only — NOT source_url filters.
    search_context: query parameters from URL.
    navigation: path + coarse URL shape markers.
    page_context: page_role and light structure labels (not sibling members).
    """
    candidate: list[str] = []
    candidate.append(str(item.get("name") or ""))
    candidate.append(str(item.get("price") or ""))
    candidate.append(str(item.get("details") or ""))

    ev = item.get("evidence") or {}
    obs = ev.get("observed") or {}
    if isinstance(obs, dict):
        candidate.append(str(obs.get("entity") or ""))
        candidate.append(str(obs.get("value") or ""))
        candidate.append(str(obs.get("raw_evidence") or ""))

    for c in item.get("claims") or []:
        if isinstance(c, dict):
            candidate.append(str(c.get("claim") or ""))
        else:
            candidate.append(str(c))

    # Matching structure member for this item only
    name_cf = str(item.get("name") or "").casefold()
    ps = item.get("page_state") or {}
    st = ps.get("structure") or {}
    for m in st.get("members") or []:
        ent = str(m.get("entity") or "")
        if name_cf and name_cf in ent.casefold():
            candidate.append(ent)
            candidate.append(str(m.get("value") or ""))
            candidate.append(str(m.get("raw_evidence") or ""))

    url = str(item.get("source_url") or ps.get("observed_url") or "")
    req = str(ps.get("requested_url") or "")

    search = _join([_query_blob(url), _query_blob(req)])
    nav = _join([_path_blob(url), _path_blob(req), url, req])

    page: list[str] = []
    page.append(str(ps.get("page_role") or ""))
    # rejected reasons as page chrome labels only (not as candidate claims)
    for r in (st.get("rejected_members") or [])[:8]:
        page.append(str(r.get("reject_reason") or ""))
        page.append(str(r.get("role") or ""))

    return {
        "candidate_claims": _join(candidate),
        "search_context": search,
        "navigation": nav,
        "page_context": _join(page),
    }


def build_evidence_text(item: dict[str, Any]) -> str:
    """Backward-compat flat blob (all channels). Prefer channel-aware matching."""
    ch = build_evidence_channels(item)
    return _join([ch.get(k, "") for k in EVIDENCE_CHANNELS])


def text_for_signal(channels: dict[str, str], signal: dict[str, Any]) -> tuple[str, list[str]]:
    """
    Resolve which channel texts a signal may read.
    Default: candidate_claims only (fail-closed).
    """
    requested = signal.get("evidence_channels")
    if not requested:
        used = list(DEFAULT_SIGNAL_CHANNELS)
    else:
        if isinstance(requested, str):
            requested = [requested]
        used = []
        for c in requested:
            c = str(c).strip()
            if c in EVIDENCE_CHANNELS and c not in used:
                used.append(c)
        if not used:
            used = list(DEFAULT_SIGNAL_CHANNELS)
    parts = [channels.get(c, "") for c in used]
    return _join(parts), used


def item_key(item: dict[str, Any], index: int) -> str:
    name = str(item.get("name") or f"item_{index}")
    url = str(item.get("source_url") or "")[:60]
    return f"{index}:{name}|{url}"


def validate_decision_schema(decision: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(decision, dict):
        return False, "decision is not an object"
    did = decision.get("id")
    if not did:
        return False, "missing decision.id"
    outcomes = decision.get("outcomes")
    if not isinstance(outcomes, list) or len(outcomes) < 2:
        return False, "outcomes need >= 2 values"
    if OUTCOME_UNKNOWN not in outcomes:
        return False, "outcomes must include UNKNOWN"
    if not decision.get("question"):
        return False, "missing question"
    signals = decision.get("evidence_signals")
    if signals is not None and not isinstance(signals, list):
        return False, "evidence_signals must be a list when present"
    if isinstance(signals, list):
        for j, sig in enumerate(signals):
            if not isinstance(sig, dict):
                return False, f"evidence_signals[{j}] not object"
            if str(sig.get("polarity") or "") not in VALID_POLARITY:
                return False, f"evidence_signals[{j}].polarity invalid"
            pats = sig.get("patterns")
            if not isinstance(pats, list) or not pats:
                return False, f"evidence_signals[{j}].patterns required"
            ch = sig.get("evidence_channels")
            if ch is not None:
                if isinstance(ch, str):
                    ch = [ch]
                if not isinstance(ch, list):
                    return False, f"evidence_signals[{j}].evidence_channels must be list"
                for c in ch:
                    if str(c) not in EVIDENCE_CHANNELS:
                        return False, (
                            f"evidence_signals[{j}].evidence_channels unknown {c!r}; "
                            f"allowed={list(EVIDENCE_CHANNELS)}"
                        )
    return True, ""


# ---------------------------------------------------------------------------
# Deterministic evaluation via contract evidence_signals
# ---------------------------------------------------------------------------

def _match_signals(
    channels: dict[str, str],
    signals: list[dict[str, Any]],
) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, list[str]]]:
    """
    Return supports, contradicts, and channels_hit per outcome.
    Each signal only searches text from its evidence_channels (default candidate_claims).
    """
    supports: dict[str, list[str]] = {}
    contradicts: dict[str, list[str]] = {}
    channels_hit: dict[str, list[str]] = {}
    for sig in signals:
        outcome = str(sig.get("outcome") or "")
        if not outcome or outcome == OUTCOME_UNKNOWN:
            continue
        polarity = str(sig.get("polarity") or "")
        blob, used = text_for_signal(channels, sig)
        blob_cf = blob.casefold()
        hits = []
        for pat in sig.get("patterns") or []:
            p = str(pat).casefold()
            if p and p in blob_cf:
                hits.append(str(pat))
        if not hits:
            continue
        if polarity == "supports":
            supports.setdefault(outcome, []).extend(hits)
        elif polarity == "contradicts":
            contradicts.setdefault(outcome, []).extend(hits)
        channels_hit.setdefault(outcome, [])
        for c in used:
            if c not in channels_hit[outcome]:
                channels_hit[outcome].append(c)
    return supports, contradicts, channels_hit


def evaluate_decision_deterministic(
    decision: dict[str, Any],
    evidence: dict[str, str] | str,
    *,
    item_key_str: str = "",
) -> StageResult:
    """evidence: channel dict from build_evidence_channels, or legacy flat string."""
    did = str(decision.get("id") or "")
    ok, reason = validate_decision_schema(decision)
    if not ok:
        return StageResult(
            decision_id=did or "?",
            result="SPEC_GAP",
            reason=reason,
            source="none",
            item_key=item_key_str,
        )
    if isinstance(evidence, str):
        channels = {c: (evidence if c == "candidate_claims" else "") for c in EVIDENCE_CHANNELS}
        # legacy: put full blob only in candidate_claims path is wrong for URL;
        # put full string in all channels for backward compat of old tests only
        channels = {c: evidence for c in EVIDENCE_CHANNELS}
    else:
        channels = {c: str((evidence or {}).get(c) or "") for c in EVIDENCE_CHANNELS}

    signals = decision.get("evidence_signals") or []
    if not signals:
        return StageResult(
            decision_id=did,
            result="UNKNOWN",
            reason="no evidence_signals in contract for this decision",
            source="deterministic",
            item_key=item_key_str,
        )

    if not any(str(channels.get(c) or "").strip() for c in EVIDENCE_CHANNELS):
        return StageResult(
            decision_id=did,
            result="UNKNOWN",
            reason="empty evidence channels",
            source="deterministic",
            item_key=item_key_str,
        )

    supports, contradicts, channels_hit = _match_signals(channels, signals)

    # Unique support wins. Contradicts on *other* outcomes is compatible
    # (e.g. "enkel kamer" supports ROOM_ONLY and contradicts ALL_INCLUSIVE).
    if len(supports) == 1:
        outcome = next(iter(supports))
        if outcome in contradicts:
            return StageResult(
                decision_id=did,
                result="UNKNOWN",
                reason=f"outcome {outcome} has both supports and contradicts hits",
                source="deterministic",
                matched_patterns=supports[outcome] + contradicts.get(outcome, []),
                item_key=item_key_str,
            )
        pats = list(supports[outcome])
        for co, cp in contradicts.items():
            if co != outcome:
                pats.extend(cp)
        return StageResult(
            decision_id=did,
            result="PASS",
            outcome=outcome,
            reason=f"supports signal matched uniquely for {outcome}",
            source="deterministic",
            matched_patterns=pats,
            matched_channels=channels_hit.get(outcome, []),
            item_key=item_key_str,
        )

    if len(supports) > 1:
        return StageResult(
            decision_id=did,
            result="UNKNOWN",
            reason=f"ambiguous supports: {sorted(supports.keys())}",
            source="deterministic",
            matched_patterns=[p for ps in supports.values() for p in ps],
            item_key=item_key_str,
        )

    # No supports: FAIL only with exactly one contradicted outcome
    if len(contradicts) == 1:
        outcome = next(iter(contradicts))
        return StageResult(
            decision_id=did,
            result="FAIL",
            outcome=outcome,
            reason=f"contradicts signal matched uniquely for {outcome} (no supports)",
            source="deterministic",
            matched_patterns=contradicts[outcome],
            matched_channels=channels_hit.get(outcome, []),
            item_key=item_key_str,
        )

    if len(contradicts) > 1:
        return StageResult(
            decision_id=did,
            result="UNKNOWN",
            reason=f"ambiguous contradicts without supports: {sorted(contradicts.keys())}",
            source="deterministic",
            matched_patterns=[p for ps in contradicts.values() for p in ps],
            item_key=item_key_str,
        )

    return StageResult(
        decision_id=did,
        result="UNKNOWN",
        reason="no evidence_signals matched",
        source="deterministic",
        item_key=item_key_str,
    )


# ---------------------------------------------------------------------------
# Optional LLM micro-call on UNKNOWN only (enum-only)
# ---------------------------------------------------------------------------

def evaluate_decision_llm(
    decision: dict[str, Any],
    evidence_text: str,
    chat_fn: ChatFn,
    *,
    item_key_str: str = "",
) -> StageResult:
    did = str(decision.get("id") or "")
    outcomes = [str(o) for o in (decision.get("outcomes") or [])]
    if OUTCOME_UNKNOWN not in outcomes:
        return StageResult(
            decision_id=did,
            result="SPEC_GAP",
            reason="outcomes missing UNKNOWN",
            source="none",
            item_key=item_key_str,
        )

    system = (
        "You are a typed semantic decision coprocessor. "
        "Answer with EXACTLY one allowed outcome string. No JSON, no explanation."
    )
    user = json.dumps(
        {
            "decision_id": did,
            "question": decision.get("question"),
            "allowed_outcomes": outcomes,
            "evidence_text": (evidence_text or "")[:2000],
            "unknown_conditions": decision.get("unknown_conditions") or [],
        },
        ensure_ascii=False,
    )
    try:
        msg = chat_fn(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
        content = (msg.get("content") if isinstance(msg, dict) else str(msg)) or ""
        content = content.strip().strip('"').strip("'")
        # take first line / first token that matches an outcome
        chosen = None
        for o in outcomes:
            if o in content or content == o:
                chosen = o
                break
        if chosen is None:
            # try exact first word
            first = content.split()[0] if content.split() else ""
            if first in outcomes:
                chosen = first
        if chosen is None or chosen == OUTCOME_UNKNOWN:
            return StageResult(
                decision_id=did,
                result="UNKNOWN",
                outcome=OUTCOME_UNKNOWN if chosen == OUTCOME_UNKNOWN else None,
                reason=f"llm returned non-outcome or UNKNOWN: {content[:80]!r}",
                source="llm",
                item_key=item_key_str,
            )
        return StageResult(
            decision_id=did,
            result="PASS",
            outcome=chosen,
            reason="llm enum decision",
            source="llm",
            item_key=item_key_str,
        )
    except Exception as e:
        return StageResult(
            decision_id=did,
            result="UNKNOWN",
            reason=f"llm error: {type(e).__name__}: {e}",
            source="llm",
            item_key=item_key_str,
        )


def execute_decision(
    decision: dict[str, Any],
    item: dict[str, Any],
    *,
    index: int = 0,
    chat_fn: ChatFn | None = None,
    llm_on_unknown: bool = False,
) -> StageResult:
    """Generic entry: deterministic first; optional LLM only on UNKNOWN."""
    key = item_key(item, index)
    channels = build_evidence_channels(item)
    det = evaluate_decision_deterministic(decision, channels, item_key_str=key)
    if det.result != "UNKNOWN" or not llm_on_unknown or chat_fn is None:
        return det
    # LLM sees candidate_claims primarily; append other channels labeled
    llm_blob = "\n".join(f"{k}: {v}" for k, v in channels.items() if v)
    return evaluate_decision_llm(decision, llm_blob, chat_fn, item_key_str=key)


# ---------------------------------------------------------------------------
# Batch + metrics vs oracle
# ---------------------------------------------------------------------------

def execute_contract_on_items(
    contract: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    decision_ids: list[str] | None = None,
    chat_fn: ChatFn | None = None,
    llm_on_unknown: bool = False,
) -> list[StageResult]:
    decisions = contract.get("decisions") or []
    if decision_ids:
        want = set(decision_ids)
        decisions = [d for d in decisions if str(d.get("id")) in want]
    results: list[StageResult] = []
    for i, item in enumerate(items):
        for d in decisions:
            results.append(
                execute_decision(
                    d,
                    item,
                    index=i,
                    chat_fn=chat_fn,
                    llm_on_unknown=llm_on_unknown,
                )
            )
    return results


def load_oracle(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def score_against_oracle(
    results: list[StageResult],
    oracle: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Oracle row:
      {
        "item_name_substr": "Sercotel",
        "decision_id": "board_type",
        "expected_result": "PASS"|"FAIL"|"UNKNOWN",
        "expected_outcome": "ROOM_ONLY"|null
      }
    Matching: decision_id exact + item_name_substr in item_key (casefold).
    """
    by_pair: dict[tuple[str, str], StageResult] = {}
    for r in results:
        # item_key format index:name|url
        name = r.item_key.split(":", 1)[-1].split("|", 1)[0]
        by_pair[(r.decision_id, name.casefold())] = r

    n = 0
    correct = 0
    false_pass = 0
    false_pass_cases: list[dict[str, Any]] = []
    blocker_hits = 0
    blocker_total = 0
    details: list[dict[str, Any]] = []

    for row in oracle:
        did = str(row.get("decision_id") or "")
        substr = str(row.get("item_name_substr") or "").casefold()
        exp_result = str(row.get("expected_result") or "")
        exp_outcome = row.get("expected_outcome")
        is_blocker = bool(row.get("is_blocker"))

        matched: StageResult | None = None
        for (d, name), r in by_pair.items():
            if d == did and substr in name:
                matched = r
                break

        n += 1
        if is_blocker:
            blocker_total += 1

        if matched is None:
            details.append({**row, "actual": None, "ok": False, "note": "no matching result"})
            continue

        ok = matched.result == exp_result
        if exp_outcome is not None and matched.outcome is not None:
            # soft-align list-only labels across contract versions
            equiv = {
                "ABSENT": {"ABSENT", "SEARCH_LIST_ONLY"},
                "SEARCH_LIST_ONLY": {"ABSENT", "SEARCH_LIST_ONLY"},
                "PRESENT": {"PRESENT", "HAS_DETAIL_LINK"},
                "HAS_DETAIL_LINK": {"PRESENT", "HAS_DETAIL_LINK"},
            }
            if matched.outcome == exp_outcome:
                pass
            elif matched.outcome in equiv.get(str(exp_outcome), set()):
                pass
            else:
                ok = False
        elif exp_outcome is not None and matched.result == "PASS":
            ok = ok and (matched.outcome == exp_outcome)

        if ok:
            correct += 1
            if is_blocker:
                # Blocker handled if not an erroneous PASS on a hard criterion,
                # or PASS with expected ABSENT/negative outcome that documents the gap.
                if matched.result in ("UNKNOWN", "FAIL"):
                    blocker_hits += 1
                elif matched.result == "PASS" and exp_result == "PASS":
                    blocker_hits += 1
        else:
            # false PASS: predicted PASS when oracle says UNKNOWN/FAIL
            if matched.result == "PASS" and exp_result in ("UNKNOWN", "FAIL"):
                false_pass += 1
                false_pass_cases.append(
                    {
                        "oracle": row,
                        "actual": matched.to_dict(),
                    }
                )

        details.append(
            {
                **row,
                "actual_result": matched.result,
                "actual_outcome": matched.outcome,
                "ok": ok,
            }
        )

    # also aggregate rates over all results
    total = len(results) or 1
    counts = {k: 0 for k in VALID_RESULTS}
    for r in results:
        counts[r.result] = counts.get(r.result, 0) + 1

    return {
        "oracle_n": n,
        "oracle_correct": correct,
        "oracle_accuracy": (correct / n) if n else 0.0,
        "false_pass": false_pass,
        "false_pass_rate": (false_pass / n) if n else 0.0,
        "false_pass_cases": false_pass_cases,
        "blocker_total": blocker_total,
        "blocker_recall": (blocker_hits / blocker_total) if blocker_total else None,
        "result_counts": counts,
        "unknown_rate": counts.get("UNKNOWN", 0) / total,
        "spec_gap_rate": counts.get("SPEC_GAP", 0) / total,
        "pass_rate": counts.get("PASS", 0) / total,
        "fail_rate": counts.get("FAIL", 0) / total,
        "details": details,
    }


def go_no_go(metrics: dict[str, Any]) -> dict[str, Any]:
    """
    GO if:
      - false_pass == 0
      - spec_gap_rate == 0 (on executed decisions with schema)
      - blocker_recall is None or >= 0.9
      - oracle_accuracy >= 0.8 when oracle_n >= 5
    """
    reasons = []
    ok = True
    if metrics.get("false_pass", 0) != 0:
        ok = False
        reasons.append(f"false_pass={metrics['false_pass']} (must be 0)")
    if (metrics.get("spec_gap_rate") or 0) > 0:
        # allow tiny float noise
        if metrics["spec_gap_rate"] > 1e-9:
            ok = False
            reasons.append(f"spec_gap_rate={metrics['spec_gap_rate']}")
    br = metrics.get("blocker_recall")
    if br is not None and br < 0.9:
        ok = False
        reasons.append(f"blocker_recall={br} < 0.9")
    if metrics.get("oracle_n", 0) >= 5 and metrics.get("oracle_accuracy", 0) < 0.8:
        ok = False
        reasons.append(f"oracle_accuracy={metrics['oracle_accuracy']} < 0.8")
    if not reasons:
        reasons.append("all GO criteria met")
    return {"go": ok, "reasons": reasons}
