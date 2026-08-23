"""
Inline recon skeleton — separate process from retrieval.

When retrieval hits a structural failure (needs_recon), the control plane may:
  1. Pause further UI on that host in the retrieval session
  2. Run a short learning-only burst (this module)
  3. Write only to global memory (recipes / url patterns / param warnings)
  4. Never touch shortlist / report candidates
  5. Optionally retry the host once in retrieval with refreshed memory

The retrieval LLM must NOT see recon transcripts — only summarized memory
after this module returns.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from memory_store import MemoryStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _host(url: str) -> str:
    try:
        h = (urlparse(url).hostname or "").lower()
        if h.startswith("www."):
            h = h[4:]
        return h
    except Exception:
        return ""


def build_probe_urls(host: str, memory: MemoryStore, max_urls: int = 3) -> list[str]:
    """
    Build a few relaxed probe deep-links from stored patterns.
    Uses broad/simple values so a results surface is likely (learning inventory).
    No task-specific hardcoding — values are structural placeholders.
    """
    recipes = memory.load_recipes()
    patterns = memory.load_url_patterns() if hasattr(memory, "load_url_patterns") else {}
    entry = recipes.get(host) or {}
    pat = patterns.get(host) or {}

    examples = list(pat.get("example_urls") or [])[:5]
    path_hints = list(
        (entry.get("navigation") or {}).get("path_hints")
        or pat.get("path_hints")
        or []
    )
    param_names = list(pat.get("param_names") or [])

    urls: list[str] = []
    for ex in examples:
        if not isinstance(ex, str) or "…" in ex or "..." in ex:
            continue
        urls.append(ex)
        if len(urls) >= max_urls:
            return urls

    # Synthesize minimal probes from path + known param names with relaxed placeholders
    scheme_netloc = f"https://www.{host}" if not host.startswith("http") else host
    if "://" not in scheme_netloc:
        scheme_netloc = f"https://{host}"
    base = scheme_netloc.rstrip("/")
    for path in path_hints[:2]:
        if not path.startswith("/"):
            path = "/" + path
        # Prefer empty/minimal query — recon goal is structure, not task filters
        relaxed_params: dict[str, str] = {}
        for p in param_names:
            pl = p.lower()
            if "adult" in pl or p.endswith("[1]") and "participant" in pl.lower():
                relaxed_params[p] = "2"
            elif "child" in pl:
                relaxed_params[p] = "0"
            elif "room" in pl:
                relaxed_params[p] = "1"
            # Skip date/meal — recon discovers encoding; wrong dates are OK for learning
        q = urlencode(relaxed_params, doseq=True) if relaxed_params else ""
        urls.append(f"{base}{path}" + (f"?{q}" if q else ""))
        if len(urls) >= max_urls:
            break

    if not urls and path_hints:
        p = path_hints[0]
        if not p.startswith("/"):
            p = "/" + p
        urls.append(f"{base}{p}")

    return urls[:max_urls]


def run_inline_recon_burst(
    *,
    host: str,
    memory: MemoryStore,
    browser_open_fn,
    max_probes: int = 2,
    session_label: str = "inline_recon",
) -> dict[str, Any]:
    """
    Learning-only burst for one host. Side effects:
    - memory recipes / url patterns / needs_recon flag
    - NO shortlist, NO task report data

    browser_open_fn(url) -> dict with url, text, price_hints, error
    """
    host = (host or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return {"ok": False, "error": "no host"}

    probes = build_probe_urls(host, memory, max_urls=max_probes)
    results: list[dict[str, Any]] = []
    learned: list[str] = []

    for url in probes:
        try:
            res = browser_open_fn(url)
        except Exception as e:
            results.append({"url": url, "error": str(e)[:200]})
            continue
        if not isinstance(res, dict):
            continue
        final_url = str(res.get("url") or url)
        err = res.get("error")
        price_hints = res.get("price_hints") if isinstance(res.get("price_hints"), list) else []
        results.append(
            {
                "requested": url,
                "final": final_url,
                "error": err,
                "price_hints_n": len(price_hints),
            }
        )
        try:
            memory.record_navigation_success(final_url, channel="browser_open")
        except Exception:
            try:
                memory.touch_domain(final_url)
            except Exception:
                pass
        if price_hints and not err:
            try:
                memory.record_harvest_hint(
                    final_url,
                    hint="list/detail page yields price_hints in extract",
                    has_price_signals=True,
                )
            except Exception:
                pass
            learned.append(f"prices_visible on {final_url[:80]}")
        # Compare query rewrite (generic) — discovery ≠ resolved query state
        rewrite_keys: list[str] = []
        try:
            rq = parse_qs(urlparse(url).query)
            fq = parse_qs(urlparse(final_url).query)
            for k, vals in rq.items():
                if k in fq and fq[k] != vals:
                    detail = f"{k}: requested={vals[0][:40]} final={fq[k][0][:40]}"
                    learned.append(f"param_rewrite {detail}")
                    rewrite_keys.append(k.lower())
                    try:
                        memory.record_param_warning(
                            host,
                            param=k,
                            kind="rewritten_on_open",
                            detail=detail,
                        )
                    except Exception:
                        pass
        except Exception:
            pass
        results[-1]["rewrite_keys"] = rewrite_keys

    # Clear needs_recon ONLY when a probe has no structural rewrite on
    # date/occupancy-like keys. price_hints alone are discovery, not success.
    def _severe_rewrite(keys: list[str]) -> bool:
        for k in keys:
            if any(
                s in k
                for s in (
                    "date",
                    "depart",
                    "participant",
                    "adult",
                    "child",
                    "pax",
                    "room",
                    "person",
                )
            ):
                return True
        return False

    cleared = False
    clean_probe = any(
        not r.get("error")
        and not _severe_rewrite(list(r.get("rewrite_keys") or []))
        for r in results
    )
    if clean_probe:
        try:
            memory.clear_needs_recon(host)
            cleared = True
            learned.append("cleared_needs_recon (no severe param rewrite)")
        except Exception:
            pass
    else:
        learned.append("kept_needs_recon (rewrite or no clean probe)")

    summary = {
        "ok": True,
        "host": host,
        "session": session_label,
        "probes": len(probes),
        "results": results,
        "learned": learned[:12],
        "cleared_needs_recon": cleared,
        "ts": _now(),
        # Explicit: recon output is not retrieval evidence
        "isolation": "memory_only_no_shortlist",
    }
    memory.log_event(
        {
            "type": "inline_recon_burst",
            "domain": host,
            "probes": len(probes),
            "cleared_needs_recon": cleared,
            "learned_n": len(learned),
        }
    )
    return summary
