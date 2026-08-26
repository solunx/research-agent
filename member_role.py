"""
MEMBER_ROLE decision (experiment v0).

Deterministic-first → LLM only on UNCERTAIN → enum-only → code enforcement.

Roles are structural (domain-agnostic). Task contract binds which role is
admissible as evidence (typically TARGET).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

MEMBER_ROLES = frozenset(
    {"TARGET", "NAVIGATION", "ACTION", "FRAGMENT", "CHROME", "UNKNOWN"}
)

# Admissible for evidence buffer in this experiment
ADMISSIBLE_ROLES = frozenset({"TARGET"})


def deterministic_member_decision(assessment: dict[str, Any]) -> dict[str, Any]:
    """
    Map structural admissibility features → ACCEPT | REJECT | UNCERTAIN.

    ACCEPT  → treat as TARGET path (no LLM)
    REJECT  → drop with reason
    UNCERTAIN → optional LLM MEMBER_ROLE
    """
    features = assessment.get("features") or {}
    reason = assessment.get("reject_reason")
    admissible = bool(assessment.get("admissible"))

    # Hard structural rejects → REJECT with role hint
    if reason in ("reject_cta",):
        return {
            "decision": "REJECT",
            "role": "ACTION",
            "source": "deterministic",
            "reject_reason": reason,
            "features": features,
        }
    if reason in ("reject_amenity", "reject_unit_or_line_item"):
        return {
            "decision": "REJECT",
            "role": "FRAGMENT",
            "source": "deterministic",
            "reject_reason": reason,
            "features": features,
        }
    if reason in ("reject_type_label", "reject_slogan", "reject_empty"):
        return {
            "decision": "REJECT",
            "role": "CHROME",
            "source": "deterministic",
            "reject_reason": reason,
            "features": features,
        }
    if reason in ("reject_geo_nav",):
        return {
            "decision": "REJECT",
            "role": "NAVIGATION",
            "source": "deterministic",
            "reject_reason": reason,
            "features": features,
        }
    if reason in ("reject_schema_outlier", "reject_weak_offer_shape"):
        # borderline structural — escalate if LLM enabled
        return {
            "decision": "UNCERTAIN",
            "role": None,
            "source": "deterministic",
            "reject_reason": reason,
            "features": features,
        }

    if admissible:
        score = float(features.get("offer_shape_score") or 0)
        # Strong offer shape → ACCEPT without LLM
        if score >= 0.55 and not features.get("dest_card_shape"):
            return {
                "decision": "ACCEPT",
                "role": "TARGET",
                "source": "deterministic",
                "reject_reason": None,
                "features": features,
            }
        # Accepted but weak/borderline → UNCERTAIN
        return {
            "decision": "UNCERTAIN",
            "role": None,
            "source": "deterministic",
            "reject_reason": None,
            "features": features,
        }

    return {
        "decision": "REJECT",
        "role": "UNKNOWN",
        "source": "deterministic",
        "reject_reason": reason or "reject_other",
        "features": features,
    }


_ROLE_JSON_RE = re.compile(
    r'\{\s*"role"\s*:\s*"(TARGET|NAVIGATION|ACTION|FRAGMENT|CHROME|UNKNOWN)"\s*\}',
    re.I,
)


def parse_member_role_response(text: str) -> str:
    """Extract role enum from model output; default UNKNOWN."""
    if not text:
        return "UNKNOWN"
    m = _ROLE_JSON_RE.search(text)
    if m:
        return m.group(1).upper()
    # bare token
    for role in MEMBER_ROLES:
        if re.search(rf"\b{role}\b", text, re.I):
            return role
    return "UNKNOWN"


def build_member_role_prompt(
    *,
    task_subject_type: str,
    candidate: dict[str, Any],
    dominant_list_schema: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    schema = dominant_list_schema or {}
    payload = {
        "task_subject_type": task_subject_type or "unknown_subject",
        "candidate": {
            "text": str(candidate.get("entity") or "")[:120],
            "value": str(candidate.get("value") or "")[:40],
            "raw_evidence": str(candidate.get("raw_evidence") or "")[:240],
        },
        "dominant_list_schema": {
            "sample_targets": (schema.get("sample_targets") or [])[:5],
            "typical_signals": schema.get("typical_signals")
            or ["price", "subject_body", "repeated_list_shape"],
        },
        "instruction": (
            "Classify the candidate's structural role on this page. "
            "TARGET = concrete instance of task_subject_type. "
            "NAVIGATION = destination/region aggregate. "
            "ACTION = button/CTA. FRAGMENT = amenity/line-item. "
            "CHROME = UI noise. UNKNOWN = cannot tell. "
            'Reply with ONLY JSON: {"role":"TARGET"} (or other allowed role).'
        ),
    }
    return [
        {
            "role": "system",
            "content": (
                "You are a structural classifier. Output exactly one JSON object "
                'with key "role" and one of: TARGET, NAVIGATION, ACTION, FRAGMENT, '
                "CHROME, UNKNOWN. No other text."
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def llm_member_role(
    *,
    candidate: dict[str, Any],
    task_subject_type: str = "accommodation_offer",
    dominant_list_schema: dict[str, Any] | None = None,
    chat_fn: Callable[[list[dict[str, str]]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Call a chat function (Ollama-compatible message → message dict).
    Returns {role, source, raw}.
    """
    if chat_fn is None:
        return {
            "role": "UNKNOWN",
            "source": "llm_skipped",
            "raw": "",
        }
    messages = build_member_role_prompt(
        task_subject_type=task_subject_type,
        candidate=candidate,
        dominant_list_schema=dominant_list_schema,
    )
    try:
        msg = chat_fn(messages)
        content = ""
        if isinstance(msg, dict):
            content = str(msg.get("content") or "")
        else:
            content = str(msg)
        role = parse_member_role_response(content)
        if role not in MEMBER_ROLES:
            role = "UNKNOWN"
        return {"role": role, "source": "llm", "raw": content[:200]}
    except Exception as e:
        return {
            "role": "UNKNOWN",
            "source": "llm_error",
            "raw": str(e)[:120],
        }


def resolve_member_role(
    assessment: dict[str, Any],
    *,
    candidate: dict[str, Any],
    task_subject_type: str = "accommodation_offer",
    dominant_list_schema: dict[str, Any] | None = None,
    enable_llm: bool | None = None,
    chat_fn: Callable[[list[dict[str, str]]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Full resolve: deterministic → optional LLM on UNCERTAIN → final role + admissible.

    enable_llm defaults to env MEMBER_ROLE_LLM=1
    """
    if enable_llm is None:
        enable_llm = os.environ.get("MEMBER_ROLE_LLM", "").strip() in (
            "1",
            "true",
            "yes",
        )

    det = deterministic_member_decision(assessment)
    telemetry: dict[str, Any] = {
        "deterministic_result": det["decision"],
        "llm_called": False,
        "llm_role": None,
        "features": det.get("features") or {},
    }

    if det["decision"] == "ACCEPT":
        role = "TARGET"
        telemetry["final_result"] = "accepted"
        telemetry["role"] = role
        return {
            "admissible": True,
            "role": role,
            "reject_reason": None,
            "telemetry": telemetry,
        }

    if det["decision"] == "REJECT":
        role = det.get("role") or "UNKNOWN"
        telemetry["final_result"] = "rejected"
        telemetry["role"] = role
        return {
            "admissible": False,
            "role": role,
            "reject_reason": det.get("reject_reason") or f"role_{role.lower()}",
            "telemetry": telemetry,
        }

    # UNCERTAIN
    if enable_llm and chat_fn is not None:
        llm = llm_member_role(
            candidate=candidate,
            task_subject_type=task_subject_type,
            dominant_list_schema=dominant_list_schema,
            chat_fn=chat_fn,
        )
        telemetry["llm_called"] = True
        telemetry["llm_role"] = llm.get("role")
        telemetry["llm_source"] = llm.get("source")
        role = str(llm.get("role") or "UNKNOWN").upper()
        if role not in MEMBER_ROLES:
            role = "UNKNOWN"
    else:
        # Fail closed without LLM: treat UNCERTAIN as reject
        role = "UNKNOWN"
        telemetry["llm_called"] = False

    admissible = role in ADMISSIBLE_ROLES
    telemetry["role"] = role
    telemetry["final_result"] = "accepted" if admissible else "rejected"
    return {
        "admissible": admissible,
        "role": role,
        "reject_reason": None if admissible else f"role_{role.lower()}",
        "telemetry": telemetry,
    }


def eval_golden_set(
    path: str,
    *,
    assess_fn: Callable[..., dict[str, Any]],
    enable_llm: bool = False,
    chat_fn: Callable | None = None,
) -> dict[str, Any]:
    """Offline eval against member_role_golden.jsonl."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    correct = 0
    total = 0
    by_role: dict[str, dict[str, int]] = {}
    details = []
    for row in rows:
        cand = {
            "entity": row["entity"],
            "value": row.get("value"),
            "raw_evidence": row.get("raw_evidence"),
            "entity_score": 0.75,
            "confidence": 0.9,
            "marketing_penalty": 0.0,
            "is_line_item": False,
        }
        assessment = assess_fn(cand, page_role="list", cohort_offer_scores=None)
        resolved = resolve_member_role(
            assessment,
            candidate=cand,
            enable_llm=enable_llm,
            chat_fn=chat_fn,
        )
        expected = row["expected_role"].upper()
        got = str(resolved.get("role") or "UNKNOWN").upper()
        total += 1
        ok = got == expected
        if ok:
            correct += 1
        by_role.setdefault(expected, {"n": 0, "ok": 0})
        by_role[expected]["n"] += 1
        if ok:
            by_role[expected]["ok"] += 1
        details.append(
            {
                "entity": row["entity"],
                "expected": expected,
                "got": got,
                "ok": ok,
                "decision": (resolved.get("telemetry") or {}).get(
                    "deterministic_result"
                ),
            }
        )
    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 3) if total else 0.0,
        "by_role": by_role,
        "details": details,
    }
