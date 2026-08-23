"""
Thin Web Policy layer — gate before web_fetch / browser / search-driven fetches.

Principles (lean, not a compliance framework):
- Honest automation (no stealth); sites may refuse — that is a capability signal.
- CAPTCHA / hard anti-bot → stop host (no bypass).
- Rolling per-domain budgets across runs.
- Optional blocked / manual_only flags in memory/domain_policy.json.

Does not parse full robots.txt in v1; operators can mark hosts manual_only.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Generic bot-wall / challenge signals (language-light + common product names)
_BOT_WALL_RE = re.compile(
    r"(?:\bcaptcha\b|\brecaptcha\b|\bhcaptcha\b|\bturnstile\b|"
    r"cf-browser-verification|challenge-platform|attention required|"
    r"access denied|permission denied|bot detection|automated (?:traffic|access)|"
    r"verify you are human|are you a robot|security check)",
    re.I,
)

_DEFAULT_POLICY = {
    "version": 1,
    "hosts": {},
    "defaults": {
        "requests_per_hour": 40,
        "browser_actions_per_hour": 24,
        "cooldown_seconds_after_block": 1800,
    },
}


def _now_ts() -> float:
    return time.time()


def _host_key(url_or_host: str) -> str:
    s = (url_or_host or "").strip().lower()
    if not s:
        return ""
    if "://" not in s:
        host = s.split("/")[0]
    else:
        host = urlparse(s).hostname or ""
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def policy_path(memory_dir: Path | str) -> Path:
    return Path(memory_dir) / "domain_policy.json"


def load_policy(memory_dir: Path | str) -> dict[str, Any]:
    path = policy_path(memory_dir)
    if not path.exists():
        return json.loads(json.dumps(_DEFAULT_POLICY))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return json.loads(json.dumps(_DEFAULT_POLICY))
        data.setdefault("hosts", {})
        data.setdefault("defaults", dict(_DEFAULT_POLICY["defaults"]))
        return data
    except Exception:
        return json.loads(json.dumps(_DEFAULT_POLICY))


def save_policy(memory_dir: Path | str, data: dict[str, Any]) -> None:
    path = policy_path(memory_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _host_entry(policy: dict[str, Any], host: str) -> dict[str, Any]:
    hosts = policy.setdefault("hosts", {})
    if host not in hosts or not isinstance(hosts[host], dict):
        hosts[host] = {
            "status": "allowed",  # allowed | limited | blocked | manual_only
            "request_log": [],  # timestamps of requests
            "browser_log": [],
            "cooldown_until": 0.0,
            "last_block_reason": "",
        }
    return hosts[host]


def _prune_log(log: list[Any], window_s: float = 3600.0) -> list[float]:
    cutoff = _now_ts() - window_s
    out: list[float] = []
    for t in log:
        try:
            ft = float(t)
        except (TypeError, ValueError):
            continue
        if ft >= cutoff:
            out.append(ft)
    return out


def detect_bot_wall(text: str = "", title: str = "", error: str = "") -> str | None:
    """Return a short reason if page/error looks like CAPTCHA or hard anti-bot."""
    blob = f"{title or ''}\n{text or ''}\n{error or ''}"
    if not blob.strip():
        return None
    # Only scan a prefix — full pages are huge
    sample = blob[:8000]
    if _BOT_WALL_RE.search(sample):
        return "bot_wall_or_captcha_signal"
    return None


def check_access(
    memory_dir: Path | str,
    url: str,
    *,
    kind: str = "request",  # request | browser
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Decide whether a web action may proceed.
    Returns {ok, host, reason, status, retry_after_s?}.
    """
    host = _host_key(url)
    if not host:
        return {"ok": False, "host": "", "reason": "empty_host", "status": "blocked"}

    policy = load_policy(memory_dir)
    defaults = policy.get("defaults") or _DEFAULT_POLICY["defaults"]
    cfg = (config or {}).get("web_policy") or {}
    req_limit = int(cfg.get("requests_per_hour", defaults.get("requests_per_hour", 40)))
    br_limit = int(
        cfg.get("browser_actions_per_hour", defaults.get("browser_actions_per_hour", 24))
    )

    entry = _host_entry(policy, host)
    status = str(entry.get("status") or "allowed").lower()

    if status in ("blocked", "manual_only"):
        return {
            "ok": False,
            "host": host,
            "reason": f"host_status={status}",
            "status": status,
            "last_block_reason": entry.get("last_block_reason") or "",
        }

    now = _now_ts()
    cooldown_until = float(entry.get("cooldown_until") or 0)
    if cooldown_until > now:
        return {
            "ok": False,
            "host": host,
            "reason": "cooldown",
            "status": "limited",
            "retry_after_s": int(cooldown_until - now),
            "last_block_reason": entry.get("last_block_reason") or "",
        }

    entry["request_log"] = _prune_log(list(entry.get("request_log") or []))
    entry["browser_log"] = _prune_log(list(entry.get("browser_log") or []))

    if kind == "browser":
        if len(entry["browser_log"]) >= br_limit:
            return {
                "ok": False,
                "host": host,
                "reason": "browser_rate_limit",
                "status": "limited",
                "retry_after_s": 600,
            }
    else:
        if len(entry["request_log"]) >= req_limit:
            return {
                "ok": False,
                "host": host,
                "reason": "request_rate_limit",
                "status": "limited",
                "retry_after_s": 600,
            }

    return {"ok": True, "host": host, "reason": "", "status": status}


def record_access(
    memory_dir: Path | str,
    url: str,
    *,
    kind: str = "request",
) -> None:
    host = _host_key(url)
    if not host:
        return
    policy = load_policy(memory_dir)
    entry = _host_entry(policy, host)
    now = _now_ts()
    entry["request_log"] = _prune_log(list(entry.get("request_log") or []))
    entry["browser_log"] = _prune_log(list(entry.get("browser_log") or []))
    entry["request_log"].append(now)
    if kind == "browser":
        entry["browser_log"].append(now)
    save_policy(memory_dir, policy)


def record_block(
    memory_dir: Path | str,
    url: str,
    reason: str,
    *,
    hard: bool = False,
    config: dict[str, Any] | None = None,
) -> None:
    """Cooldown cooldown after 403/429/CAPTCHA; hard=True → status blocked until cleared."""
    host = _host_key(url)
    if not host:
        return
    policy = load_policy(memory_dir)
    defaults = policy.get("defaults") or _DEFAULT_POLICY["defaults"]
    cfg = (config or {}).get("web_policy") or {}
    cooldown = int(
        cfg.get(
            "cooldown_seconds_after_block",
            defaults.get("cooldown_seconds_after_block", 1800),
        )
    )
    entry = _host_entry(policy, host)
    entry["last_block_reason"] = (reason or "")[:300]
    entry["cooldown_until"] = _now_ts() + max(60, cooldown)
    if hard:
        entry["status"] = "blocked"
    elif entry.get("status") == "allowed":
        entry["status"] = "limited"
    save_policy(memory_dir, policy)


def apply_result_signals(
    memory_dir: Path | str,
    url: str,
    result: dict[str, Any] | None,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Inspect tool result: CAPTCHA / 403 / 429 → cooldown.
    Mutates nothing about the page content; returns flags for the agent.
    """
    if not isinstance(result, dict):
        return {"blocked_by_policy": False}
    text = str(result.get("text") or "")
    title = str(result.get("title") or "")
    err = str(result.get("error") or "")
    status_code = result.get("status_code")

    wall = detect_bot_wall(text=text, title=title, error=err)
    if wall:
        record_block(memory_dir, url, wall, hard=False, config=config)
        result = dict(result)
        result["policy_stop"] = True
        result["policy_reason"] = wall
        result["blocked"] = True
        return {"blocked_by_policy": True, "reason": wall, "result": result}

    if status_code in (401, 403, 429) or result.get("blocked"):
        reason = f"http_{status_code}" if status_code else "blocked_flag"
        record_block(memory_dir, url, reason, hard=False, config=config)
        return {"blocked_by_policy": True, "reason": reason, "result": result}

    return {"blocked_by_policy": False, "result": result}
