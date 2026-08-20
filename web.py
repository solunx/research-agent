"""
Web tools: search + fetch (Tier 1).

Escalation to browser is driven by runtime errors + memory_store tactics,
not a hardcoded list of travel brands (general research agent).
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS  # type: ignore


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


# Soft limits for search queries (generic — not domain-specific).
MAX_SEARCH_QUERY_CHARS = 120
MAX_SEARCH_QUERY_WORDS = 12


def normalize_search_query(query: str) -> tuple[str, str | None]:
    """
    Soft guardrail: keep queries keyword-like.
    Returns (query_to_use, warning_or_None).
    Does not invent domain rules — only length / sentence-shape.
    """
    q = (query or "").strip()
    if not q:
        return q, "empty query"

    words = q.split()
    warning: str | None = None

    # Sentence-like: many words or ends with punctuation typical of full questions
    looks_like_sentence = (
        len(words) > MAX_SEARCH_QUERY_WORDS
        or len(q) > MAX_SEARCH_QUERY_CHARS
        or (len(words) >= 8 and q.rstrip().endswith(("?", ".", "!")))
    )

    if looks_like_sentence:
        # Keep first N words as a crude keyword extract; agent should retry shorter next time
        shortened = " ".join(words[:MAX_SEARCH_QUERY_WORDS])
        if len(shortened) > MAX_SEARCH_QUERY_CHARS:
            shortened = shortened[:MAX_SEARCH_QUERY_CHARS].rsplit(" ", 1)[0]
        warning = (
            f"Query was long/sentence-like ({len(words)} words, {len(q)} chars). "
            f"Truncated for search engines. Prefer 2–8 keywords next time. "
            f"Used: {shortened!r}"
        )
        q = shortened

    return q, warning


def web_search(
    query: str,
    max_results: int = 8,
    region: str = "be-nl",
) -> list[dict[str, str]]:
    q, warning = normalize_search_query(query)
    if not q:
        return [
            {
                "title": "Search error",
                "url": "",
                "snippet": warning or "empty query",
            }
        ]

    results: list[dict[str, str]] = []
    try:
        with DDGS() as ddgs:
            kwargs: dict[str, Any] = {"max_results": max_results}
            try:
                raw = list(ddgs.text(q, region=region, **kwargs))
            except TypeError:
                raw = list(ddgs.text(q, max_results=max_results))

            for r in raw:
                results.append(
                    {
                        "title": r.get("title") or "",
                        "url": r.get("href") or r.get("link") or "",
                        "snippet": r.get("body") or r.get("snippet") or "",
                    }
                )
    except Exception as e:
        return [{"title": "Search error", "url": "", "snippet": str(e)}]

    if warning:
        # Prepend advisory so the LLM sees the guardrail feedback
        results.insert(
            0,
            {
                "title": "Query notice",
                "url": "",
                "snippet": warning,
            },
        )
    return results


def web_fetch(
    url: str,
    max_chars: int = 12000,
    timeout: int = 20,
    user_agent: str | None = None,
    max_retries: int = 2,
    prefer_browser_hint: bool = False,
) -> dict[str, Any]:
    """
    Fast HTTP fetch. On block/403 returns blocked=True so agent/memory can escalate.
    If prefer_browser_hint (from learned tactics), skip HTTP and tell agent to use browser.
    """
    if prefer_browser_hint:
        return {
            "url": url,
            "title": "",
            "text": "",
            "error": (
                f"Learned tactic for {_domain(url)}: prefer browser_open "
                "(previous HTTP fetches failed). Use browser_open."
            ),
            "status_code": None,
            "blocked": True,
            "prefer_browser": True,
        }

    ua = user_agent or DEFAULT_USER_AGENT
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "nl-BE,nl;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }

    last_error: str | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )
            if resp.status_code in (429, 503) and attempt < max_retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code in (401, 403):
                return {
                    "url": url,
                    "title": "",
                    "text": "",
                    "error": f"{resp.status_code} Forbidden/Unauthorized – use browser_open",
                    "status_code": resp.status_code,
                    "blocked": True,
                }
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return {
                    "url": url,
                    "title": "",
                    "text": f"[Non-text content type: {content_type}]",
                    "error": None,
                    "status_code": resp.status_code,
                    "blocked": False,
                }

            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
                tag.decompose()

            title = ""
            if soup.title and soup.title.string:
                title = soup.title.string.strip()

            text = soup.get_text(separator="\n", strip=True)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            text = "\n".join(lines)

            if len(text) > max_chars:
                text = text[:max_chars] + f"\n\n...[truncated at {max_chars} chars]"

            # <400 chars is usually a cookie wall, anti-bot shell, or empty shell page
            blocked = len(text) < 400
            return {
                "url": url,
                "title": title,
                "text": text,
                "error": (
                    "Page text very short – consider browser_open"
                    if blocked
                    else None
                ),
                "status_code": resp.status_code,
                "blocked": blocked,
            }
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries:
                time.sleep(1.0 * (attempt + 1))
                continue

    return {
        "url": url,
        "title": "",
        "text": "",
        "error": last_error,
        "status_code": None,
        "blocked": False,
    }
