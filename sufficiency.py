"""
Generic sufficiency gate — code decides STOP vs CONTINUE from a *frozen* contract.

Boundary (see docs/FRAMEWORK_BOUNDARY.md)
----------------------------------------
- Code owns: parse contract.sufficiency, compare to outcomes/evidence, STOP decision.
- LLM owns: claim/decision content inside the frozen contract; may *propose*
  that a claim is proven, but must not be the final STOP authority.
- No domain enums (board_type, offer_state, …) in this module.

Input shapes (all task-agnostic)
--------------------------------
frozen_contract:
  decisions: [{id, outcomes, ...}]
  sufficiency: {required: [...], blocking_unknowns: [...]}

outcomes:
  {decision_id: outcome_string}   # values typically include UNKNOWN

optional proven_labels:
  set/list of free-text labels the runtime marked as observed/proven
  (for required entries that are not decision ids)

Output
------
{
  "satisfied": bool,
  "gaps": [{kind, decision_id?, required_entry, observed?, detail}],
  "details": [... per required entry ...],
  "stop_reason": "CONTRACT_SATISFIED" | "CONTRACT_GAPS" | "CONTRACT_NOT_FROZEN",
}
"""
from __future__ import annotations

import re
from typing import Any


_EQ = re.compile(
    r"^\s*([A-Za-z0-9_]+)\s*=\s*([A-Za-z0-9_]+)\s*$"
)
_IN = re.compile(
    r"^\s*([A-Za-z0-9_]+)\s+in\s+\[([^\]]+)\]\s*$",
    re.I,
)


def _decision_ids(contract: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for d in contract.get("decisions") or []:
        if isinstance(d, dict) and d.get("id"):
            out.add(str(d["id"]))
    return out


def _parse_required_entry(
    entry: str,
    decision_ids: set[str],
) -> dict[str, Any]:
    """
    Normalize one sufficiency.required item into a check descriptor.

    Supported forms (LLM-written, not framework enums):
      - "board_type"                         → outcome must not be UNKNOWN
      - "subject_instance = YES"              → exact match
      - "price_scope in [A, B]"               → observed in set
      - free text ("shop_name", …)            → label must be in proven_labels
    """
    raw = (entry or "").strip()
    if not raw:
        return {"kind": "empty", "raw": raw}

    m_eq = _EQ.match(raw)
    if m_eq:
        return {
            "kind": "decision_eq",
            "decision_id": m_eq.group(1),
            "allowed": [m_eq.group(2)],
            "raw": raw,
        }

    m_in = _IN.match(raw)
    if m_in:
        allowed = [p.strip().strip("'\"") for p in m_in.group(2).split(",") if p.strip()]
        return {
            "kind": "decision_in",
            "decision_id": m_in.group(1),
            "allowed": allowed,
            "raw": raw,
        }

    # Bare decision id
    token = raw.split()[0].rstrip(".,;:")
    if token in decision_ids or (raw in decision_ids):
        return {
            "kind": "decision_known",
            "decision_id": token if token in decision_ids else raw,
            "allowed": None,  # any non-UNKNOWN
            "raw": raw,
        }

    # Free-text label (observable name, prose requirement)
    return {"kind": "label", "label": raw, "raw": raw}


def evaluate_sufficiency(
    frozen_contract: dict[str, Any] | None,
    outcomes: dict[str, str] | None = None,
    *,
    proven_labels: list[str] | set[str] | None = None,
    require_frozen_flag: bool = True,
) -> dict[str, Any]:
    """
    Code-level gate: are all contractually required items satisfied?

    Fail-closed: missing contract, unfrozen contract (if required), or UNKNOWN
    on a required decision → not satisfied.
    """
    outcomes = {str(k): str(v) for k, v in (outcomes or {}).items()}
    proven = {str(x).strip().lower() for x in (proven_labels or []) if str(x).strip()}

    if not frozen_contract:
        return {
            "satisfied": False,
            "gaps": [
                {
                    "kind": "no_contract",
                    "required_entry": None,
                    "detail": "no frozen contract provided",
                }
            ],
            "details": [],
            "stop_reason": "CONTRACT_NOT_FROZEN",
        }

    if require_frozen_flag and not frozen_contract.get("frozen", False):
        return {
            "satisfied": False,
            "gaps": [
                {
                    "kind": "not_frozen",
                    "required_entry": None,
                    "detail": "contract.frozen is not true",
                }
            ],
            "details": [],
            "stop_reason": "CONTRACT_NOT_FROZEN",
        }

    decision_ids = _decision_ids(frozen_contract)
    sufficiency = frozen_contract.get("sufficiency") or {}
    required_list = list(sufficiency.get("required") or [])

    # Also honor per-decision required_for_eligibility if present (legacy/fixture shape)
    for d in frozen_contract.get("decisions") or []:
        if not isinstance(d, dict):
            continue
        did = d.get("id")
        req = d.get("required_for_eligibility") or []
        if did and req:
            # encode as decision_in so we don't double-count bare id
            entry = f"{did} in [{', '.join(str(x) for x in req)}]"
            if entry not in required_list and did not in required_list:
                required_list.append(entry)

    if not required_list:
        # Empty required → nothing to prove → satisfied (explicit empty contract)
        return {
            "satisfied": True,
            "gaps": [],
            "details": [],
            "stop_reason": "CONTRACT_SATISFIED",
            "note": "sufficiency.required was empty",
        }

    details: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []

    for entry in required_list:
        spec = _parse_required_entry(str(entry), decision_ids)
        kind = spec["kind"]

        if kind == "empty":
            continue

        if kind == "label":
            label = str(spec["label"])
            ok = label.lower() in proven or any(
                label.lower() in p or p in label.lower() for p in proven
            )
            row = {
                "kind": "label",
                "required_entry": entry,
                "label": label,
                "result": "PASS" if ok else "UNKNOWN",
                "observed": "proven" if ok else "missing",
            }
            details.append(row)
            if not ok:
                gaps.append(
                    {
                        "kind": "label_missing",
                        "required_entry": entry,
                        "detail": f"label not in proven_labels: {label}",
                    }
                )
            continue

        did = str(spec.get("decision_id") or "")
        observed = outcomes.get(did, "UNKNOWN")
        allowed = spec.get("allowed")

        if kind == "decision_known":
            # any concrete outcome except UNKNOWN
            ok = observed != "UNKNOWN"
            result = "PASS" if ok else "UNKNOWN"
        elif kind in ("decision_eq", "decision_in"):
            if observed == "UNKNOWN":
                ok = False
                result = "UNKNOWN"
            elif allowed and observed in allowed:
                ok = True
                result = "PASS"
            else:
                ok = False
                result = "FAIL"
        else:
            ok = False
            result = "UNKNOWN"

        row = {
            "kind": kind,
            "decision_id": did,
            "required_entry": entry,
            "observed": observed,
            "allowed": allowed,
            "result": result,
        }
        details.append(row)
        if not ok:
            gaps.append(
                {
                    "kind": "decision_gap",
                    "decision_id": did,
                    "required_entry": entry,
                    "observed": observed,
                    "allowed": allowed,
                    "result": result,
                }
            )

    satisfied = len(gaps) == 0
    return {
        "satisfied": satisfied,
        "gaps": gaps,
        "details": details,
        "stop_reason": "CONTRACT_SATISFIED" if satisfied else "CONTRACT_GAPS",
    }


def gaps_for_acquisition(
    frozen_contract: dict[str, Any] | None,
    outcomes: dict[str, str] | None = None,
    *,
    proven_labels: list[str] | set[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Shape compatible with evidence_acquisition.gaps_from_eligibility consumers:
    list of {decision_id, result, observed, allowed}.
    """
    ev = evaluate_sufficiency(
        frozen_contract,
        outcomes,
        proven_labels=proven_labels,
        require_frozen_flag=True,
    )
    out: list[dict[str, Any]] = []
    for g in ev.get("gaps") or []:
        if g.get("kind") == "decision_gap":
            out.append(
                {
                    "decision_id": g.get("decision_id"),
                    "result": g.get("result") or "UNKNOWN",
                    "observed": g.get("observed"),
                    "allowed": g.get("allowed"),
                }
            )
        else:
            out.append(
                {
                    "decision_id": g.get("kind") or "contract",
                    "result": "UNKNOWN",
                    "observed": None,
                    "allowed": None,
                    "detail": g.get("detail") or g.get("required_entry"),
                }
            )
    return out
