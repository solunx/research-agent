"""
Persistent learnings: site tactics + general strategies + URL patterns + recipes + event log.

Phase goal: agent becomes more efficient over runs without hardcoding domains.
Host-level knowledge is GLOBAL (shared across all tasks) and split into three layers:

  1. navigation  – how to reach search/list (channel, paths)
  2. semantics   – what params/fields mean (rewrites, ignored keys, encodings)
  3. harvest     – how to extract names/prices/links from results

Run/task content (shortlist, notes, report) stays per-run.

Files (under memory_dir):
  site_tactics.json       – per-domain preferred tool / tier outcomes
  site_recipes.json       – channels + param_warnings + semantics + harvest + human_setup
  general_strategies.json – pattern-level rules
  site_url_patterns.json  – learned search/filter URL shapes per domain
  events.jsonl            – append-only success/fail log
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse, urlunparse

# Cheap → expensive transport channels (generic, not task-specific)
CHANNEL_ORDER = ("api_json", "html_list", "html_detail", "browser_open", "browser_use", "blocked")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _domain(url_or_host: str) -> str:
    s = (url_or_host or "").strip().lower()
    if not s:
        return ""
    if "://" in s:
        host = urlparse(s).netloc.lower()
    else:
        host = s
    if host.startswith("www."):
        host = host[4:]
    return host


# Query keys that look like occupancy / date / filter structure (generic)
_PARAM_HINTS = (
    "participant",
    "adult",
    "pax",
    "person",
    "traveler",
    "traveller",
    "guest",
    "date",
    "depart",
    "arrival",
    "checkin",
    "checkout",
    "meal",
    "board",
    "duration",
    "night",
    "airport",
    "from",
    "origin",
    "transport",
    "room",
)


class MemoryStore:
    def __init__(self, memory_dir: str = "memory"):
        self.root = Path(memory_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.tactics_path = self.root / "site_tactics.json"
        self.strategies_path = self.root / "general_strategies.json"
        self.url_patterns_path = self.root / "site_url_patterns.json"
        self.recipes_path = self.root / "site_recipes.json"
        self.events_path = self.root / "events.jsonl"
        # Domains touched during this process lifetime (for end-of-run summary)
        self._touched_domains: set[str] = set()

    def touch_domain(self, domain_or_url: str) -> str:
        d = _domain(domain_or_url)
        if d:
            self._touched_domains.add(d)
        return d

    def load_tactics(self) -> dict[str, Any]:
        if not self.tactics_path.exists():
            return {}
        try:
            return json.loads(self.tactics_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_tactics(self, data: dict[str, Any]) -> None:
        self.tactics_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def load_strategies(self) -> list[dict[str, Any]]:
        if not self.strategies_path.exists():
            return []
        try:
            data = json.loads(self.strategies_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return list(data.get("strategies") or [])
            if isinstance(data, list):
                return data
            return []
        except Exception:
            return []

    def save_strategies(self, strategies: list[dict[str, Any]]) -> None:
        payload = {"strategies": strategies, "updated_at": _now()}
        self.strategies_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def log_event(self, event: dict[str, Any]) -> None:
        event = dict(event)
        event.setdefault("ts", _now())
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def record_tool_result(
        self,
        tool: str,
        url: str | None = None,
        ok: bool = True,
        duration_ms: float | None = None,
        error: str | None = None,
        blocked: bool = False,
    ) -> None:
        domain = self.touch_domain(url or "")
        self.log_event(
            {
                "type": "tool_result",
                "tool": tool,
                "domain": domain,
                "url": url,
                "ok": ok,
                "blocked": blocked,
                "duration_ms": duration_ms,
                "error": (error or "")[:300] if error else None,
            }
        )
        # Update site tactic on clear success/failure signals
        if not domain:
            return
        if tool == "web_fetch" and (blocked or (error and "403" in str(error))):
            self._set_tactic(
                domain,
                preferred_tool="browser_open",
                reason="HTTP fetch blocked or 403",
            )
            self.record_channel_outcome(
                domain, channel="html_list", success=False, reason="fetch blocked/403"
            )
        elif tool == "web_fetch" and ok:
            # Cheap success signal — may still be a JS shell; recipe refined elsewhere
            self.record_channel_outcome(
                domain, channel="html_detail", success=True, reason="web_fetch ok"
            )
        elif tool == "browser_open" and ok:
            tactics = self.load_tactics()
            existing = tactics.get(domain) or {}
            # Only lock browser preference if we already saw fetch fail
            if existing.get("preferred_tool") == "browser_open" or blocked:
                self._set_tactic(
                    domain,
                    preferred_tool="browser_open",
                    reason=existing.get("reason") or "browser succeeded",
                )
            self.record_channel_outcome(
                domain, channel="browser_open", success=True, reason="browser_open ok"
            )

    def _set_tactic(
        self,
        domain: str,
        preferred_tool: str,
        reason: str,
    ) -> None:
        tactics = self.load_tactics()
        prev = tactics.get(domain) or {}
        tactics[domain] = {
            "preferred_tool": preferred_tool,
            "reason": reason,
            "last_verified": _now(),
            "success_count": int(prev.get("success_count") or 0) + 1,
        }
        self.save_tactics(tactics)

    def preferred_tool_for_url(self, url: str) -> str | None:
        domain = _domain(url)
        if not domain:
            return None
        tactics = self.load_tactics()
        entry = tactics.get(domain)
        if not entry:
            # parent domain match (e.g. www handled already)
            for key, val in tactics.items():
                if domain == key or domain.endswith("." + key):
                    entry = val
                    break
        if not entry:
            return None
        return entry.get("preferred_tool")

    def record_tier_outcome(
        self,
        domain_or_url: str,
        *,
        tier: str,
        success: bool,
        reason: str = "",
    ) -> None:
        """
        Track which escalation tier worked or failed for a host.
        Tiers (cheap → expensive): web_fetch | browser_open | browser_use
        Stored on site_tactics so next runs prefer the cheapest successful path.
        Also updates global site_recipes (cross-task).
        """
        domain = self.touch_domain(domain_or_url)
        if not domain:
            return
        tactics = self.load_tactics()
        prev = tactics.get(domain) or {}
        failed = list(prev.get("failed_tiers") or [])
        if success:
            # Promote this tier; clear it from failed if present
            failed = [t for t in failed if t != tier]
            tactics[domain] = {
                **prev,
                "preferred_tool": tier if tier != "web_fetch" else prev.get(
                    "preferred_tool", "web_fetch"
                ),
                "successful_tier": tier,
                "failed_tiers": failed,
                "reason": reason or prev.get("reason") or f"{tier} succeeded",
                "last_verified": _now(),
                "success_count": int(prev.get("success_count") or 0) + 1,
            }
        else:
            if tier not in failed:
                failed.append(tier)
            tactics[domain] = {
                **prev,
                "failed_tiers": failed[-6:],  # keep recent
                "last_failure_tier": tier,
                "last_failure_reason": (reason or "")[:200],
                "last_verified": _now(),
                "failure_count": int(prev.get("failure_count") or 0) + 1,
            }
            # If browser_use failed, do not prefer it next time
            if tier == "browser_use" and prev.get("preferred_tool") == "browser_use":
                tactics[domain]["preferred_tool"] = "browser_open"
                tactics[domain]["reason"] = "browser_use failed; prefer cheaper browser"
        self.save_tactics(tactics)
        self.log_event(
            {
                "type": "tier_outcome",
                "domain": domain,
                "tier": tier,
                "success": success,
                "reason": (reason or "")[:200],
            }
        )
        # Mirror into global recipes (channel names align with tiers where possible)
        channel = {
            "web_fetch": "html_list",
            "browser_open": "browser_open",
            "browser_use": "browser_use",
        }.get(tier, tier)
        self.record_channel_outcome(
            domain, channel=channel, success=success, reason=reason
        )
        # After any failure, check if host is exhausted for automation
        if not success:
            self._maybe_flag_human_setup(domain, reason or f"{tier} failed")

    # --- Global site recipes (cross-task transport knowledge) ---

    def load_recipes(self) -> dict[str, Any]:
        if not self.recipes_path.exists():
            return {}
        try:
            return json.loads(self.recipes_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_recipes(self, data: dict[str, Any]) -> None:
        self.recipes_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def record_channel_outcome(
        self,
        domain_or_url: str,
        *,
        channel: str,
        success: bool,
        reason: str = "",
        template: str | None = None,
        param_names: list[str] | None = None,
    ) -> None:
        """
        Upsert a generic transport channel for a host.
        Channels are task-agnostic (api_json, html_list, html_detail, browser_*, blocked).
        """
        domain = self.touch_domain(domain_or_url)
        if not domain or not channel:
            return
        recipes = self.load_recipes()
        entry = recipes.get(domain) or self._empty_recipe_entry()
        channels = dict(entry.get("channels") or {})
        ch = dict(channels.get(channel) or {})
        if success:
            ch["success_count"] = int(ch.get("success_count") or 0) + 1
            ch["last_success"] = _now()
            if template:
                ch["template"] = template[:500]
            if param_names:
                known = list(ch.get("param_names") or [])
                for p in param_names:
                    if p not in known:
                        known.append(p)
                ch["param_names"] = known[:40]
            entry["preferred_channel"] = channel
            entry["success_count"] = int(entry.get("success_count") or 0) + 1
            # Successful channel clears human_setup unless still blocked elsewhere
            if entry.get("human_setup_needed") and channel not in ("blocked",):
                if channel in ("api_json", "html_list", "html_detail"):
                    entry["human_setup_needed"] = False
                    entry["human_setup_reason"] = ""
            # Navigation layer
            if channel in ("browser_open", "html_list", "html_detail", "api_json"):
                nav = dict(entry.get("navigation") or {})
                nav["preferred_channel"] = channel
                nav["last_success"] = _now()
                entry["navigation"] = nav
                if entry.get("needs_recon"):
                    entry["needs_recon"] = False
                    entry["needs_recon_reason"] = ""
        else:
            ch["failure_count"] = int(ch.get("failure_count") or 0) + 1
            ch["last_failure"] = _now()
            if reason:
                ch["last_failure_reason"] = reason[:200]
            entry["failure_count"] = int(entry.get("failure_count") or 0) + 1
        channels[channel] = ch
        entry["channels"] = channels
        self._refresh_capability_score(entry)
        entry["last_verified"] = _now()
        recipes[domain] = entry
        self.save_recipes(recipes)

    def mark_human_setup_needed(self, domain_or_url: str, reason: str) -> None:
        """Flag a host for manual API/affiliate setup (global, cross-task)."""
        domain = self.touch_domain(domain_or_url)
        if not domain:
            return
        recipes = self.load_recipes()
        entry = recipes.get(domain) or self._empty_recipe_entry()
        entry["human_setup_needed"] = True
        entry["human_setup_reason"] = (reason or "all automated channels failed")[:300]
        entry["last_verified"] = _now()
        recipes[domain] = entry
        self.save_recipes(recipes)
        self.log_event(
            {
                "type": "human_setup_needed",
                "domain": domain,
                "reason": entry["human_setup_reason"],
            }
        )

    def _empty_recipe_entry(self) -> dict[str, Any]:
        return {
            "channels": {},
            "preferred_channel": None,
            "human_setup_needed": False,
            "human_setup_reason": "",
            "success_count": 0,
            "failure_count": 0,
            # Capability layers (recon fills these; research consumes them)
            "navigation": {},
            "semantics": {},
            "harvest": {},
            "param_warnings": [],
            "needs_recon": False,
            "capability_score": {
                "navigation": 0,
                "semantics": 0,
                "harvest": 0,
            },
        }

    def record_param_warning(
        self,
        domain_or_url: str,
        *,
        param: str,
        kind: str,
        detail: str = "",
    ) -> None:
        """
        Persist generic param-semantics warnings (cross-task).
        Example: a 'participant' key that accepts dates, not headcount.
        Also mirrored under recipes[domain].semantics.param_notes.
        """
        domain = self.touch_domain(domain_or_url)
        param = (param or "").strip().lower()
        if not domain or not param:
            return
        recipes = self.load_recipes()
        entry = recipes.get(domain) or self._empty_recipe_entry()
        warnings = list(entry.get("param_warnings") or [])
        # Dedupe by param+kind
        warnings = [w for w in warnings if not (
            str(w.get("param") or "").lower() == param
            and str(w.get("kind") or "") == kind
        )]
        warnings.insert(
            0,
            {
                "param": param,
                "kind": kind,
                "detail": (detail or "")[:300],
                "last_seen": _now(),
            },
        )
        entry["param_warnings"] = warnings[:12]
        # Mirror into semantics layer
        sem = dict(entry.get("semantics") or {})
        notes = list(sem.get("param_notes") or [])
        note = f"{param}: {kind}" + (f" — {detail[:120]}" if detail else "")
        if note not in notes:
            notes.insert(0, note)
        sem["param_notes"] = notes[:20]
        if kind in ("ignored", "rewritten", "not_count_looks_like_date"):
            ignored = list(sem.get("ignored_or_unsafe_params") or [])
            if param not in ignored:
                ignored.append(param)
            sem["ignored_or_unsafe_params"] = ignored[:20]
        entry["semantics"] = sem
        self._refresh_capability_score(entry)
        entry["last_verified"] = _now()
        recipes[domain] = entry
        self.save_recipes(recipes)
        self.log_event(
            {
                "type": "param_warning",
                "domain": domain,
                "param": param,
                "kind": kind,
                "detail": (detail or "")[:200],
            }
        )

    def record_semantic_observation(
        self,
        domain_or_url: str,
        *,
        observation: str,
        kind: str = "note",
        param: str | None = None,
    ) -> None:
        """
        Recon: store a short semantic finding (task-agnostic).
        kind examples: ignored | rewritten | encoding | field_maps_to | note
        """
        domain = self.touch_domain(domain_or_url)
        obs = (observation or "").strip()
        if not domain or not obs:
            return
        recipes = self.load_recipes()
        entry = recipes.get(domain) or self._empty_recipe_entry()
        sem = dict(entry.get("semantics") or {})
        notes = list(sem.get("param_notes") or [])
        line = obs[:240]
        if line not in notes:
            notes.insert(0, line)
        sem["param_notes"] = notes[:20]
        if param:
            p = param.strip().lower()
            if kind in ("ignored", "rewritten", "not_count_looks_like_date"):
                unsafe = list(sem.get("ignored_or_unsafe_params") or [])
                if p not in unsafe:
                    unsafe.append(p)
                sem["ignored_or_unsafe_params"] = unsafe[:20]
        sem["last_probe"] = _now()
        entry["semantics"] = sem
        self._refresh_capability_score(entry)
        entry["last_verified"] = _now()
        recipes[domain] = entry
        self.save_recipes(recipes)
        self.log_event(
            {
                "type": "semantic_observation",
                "domain": domain,
                "kind": kind,
                "param": param,
                "observation": obs[:200],
            }
        )

    def record_harvest_hint(
        self,
        domain_or_url: str,
        *,
        hint: str,
        has_price_signals: bool | None = None,
        has_name_list: bool | None = None,
        relationships_extractable: str | None = None,
        success: bool | None = None,
    ) -> None:
        """
        Recon/retrieval: harvest capability is multi-field, not binary.

        price_signals = discovery only (amounts visible).
        relationships_extractable = unknown|partial|ok|failed — entity↔value pairing.
        """
        domain = self.touch_domain(domain_or_url)
        hint = (hint or "").strip()
        if not domain:
            return
        recipes = self.load_recipes()
        entry = recipes.get(domain) or self._empty_recipe_entry()
        har = dict(entry.get("harvest") or {})
        hints = list(har.get("hints") or [])
        if hint and hint[:240] not in hints:
            hints.insert(0, hint[:240])
        har["hints"] = hints[:12]
        if has_price_signals is not None:
            har["has_price_signals"] = bool(has_price_signals)
        if has_name_list is not None:
            har["has_name_list"] = bool(has_name_list)
        if relationships_extractable in ("unknown", "partial", "ok", "failed"):
            har["relationships_extractable"] = relationships_extractable
        # Empirical counters (experience, not truth)
        if success is True:
            har["success_count"] = int(har.get("success_count") or 0) + 1
        elif success is False:
            har["failure_count"] = int(har.get("failure_count") or 0) + 1
        har["last_probe"] = _now()
        entry["harvest"] = har
        self._refresh_capability_score(entry)
        entry["last_verified"] = _now()
        recipes[domain] = entry
        self.save_recipes(recipes)
        self.log_event(
            {
                "type": "harvest_hint",
                "domain": domain,
                "hint": (hint or "")[:200],
                "has_price_signals": has_price_signals,
                "relationships_extractable": har.get("relationships_extractable"),
            }
        )

    def record_navigation_success(
        self,
        domain_or_url: str,
        *,
        channel: str,
        path_hint: str | None = None,
    ) -> None:
        """Mark that we can reach a useful search/list surface on this host."""
        domain = self.touch_domain(domain_or_url)
        if not domain:
            return
        recipes = self.load_recipes()
        entry = recipes.get(domain) or self._empty_recipe_entry()
        nav = dict(entry.get("navigation") or {})
        nav["preferred_channel"] = channel or nav.get("preferred_channel")
        nav["last_success"] = _now()
        if path_hint:
            paths = list(nav.get("path_hints") or [])
            if path_hint not in paths:
                paths.insert(0, path_hint)
            nav["path_hints"] = paths[:8]
        entry["navigation"] = nav
        if channel:
            entry["preferred_channel"] = channel
        self._refresh_capability_score(entry)
        entry["last_verified"] = _now()
        recipes[domain] = entry
        self.save_recipes(recipes)

    def mark_needs_recon(self, domain_or_url: str, reason: str = "") -> None:
        """Research path: recipe looked stale / structurally broken — recon next."""
        domain = self.touch_domain(domain_or_url)
        if not domain:
            return
        recipes = self.load_recipes()
        entry = recipes.get(domain) or self._empty_recipe_entry()
        entry["needs_recon"] = True
        entry["needs_recon_reason"] = (reason or "structural failure in research")[:300]
        entry["last_verified"] = _now()
        recipes[domain] = entry
        self.save_recipes(recipes)
        self.log_event(
            {
                "type": "needs_recon",
                "domain": domain,
                "reason": entry["needs_recon_reason"],
            }
        )

    def clear_needs_recon(self, domain_or_url: str) -> None:
        domain = self.touch_domain(domain_or_url)
        if not domain:
            return
        recipes = self.load_recipes()
        entry = recipes.get(domain)
        if not entry:
            return
        entry["needs_recon"] = False
        entry["needs_recon_reason"] = ""
        entry["last_verified"] = _now()
        recipes[domain] = entry
        self.save_recipes(recipes)

    def _refresh_capability_score(self, entry: dict[str, Any]) -> None:
        """Rough 0–2 scores so recon knows what is still missing (generic)."""
        nav = entry.get("navigation") or {}
        sem = entry.get("semantics") or {}
        har = entry.get("harvest") or {}
        n = 0
        if entry.get("preferred_channel") or nav.get("preferred_channel"):
            n += 1
        if nav.get("path_hints") or (entry.get("channels") or {}):
            n += 1
        s = 0
        if entry.get("param_warnings") or sem.get("param_notes"):
            s += 1
        if sem.get("ignored_or_unsafe_params") or len(sem.get("param_notes") or []) >= 2:
            s += 1
        h = 0
        # price_signals alone → at most 1; relationships ok → full harvest score
        if har.get("has_price_signals") or har.get("hints"):
            h += 1
        rel = str(har.get("relationships_extractable") or "")
        if rel == "ok" or har.get("has_name_list"):
            h += 1
        elif rel == "partial" and h < 1:
            h += 1
        entry["capability_score"] = {
            "navigation": min(2, n),
            "semantics": min(2, s),
            "harvest": min(2, h),
        }

    def _maybe_flag_human_setup(self, domain: str, reason: str) -> None:
        """Flag host when multiple tiers have failed and nothing preferred works."""
        tactics = self.load_tactics()
        t = tactics.get(domain) or {}
        failed = list(t.get("failed_tiers") or [])
        recipes = self.load_recipes()
        r = recipes.get(domain) or {}
        # Already flagged
        if r.get("human_setup_needed"):
            return
        # Need both browser paths failed or repeated fails with no successful_tier
        heavy_fails = sum(1 for x in failed if x in ("browser_open", "browser_use", "web_fetch"))
        if heavy_fails >= 2 and not t.get("successful_tier"):
            self.mark_human_setup_needed(
                domain,
                reason or "Multiple tiers failed; no successful automated channel",
            )

    def summarize_host_learnings(
        self,
        *,
        domains: set[str] | None = None,
    ) -> dict[str, Any]:
        """
        End-of-run summary of global host knowledge (for human + next tasks).
        Returns structured dict + plain-text block for CLI / host_learnings.md.
        """
        domains = set(domains or self._touched_domains)
        tactics = self.load_tactics()
        recipes = self.load_recipes()
        patterns = self.load_url_patterns()

        # Also surface any global human_setup flags even if not touched this run
        for d, r in recipes.items():
            if r.get("human_setup_needed"):
                domains.add(d)

        rows: list[dict[str, Any]] = []
        human_candidates: list[str] = []
        lines: list[str] = [
            "# Host learnings (global — shared across tasks)",
            "",
            "Capability model: **navigation** (reach) · **semantics** (params mean) · **harvest** (extract).",
            "Task content (shortlist/report) stays in the run folder.",
            "",
        ]

        if not domains:
            lines.append("(no hosts touched this run)")
            return {
                "domains": [],
                "rows": [],
                "human_setup_candidates": [],
                "text": "\n".join(lines) + "\n",
            }

        for domain in sorted(domains):
            t = tactics.get(domain) or {}
            r = recipes.get(domain) or {}
            p = patterns.get(domain) or {}
            pref = (
                r.get("preferred_channel")
                or t.get("successful_tier")
                or t.get("preferred_tool")
                or "unknown"
            )
            failed = list(t.get("failed_tiers") or [])
            human = bool(r.get("human_setup_needed"))
            reason = r.get("human_setup_reason") or t.get("last_failure_reason") or ""
            row = {
                "domain": domain,
                "preferred_channel": pref,
                "failed_tiers": failed,
                "successful_tier": t.get("successful_tier"),
                "url_pattern_ok": int(p.get("success_count") or 0),
                "url_pattern_fail": int(p.get("failure_count") or 0),
                "human_setup_needed": human,
                "human_setup_reason": reason,
            }
            rows.append(row)
            status = "OK" if not human else "HUMAN_SETUP"
            score = r.get("capability_score") or {}
            lines.append(f"## {domain}  [{status}]")
            lines.append(f"- preferred_channel / tier: `{pref}`")
            if score:
                lines.append(
                    f"- capability: nav={score.get('navigation', 0)}/2 "
                    f"sem={score.get('semantics', 0)}/2 "
                    f"har={score.get('harvest', 0)}/2"
                )
            if r.get("needs_recon"):
                lines.append(
                    f"- **needs_recon:** {r.get('needs_recon_reason') or 'yes'}"
                )
            if failed:
                lines.append(f"- failed_tiers: {', '.join(str(x) for x in failed)}")
            if p.get("path_hints") or p.get("param_names"):
                paths = ", ".join((p.get("path_hints") or [])[:3])
                params = ", ".join((p.get("param_names") or [])[:8])
                lines.append(
                    f"- navigation/url_patterns: paths=[{paths}] params=[{params}] "
                    f"(ok={row['url_pattern_ok']}, fail={row['url_pattern_fail']})"
                )
            for w in (r.get("param_warnings") or [])[:4]:
                lines.append(
                    f"- semantics param_warning `{w.get('param')}`: {w.get('kind')} — "
                    f"{(w.get('detail') or '')[:100]}"
                )
            for note in ((r.get("semantics") or {}).get("param_notes") or [])[:3]:
                if note:
                    lines.append(f"- semantics: {note[:120]}")
            for hint in ((r.get("harvest") or {}).get("hints") or [])[:3]:
                if hint:
                    lines.append(f"- harvest: {hint[:120]}")
            if human:
                human_candidates.append(domain)
                lines.append(
                    f"- **human_setup_needed:** {reason or 'all automated channels weak/failed'}"
                )
                lines.append(
                    "  → Consider a one-time API/affiliate/deep-link setup; "
                    "store it in memory so every future task reuses it."
                )
            lines.append("")

        if human_candidates:
            lines.append("## Action for operator")
            lines.append(
                "These hosts need a manual channel (API key, affiliate feed, or stable deep-link):"
            )
            for d in human_candidates:
                lines.append(f"- {d}")
            lines.append("")

        lines.append(
            "_Next run (any task) loads the same `memory/site_recipes.json` + tactics — "
            "no rediscovery of the same host failures._"
        )
        return {
            "domains": sorted(domains),
            "rows": rows,
            "human_setup_candidates": human_candidates,
            "text": "\n".join(lines) + "\n",
        }

    # --- Learned search / filter URL patterns per domain ---

    def load_url_patterns(self) -> dict[str, Any]:
        if not self.url_patterns_path.exists():
            return {}
        try:
            return json.loads(self.url_patterns_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_url_patterns(self, data: dict[str, Any]) -> None:
        self.url_patterns_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def record_search_url(self, url: str, *, useful: bool = True) -> None:
        """
        Learn generic URL shape when a page looks like a filtered search/results page.
        Stores path + query parameter *names* (not values) so next runs can rebuild.
        """
        if not useful or not url or not url.startswith("http"):
            return
        try:
            parsed = urlparse(url)
        except Exception:
            return
        domain = self.touch_domain(url)
        if not domain:
            return
        qs = parse_qs(parsed.query, keep_blank_values=True)
        if not qs and "/zoeken" not in parsed.path and "/search" not in parsed.path.lower():
            return
        # Only store if we see occupancy/date-like keys OR a clear search path
        keys = list(qs.keys())
        interesting = [
            k
            for k in keys
            if any(h in k.lower() for h in _PARAM_HINTS)
        ]
        if not interesting and not re.search(r"/(zoeken|search|results?)/?", parsed.path, re.I):
            return

        patterns = self.load_url_patterns()
        entry = patterns.get(domain) or {
            "example_urls": [],
            "param_names": [],
            "path_hints": [],
            "success_count": 0,
            "failure_count": 0,
        }
        # Merge param names
        known = list(entry.get("param_names") or [])
        for k in keys:
            if k not in known:
                known.append(k)
        entry["param_names"] = known[:40]

        path = parsed.path or "/"
        paths = list(entry.get("path_hints") or [])
        if path and path not in paths:
            paths.insert(0, path)
        entry["path_hints"] = paths[:8]

        # Keep a few anonymized examples (truncate long query values)
        examples = list(entry.get("example_urls") or [])
        # Strip very long values for storage hygiene
        safe_q = "&".join(f"{k}=…" for k in list(qs.keys())[:15])
        example = urlunparse(
            (parsed.scheme, parsed.netloc, path, "", safe_q, "")
        )
        if example not in examples:
            examples.insert(0, example)
        entry["example_urls"] = examples[:5]
        entry["success_count"] = int(entry.get("success_count") or 0) + 1
        entry.setdefault("failure_count", int(entry.get("failure_count") or 0))
        entry["last_verified"] = _now()
        patterns[domain] = entry
        self.save_url_patterns(patterns)

    def record_url_pattern_outcome(
        self,
        url_or_host: str,
        *,
        success: bool,
        reason: str = "",
    ) -> None:
        """
        Treat learned URL patterns as empirical hypotheses, not truth.
        success=True bumps success_count; False bumps failure_count.
        """
        domain = _domain(url_or_host)
        if not domain:
            return
        patterns = self.load_url_patterns()
        entry = patterns.get(domain)
        if not entry:
            # parent/sibling host match
            for k, v in patterns.items():
                if domain == k or domain.endswith("." + k) or k.endswith("." + domain):
                    entry = v
                    domain = k
                    break
        if not entry:
            return
        if success:
            entry["success_count"] = int(entry.get("success_count") or 0) + 1
            entry["last_verified"] = _now()
        else:
            entry["failure_count"] = int(entry.get("failure_count") or 0) + 1
            entry["last_failure"] = _now()
            if reason:
                entry["last_failure_reason"] = reason[:200]
        patterns[domain] = entry
        self.save_url_patterns(patterns)
        self.log_event(
            {
                "type": "url_pattern_outcome",
                "domain": domain,
                "success": success,
                "reason": (reason or "")[:200],
            }
        )

    def prompt_block(
        self,
        max_tactics: int = 40,
        max_strategies: int = 15,
        retest_after_days: int = 30,
    ) -> str:
        """Compact text injected into system prompt."""
        lines: list[str] = []
        tactics = self.load_tactics()
        if tactics:
            lines.append("### Learned site tactics (prefer these tools)")
            # Sort by last_verified desc
            items = sorted(
                tactics.items(),
                key=lambda kv: kv[1].get("last_verified") or "",
                reverse=True,
            )[:max_tactics]
            cutoff = datetime.now(timezone.utc) - timedelta(days=retest_after_days)
            for domain, info in items:
                pref = info.get("preferred_tool", "?")
                reason = info.get("reason", "")
                verified = info.get("last_verified", "")
                succ = info.get("successful_tier") or ""
                failed = info.get("failed_tiers") or []
                stale = ""
                try:
                    if verified:
                        vt = datetime.fromisoformat(verified.replace("Z", "+00:00"))
                        if vt < cutoff:
                            stale = " [stale—consider retesting cheaper method]"
                except Exception:
                    pass
                extra = ""
                if succ:
                    extra += f"; successful_tier={succ}"
                if failed:
                    extra += f"; failed_tiers={','.join(str(t) for t in failed[-4:])}"
                lines.append(
                    f"- {domain}: prefer `{pref}` ({reason}){extra}{stale}"
                )

        patterns = self.load_url_patterns()
        if patterns:
            lines.append("")
            lines.append(
                "### Learned search URL patterns (reuse; rebuild with task constraints)"
            )
            pitems = sorted(
                patterns.items(),
                key=lambda kv: kv[1].get("last_verified") or "",
                reverse=True,
            )[:20]
            for domain, info in pitems:
                params = ", ".join((info.get("param_names") or [])[:12])
                paths = ", ".join((info.get("path_hints") or [])[:3])
                sc = int(info.get("success_count") or 0)
                fc = int(info.get("failure_count") or 0)
                lines.append(
                    f"- {domain}: paths=[{paths}] params=[{params}] "
                    f"(ok={sc}, fail={fc})"
                )
                for ex in (info.get("example_urls") or [])[:1]:
                    lines.append(f"  e.g. {ex}")

        recipes = self.load_recipes()
        if recipes:
            lines.append("")
            lines.append(
                "### Global site recipes (cross-task; reuse preferred channel first)"
            )
            ritems = sorted(
                recipes.items(),
                key=lambda kv: kv[1].get("last_verified") or "",
                reverse=True,
            )[:20]
            for domain, info in ritems:
                pref = info.get("preferred_channel") or "?"
                human = " HUMAN_SETUP" if info.get("human_setup_needed") else ""
                chans = info.get("channels") or {}
                ch_summary = ", ".join(
                    f"{k}(ok={v.get('success_count', 0)}/fail={v.get('failure_count', 0)})"
                    for k, v in list(chans.items())[:4]
                )
                score = info.get("capability_score") or {}
                score_s = ""
                if score:
                    score_s = (
                        f" cap[nav={score.get('navigation', 0)} "
                        f"sem={score.get('semantics', 0)} "
                        f"har={score.get('harvest', 0)}]"
                    )
                needs = " NEEDS_RECON" if info.get("needs_recon") else ""
                lines.append(f"- {domain}: preferred=`{pref}`{human}{needs}{score_s}")
                if ch_summary:
                    lines.append(f"  channels: {ch_summary}")
                for w in (info.get("param_warnings") or [])[:3]:
                    lines.append(
                        f"  ⚠ semantics param `{w.get('param')}`: {w.get('kind')} — "
                        f"{(w.get('detail') or '')[:120]}"
                    )
                for note in ((info.get("semantics") or {}).get("param_notes") or [])[:2]:
                    lines.append(f"  semantics: {note[:120]}")
                for hint in ((info.get("harvest") or {}).get("hints") or [])[:2]:
                    lines.append(f"  harvest: {hint[:120]}")
                if info.get("human_setup_needed"):
                    lines.append(
                        f"  human: {info.get('human_setup_reason') or 'needs manual API/deep-link'}"
                    )

        strategies = self.load_strategies()
        if strategies:
            lines.append("")
            lines.append("### General strategies")
            for s in strategies[:max_strategies]:
                trigger = s.get("trigger") or s.get("when") or ""
                tactic = s.get("tactic") or s.get("then") or ""
                lines.append(f"- When: {trigger} → {tactic}")

        if not lines:
            return (
                "### Learned tactics\n"
                "(none yet — discover by trying web_fetch first; on 403/blocked use browser_open; "
                "successful escalations are saved automatically and shared across all tasks.)"
            )
        return "\n".join(lines)

    def ensure_seed_strategies(self) -> None:
        """Install / merge generic strategies (idempotent on trigger text)."""
        existing = self.load_strategies()
        seeds = [
            {
                "trigger": "HTTP 403, blocked, or empty body from web_fetch",
                "tactic": (
                    "Escalate one tier: browser_open (Playwright) if available, "
                    "else one narrow browser_use on a deep-link — never homepage-first"
                ),
                "efficiency_gain": "Avoids repeated failed fetches",
            },
            {
                "trigger": "JS-heavy page or cookie wall, little useful text from fetch",
                "tactic": "Use browser_open; dismiss cookies then browser_extract_text",
                "efficiency_gain": "Gets visible content when static fetch fails",
            },
            {
                "trigger": "Enough candidates with sources already collected",
                "tactic": "Stop extra searches; write RESEARCH_COMPLETE report",
                "efficiency_gain": "Prevents context bloat and LLM timeouts",
            },
            {
                "trigger": "Learned URL patterns exist for a host",
                "tactic": "First browser_open on that host must be a search/deep-link URL (path+params from memory, values from task); never site root first",
                "efficiency_gain": "Skips homepage form thrash and cookie walls",
            },
            {
                "trigger": "Two form click/type no-ops on same host",
                "tactic": "Stop UI clicks; one browser_open with a different search URL (query params), not another homepage; then abandon if that fails",
                "efficiency_gain": "URL-param recovery before permanent block",
            },
            {
                "trigger": "Deep-link/search URL returns 404 or empty after patterns were used",
                "tactic": "Brief homepage relearn (few actions only); update url_patterns; do not enter long form loops",
                "efficiency_gain": "Recovers from stale patterns without wasting the session",
            },
            {
                "trigger": "Adding a candidate to the shortlist",
                "tactic": "Always include constraints_check (matched/unmatched/unknown from task hard requirements) so partial matches are explicit",
                "efficiency_gain": "Prevents silent junk shortlist entries",
            },
            {
                "trigger": "After browser_open, final URL query params differ structurally from requested (e.g. date/pax filters rewritten by the site)",
                "tactic": (
                    "Do not reopen the same URL. If the page still shows names+prices, "
                    "shortlist with match_status=partial and honest unmatched/unknown; "
                    "only leave the host when the page is empty of candidates"
                ),
                "efficiency_gain": "Keeps partial deals instead of abandoning a useful list page",
            },
            {
                "trigger": "Param warning: small integer request became a date-like final value",
                "tactic": (
                    "That query key is not occupancy/count — stop sending party size there; "
                    "set travelers via visible UI controls or a different param from patterns"
                ),
                "efficiency_gain": "Avoids repeating the same broken deep-link encoding",
            },
            {
                "trigger": "Phase-1 shortlist is empty after primary sources were tried",
                "tactic": "Skip broad verification phase; document limitations and synthesize",
                "efficiency_gain": "Avoids a second discovery loop with no candidates",
            },
            {
                "trigger": "browser_use timed out or returned error on a host",
                "tactic": (
                    "Do not retry browser_use on that host this session; "
                    "web_fetch any known detail URLs, try another primary source, or RESEARCH_COMPLETE"
                ),
                "efficiency_gain": "Prevents 3+ minute repeated timeouts with zero yield",
            },
            {
                "trigger": "Need Browser Use (tier 3) after cheaper tools failed",
                "tactic": (
                    "One narrow instruction only: list visible packages OR open one detail page — "
                    "never filter+list+detail in one call; always pass a deep-link start_url"
                ),
                "efficiency_gain": "Raises success rate and keeps sessions under timeout",
            },
            {
                "trigger": "Global site recipe exists for a host (preferred_channel set)",
                "tactic": (
                    "Use that channel first on every task that hits this host — "
                    "do not rediscover from the homepage"
                ),
                "efficiency_gain": "Cross-task reuse of transport knowledge",
            },
            {
                "trigger": "Host marked human_setup_needed",
                "tactic": (
                    "Skip expensive browser loops; document limitation; "
                    "operator may add API/deep-link to memory later"
                ),
                "efficiency_gain": "Stops burning compute on structurally blocked hosts",
            },
            {
                "trigger": "All automated tiers failed on a host",
                "tactic": (
                    "Mark host exhausted for this session; move to next source; "
                    "learnings are saved globally for the next task"
                ),
                "efficiency_gain": "Fail fast and improve the system over runs",
            },
            {
                "trigger": "Repeated browser_open with 0 results / no price signals on a host",
                "tactic": (
                    "After one empty page, retry once with fewer filters; "
                    "if still empty, abandon host for this session"
                ),
                "efficiency_gain": "Stops inventory thrashing that burns Ollama context",
            },
            {
                "trigger": "Run kind is recon (learning)",
                "tactic": (
                    "Never call add_to_shortlist; never rank task candidates. "
                    "Optimize for interface learning (navigation + semantics + harvest probes), "
                    "not for finishing a user booking. RESEARCH_COMPLETE = mechanism summary only"
                ),
                "efficiency_gain": "Keeps learning runs out of research deliverables",
            },
            {
                "trigger": "Recon: learn a host interface",
                "tactic": (
                    "Run small probes (one dimension at a time when possible): "
                    "destination/date/pax/filter → compare final URL; note ignored/rewritten params; "
                    "confirm results list shows names+prices. Stop at list/detail — never checkout"
                ),
                "efficiency_gain": "Builds reusable capability model instead of one-off trajectories",
            },
            {
                "trigger": "Research: known recipe structurally fails (param rewrite, ignored filter, empty after valid deep-link)",
                "tactic": (
                    "Do not rediscover from homepage thrash. Note needs_recon for that host, "
                    "document limitation, move to next primary source. Full recon is a separate run"
                ),
                "efficiency_gain": "Protects research budget; improves next recon pass",
            },
            {
                "trigger": "Recon capability incomplete (navigation ok, semantics or harvest weak)",
                "tactic": (
                    "Prefer more probes on missing layer only — do not re-solve navigation. "
                    "Harvest: open one results page and note where prices/names appear"
                ),
                "efficiency_gain": "Fills the gap that caused weak research yields",
            },
        ]
        by_trigger = {
            str(s.get("trigger") or ""): s for s in existing if s.get("trigger")
        }
        changed = False
        for s in seeds:
            t = str(s.get("trigger") or "")
            if not t:
                continue
            if t not in by_trigger:
                existing.append(s)
                by_trigger[t] = s
                changed = True
            else:
                # Refresh tactic text when seeds evolve (soft mismatch, etc.)
                old = by_trigger[t]
                if old.get("tactic") != s.get("tactic"):
                    old["tactic"] = s["tactic"]
                    if s.get("efficiency_gain"):
                        old["efficiency_gain"] = s["efficiency_gain"]
                    changed = True
        if changed or not existing:
            self.save_strategies(existing if existing else seeds)
