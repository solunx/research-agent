"""
Persistent learnings: site tactics + general strategies + URL patterns + event log.

Phase goal: agent becomes more efficient over runs without hardcoding domains.
Files (under memory_dir):
  site_tactics.json       – per-domain preferred tool
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
        self.events_path = self.root / "events.jsonl"

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
        domain = _domain(url or "")
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
        domain = _domain(url)
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
        entry["last_verified"] = _now()
        patterns[domain] = entry
        self.save_url_patterns(patterns)

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
                stale = ""
                try:
                    if verified:
                        vt = datetime.fromisoformat(verified.replace("Z", "+00:00"))
                        if vt < cutoff:
                            stale = " [stale—consider retesting cheaper method]"
                except Exception:
                    pass
                lines.append(f"- {domain}: prefer `{pref}` ({reason}){stale}")

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
                lines.append(
                    f"- {domain}: paths=[{paths}] params=[{params}] "
                    f"(hits={info.get('success_count', 0)})"
                )
                for ex in (info.get("example_urls") or [])[:1]:
                    lines.append(f"  e.g. {ex}")

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
                "successful escalations are saved automatically.)"
            )
        return "\n".join(lines)

    def ensure_seed_strategies(self) -> None:
        """Install / merge generic strategies (idempotent on trigger text)."""
        existing = self.load_strategies()
        seeds = [
            {
                "trigger": "HTTP 403, blocked, or empty body from web_fetch",
                "tactic": "Retry same URL with browser_open",
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
        ]
        by_trigger = {
            str(s.get("trigger") or ""): s for s in existing if s.get("trigger")
        }
        for s in seeds:
            t = str(s.get("trigger") or "")
            if t and t not in by_trigger:
                existing.append(s)
        if existing != self.load_strategies():
            self.save_strategies(existing)
        elif not existing:
            self.save_strategies(seeds)
