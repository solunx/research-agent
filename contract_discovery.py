"""
Contract Discovery v0 — isolated experiment.

Hypothesis
----------
A small LLM pass over TASK + compact PageState/structure samples can produce a
*task-specific Research Contract* (fixed meta-schema, dynamic content) that:

1. Defines the subject and required observables
2. Lists semantic decisions needed to turn observations into rankable candidates
3. Explains why a run with 0 rankable failed (which decisions are UNKNOWN / missing)

Code owns the schema, validation, versioning hooks, and gap analysis.
LLM only fills content. No changes to the live retrieval execution pipeline.

This is NOT a full discovery loop with freeze/recon-across-hosts yet.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Fixed meta-schema (code-owned). LLM may only fill values that match this.
# ---------------------------------------------------------------------------

CONTRACT_SCHEMA_VERSION = "0.3"

REQUIRED_TOP_LEVEL = (
    "schema_version",
    "subject",
    "observables",
    "decisions",
    "sufficiency",
    "missing_to_solve",
)

REQUIRED_SUBJECT_KEYS = ("name", "definition")
REQUIRED_DECISION_KEYS = ("id", "question", "outcomes")
REQUIRED_SUFFICIENCY_KEYS = ("required", "blocking_unknowns")

# Outcomes must always include UNKNOWN so fail-closed is possible
OUTCOME_UNKNOWN = "UNKNOWN"

ChatFn = Callable[[list[dict[str, Any]]], dict[str, Any]]


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class GapAnalysis:
    """Compare frozen/discovered contract against what a run actually produced."""

    decision_status: dict[str, str]  # decision_id -> PASS | UNKNOWN | MISSING_DECISION | N/A
    observable_status: dict[str, str]  # observable -> PRESENT | ABSENT | PARTIAL
    why_zero_rankable: list[str]
    contract_explains_run: bool
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Compact recon packet builders (from run artifacts)
# ---------------------------------------------------------------------------

def _truncate(s: str, n: int = 240) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def compact_page_surface(item: dict[str, Any], max_members: int = 6) -> dict[str, Any]:
    """Shrink one shortlist/page_state row into LLM-safe recon context."""
    ps = item.get("page_state") or {}
    st = ps.get("structure") or {}
    aw = ps.get("awareness") or {}
    evidence = item.get("evidence") or {}
    observed = evidence.get("observed") or {}

    members_out = []
    for m in (st.get("members") or [])[:max_members]:
        members_out.append(
            {
                "entity": _truncate(str(m.get("entity") or ""), 80),
                "value": m.get("value"),
                "role": (m.get("admissibility") or {}).get("role")
                or (m.get("member_role") or {}).get("role"),
            }
        )

    rejected_out = []
    for r in (st.get("rejected_members") or [])[:5]:
        rejected_out.append(
            {
                "entity": _truncate(str(r.get("entity") or ""), 60),
                "value": r.get("value"),
                "reject_reason": r.get("reject_reason"),
                "role": r.get("role"),
            }
        )

    return {
        "name": item.get("name"),
        "source_url": _truncate(str(item.get("source_url") or ps.get("observed_url") or ""), 160),
        "page_role": ps.get("page_role"),
        "usable_for_task": ps.get("usable_for_task"),
        "awareness_status": aw.get("status"),
        "awareness_gaps": aw.get("gaps") or [],
        "member_count": st.get("member_count"),
        "admissibility_stats": st.get("admissibility_stats"),
        "member_role_stats": st.get("member_role_stats"),
        "sample_members": members_out,
        "sample_rejected": rejected_out,
        "observed_entity": observed.get("entity"),
        "observed_value": observed.get("value"),
        "observed_raw": _truncate(str(observed.get("raw_evidence") or ""), 160),
        "match_status": item.get("match_status") or (item.get("constraints_check") or {}).get("match_status"),
        "eligibility": item.get("eligibility"),
        "rankable": item.get("rankable"),
    }


def select_representative_surfaces(
    shortlist: list[dict[str, Any]],
    max_surfaces: int = 4,
) -> list[dict[str, Any]]:
    """
    Pick diverse surfaces: destination noise, hotel-list adequate, empty harvest hosts.
    Prefer unique observed_url hosts + awareness diversity.
    """
    if not shortlist:
        return []

    selected: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    def key(item: dict[str, Any]) -> str:
        ps = item.get("page_state") or {}
        url = str(ps.get("observed_url") or item.get("source_url") or "")
        host = url.split("/")[2] if "://" in url else url[:40]
        role = ps.get("page_role") or "?"
        aw = (ps.get("awareness") or {}).get("status") or "?"
        mc = (ps.get("structure") or {}).get("member_count")
        return f"{host}|{role}|{aw}|{mc}"

    # Prefer: partial+0 members (noise), adequate+members (real offers), then others
    ranked = sorted(
        shortlist,
        key=lambda it: (
            0
            if ((it.get("page_state") or {}).get("awareness") or {}).get("status") == "partial"
            and ((it.get("page_state") or {}).get("structure") or {}).get("member_count") == 0
            else 1
            if ((it.get("page_state") or {}).get("awareness") or {}).get("status") == "adequate"
            else 2,
            -int((((it.get("page_state") or {}).get("structure") or {}).get("member_count") or 0)),
        ),
    )

    for item in ranked:
        k = key(item)
        if k in seen_keys:
            continue
        seen_keys.add(k)
        selected.append(compact_page_surface(item))
        if len(selected) >= max_surfaces:
            break

    # If still short, pad with first items
    for item in shortlist:
        if len(selected) >= max_surfaces:
            break
        k = key(item)
        if k in seen_keys:
            continue
        seen_keys.add(k)
        selected.append(compact_page_surface(item))

    return selected


def load_run_context(run_dir: Path) -> dict[str, Any]:
    """Load task + shortlist (+ optional metadata) from a run directory."""
    run_dir = Path(run_dir)
    task_path = run_dir / "task.md"
    if not task_path.exists():
        # fallback: tasks/ sibling
        alt = run_dir.parent.parent / "tasks" / "compare_packages_dec2026.md"
        task_text = alt.read_text(encoding="utf-8") if alt.exists() else ""
    else:
        task_text = task_path.read_text(encoding="utf-8")

    shortlist: list[dict[str, Any]] = []
    sl_path = run_dir / "shortlist.json"
    if sl_path.exists():
        shortlist = json.loads(sl_path.read_text(encoding="utf-8"))

    meta: dict[str, Any] = {}
    meta_path = run_dir / "metadata.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    report = ""
    rp = run_dir / "report.md"
    if rp.exists():
        report = rp.read_text(encoding="utf-8")[:2000]

    return {
        "task_text": task_text,
        "shortlist": shortlist,
        "metadata": meta,
        "report_excerpt": report,
        "run_dir": str(run_dir),
    }


# ---------------------------------------------------------------------------
# Prompt + LLM call
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a Research Contract compiler for a generic web research agent.

Your job is NOT to find hotels or answer the user task.
Your job is to produce a TASK-SPECIFIC Research Contract that tells the execution
engine what subject it is looking for, which observables it must collect, and
which semantic decisions it must be able to take.

Rules:
1. Output EXACTLY one JSON object. No markdown fences, no commentary.
2. Use ONLY the schema fields listed in the user message. Do not invent top-level keys.
3. Every decision.outcomes array MUST include the string "UNKNOWN".
4. Prefer generic decision ids (e.g. subject_instance, price_scope, board_type, detail_link)
   over vertical labels (do not invent TARGET_OFFER / AMENITY enums).
5. TARGET-like meaning belongs inside subject.definition, not as a domain enum.
6. missing_to_solve must list concrete information gaps visible in the recon surfaces
   that currently prevent reliable task completion (e.g. board_type not confirmed,
   no per-item detail URL, price may be group/destination aggregate).
7. Be conservative: if recon surfaces do not show something, mark it as needed, not assumed present.
8. For EVERY decision, include evidence_signals: a list of
   { "outcome": "<one of outcomes except UNKNOWN>",
     "patterns": ["literal substrings"],
     "polarity": "supports"|"contradicts",
     "evidence_channels": ["candidate_claims"] }.
   Allowed evidence_channels (provenance):
     - candidate_claims: hotel/card name, price, raw card text only
     - search_context: URL query filters (meal=, dateFrom=) — NOT proof of per-offer claims
     - navigation: URL path shape (list vs detail)
     - page_context: page role / chrome labels
   Default if omitted is candidate_claims only (fail-closed).
   Rules:
     - Board/meal type MUST use candidate_claims only (never search_context alone for ALL_INCLUSIVE).
     - detail_link MAY use navigation.
     - dates_validity MAY use search_context + candidate_claims.
     - Do NOT use instance-specific euro amounts as semantic patterns.
     - Do NOT use baggage/CTA/chrome phrases to classify subject TARGET/NOT_TARGET.
     - contradicts must stay on the same semantic axis as the outcome.
   The executor has NO domain knowledge — you supply all interpretation rules.
"""


def build_user_prompt(task_text: str, surfaces: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> str:
    meta = meta or {}
    schema_example = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "subject": {
            "name": "short_snake_case_subject",
            "definition": "one-sentence definition of what counts as an instance",
        },
        "observables": [
            "property_identity",
            "price",
            "price_scope",
            "board_type",
            "detail_or_booking_link",
            "departure_origin",
            "stay_dates_or_duration",
        ],
        "decisions": [
            {
                "id": "subject_instance",
                "question": "Does this page object represent one concrete instance of the subject?",
                "outcomes": ["TARGET", "NOT_TARGET", "UNKNOWN"],
                "evidence_required": ["property_identity"],
                "unknown_conditions": ["entity is a destination aggregate or CTA label"],
                "evidence_signals": [
                    {
                        "outcome": "NOT_TARGET",
                        "patterns": ["personaliseer je pakket", "pakket bekijken"],
                        "polarity": "supports",
                        "evidence_channels": ["candidate_claims"],
                    }
                ],
            },
            {
                "id": "price_scope",
                "question": "What does the visible price apply to?",
                "outcomes": ["PER_PERSON_STAY", "GROUP_TOTAL", "STARTING_FROM", "DESTINATION_AGGREGATE", "UNKNOWN"],
                "evidence_required": ["price", "price_scope"],
                "unknown_conditions": ["price shown only on destination card without hotel name"],
                "evidence_signals": [
                    {
                        "outcome": "PER_PERSON_STAY",
                        "patterns": [" pp", "p.p", "per persoon"],
                        "polarity": "supports",
                        "evidence_channels": ["candidate_claims"],
                    }
                ],
            },
        ],
        "sufficiency": {
            "required": [
                "subject_instance=TARGET",
                "price present",
                "board_type known or explicitly unknown-documented",
                "detail_or_booking_link present",
            ],
            "blocking_unknowns": [
                "board_type",
                "detail_or_booking_link",
            ],
        },
        "missing_to_solve": [
            "Explicit confirmation that meal plan is all-inclusive/volpension on the priced offer",
            "Per-hotel detail or booking URL (not only search-list URL)",
        ],
    }

    payload = {
        "task": task_text.strip()[:3500],
        "run_metadata": {
            "shortlist_count": meta.get("shortlist_count"),
            "rankable_count": meta.get("rankable_count"),
            "candidate_precision": meta.get("candidate_precision"),
            "status": meta.get("status"),
        },
        "recon_surfaces": surfaces,
        "required_output_schema_example": schema_example,
        "instructions": (
            "Fill the schema for THIS task given the recon surfaces. "
            "Explain gaps in missing_to_solve. "
            "Do not claim the task is solvable if rankable_count is 0 and surfaces show UNKNOWN board/link."
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty LLM response")
    # strip optional fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # find first { ... last }
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise ValueError("no JSON object in LLM response")
    return json.loads(text[start : end + 1])


# Channel aliases the LLM commonly invents → canonical schema channels
_CHANNEL_ALIASES: dict[str, str] = {
    "candidate_claim": "candidate_claims",
    "candidate_claims": "candidate_claims",
    "claims": "candidate_claims",
    "card": "candidate_claims",
    "card_text": "candidate_claims",
    "raw_evidence": "candidate_claims",
    "search_context": "search_context",
    "search": "search_context",
    "url_filter": "search_context",
    "url_query": "search_context",
    "navigation": "navigation",
    "nav": "navigation",
    "url": "navigation",
    "link": "navigation",
    "page_context": "page_context",
    "page_chrome": "page_context",
    "chrome": "page_context",
    "ui": "page_context",
    "footer": "page_context",
}

ALLOWED_EVIDENCE_CHANNELS = frozenset(
    {"candidate_claims", "search_context", "navigation", "page_context"}
)


def normalize_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """
    Best-effort repair of LLM output so validation is stable across CD0/CD1/CD2.

    - Ensure top-level keys exist
    - Force UNKNOWN into every outcomes list
    - Map channel aliases; drop empty/broken signals instead of hard-failing
    - Coerce polarity; default missing polarity to supports
    Does NOT invent domain semantics — only structural hygiene.
    """
    if not isinstance(contract, dict):
        return {
            "schema_version": CONTRACT_SCHEMA_VERSION,
            "subject": {"name": "unknown", "definition": "invalid contract payload"},
            "observables": ["subject_identity"],
            "decisions": [
                {
                    "id": "subject_instance",
                    "question": "Is this a concrete subject instance?",
                    "outcomes": ["TARGET", "NOT_TARGET", OUTCOME_UNKNOWN],
                }
            ],
            "sufficiency": {"required": [], "blocking_unknowns": []},
            "missing_to_solve": ["contract payload was not an object"],
            "_source": "normalize_fallback",
        }

    c = dict(contract)
    c.setdefault("schema_version", CONTRACT_SCHEMA_VERSION)

    subj = c.get("subject")
    if not isinstance(subj, dict):
        c["subject"] = {"name": "unknown_subject", "definition": str(subj or "missing")}
    else:
        subj = dict(subj)
        subj.setdefault("name", "unnamed_subject")
        subj.setdefault("definition", "definition missing from model output")
        c["subject"] = subj

    obs = c.get("observables")
    if not isinstance(obs, list) or not obs:
        c["observables"] = ["subject_identity"]
    else:
        c["observables"] = [str(x) for x in obs if x is not None]

    decisions_in = c.get("decisions")
    decisions_out: list[dict[str, Any]] = []
    if isinstance(decisions_in, list):
        for d in decisions_in:
            if not isinstance(d, dict):
                continue
            dd = dict(d)
            dd.setdefault("id", f"decision_{len(decisions_out)}")
            dd.setdefault("question", str(dd.get("id")))
            outcomes = dd.get("outcomes")
            if not isinstance(outcomes, list):
                outcomes = []
            outcomes = [str(o) for o in outcomes if o is not None]
            if OUTCOME_UNKNOWN not in outcomes:
                outcomes.append(OUTCOME_UNKNOWN)
            if len(outcomes) < 2:
                outcomes = ["TARGET", "NOT_TARGET", OUTCOME_UNKNOWN]
            dd["outcomes"] = outcomes

            signals = dd.get("evidence_signals")
            if signals is None:
                pass  # sparse OK for CD0
            elif not isinstance(signals, list):
                dd.pop("evidence_signals", None)
            else:
                cleaned: list[dict[str, Any]] = []
                for sig in signals:
                    if not isinstance(sig, dict):
                        continue
                    ss = dict(sig)
                    pats = ss.get("patterns")
                    if isinstance(pats, str):
                        pats = [pats]
                    if not isinstance(pats, list):
                        continue
                    pats = [str(p) for p in pats if p is not None and str(p).strip()]
                    if not pats:
                        continue
                    ss["patterns"] = pats
                    pol = str(ss.get("polarity") or "").lower().strip()
                    if pol not in ("supports", "contradicts"):
                        ss["polarity"] = "supports"
                    else:
                        ss["polarity"] = pol
                    ch = ss.get("evidence_channels")
                    if ch is None:
                        ss["evidence_channels"] = ["candidate_claims"]
                    else:
                        if isinstance(ch, str):
                            ch = [ch]
                        mapped: list[str] = []
                        for cname in ch or []:
                            key = str(cname).strip().lower()
                            canon = _CHANNEL_ALIASES.get(key) or _CHANNEL_ALIASES.get(
                                key.replace(" ", "_")
                            )
                            if canon and canon not in mapped:
                                mapped.append(canon)
                        ss["evidence_channels"] = mapped or ["candidate_claims"]
                    cleaned.append(ss)
                dd["evidence_signals"] = cleaned
            decisions_out.append(dd)
    if not decisions_out:
        decisions_out = [
            {
                "id": "subject_instance",
                "question": "Does this object represent one concrete subject instance?",
                "outcomes": ["TARGET", "NOT_TARGET", OUTCOME_UNKNOWN],
            }
        ]
    c["decisions"] = decisions_out

    suf = c.get("sufficiency")
    if not isinstance(suf, dict):
        c["sufficiency"] = {"required": [], "blocking_unknowns": []}
    else:
        suf = dict(suf)
        if not isinstance(suf.get("required"), list):
            suf["required"] = list(suf.get("required") or []) if suf.get("required") else []
            if not isinstance(suf["required"], list):
                suf["required"] = []
        if not isinstance(suf.get("blocking_unknowns"), list):
            suf["blocking_unknowns"] = []
        c["sufficiency"] = suf

    miss = c.get("missing_to_solve")
    if not isinstance(miss, list):
        c["missing_to_solve"] = [str(miss)] if miss else ["missing_to_solve not provided"]
    elif not miss:
        c["missing_to_solve"] = ["no gaps listed by model"]

    return c


def validate_contract(contract: dict[str, Any]) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(contract, dict):
        return ValidationResult(ok=False, errors=["contract is not an object"])

    for k in REQUIRED_TOP_LEVEL:
        if k not in contract:
            errors.append(f"missing top-level key: {k}")

    subj = contract.get("subject")
    if isinstance(subj, dict):
        for k in REQUIRED_SUBJECT_KEYS:
            if not subj.get(k):
                errors.append(f"subject.{k} required")
    else:
        errors.append("subject must be object")

    obs = contract.get("observables")
    if not isinstance(obs, list) or not obs:
        errors.append("observables must be non-empty list")

    decisions = contract.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        errors.append("decisions must be non-empty list")
    else:
        ids: set[str] = set()
        for i, d in enumerate(decisions):
            if not isinstance(d, dict):
                errors.append(f"decisions[{i}] not object")
                continue
            for k in REQUIRED_DECISION_KEYS:
                if not d.get(k):
                    errors.append(f"decisions[{i}].{k} required")
            did = d.get("id")
            if did:
                if did in ids:
                    errors.append(f"duplicate decision id: {did}")
                ids.add(str(did))
            outcomes = d.get("outcomes") or []
            if not isinstance(outcomes, list) or len(outcomes) < 2:
                errors.append(f"decisions[{i}].outcomes need >= 2 values")
            elif OUTCOME_UNKNOWN not in outcomes:
                # after normalize this should not happen; still hard error if it does
                errors.append(f"decisions[{i}].outcomes must include UNKNOWN")
            # evidence_signals: sparse allowed (CD0); malformed → warning after normalize
            signals = d.get("evidence_signals")
            if signals is None:
                warnings.append(f"decisions[{i}] ({did}) missing evidence_signals")
            elif not isinstance(signals, list):
                errors.append(f"decisions[{i}].evidence_signals must be a list")
            else:
                outcome_set = {str(o) for o in outcomes if o != OUTCOME_UNKNOWN}
                for j, sig in enumerate(signals):
                    if not isinstance(sig, dict):
                        warnings.append(f"decisions[{i}].evidence_signals[{j}] not object (ignored)")
                        continue
                    so = str(sig.get("outcome") or "")
                    pats = sig.get("patterns")
                    pol = str(sig.get("polarity") or "")
                    if so and so not in outcome_set and so != OUTCOME_UNKNOWN:
                        warnings.append(
                            f"decisions[{i}].evidence_signals[{j}].outcome {so!r} not in outcomes"
                        )
                    if not isinstance(pats, list) or not pats:
                        warnings.append(
                            f"decisions[{i}].evidence_signals[{j}].patterns empty/missing (ignored)"
                        )
                        continue
                    if pol not in ("supports", "contradicts"):
                        warnings.append(
                            f"decisions[{i}].evidence_signals[{j}].polarity {pol!r} "
                            f"(expected supports|contradicts; normalize should default)"
                        )
                    ch = sig.get("evidence_channels")
                    if ch is None:
                        warnings.append(
                            f"decisions[{i}].evidence_signals[{j}] missing evidence_channels "
                            f"(executor defaults to candidate_claims)"
                        )
                    else:
                        if isinstance(ch, str):
                            ch = [ch]
                        if not isinstance(ch, list) or not ch:
                            warnings.append(
                                f"decisions[{i}].evidence_signals[{j}].evidence_channels empty"
                            )
                        else:
                            for c in ch:
                                if str(c) not in ALLOWED_EVIDENCE_CHANNELS:
                                    warnings.append(
                                        f"decisions[{i}].evidence_signals[{j}].evidence_channels "
                                        f"unknown {c!r}"
                                    )

    suf = contract.get("sufficiency")
    if isinstance(suf, dict):
        for k in REQUIRED_SUFFICIENCY_KEYS:
            if k not in suf:
                errors.append(f"sufficiency.{k} required")
    else:
        errors.append("sufficiency must be object")

    miss = contract.get("missing_to_solve")
    if not isinstance(miss, list) or not miss:
        warnings.append("missing_to_solve empty — contract may be over-optimistic")

    sv = contract.get("schema_version")
    if sv and str(sv) != CONTRACT_SCHEMA_VERSION:
        warnings.append(f"schema_version {sv!r} != code {CONTRACT_SCHEMA_VERSION}")

    return ValidationResult(ok=not errors, errors=errors, warnings=warnings)


def discover_contract(
    task_text: str,
    surfaces: list[dict[str, Any]],
    *,
    chat_fn: ChatFn | None = None,
    meta: dict[str, Any] | None = None,
    use_heuristic_fallback: bool = True,
) -> dict[str, Any]:
    """
    Produce a Research Contract.

    If chat_fn is provided, call LLM.
    If LLM fails or is absent and use_heuristic_fallback, return a deterministic
    contract derived from task keywords + surface gaps (for offline smoke tests).
    """
    if chat_fn is not None:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(task_text, surfaces, meta)},
        ]
        try:
            msg = chat_fn(messages)
            content = msg.get("content") if isinstance(msg, dict) else str(msg)
            contract = normalize_contract(_extract_json(content or ""))
            contract.setdefault("schema_version", CONTRACT_SCHEMA_VERSION)
            contract["_source"] = "llm"
            return contract
        except Exception as e:
            if not use_heuristic_fallback:
                raise
            contract = normalize_contract(
                heuristic_contract_generic(task_text, surfaces, meta)
            )
            contract["_source"] = f"heuristic_fallback:{type(e).__name__}:{e}"
            return contract

    if use_heuristic_fallback:
        contract = normalize_contract(
            heuristic_contract_generic(task_text, surfaces, meta)
        )
        contract["_source"] = "heuristic"
        return contract

    raise RuntimeError("no chat_fn and heuristic fallback disabled")


def heuristic_contract_for_packages(
    task_text: str,
    surfaces: list[dict[str, Any]],
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    EXPERIMENT FIXTURE ONLY — packages / travel vertical smoke tests.

    Do NOT use as production fallback. Prefer heuristic_contract_generic or LLM
    synthesis (synthesize_and_freeze_contract). Kept for offline schema/gap
    regression against historical package runs. See FRAMEWORK_BOUNDARY.md.
    """
    meta = meta or {}
    has_partial_noise = any(
        s.get("awareness_status") == "partial" and (s.get("member_count") or 0) == 0 for s in surfaces
    )
    has_adequate_offers = any(
        s.get("awareness_status") == "adequate" and (s.get("member_count") or 0) > 0 for s in surfaces
    )
    any_rankable = any(s.get("rankable") for s in surfaces)
    host_urls = " ".join(str(s.get("source_url") or "") for s in surfaces)
    weak_hosts = []
    if "sunweb" in host_urls and not any(
        "sunweb" in str(s.get("source_url") or "") and (s.get("member_count") or 0) > 0 for s in surfaces
    ):
        weak_hosts.append("sunweb.be")
    if "corendon" in host_urls and not any(
        "corendon" in str(s.get("source_url") or "") and (s.get("member_count") or 0) > 0 for s in surfaces
    ):
        weak_hosts.append("corendon.be")

    missing = [
        "Explicit board_type (all-inclusive / volpension) confirmed on the priced offer, not only via URL filter",
        "Per-offer detail or booking URL (search-list URL is not sufficient)",
        "price_scope: per-person stay vs destination aggregate vs starting-from",
    ]
    if has_partial_noise:
        missing.append("Filter out destination/geo navigation cards that carry group-level prices")
    if weak_hosts:
        missing.append(f"Usable structure.members / harvest on: {', '.join(weak_hosts)}")
    if not any_rankable and (meta.get("rankable_count") in (0, None)):
        missing.append("Path from observed list prices to rankable eligibility (constraints fully evaluated)")

    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "subject": {
            "name": "flight_hotel_package_offer",
            "definition": (
                "One concrete bookable package combining flight and hotel accommodation "
                "for the requested party size and dates, with a visible price on the provider page."
            ),
        },
        "observables": [
            "property_identity",
            "price",
            "price_scope",
            "board_type",
            "detail_or_booking_link",
            "departure_origin",
            "stay_dates_or_duration",
            "party_size",
        ],
        "decisions": [
            {
                "id": "subject_instance",
                "question": "Does this page object represent one concrete package offer (property + price), not a destination aggregate or CTA?",
                "outcomes": ["TARGET", "NOT_TARGET", "UNKNOWN"],
                "evidence_required": ["property_identity"],
                "unknown_conditions": [
                    "entity is a place name without property identity",
                    "entity is a CTA or amenity fragment",
                ],
                "evidence_signals": [
                    {
                        "outcome": "NOT_TARGET",
                        "patterns": [
                            "personaliseer je pakket",
                            "pakket bekijken",
                            "bekijk op kaart",
                        ],
                        "polarity": "supports",
                        "evidence_channels": ["candidate_claims"],
                    },
                    {
                        "outcome": "NOT_TARGET",
                        "patterns": [" pp, 30 nachten", "pp, 30 nights"],
                        "polarity": "supports",
                        "evidence_channels": ["candidate_claims"],
                    },
                ],
            },
            {
                "id": "price_scope",
                "question": "What unit does the visible price apply to?",
                "outcomes": [
                    "PER_PERSON_STAY",
                    "GROUP_TOTAL",
                    "STARTING_FROM",
                    "DESTINATION_AGGREGATE",
                    "UNKNOWN",
                ],
                "evidence_required": ["price", "price_scope"],
                "unknown_conditions": ["price only on destination card", "nights mismatched to request"],
                "evidence_signals": [
                    {
                        "outcome": "PER_PERSON_STAY",
                        "patterns": [" pp", "p.p", "per persoon", "| pp"],
                        "polarity": "supports",
                        "evidence_channels": ["candidate_claims"],
                    },
                    {
                        "outcome": "DESTINATION_AGGREGATE",
                        "patterns": ["pp, 30 nachten", "30 nachten", "searchdestinations"],
                        "polarity": "supports",
                        "evidence_channels": ["candidate_claims"],
                    },
                ],
            },
            {
                "id": "board_type",
                "question": "Is the meal plan for this priced offer all-inclusive, volpension, or something else?",
                "outcomes": ["ALL_INCLUSIVE", "FULL_BOARD", "HALF_BOARD", "BREAKFAST", "ROOM_ONLY", "UNKNOWN"],
                "evidence_required": ["board_type"],
                "unknown_conditions": [
                    "only URL meal filter present",
                    "label is ambiguous (e.g. Enkel kamer / Ontbijt)",
                ],
                "evidence_signals": [
                    {
                        "outcome": "ALL_INCLUSIVE",
                        "patterns": ["all-inclusive", "all inclusive", "all-in", "ultra all"],
                        "polarity": "supports",
                        "evidence_channels": ["candidate_claims"],
                    },
                    {
                        "outcome": "FULL_BOARD",
                        "patterns": ["volpension", "full board", "vol pension"],
                        "polarity": "supports",
                        "evidence_channels": ["candidate_claims"],
                    },
                    {
                        "outcome": "BREAKFAST",
                        "patterns": ["ontbijt", "breakfast only", "enkel ontbijt"],
                        "polarity": "supports",
                        "evidence_channels": ["candidate_claims"],
                    },
                    {
                        "outcome": "ROOM_ONLY",
                        "patterns": ["enkel kamer", "room only", "logies alleen"],
                        "polarity": "supports",
                        "evidence_channels": ["candidate_claims"],
                    },
                    {
                        "outcome": "ALL_INCLUSIVE",
                        "patterns": ["enkel kamer", "ontbijt"],
                        "polarity": "contradicts",
                        "evidence_channels": ["candidate_claims"],
                    },
                ],
            },
            {
                "id": "detail_link",
                "question": "Is there a resolvable detail or booking URL for this specific offer?",
                "outcomes": ["PRESENT", "ABSENT", "UNKNOWN"],
                "evidence_required": ["detail_or_booking_link"],
                "unknown_conditions": ["only search results page URL available"],
                "evidence_signals": [
                    {
                        "outcome": "ABSENT",
                        "patterns": ["/s/tsx", "pageType=search", "searchdestinations"],
                        "polarity": "supports",
                        "evidence_channels": ["navigation"],
                    },
                    {
                        "outcome": "PRESENT",
                        "patterns": ["/hotel/", "/hotels/", "booking?", "detail"],
                        "polarity": "supports",
                        "evidence_channels": ["navigation"],
                    },
                ],
            },
        ],
        "sufficiency": {
            "required": [
                "subject_instance=TARGET",
                "price present with known price_scope",
                "board_type known or explicitly documented as unknown",
                "detail_or_booking_link PRESENT",
            ],
            "blocking_unknowns": ["board_type", "detail_link", "price_scope"],
        },
        "missing_to_solve": missing,
        "_heuristic_flags": {
            "has_partial_noise": has_partial_noise,
            "has_adequate_offers": has_adequate_offers,
            "weak_hosts": weak_hosts,
        },
    }


# ---------------------------------------------------------------------------
# Gap analysis vs run observations (no pipeline changes)
# ---------------------------------------------------------------------------

def analyze_gaps(
    contract: dict[str, Any],
    shortlist: list[dict[str, Any]],
    meta: dict[str, Any] | None = None,
) -> GapAnalysis:
    meta = meta or {}
    rankable = int(meta.get("rankable_count") or 0)
    if not rankable:
        rankable = sum(1 for x in shortlist if x.get("rankable"))

    decision_status: dict[str, str] = {}
    notes: list[str] = []

    # Aggregate signals from shortlist
    any_target_like = False
    any_price = False
    any_detail = False
    board_confirmed = False
    price_scope_clear = False
    destination_noise_present = False

    for item in shortlist:
        name = str(item.get("name") or "")
        ps = item.get("page_state") or {}
        st = ps.get("structure") or {}
        raw = str(((item.get("evidence") or {}).get("observed") or {}).get("raw_evidence") or "")
        price = item.get("price") or ((item.get("evidence") or {}).get("observed") or {}).get("value")
        if price:
            any_price = True
        if (st.get("member_count") or 0) > 0 or item.get("eligibility") == "eligible":
            any_target_like = True
        # detail: only search URL → absent
        url = str(item.get("source_url") or "")
        if "/s/tsx" in url or "search" in url.lower():
            pass
        elif url and "hotel" in url.lower():
            any_detail = True
        # board heuristics from raw text
        low = (raw + " " + name).lower()
        if any(k in low for k in ("all-inclusive", "all inclusive", "all-in", "volpension")):
            board_confirmed = True
        if "ontbijt" in low or "enkel kamer" in low:
            # observed label but ambiguous relative to all-inclusive filter
            pass
        if "pp" in low or "p.p" in low:
            price_scope_clear = True
        for r in st.get("rejected_members") or []:
            if r.get("reject_reason") == "reject_geo_nav":
                destination_noise_present = True
        if (st.get("member_count") or 0) == 0 and (ps.get("awareness") or {}).get("status") == "partial":
            destination_noise_present = True

    for d in contract.get("decisions") or []:
        did = str(d.get("id") or "")
        if did in ("subject_instance", "subject_identity"):
            if any_target_like:
                decision_status[did] = "PASS"
            elif destination_noise_present:
                decision_status[did] = "UNKNOWN"
            else:
                decision_status[did] = "UNKNOWN"
        elif did == "price_scope":
            decision_status[did] = "PASS" if price_scope_clear and any_price else "UNKNOWN"
        elif did in ("board_type", "meal_plan"):
            decision_status[did] = "PASS" if board_confirmed else "UNKNOWN"
        elif did in ("detail_link", "booking_link"):
            decision_status[did] = "PASS" if any_detail else "UNKNOWN"
        else:
            decision_status[did] = "UNKNOWN"

    obs_status: dict[str, str] = {}
    for o in contract.get("observables") or []:
        o = str(o)
        if o in ("property_identity", "subject_identity"):
            obs_status[o] = "PRESENT" if any_target_like else "PARTIAL"
        elif o == "price":
            obs_status[o] = "PRESENT" if any_price else "ABSENT"
        elif o == "price_scope":
            obs_status[o] = "PRESENT" if price_scope_clear else "ABSENT"
        elif o in ("board_type", "meal_plan"):
            obs_status[o] = "PRESENT" if board_confirmed else "ABSENT"
        elif o in ("detail_or_booking_link", "detail_link"):
            obs_status[o] = "PRESENT" if any_detail else "ABSENT"
        else:
            obs_status[o] = "PARTIAL"

    why: list[str] = []
    blocking = (contract.get("sufficiency") or {}).get("blocking_unknowns") or []
    for b in blocking:
        b = str(b)
        # map blocking name to decision status if possible
        st = decision_status.get(b) or decision_status.get(b.replace("detail_or_booking_link", "detail_link"))
        if st in (None, "UNKNOWN", "MISSING_DECISION"):
            why.append(f"blocking_unknown: {b} is not resolved (status={st or 'n/a'})")

    for miss in contract.get("missing_to_solve") or []:
        why.append(f"contract.missing: {miss}")

    if rankable == 0 and not why:
        why.append("rankable_count=0 but contract did not list concrete gaps")

    # Success criterion for v0: contract names concrete gaps when rankable=0
    # (travel + literature + generic research keywords)
    explains = False
    blob = " ".join(why).lower()
    if rankable == 0:
        explains = any(
            k in blob
            for k in (
                "board",
                "meal",
                "detail",
                "booking",
                "link",
                "scope",
                "aggregate",
                "destination",
                "comparator",
                "placebo",
                "drug",
                "endpoint",
                "population",
                "provenance",
                "full-text",
                "full text",
                "doi",
                "citation",
                "study",
                "rct",
                "standard care",
                "budget",
                "price",
                "origin",
                "date",
            )
        )
    else:
        explains = True

    if not explains:
        notes.append("Contract failed success criterion: does not explain zero rankable")
    else:
        notes.append("Contract explains zero-rankable via missing semantic decisions/observables")

    return GapAnalysis(
        decision_status=decision_status,
        observable_status=obs_status,
        why_zero_rankable=why,
        contract_explains_run=explains,
        notes=notes,
    )


def run_discovery_on_run_dir(
    run_dir: Path,
    *,
    chat_fn: ChatFn | None = None,
    use_heuristic_fallback: bool = True,
    max_surfaces: int = 4,
) -> dict[str, Any]:
    """End-to-end offline (or LLM) discovery + validation + gap analysis."""
    ctx = load_run_context(run_dir)
    surfaces = select_representative_surfaces(ctx["shortlist"], max_surfaces=max_surfaces)
    contract = discover_contract(
        ctx["task_text"],
        surfaces,
        chat_fn=chat_fn,
        meta=ctx["metadata"],
        use_heuristic_fallback=use_heuristic_fallback,
    )
    validation = validate_contract(contract)
    gaps = analyze_gaps(contract, ctx["shortlist"], ctx["metadata"])

    return {
        "run_dir": str(run_dir),
        "surfaces_used": surfaces,
        "contract": contract,
        "validation": {
            "ok": validation.ok,
            "errors": validation.errors,
            "warnings": validation.warnings,
        },
        "gap_analysis": {
            "decision_status": gaps.decision_status,
            "observable_status": gaps.observable_status,
            "why_zero_rankable": gaps.why_zero_rankable,
            "contract_explains_run": gaps.contract_explains_run,
            "notes": gaps.notes,
        },
        "success_v0": bool(validation.ok and gaps.contract_explains_run),
    }


# ---------------------------------------------------------------------------
# Contract Discovery modes CD0 / CD1 / CD2 (experimental campaign)
# ---------------------------------------------------------------------------

PROVISIONAL_SYSTEM = """You are a Research Contract compiler for a generic research agent.

PHASE: PROVISIONAL (task only — no retrieved data yet).

Produce a TASK-SPECIFIC Research Contract from the user task alone.
Infer subject, observables, decisions, outcomes (always include UNKNOWN),
sufficiency, and missing_to_solve as *hypotheses* about what evidence will be needed.

Rules:
1. Output EXACTLY one JSON object. No markdown fences, no commentary.
2. Use ONLY schema fields: schema_version, subject, observables, decisions, sufficiency, missing_to_solve.
3. Every decision.outcomes MUST include "UNKNOWN".
4. Prefer generic decision ids (subject_instance, price_scope, board_type, detail_link, study_design, …).
5. Do not invent domain enum families like TARGET_OFFER / AMENITY as top-level types.
6. evidence_signals may be sparse or omitted in provisional mode.
   When present, each signal MUST be:
   { "outcome": "<outcome>", "patterns": ["literal"], "polarity": "supports"|"contradicts",
     "evidence_channels": ["candidate_claims"] }
   Allowed evidence_channels ONLY: candidate_claims, search_context, navigation, page_context.
   Never use page_chrome, candidate_claim (singular), or other aliases.
7. Be conservative: list information you will need to confirm later under missing_to_solve.
8. sufficiency must include required (list) and blocking_unknowns (list).
9. CRITICAL — sufficiency.required entries MUST be machine-checkable against decision outcomes:
   - "decision_id"  (any non-UNKNOWN outcome counts as proven), OR
   - "decision_id = OUTCOME", OR
   - "decision_id in [OUTCOME_A, OUTCOME_B]"
   Do NOT put free-text prose sentences in sufficiency.required (those cannot be matched to outcomes).
   Prose belongs in missing_to_solve or decision.question only.
"""


REFINE_SYSTEM = """You are a Research Contract compiler refining a PROVISIONAL contract
after seeing representative retrieved surfaces (structure + text samples).

PHASE: REFINE (task + provisional contract + samples).

Update the contract so decisions, outcomes, evidence_signals, and missing_to_solve
reflect what the samples actually show (and what they still lack).

Rules:
1. Output EXACTLY one JSON object (full contract, not a patch). No markdown fences.
2. Keep schema fields only: schema_version, subject, observables, decisions, sufficiency, missing_to_solve.
3. Every decision.outcomes MUST include "UNKNOWN".
4. Prefer keeping stable decision ids from the provisional contract when still valid.
5. Add or drop decisions only when samples justify it.
6. missing_to_solve must be concrete gaps visible in samples (or still required by task).
7. Board/meal claims must not rely on search_context URL filters alone.
8. For each decision, prefer non-empty evidence_signals with:
   { "outcome", "patterns", "polarity": "supports"|"contradicts",
     "evidence_channels": ["candidate_claims"|"search_context"|"navigation"|"page_context"] }
   Only those four channel names are allowed.
9. sufficiency must include required (list) and blocking_unknowns (list).
10. CRITICAL — sufficiency.required MUST use only:
    "decision_id" | "decision_id = OUTCOME" | "decision_id in [A, B]"
    Never free-text prose in required (runtime matches outcomes by decision id only).
"""


def build_provisional_prompt(task_text: str) -> str:
    return (
        "Produce a provisional Research Contract from this task only.\n\n"
        f"## TASK\n{task_text.strip()}\n\n"
        f"schema_version must be \"{CONTRACT_SCHEMA_VERSION}\".\n"
        "Return JSON only."
    )


def build_refine_prompt(
    task_text: str,
    provisional: dict[str, Any],
    surfaces: list[dict[str, Any]],
    meta: dict[str, Any] | None = None,
) -> str:
    meta = meta or {}
    return (
        "Refine the provisional contract using the recon surfaces.\n\n"
        f"## TASK\n{task_text.strip()}\n\n"
        f"## PROVISIONAL_CONTRACT\n{json.dumps(provisional, ensure_ascii=False, indent=2)}\n\n"
        f"## SURFACES (compact)\n{json.dumps(surfaces, ensure_ascii=False, indent=2)}\n\n"
        f"## RUN_META\n{json.dumps({k: meta.get(k) for k in ('rankable_count', 'shortlist_count', 'status') if k in meta}, ensure_ascii=False)}\n\n"
        f"schema_version must be \"{CONTRACT_SCHEMA_VERSION}\".\n"
        "Return JSON only (full refined contract)."
    )


def _call_llm_contract(
    system: str,
    user: str,
    chat_fn: ChatFn,
    *,
    source_tag: str,
) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    msg = chat_fn(messages)
    content = msg.get("content") if isinstance(msg, dict) else str(msg)
    contract = _extract_json(content or "")
    contract = normalize_contract(contract)
    contract.setdefault("schema_version", CONTRACT_SCHEMA_VERSION)
    contract["_source"] = source_tag
    return contract


def discover_contract_mode(
    mode: str,
    task_text: str,
    surfaces: list[dict[str, Any]],
    *,
    chat_fn: ChatFn | None = None,
    meta: dict[str, Any] | None = None,
    use_heuristic_fallback: bool = True,
) -> dict[str, Any]:
    """
    CD0: task only → contract
    CD1: task + surfaces one-shot (existing discover_contract behaviour)
    CD2: task → provisional → refine with surfaces

    Returns dict with keys: mode, contract, provisional (optional), llm_calls, source.
    """
    mode = (mode or "CD1").upper()
    meta = meta or {}
    llm_calls = 0
    provisional: dict[str, Any] | None = None

    if mode == "CD0":
        if chat_fn is not None:
            try:
                contract = _call_llm_contract(
                    PROVISIONAL_SYSTEM,
                    build_provisional_prompt(task_text),
                    chat_fn,
                    source_tag="llm_cd0",
                )
                llm_calls = 1
            except Exception as e:
                if not use_heuristic_fallback:
                    raise
                contract = normalize_contract(
                    heuristic_contract_generic(task_text, [], meta)
                )
                contract["_source"] = f"heuristic_fallback_cd0:{type(e).__name__}"
        elif use_heuristic_fallback:
            contract = normalize_contract(
                heuristic_contract_generic(task_text, [], meta)
            )
            contract["_source"] = "heuristic_cd0"
        else:
            raise RuntimeError("CD0 requires chat_fn or heuristic fallback")
        return {
            "mode": "CD0",
            "contract": contract,
            "provisional": None,
            "llm_calls": llm_calls,
            "surfaces_n": 0,
        }

    if mode == "CD1":
        if chat_fn is not None:
            try:
                contract = discover_contract(
                    task_text,
                    surfaces,
                    chat_fn=chat_fn,
                    meta=meta,
                    use_heuristic_fallback=False,
                )
                llm_calls = 1
            except Exception as e:
                if not use_heuristic_fallback:
                    raise
                contract = normalize_contract(
                    heuristic_contract_generic(task_text, surfaces, meta)
                )
                contract["_source"] = f"heuristic_fallback_cd1:{type(e).__name__}"
        else:
            contract = discover_contract(
                task_text,
                surfaces,
                chat_fn=None,
                meta=meta,
                use_heuristic_fallback=use_heuristic_fallback,
            )
        return {
            "mode": "CD1",
            "contract": contract,
            "provisional": None,
            "llm_calls": llm_calls,
            "surfaces_n": len(surfaces),
        }

    if mode == "CD2":
        # Step 1: provisional
        if chat_fn is not None:
            try:
                provisional = _call_llm_contract(
                    PROVISIONAL_SYSTEM,
                    build_provisional_prompt(task_text),
                    chat_fn,
                    source_tag="llm_cd2_provisional",
                )
                llm_calls += 1
            except Exception as e:
                if not use_heuristic_fallback:
                    raise
                provisional = normalize_contract(
                    heuristic_contract_generic(task_text, [], meta)
                )
                provisional["_source"] = f"heuristic_fallback_cd2_prov:{type(e).__name__}"
        else:
            provisional = normalize_contract(
                heuristic_contract_generic(task_text, [], meta)
            )
            provisional["_source"] = "heuristic_cd2_provisional"

        # Step 2: refine with surfaces
        if chat_fn is not None:
            try:
                contract = _call_llm_contract(
                    REFINE_SYSTEM,
                    build_refine_prompt(task_text, provisional, surfaces, meta),
                    chat_fn,
                    source_tag="llm_cd2_refined",
                )
                llm_calls += 1
            except Exception as e:
                if not use_heuristic_fallback:
                    raise
                contract = normalize_contract(
                    heuristic_contract_generic(task_text, surfaces, meta)
                )
                contract["_source"] = f"heuristic_fallback_cd2_refine:{type(e).__name__}"
                contract["_provisional_source"] = provisional.get("_source")
        else:
            contract = normalize_contract(
                heuristic_contract_generic(task_text, surfaces, meta)
            )
            contract["_source"] = "heuristic_cd2_refined"
            contract["_provisional_source"] = provisional.get("_source")

        return {
            "mode": "CD2",
            "contract": contract,
            "provisional": provisional,
            "llm_calls": llm_calls,
            "surfaces_n": len(surfaces),
        }

    raise ValueError(f"unknown mode {mode!r}; use CD0|CD1|CD2")


def compare_contracts(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Lightweight stability metrics between provisional and refined (or CD0 vs CD1)."""

    def dec_ids(c: dict[str, Any]) -> set[str]:
        out = set()
        for d in c.get("decisions") or []:
            if isinstance(d, dict) and d.get("id"):
                out.add(str(d["id"]))
        return out

    da, db = dec_ids(a), dec_ids(b)
    return {
        "decision_ids_a": sorted(da),
        "decision_ids_b": sorted(db),
        "shared_decision_ids": sorted(da & db),
        "only_in_a": sorted(da - db),
        "only_in_b": sorted(db - da),
        "jaccard_decisions": (len(da & db) / len(da | db)) if (da or db) else 1.0,
        "subject_a": (a.get("subject") or {}).get("name"),
        "subject_b": (b.get("subject") or {}).get("name"),
        "subject_same": (a.get("subject") or {}).get("name") == (b.get("subject") or {}).get("name"),
    }


# ---------------------------------------------------------------------------
# End-to-end contract synthesis + FREEZE (step 1 of generic agent path)
# ---------------------------------------------------------------------------
#
# Code owns: meta-schema, loop, freeze flag, validation.
# LLM owns: all claim/decision content, sufficiency criteria, gap judgment.
# No domain enums (board_type, offer_state, …) as framework vocabulary.
#

GAP_CHECK_SYSTEM = """You are a Research Contract gap checker for a generic research agent.

Given a TASK and a draft Research Contract (JSON), decide whether the contract
is ready to FREEZE or still has gaps that must be filled before execution.

Rules:
1. Output EXACTLY one JSON object. No markdown fences, no commentary.
2. Schema of your reply:
   {
     "ready_to_freeze": true | false,
     "remaining_gaps": ["..."],   // empty list if ready
     "rationale": "one short paragraph"
   }
3. ready_to_freeze=true only when:
   - subject is clear for this task
   - every required decision has outcomes that include UNKNOWN
   - sufficiency.required names the decisions that must be proven
   - missing_to_solve is empty OR only lists things that will be discovered at runtime
     (not missing structural pieces of the contract itself)
4. Be conservative: if the contract could stop too early for this task
   (e.g. property-level claim when the task asks for a concrete offer),
   list that as a remaining gap and set ready_to_freeze=false.
5. Do not invent new domain field names for the framework; only judge content.
"""


def build_gap_check_prompt(task_text: str, contract: dict[str, Any]) -> str:
    return (
        "Judge whether this Research Contract is ready to FREEZE for the task.\n\n"
        f"## TASK\n{task_text.strip()}\n\n"
        f"## CONTRACT\n{json.dumps(contract, ensure_ascii=False, indent=2)}\n\n"
        "Return JSON only: ready_to_freeze, remaining_gaps, rationale."
    )


def heuristic_contract_generic(
    task_text: str,
    surfaces: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Domain-agnostic offline fallback. Produces a minimal valid contract so
    schema/loop tests work without an LLM. Content is deliberately shallow;
    real contracts must come from LLM synthesis.

    NOT a packages / travel / GPU ontology — only structural placeholders
    derived from task text length and optional surface awareness gaps.
    """
    surfaces = surfaces or []
    meta = meta or {}
    text = (task_text or "").strip()
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "research_subject")
    subject_name = re.sub(r"[^a-zA-Z0-9_]+", "_", first_line[:48]).strip("_").lower() or "subject"
    if len(subject_name) < 3:
        subject_name = "research_subject"

    awareness_gaps: list[str] = []
    for s in surfaces:
        for g in s.get("awareness_gaps") or []:
            if g and g not in awareness_gaps:
                awareness_gaps.append(str(g))

    missing = list(awareness_gaps[:6]) if awareness_gaps else [
        "Confirm which observables the task actually requires after first observations"
    ]

    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "subject": {
            "name": subject_name[:64],
            "definition": (
                "Instance that satisfies the user task as stated in task.md. "
                "Exact criteria are filled by LLM synthesis when available."
            ),
        },
        "observables": ["primary_identity", "supporting_evidence", "source_location"],
        "decisions": [
            {
                "id": "task_satisfied",
                "question": "Does the available evidence fully answer the user task?",
                "outcomes": ["YES", "NO", "UNKNOWN"],
                "evidence_required": ["supporting_evidence"],
                "unknown_conditions": [
                    "evidence incomplete relative to task wording",
                    "source not inspected",
                ],
            },
            {
                "id": "evidence_grounded",
                "question": "Is each key claim tied to an inspectable source (URL, file, quote)?",
                "outcomes": ["GROUNDED", "UNGROUNDED", "UNKNOWN"],
                "evidence_required": ["source_location"],
                "unknown_conditions": ["no source URL or path"],
            },
        ],
        "sufficiency": {
            "required": ["task_satisfied", "evidence_grounded"],
            "blocking_unknowns": ["task_satisfied"],
        },
        "missing_to_solve": missing,
        "_source": "heuristic_generic",
    }


def synthesize_and_freeze_contract(
    task_text: str,
    *,
    surfaces: list[dict[str, Any]] | None = None,
    chat_fn: ChatFn | None = None,
    meta: dict[str, Any] | None = None,
    max_passes: int = 3,
    use_heuristic_fallback: bool = True,
) -> dict[str, Any]:
    """
    End-to-end contract synthesis for one task.md.

    Flow (code-owned loop, LLM-owned content):
      Pass 0  CD0  provisional from task only
      Pass 1+ refine with surfaces (if any) and/or gap-driven revise
      After each pass: LLM gap-check → FREEZE or continue
      Cap at max_passes; last draft freezes with flag frozen=false if still gappy

    Returns:
      {
        "frozen": bool,
        "contract": { ... meta-schema fields ..., "frozen": bool, "freeze_rationale": str },
        "passes": [ {pass_index, mode, contract_source, ready_to_freeze, remaining_gaps} ],
        "llm_calls": int,
        "validation": {ok, errors, warnings},
      }
    """
    surfaces = surfaces or []
    meta = meta or {}
    passes_log: list[dict[str, Any]] = []
    llm_calls = 0
    contract: dict[str, Any] | None = None

    def _llm_or_heuristic(system: str, user: str, tag: str) -> dict[str, Any]:
        nonlocal llm_calls
        if chat_fn is not None:
            try:
                c = _call_llm_contract(system, user, chat_fn, source_tag=tag)
                llm_calls += 1
                return c
            except Exception as e:
                if not use_heuristic_fallback:
                    raise
                c = normalize_contract(heuristic_contract_generic(task_text, surfaces, meta))
                c["_source"] = f"heuristic_fallback:{tag}:{type(e).__name__}"
                return c
        if use_heuristic_fallback:
            c = normalize_contract(heuristic_contract_generic(task_text, surfaces, meta))
            c["_source"] = f"heuristic:{tag}"
            return c
        raise RuntimeError(f"synthesize pass {tag} needs chat_fn or heuristic fallback")

    def _gap_check(c: dict[str, Any]) -> dict[str, Any]:
        nonlocal llm_calls
        # Structural minimum without LLM: empty missing_to_solve + valid schema
        validation = validate_contract(c)
        structural_ready = validation.ok and not (c.get("missing_to_solve") or [])
        if chat_fn is None:
            return {
                "ready_to_freeze": structural_ready,
                "remaining_gaps": list(c.get("missing_to_solve") or [])
                if not structural_ready
                else [],
                "rationale": "heuristic gap-check (no LLM): schema ok and missing_to_solve empty"
                if structural_ready
                else "heuristic gap-check: schema issues or missing_to_solve non-empty",
                "_source": "heuristic_gap_check",
            }
        messages = [
            {"role": "system", "content": GAP_CHECK_SYSTEM},
            {"role": "user", "content": build_gap_check_prompt(task_text, c)},
        ]
        try:
            msg = chat_fn(messages)
            llm_calls += 1
            content = msg.get("content") if isinstance(msg, dict) else str(msg)
            parsed = _extract_json(content or "")
            ready = bool(parsed.get("ready_to_freeze"))
            gaps = parsed.get("remaining_gaps") or []
            if not isinstance(gaps, list):
                gaps = [str(gaps)]
            return {
                "ready_to_freeze": ready and validation.ok,
                "remaining_gaps": [str(g) for g in gaps],
                "rationale": str(parsed.get("rationale") or ""),
                "_source": "llm_gap_check",
            }
        except Exception as e:
            return {
                "ready_to_freeze": structural_ready,
                "remaining_gaps": list(c.get("missing_to_solve") or []),
                "rationale": f"gap-check LLM failed ({type(e).__name__}); fell back to structural",
                "_source": f"gap_check_fallback:{type(e).__name__}",
            }

    # --- Pass 0: provisional (task only) ---
    contract = _llm_or_heuristic(
        PROVISIONAL_SYSTEM,
        build_provisional_prompt(task_text),
        "cd0_provisional",
    )
    gap = _gap_check(contract)
    passes_log.append(
        {
            "pass_index": 0,
            "mode": "CD0",
            "contract_source": contract.get("_source"),
            "ready_to_freeze": gap["ready_to_freeze"],
            "remaining_gaps": gap["remaining_gaps"],
            "gap_source": gap.get("_source"),
        }
    )

    # --- Further passes: refine with surfaces and/or gap list ---
    pass_i = 1
    while not gap["ready_to_freeze"] and pass_i < max_passes:
        if surfaces:
            contract = _llm_or_heuristic(
                REFINE_SYSTEM,
                build_refine_prompt(task_text, contract, surfaces, meta),
                f"refine_pass_{pass_i}",
            )
            mode = "CD2_refine"
        else:
            # No surfaces yet: ask LLM to revise purely from remaining gaps + task
            gap_user = (
                "Revise the contract so remaining gaps are resolved as far as possible "
                "from the task text alone. Clear missing_to_solve items that are only "
                "runtime discovery issues; keep structural gaps that the contract itself "
                "must define before execution.\n\n"
                f"## TASK\n{task_text.strip()}\n\n"
                f"## CURRENT_CONTRACT\n{json.dumps(contract, ensure_ascii=False, indent=2)}\n\n"
                f"## REMAINING_GAPS\n{json.dumps(gap['remaining_gaps'], ensure_ascii=False)}\n\n"
                f"schema_version must be \"{CONTRACT_SCHEMA_VERSION}\".\n"
                "Return JSON only (full contract)."
            )
            contract = _llm_or_heuristic(REFINE_SYSTEM, gap_user, f"gap_revise_pass_{pass_i}")
            mode = "gap_revise"
        gap = _gap_check(contract)
        passes_log.append(
            {
                "pass_index": pass_i,
                "mode": mode,
                "contract_source": contract.get("_source"),
                "ready_to_freeze": gap["ready_to_freeze"],
                "remaining_gaps": gap["remaining_gaps"],
                "gap_source": gap.get("_source"),
            }
        )
        pass_i += 1

    frozen = bool(gap["ready_to_freeze"])
    contract = normalize_contract(contract)
    contract["frozen"] = frozen
    contract["freeze_rationale"] = gap.get("rationale") or ""
    contract["schema_version"] = CONTRACT_SCHEMA_VERSION
    if frozen:
        contract["_source"] = f"{contract.get('_source', 'unknown')}+frozen"
    else:
        contract["_source"] = f"{contract.get('_source', 'unknown')}+unfrozen_max_passes"

    validation = validate_contract(contract)
    return {
        "frozen": frozen,
        "contract": contract,
        "passes": passes_log,
        "llm_calls": llm_calls,
        "validation": {
            "ok": validation.ok,
            "errors": validation.errors,
            "warnings": validation.warnings,
        },
        "remaining_gaps": gap.get("remaining_gaps") or [],
    }


def synthesize_contract_from_task_path(
    task_path: Path | str,
    *,
    surfaces: list[dict[str, Any]] | None = None,
    chat_fn: ChatFn | None = None,
    max_passes: int = 3,
    use_heuristic_fallback: bool = True,
) -> dict[str, Any]:
    """Load task.md and run synthesize_and_freeze_contract."""
    path = Path(task_path)
    task_text = path.read_text(encoding="utf-8")
    result = synthesize_and_freeze_contract(
        task_text,
        surfaces=surfaces,
        chat_fn=chat_fn,
        max_passes=max_passes,
        use_heuristic_fallback=use_heuristic_fallback,
    )
    result["task_path"] = str(path)
    result["task_id"] = path.stem
    return result

