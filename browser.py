"""
Tier 3 – Playwright browser tools.

Used when HTTP fetch is blocked (403) or pages are JS-heavy
(package sites, booking platforms, …).

Design goals:
- Navigate and read real prices up to (but not past) checkout.
- Return enough page text after each action so the LLM can decide next step.
- Cookie walls handled aggressively but generically (no brand-specific logic).
"""

from __future__ import annotations

import atexit
import re
import time
from typing import Any

_browser = None
_context = None
_page = None
_playwright = None

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Playwright raises this when navigation (goto/click) starts a file download
# instead of loading a document (live 05: OPEN_URL /pdf/… → "Download is starting").
_DOWNLOAD_NAV_RE = re.compile(r"download is starting", re.I)
# Open #24b Fase 2 plumbing: keep raw DOM next to innerText. Cap avoids
# unbounded trace files; extraction reads this string, not a live handle.
_HTML_SNAP_CAP = 400_000
# Non-content blocks must be stripped *before* the cap is applied.
# Coolblue 110505Z: html_chars=699128, first 200k still in <style> inside
# <head> — body product cards never reached extract_candidates.
_NONCONTENT_BLOCK_RE = re.compile(
    r"<(script|style|noscript|svg)\b[^>]*>.*?</\1>",
    re.I | re.S,
)
_DANGLING_NONCONTENT_RE = re.compile(
    r"<(script|style|noscript|svg)\b[^>]*$",
    re.I,
)
_BODY_INNER_RE = re.compile(r"<body\b[^>]*>(.*)</body>", re.I | re.S)

# Generic consent buttons (NL/FR/EN – common CMP patterns)
COOKIE_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "#accept-recommended-btn-handler",
    "button#onetrust-accept-btn-handler",
    "button[data-testid='uc-accept-all-button']",
    "button[aria-label*='Accept' i]",
    "button[aria-label*='Akkoord' i]",
    "button[aria-label*='Accepter' i]",
    "button:has-text('Accept all')",
    "button:has-text('Accept All')",
    "button:has-text('Alles accepteren')",
    "button:has-text('Alles toestaan')",
    "button:has-text('Alle cookies accepteren')",
    "button:has-text('Accepteer alle cookies')",
    "button:has-text('Accepteer')",
    "button:has-text('Akkoord')",
    "button:has-text('Ik ga akkoord')",
    "button:has-text('Accepteren')",
    "button:has-text('Tout accepter')",
    "button:has-text('Accepter tout')",
    "button:has-text('J\\'accepte')",
    "button:has-text('Agree')",
    "button:has-text('I agree')",
    "button:has-text('Allow all')",
    "button:has-text('Toestaan')",
    "button:has-text('OK')",
    "[id*='cookie' i] button:has-text('Accept')",
    "[class*='cookie' i] button:has-text('Accept')",
    ".cookie-accept",
    "#cookie-accept",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept",
]


def _ensure_browser(headless: bool = True, user_agent: str | None = None):
    global _playwright, _browser, _context, _page
    if _page is not None:
        return _page

    from playwright.sync_api import sync_playwright

    _playwright = sync_playwright().start()
    # Honest automation: no anti-detect / stealth scripts.
    # Sites that refuse bots surface as capability boundaries (needs_recon / policy stop).
    _browser = _playwright.chromium.launch(
        headless=headless,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--window-size=1280,900",
        ],
    )
    _context = _browser.new_context(
        user_agent=user_agent or DEFAULT_UA,
        viewport={"width": 1280, "height": 900},
        locale="nl-BE",
        timezone_id="Europe/Brussels",
        java_script_enabled=True,
        ignore_https_errors=True,
        extra_http_headers={
            "Accept-Language": "nl-BE,nl;q=0.9,fr-BE;q=0.8,en-US;q=0.7,en;q=0.6",
            "DNT": "1",
        },
    )
    _page = _context.new_page()
    _page.set_default_timeout(45000)
    atexit.register(_shutdown)
    return _page


def _shutdown():
    global _playwright, _browser, _context, _page
    try:
        if _context:
            _context.close()
        if _browser:
            _browser.close()
        if _playwright:
            _playwright.stop()
    except Exception:
        pass
    _page = _context = _browser = _playwright = None


def _dismiss_cookies(page, rounds: int = 3) -> int:
    """Try multiple times; some CMPs reappear after navigation."""
    dismissed = 0
    for _ in range(rounds):
        hit = False
        for sel in COOKIE_SELECTORS:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=400):
                    btn.click(timeout=1500)
                    time.sleep(0.35)
                    dismissed += 1
                    hit = True
                    break
            except Exception:
                continue
        if not hit:
            break
        time.sleep(0.3)
    return dismissed


def _page_text(page, max_chars: int = 12000) -> tuple[str, str]:
    title = page.title() or ""
    try:
        text = page.inner_text("body") or ""
    except Exception:
        text = ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n...[truncated at {max_chars} chars]"
    return title, text


def _price_hints(text: str, limit: int = 15) -> list[str]:
    """Pull lines that look like prices so the agent notices them quickly."""
    if not text:
        return []
    patterns = [
        re.compile(r"(?i)(€|eur|euro)\s?\d"),
        re.compile(r"(?i)\d[\d\s.,]{2,}\s?(€|eur)"),
        re.compile(r"(?i)(vanaf|from|dès|ab|per persoon|p\.?p\.?|pp\b).{0,20}\d"),
        re.compile(r"(?i)(total|totaal|prix|price).{0,30}\d"),
    ]
    hints: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        s = line.strip()
        if len(s) < 4 or len(s) > 180:
            continue
        if any(p.search(s) for p in patterns):
            key = s.lower()
            if key not in seen:
                seen.add(key)
                hints.append(s)
            if len(hints) >= limit:
                break
    return hints


# Generic challenge / bot-wall signals (no bypass — agent must stop)
_BOT_WALL_RE = re.compile(
    r"(?:\bcaptcha\b|\brecaptcha\b|\bhcaptcha\b|\bturnstile\b|"
    r"cf-browser-verification|challenge-platform|attention required|"
    r"access denied|verify you are human|are you a robot|security check|"
    r"automated (?:traffic|access)|bot detection)",
    re.I,
)


def prepare_html_for_snapshot(html: str, *, cap: int = _HTML_SNAP_CAP) -> str:
    """Drop non-content tags, then keep <body>, *then* apply the char cap.

    Counting the cap on raw page.content() cut Coolblue search pages inside
    a giant <head> stylesheet (110505Z html_chars=699128). Script/style/svg/
    noscript and head chrome are not candidate structure.
    """
    if not html:
        return ""
    stripped = _NONCONTENT_BLOCK_RE.sub("", html)
    stripped = _DANGLING_NONCONTENT_RE.sub("", stripped)
    body = _BODY_INNER_RE.search(stripped)
    if body:
        stripped = "<html><body>" + body.group(1) + "</body></html>"
    if cap and len(stripped) > cap:
        stripped = stripped[: cap]
    return stripped


def _snapshot(
    page,
    max_chars: int = 12000,
    include_hints: bool = True,
) -> dict[str, Any]:
    title, text = _page_text(page, max_chars=max_chars)
    html = ""
    try:
        html = str(page.content() or "")
    except Exception:
        html = ""
    html_chars = len(html)
    html = prepare_html_for_snapshot(html, cap=_HTML_SNAP_CAP)
    out: dict[str, Any] = {
        "url": page.url,
        "title": title,
        "text": text,
        "html": html,
        "html_chars": html_chars,
        "html_prepared_chars": len(html),
        "error": None,
    }
    if include_hints:
        hints = _price_hints(text)
        if hints:
            out["price_hints"] = hints
    # Flag only — never solve or retry around challenges
    sample = f"{title}\n{text}"[:6000]
    if _BOT_WALL_RE.search(sample):
        out["policy_stop"] = True
        out["policy_reason"] = "bot_wall_or_captcha_signal"
        out["blocked"] = True
    return out


def _is_download_navigation_error(exc: BaseException | str | None) -> bool:
    """True when Playwright aborted a navigation because a download started.

    Structural: matches the engine message, not URL path or file type.
    Live citation (`111714Z`): `Page.goto: Download is starting`.
    """
    return bool(_DOWNLOAD_NAV_RE.search(str(exc or "")))


def _download_kept_page_snapshot(
    page,
    *,
    requested_url: str = "",
    download_meta: dict[str, str] | None = None,
    max_chars: int = 15000,
) -> dict[str, Any]:
    """Stay on the current document after a download-navigation.

    Does not parse the downloaded bytes (that is a later capability).
    """
    meta = download_meta or {}
    try:
        snap = _snapshot(page, max_chars=max_chars)
    except Exception:
        snap = {
            "url": "",
            "title": "",
            "text": "",
            "error": None,
        }
        try:
            snap["url"] = str(page.url or "")
        except Exception:
            pass
    snap["error"] = None
    snap["download"] = True
    snap["download_filename"] = str(meta.get("filename") or "")[:200]
    snap["download_url"] = str(meta.get("url") or requested_url or "")[:400]
    snap["cookies_dismissed"] = int(snap.get("cookies_dismissed") or 0)
    return snap


def _run_keeping_download(page, fn, *, requested_url: str = "", max_chars: int = 15000):
    """Run a Playwright navigation/click. If it starts a download, return a
    stay-on-page snapshot; otherwise return None so the caller continues."""
    held: dict[str, str] = {}
    alive = True

    def _on_download(download) -> None:
        nonlocal alive
        if not alive:
            return
        held["filename"] = str(getattr(download, "suggested_filename", "") or "")
        held["url"] = str(getattr(download, "url", "") or requested_url)
        try:
            download.cancel()
        except Exception:
            pass

    page.on("download", _on_download)
    try:
        fn()
    except Exception as e:
        if held or _is_download_navigation_error(e):
            return _download_kept_page_snapshot(
                page,
                requested_url=requested_url or held.get("url") or "",
                download_meta=held,
                max_chars=max_chars,
            )
        raise
    finally:
        alive = False
    if held:
        return _download_kept_page_snapshot(
            page,
            requested_url=requested_url or held.get("url") or "",
            download_meta=held,
            max_chars=max_chars,
        )
    return None


def _resolve_navigation_url(url: str, *, base_url: str | None = None) -> str:
    """
    Resolve relative hrefs against the current page (or explicit base).

    Absolute URLs (scheme + netloc) pass through unchanged. Relative paths
    (e.g. "/egypte/.../tab=price-calculation") and scheme-relative //host
    paths are joined with urllib.parse.urljoin — no site-specific logic.
    """
    from urllib.parse import urljoin, urlparse

    u = (url or "").strip()
    if not u:
        return u
    parsed = urlparse(u)
    # Absolute http(s) (or other schemes with netloc)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return u
    if parsed.scheme and parsed.netloc:
        return u
    base = (base_url or "").strip() or None
    if not base and _page is not None:
        try:
            base = str(_page.url or "") or None
        except Exception:
            base = None
    if base:
        return urljoin(base, u)
    return u


def browser_open(
    url: str,
    wait_seconds: float = 3.0,
    headless: bool = True,
    user_agent: str | None = None,
    max_chars: int = 15000,
) -> dict[str, Any]:
    """Navigate to URL, dismiss cookies, return visible text + price hints."""
    try:
        page = _ensure_browser(headless=headless, user_agent=user_agent)
        resolved = _resolve_navigation_url(url)
        kept = _run_keeping_download(
            page,
            lambda: page.goto(resolved, wait_until="domcontentloaded", timeout=60000),
            requested_url=resolved,
            max_chars=max_chars,
        )
        if kept is not None:
            return kept
        time.sleep(max(0.4, float(wait_seconds)))
        n = _dismiss_cookies(page)
        time.sleep(0.5)
        # Prefer load first — booking sites often never reach networkidle (analytics).
        try:
            page.wait_for_load_state("load", timeout=15000)
        except Exception:
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        # Second pass – some sites show CMP after load
        n += _dismiss_cookies(page, rounds=2)
        snap = _snapshot(page, max_chars=max_chars)
        snap["cookies_dismissed"] = n
        return snap
    except Exception as e:
        return {
            "url": url,
            "title": "",
            "text": "",
            "error": str(e),
            "cookies_dismissed": 0,
        }


def browser_extract_text(max_chars: int = 15000) -> dict[str, Any]:
    """Extract text (+ price hints) from the current page."""
    try:
        page = _ensure_browser()
        _dismiss_cookies(page, rounds=1)
        return _snapshot(page, max_chars=max_chars)
    except Exception as e:
        return {"url": "", "title": "", "text": "", "error": str(e)}


def browser_dismiss_cookies() -> dict[str, Any]:
    """Explicitly try to dismiss cookie/consent banners on the current page."""
    try:
        page = _ensure_browser()
        n = _dismiss_cookies(page, rounds=4)
        time.sleep(0.5)
        snap = _snapshot(page, max_chars=8000)
        snap["ok"] = True
        snap["cookies_dismissed"] = n
        return snap
    except Exception as e:
        return {"ok": False, "error": str(e), "cookies_dismissed": 0}


def _hide_consent_overlays(page) -> int:
    """Best-effort hide common consent iframes/overlays that intercept pointer events."""
    js = """
    () => {
      let n = 0;
      const hide = (el) => { try { el.style.setProperty('display','none','important'); n++; } catch(e) {} };
      document.querySelectorAll(
        'iframe#consent_iframe, iframe[id*="consent" i], iframe[src*="consent" i], ' +
        '[id*="cookie" i][class*="overlay" i], [class*="cookie-banner" i], ' +
        '[id*="onetrust" i], [class*="onetrust" i], #didomi-popup, .qc-cmp2-container'
      ).forEach(hide);
      return n;
    }
    """
    try:
        return int(page.evaluate(js) or 0)
    except Exception:
        return 0


def overlay_intercept_retry_should_run(err: str | None) -> bool:
    """Same intercept gate browser_click already used before hide+force-retry.

    #31 (ARIA, second fingerprint) is a later net; this is the per-action
    first-line. Coolblue Zoeken Timeout is True here and False for #31.
    """
    err_s = str(err or "")
    return (
        "intercepts pointer" in err_s
        or "consent_iframe" in err_s
        or "Timeout" in err_s
    )


def _hide_overlays_and_force_click(page, locator, *, timeout_ms: int = 8000) -> tuple[bool, int, str]:
    """Hide consent iframes, then force-click. Shared by click and type."""
    hidden = _hide_consent_overlays(page)
    _dismiss_cookies(page, rounds=2)
    try:
        locator.click(timeout=timeout_ms, force=True)
        return True, hidden, ""
    except Exception as e2:
        return False, hidden, str(e2)


def browser_click(selector: str, max_chars: int = 10000) -> dict[str, Any]:
    """
    Click an element (CSS or Playwright text selector, e.g. button:has-text('Zoeken')).
    Returns updated page text so you can see prices / next form step.
    """
    try:
        page = _ensure_browser()
        _dismiss_cookies(page, rounds=2)
        try:
            kept = _run_keeping_download(
                page,
                lambda: page.locator(selector).first.click(timeout=15000),
                requested_url=str(page.url or ""),
                max_chars=max_chars,
            )
            if kept is not None:
                kept["ok"] = len(str(kept.get("text") or "")) > 40
                return kept
        except Exception as click_err:
            # Pointer intercepted by consent iframe / overlay → hide and retry once
            if overlay_intercept_retry_should_run(str(click_err)):
                ok_retry, hidden, err2 = _hide_overlays_and_force_click(
                    page, page.locator(selector).first
                )
                if not ok_retry:
                    return {
                        "ok": False,
                        "url": page.url if page else "",
                        "title": "",
                        "text": "",
                        "error": err2,
                        "pointer_intercept": True,
                        "overlays_hidden": hidden,
                        "no_op_exempt": True,  # runtime may skip no-op strike
                    }
            else:
                raise
        time.sleep(1.5)
        _dismiss_cookies(page, rounds=2)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        time.sleep(0.6)
        snap = _snapshot(page, max_chars=max_chars)
        snap["ok"] = True
        return snap
    except Exception as e:
        return {"ok": False, "url": "", "title": "", "text": "", "error": str(e)}


def browser_current_url() -> str:
    try:
        page = _ensure_browser()
        return str(page.url or "")
    except Exception:
        return ""


def browser_list_blocking_overlays() -> list[dict[str, Any]]:
    """Visible role=dialog / aria-modal overlays. No cookie/consent selectors."""
    js = """
    () => {
      const nodes = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"]'));
      const out = [];
      for (const el of nodes) {
        const st = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        if (st.display === 'none' || st.visibility === 'hidden') continue;
        if (r.width < 8 || r.height < 8) continue;
        const btns = [];
        el.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"]').forEach((b) => {
          const bs = getComputedStyle(b);
          const br = b.getBoundingClientRect();
          if (bs.display === 'none' || br.width < 2 || br.height < 2) return;
          btns.push({
            text: ((b.innerText || b.getAttribute('aria-label') || '') + '').trim().slice(0, 80)
          });
        });
        out.push({
          role: (el.getAttribute('role') || ''),
          aria_modal: (el.getAttribute('aria-modal') || ''),
          id: el.id || '',
          buttons: btns,
          n_iframes: el.querySelectorAll('iframe').length
        });
      }
      return out;
    }
    """
    try:
        page = _ensure_browser()
        raw = page.evaluate(js) or []
        return list(raw) if isinstance(raw, list) else []
    except Exception:
        return []


def browser_dismiss_blocking_overlay() -> dict[str, Any]:
    """Open #31: first DOM button inside a blocking dialog, else hide the dialog.

    Not COOKIE_SELECTORS. Not shortest-text. Cross-origin iframe → hide.
    """
    from overlay_dismiss import pick_overlay_dismiss

    try:
        page = _ensure_browser()
    except Exception as e:
        return {"ok": False, "attempted": False, "reason": str(e)}
    overlays = browser_list_blocking_overlays()
    plan = pick_overlay_dismiss(overlays)
    if not plan:
        return {"ok": False, "attempted": False, "reason": "no_overlay", "n_overlays": 0}
    method = str(plan.get("method") or "")
    if method == "first_button":
        try:
            loc = (
                page.locator('[role="dialog"], [aria-modal="true"]')
                .first.locator(
                    'button, [role="button"], input[type="button"], input[type="submit"]'
                )
                .first
            )
            loc.click(timeout=3000)
            time.sleep(0.35)
            return {
                "ok": True,
                "attempted": True,
                "method": "first_button",
                "n_overlays": len(overlays),
                "first_button_text": plan.get("first_button_text") or "",
                "overlay_id": plan.get("overlay_id") or "",
            }
        except Exception as e:
            method = "hide_blocking_dialog"
            plan["click_error"] = str(e)[:200]
    if method == "hide_blocking_dialog":
        n = 0
        try:
            n = int(
                page.evaluate(
                    """
                    () => {
                      let n = 0;
                      document.querySelectorAll('[role="dialog"], [aria-modal="true"]').forEach((el) => {
                        const st = getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        if (st.display === 'none' || r.width < 8) return;
                        el.style.setProperty('display', 'none', 'important');
                        n++;
                      });
                      return n;
                    }
                    """
                )
                or 0
            )
        except Exception as e:
            return {
                "ok": False,
                "attempted": True,
                "method": "hide_blocking_dialog",
                "reason": str(e)[:200],
                "n_overlays": len(overlays),
            }
        return {
            "ok": n > 0,
            "attempted": True,
            "method": "hide_blocking_dialog",
            "n": n,
            "n_overlays": len(overlays),
            "overlay_id": plan.get("overlay_id") or "",
            "first_button_text": "",
        }
    return {"ok": False, "attempted": False, "reason": "no_plan", "n_overlays": len(overlays)}


def browser_type(
    selector: str,
    text: str,
    press_enter: bool = False,
    max_chars: int = 8000,
) -> dict[str, Any]:
    """Type into an input; optionally press Enter. Returns page snapshot.

    Click/focus on the field uses the same overlay hide+force-retry as
    browser_click (Open #31 type/click symmetry). Fill itself is unchanged.
    """
    try:
        page = _ensure_browser()
        loc = page.locator(selector).first
        try:
            loc.click(timeout=10000)
        except Exception as click_err:
            if not overlay_intercept_retry_should_run(str(click_err)):
                raise
            ok_retry, hidden, err2 = _hide_overlays_and_force_click(page, loc)
            if not ok_retry:
                return {
                    "ok": False,
                    "url": page.url if page else "",
                    "title": "",
                    "text": "",
                    "error": err2,
                    "pointer_intercept": True,
                    "overlays_hidden": hidden,
                    "no_op_exempt": True,
                }
        loc.fill("")
        loc.fill(text, timeout=10000)
        if press_enter:
            loc.press("Enter")
            time.sleep(1.5)
            _dismiss_cookies(page, rounds=1)
        else:
            time.sleep(0.4)
        snap = _snapshot(page, max_chars=max_chars)
        snap["ok"] = True
        return snap
    except Exception as e:
        return {"ok": False, "url": "", "title": "", "text": "", "error": str(e)}


def browser_scroll(direction: str = "down", amount: int = 800) -> dict[str, Any]:
    """Scroll and return a short snapshot (prices often load on scroll)."""
    try:
        page = _ensure_browser()
        delta = amount if direction == "down" else -amount
        page.mouse.wheel(0, delta)
        time.sleep(1.0)
        snap = _snapshot(page, max_chars=8000)
        snap["ok"] = True
        return snap
    except Exception as e:
        return {"ok": False, "error": str(e)}


def browser_wait(seconds: float = 2.0) -> dict[str, Any]:
    """Wait for JS to settle, then return current page text."""
    try:
        page = _ensure_browser()
        time.sleep(max(0.2, min(float(seconds), 15.0)))
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        _dismiss_cookies(page, rounds=1)
        snap = _snapshot(page, max_chars=10000)
        snap["ok"] = True
        return snap
    except Exception as e:
        return {"ok": False, "error": str(e)}


def browser_list_affordances(max_items: int = 50) -> dict[str, Any]:
    """
    Structural affordances only (visible tabs/buttons/links/controls/input fields).

    Priority order (generic, no domain hardcoding):
      1. role=tab / tablist children / aria-selected controls
      2. panel_option (ARIA options, select options, labeled choices)
      3. buttons and role=button (incl. input[type=submit|button])
      4. input_field (text-like <input>/<textarea> — structural metadata only)
      5. same-path / fragment / empty-href links (local navigation)
      6. other in-page links
      7. global / external nav links (last)

    Each item may carry:
      kind, text, href, role, scope ∈ {local, global, unknown}
      For kind=input_field also: tag, type, name, id, placeholder, aria_label
    """
    try:
        page = _ensure_browser()
        js = """
        (maxItems) => {
          const pageUrl = location.href;
          let pageOrigin = '';
          let pagePath = '';
          try {
            const u = new URL(pageUrl);
            pageOrigin = u.origin;
            pagePath = u.pathname || '';
          } catch (e) {}

          const seen = new Set();
          // panel_option: visible choices inside open menus/panels/listboxes (generic)
          // input_field: text-like <input>/<textarea> (structural only; no lexicon)
          const buckets = {
            tab: [], panel_option: [], button: [], input_field: [],
            local_link: [], other_link: [], global_link: []
          };

          const visible = (el) => {
            if (!el) return false;
            const st = window.getComputedStyle(el);
            if (!st) return true;
            if (st.visibility === 'hidden' || st.display === 'none' || st.opacity === '0') return false;
            const r = el.getBoundingClientRect();
            if (r.width < 2 && r.height < 2) return false;
            // off-screen or collapsed height
            if (r.bottom < 0 || r.top > (window.innerHeight || 2000) + 200) return false;
            return true;
          };

          const cleanText = (t) => (t || '').replace(/\\s+/g, ' ').trim();

          const classifyHref = (href) => {
            if (!href) return 'local';
            const h = String(href).trim();
            if (!h || h === '#' || h.startsWith('#') || h.startsWith('javascript:')) return 'local';
            try {
              const u = new URL(h, pageUrl);
              if (u.origin !== pageOrigin) return 'global';
              const p = u.pathname || '';
              if (pagePath && (p === pagePath || p.startsWith(pagePath + '/') || pagePath.startsWith(p + '/')))
                return 'local';
              if (p.split('/').filter(Boolean).length <= 1) return 'global';
              return 'local';
            } catch (e) {
              return 'unknown';
            }
          };

          const push = (kind, text, href, role, preferredScope, extra) => {
            text = cleanText(text);
            // input_field may have empty visible text (placeholder-only); allow short/empty
            const isInput = kind === 'input_field';
            if (!isInput) {
              // Allow slightly longer option labels; reject paragraphs
              if (!text || text.length < 2 || text.length > 100) return;
              // Skip multi-line blobs (likely containers, not single options)
              if ((text.match(/\\n/g) || []).length > 1) return;
            } else {
              if (text && text.length > 120) text = text.slice(0, 120);
            }
            const hrefN = String(href || '').toLowerCase();
            // Open #24b Fase 1: identity is (kind, text, href, name, id) — not text
            // alone. Repeated labels ("pdf") with distinct hrefs must all survive.
            // Mirrors Python affordance_identity_accepts.
            const key = (kind + '|' + (text || '').toLowerCase() + '|' + hrefN + '|' + (extra && extra.name ? extra.name : '') + '|' + (extra && extra.id ? extra.id : ''));
            if (seen.has(key)) return;
            const textHrefKey = 'TH|' + (text || '').toLowerCase() + '|' + hrefN;
            if (!isInput && text && seen.has(textHrefKey) && kind !== 'tab') return;
            seen.add(key);
            if (text) seen.add(textHrefKey);
            const scope = preferredScope || classifyHref(href);
            const item = {
              kind: kind,
              text: (text || '').slice(0, 100) || (isInput ? '(unnamed input)' : ''),
              href: (href || '').slice(0, 300),
              role: role || '',
              scope: scope,
            };
            if (extra && typeof extra === 'object') {
              if (extra.tag) item.tag = String(extra.tag).slice(0, 20);
              if (extra.type) item.type = String(extra.type).slice(0, 30);
              if (extra.name) item.name = String(extra.name).slice(0, 80);
              if (extra.id) item.id = String(extra.id).slice(0, 80);
              if (extra.placeholder) item.placeholder = String(extra.placeholder).slice(0, 120);
              if (extra.aria_label) item.aria_label = String(extra.aria_label).slice(0, 120);
            }
            if (kind === 'tab') buckets.tab.push(item);
            else if (kind === 'panel_option') buckets.panel_option.push(item);
            else if (kind === 'button') buckets.button.push(item);
            else if (kind === 'input_field') buckets.input_field.push(item);
            else if (scope === 'local') buckets.local_link.push(item);
            else if (scope === 'global') buckets.global_link.push(item);
            else buckets.other_link.push(item);
          };

          // --- 1. Tabs (role + common tab patterns) ---
          document.querySelectorAll('[role="tab"], [role="tablist"] [role="tab"]').forEach(el => {
            if (!visible(el)) return;
            const t = el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '';
            push('tab', t, el.getAttribute('href') || '', el.getAttribute('role') || 'tab', 'local');
          });
          document.querySelectorAll('[class*="tab" i] a, [class*="tab" i] button, [class*="nav-tabs" i] a, [data-tab], [aria-controls]').forEach(el => {
            if (!visible(el)) return;
            const t = el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '';
            const href = el.getAttribute('href') || el.href || '';
            const role = el.getAttribute('role') || el.tagName.toLowerCase();
            let kind = 'link';
            if (role === 'tab' || el.getAttribute('aria-controls')) kind = 'tab';
            else if (el.tagName === 'BUTTON' || role === 'button') kind = 'button';
            push(kind, t, href, role, 'local');
          });

          // --- 1b. Panel / menu / listbox options (GENERIC) ---
          // Goal: after a filter/tab opens, surface the *choices* (months, airports,
          // categories, sizes, …) as clickable affordances — not domain keywords.
          // Sources: ARIA roles, open containers, labeled form controls, short
          // clickable nodes inside expanded surfaces.

          const isExpandedSurface = (el) => {
            if (!el) return false;
            const ariaExp = el.getAttribute('aria-expanded');
            if (ariaExp === 'true') return true;
            if (el.hasAttribute('open')) return true;
            const role = (el.getAttribute('role') || '').toLowerCase();
            if (['listbox', 'menu', 'dialog', 'tree', 'grid', 'group'].includes(role)) return true;
            // common open-state class hints (generic tokens only)
            const cls = (el.className && String(el.className)) || '';
            if (/\\b(open|opened|expanded|active|show|visible|is-open)\\b/i.test(cls)) return true;
            return false;
          };

          // Explicit ARIA options / menu items / radios / checkboxes
          document.querySelectorAll(
            '[role="option"], [role="menuitem"], [role="menuitemcheckbox"], [role="menuitemradio"], ' +
            '[role="treeitem"], [role="checkbox"], [role="radio"]'
          ).forEach(el => {
            if (!visible(el)) return;
            const t = el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '';
            push('panel_option', t, el.getAttribute('href') || '', el.getAttribute('role') || 'option', 'local');
          });

          // <select> options (visible selects only)
          document.querySelectorAll('select').forEach(sel => {
            if (!visible(sel)) return;
            Array.from(sel.options || []).forEach(opt => {
              const t = opt.text || opt.label || opt.value || '';
              if (t) push('panel_option', t, '', 'option', 'local');
            });
          });

          // Labels bound to inputs (checkbox/radio/option-like) — clickable choices
          document.querySelectorAll('label').forEach(lab => {
            if (!visible(lab)) return;
            const t = lab.innerText || lab.getAttribute('aria-label') || '';
            const short = cleanText(t);
            if (!short || short.length > 80) return;
            // Prefer labels that control an input
            const forId = lab.getAttribute('for');
            let controls = forId ? document.getElementById(forId) : null;
            if (!controls) controls = lab.querySelector('input, select');
            if (!controls) return;
            const typ = (controls.getAttribute('type') || controls.tagName || '').toLowerCase();
            if (['checkbox', 'radio', 'select-one', 'select-multiple', 'select'].includes(typ) ||
                controls.tagName === 'SELECT' || controls.tagName === 'INPUT') {
              push('panel_option', short, '', 'label', 'local');
            }
          });

          // Short clickable nodes inside expanded / listbox / filter-like surfaces
          const surfaceRoots = [];
          document.querySelectorAll(
            '[aria-expanded="true"], [open], [role="listbox"], [role="menu"], [role="dialog"], ' +
            '[class*="dropdown" i], [class*="popover" i], [class*="filter" i], [class*="facet" i], ' +
            '[class*="panel" i], [class*="drawer" i], [data-filter], [data-testid*="filter" i]'
          ).forEach(root => {
            if (!visible(root) && !isExpandedSurface(root)) return;
            // Only treat as surface if expanded or role is explicitly a choice surface
            const role = (root.getAttribute('role') || '').toLowerCase();
            if (!isExpandedSurface(root) && !['listbox', 'menu', 'dialog'].includes(role)) {
              // still allow if it has many short children (open panel heuristic)
              const kids = root.querySelectorAll('li, a, button, label, [role="option"], span, div');
              let shortKids = 0;
              kids.forEach(k => {
                if (!visible(k)) return;
                const tt = cleanText(k.innerText || '');
                if (tt.length >= 2 && tt.length <= 40) shortKids++;
              });
              if (shortKids < 3) return;
            }
            surfaceRoots.push(root);
          });

          const clickableLooks = (el) => {
            if (!el) return false;
            const tag = el.tagName;
            if (['A', 'BUTTON', 'LABEL', 'OPTION'].includes(tag)) return true;
            const role = (el.getAttribute('role') || '').toLowerCase();
            if (['option', 'menuitem', 'button', 'link', 'checkbox', 'radio', 'treeitem'].includes(role)) return true;
            if (el.getAttribute('tabindex') === '0' || el.getAttribute('tabindex') === '-1') return true;
            if (el.onclick || el.getAttribute('onclick')) return true;
            try {
              const st = window.getComputedStyle(el);
              if (st && st.cursor === 'pointer') return true;
            } catch (e) {}
            return false;
          };

          surfaceRoots.forEach(root => {
            root.querySelectorAll('li, a, button, label, span, div, [role="option"]').forEach(el => {
              if (!visible(el)) return;
              if (!clickableLooks(el) && el.tagName !== 'LI') return;
              // Prefer leaf-ish nodes: not huge containers
              const t = cleanText(el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '');
              if (!t || t.length < 2 || t.length > 60) return;
              // Avoid taking the whole panel text
              if (el.children && el.children.length > 6) return;
              const href = el.getAttribute('href') || '';
              push('panel_option', t, href, el.getAttribute('role') || el.tagName.toLowerCase(), 'local');
            });
          });

          // --- 2. Buttons ---
          document.querySelectorAll('button, [role="button"], input[type="submit"], input[type="button"]').forEach(el => {
            if (!visible(el)) return;
            const t = el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '';
            push('button', t, '', el.getAttribute('role') || el.tagName.toLowerCase(), 'local');
          });

          // --- 2b. Text-like input fields (structural only — no domain lexicon) ---
          // Collect <input> (text/search/email/…) and <textarea>. Metadata: tag, type,
          // name, id, placeholder, aria-label. Text for display is placeholder/aria/name.
          document.querySelectorAll(
            'input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="checkbox"]):not([type="radio"]):not([type="file"]):not([type="image"]):not([type="reset"]):not([type="color"]):not([type="range"]), textarea'
          ).forEach(el => {
            if (!visible(el)) return;
            const tag = (el.tagName || '').toLowerCase();
            let typ = (el.getAttribute('type') || '').toLowerCase();
            if (tag === 'textarea') typ = 'textarea';
            // Allow empty type (defaults to text) and common text-like types
            const allowed = ['', 'text', 'search', 'email', 'url', 'tel', 'number', 'password', 'textarea'];
            if (tag !== 'textarea' && !allowed.includes(typ)) return;
            const placeholder = el.getAttribute('placeholder') || '';
            const aria = el.getAttribute('aria-label') || '';
            const title = el.getAttribute('title') || '';
            const name = el.getAttribute('name') || '';
            const id = el.getAttribute('id') || '';
            const t = placeholder || aria || title || name || id || '';
            push('input_field', t, '', typ || tag, 'local', {
              tag: tag,
              type: typ || (tag === 'textarea' ? 'textarea' : 'text'),
              name: name,
              id: id,
              placeholder: placeholder,
              aria_label: aria
            });
          });

          // --- 3. Links (all), classified by scope ---
          document.querySelectorAll('a[href]').forEach(a => {
            if (!visible(a)) return;
            const t = a.innerText || a.getAttribute('aria-label') || a.getAttribute('title') || '';
            push('link', t, a.href || '', a.getAttribute('role') || 'link', null);
          });

          // Merge in priority order: tabs → panel options → buttons → input_fields → links
          const out = [];
          const take = (arr) => {
            for (const it of arr) {
              if (out.length >= maxItems) break;
              out.push(it);
            }
          };
          take(buckets.tab);
          take(buckets.panel_option);
          take(buckets.button);
          take(buckets.input_field);
          take(buckets.local_link);
          take(buckets.other_link);
          take(buckets.global_link);
          return out.slice(0, maxItems);
        }
        """
        items = page.evaluate(js, max_items) or []
        # Python-side safety: ensure scope present
        for it in items:
            if "scope" not in it or not it.get("scope"):
                it["scope"] = "unknown"
        return {"ok": True, "url": page.url, "affordances": items, "n": len(items)}
    except Exception as e:
        return {"ok": False, "url": "", "affordances": [], "n": 0, "error": str(e)}


def affordance_identity_accepts(
    seen: set[str],
    *,
    kind: str,
    text: str,
    href: str = "",
    extra_name: str = "",
    extra_id: str = "",
    is_input: bool = False,
) -> bool:
    """Keep or drop one affordance by structural identity.

    Mirrors `browser_list_affordances` JS `push()` (Open #24b Fase 1).
    Identity is (kind, text, href, extra_name, extra_id) plus a cross-kind
    (text, href) guard. Same visible text with *different* hrefs both survive.
    Exact (text, href) duplicates still collapse. No lexicon.
    """
    text_n = re.sub(r"\s+", " ", (text or "")).strip()
    href_n = (href or "").strip().lower()
    if not is_input:
        if not text_n or len(text_n) < 2 or len(text_n) > 100:
            return False
    key = f"{kind}|{text_n.lower()}|{href_n}|{extra_name}|{extra_id}"
    if key in seen:
        return False
    text_href_key = f"TH|{text_n.lower()}|{href_n}"
    if not is_input and text_n and text_href_key in seen and kind != "tab":
        return False
    seen.add(key)
    if text_n:
        seen.add(text_href_key)
    return True


def filter_affordances_by_identity(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply push()-style (text, href) identity to a raw list of affordance dicts."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in raw:
        kind = str(item.get("kind") or "link")
        if affordance_identity_accepts(
            seen,
            kind=kind,
            text=str(item.get("text") or ""),
            href=str(item.get("href") or ""),
            extra_name=str(item.get("name") or ""),
            extra_id=str(item.get("id") or ""),
            is_input=kind == "input_field",
        ):
            out.append(item)
    return out
