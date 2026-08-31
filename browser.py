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


def _snapshot(
    page,
    max_chars: int = 12000,
    include_hints: bool = True,
) -> dict[str, Any]:
    title, text = _page_text(page, max_chars=max_chars)
    out: dict[str, Any] = {
        "url": page.url,
        "title": title,
        "text": text,
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
        page.goto(resolved, wait_until="domcontentloaded", timeout=60000)
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


def browser_click(selector: str, max_chars: int = 10000) -> dict[str, Any]:
    """
    Click an element (CSS or Playwright text selector, e.g. button:has-text('Zoeken')).
    Returns updated page text so you can see prices / next form step.
    """
    try:
        page = _ensure_browser()
        _dismiss_cookies(page, rounds=2)
        try:
            page.locator(selector).first.click(timeout=15000)
        except Exception as click_err:
            err_s = str(click_err)
            # Pointer intercepted by consent iframe / overlay → hide and retry once
            if "intercepts pointer" in err_s or "consent_iframe" in err_s or "Timeout" in err_s:
                hidden = _hide_consent_overlays(page)
                _dismiss_cookies(page, rounds=2)
                try:
                    page.locator(selector).first.click(timeout=8000, force=True)
                except Exception as e2:
                    return {
                        "ok": False,
                        "url": page.url if page else "",
                        "title": "",
                        "text": "",
                        "error": str(e2),
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


def browser_type(
    selector: str,
    text: str,
    press_enter: bool = False,
    max_chars: int = 8000,
) -> dict[str, Any]:
    """Type into an input; optionally press Enter. Returns page snapshot."""
    try:
        page = _ensure_browser()
        loc = page.locator(selector).first
        loc.click(timeout=10000)
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
    Structural affordances only (visible tabs/buttons/links/controls).

    Priority order (generic, no domain hardcoding):
      1. role=tab / tablist children / aria-selected controls
      2. buttons and role=button in main/content
      3. same-path / fragment / empty-href links (local navigation)
      4. other in-page links
      5. global / external nav links (last)

    Each item may carry:
      kind, text, href, role, scope ∈ {local, global, unknown}
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
          const buckets = {
            tab: [], panel_option: [], button: [], local_link: [], other_link: [], global_link: []
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

          const push = (kind, text, href, role, preferredScope) => {
            text = cleanText(text);
            // Allow slightly longer option labels; reject paragraphs
            if (!text || text.length < 2 || text.length > 100) return;
            // Skip multi-line blobs (likely containers, not single options)
            if ((text.match(/\\n/g) || []).length > 1) return;
            const key = (kind + '|' + text.toLowerCase()).slice(0, 160);
            if (seen.has(key)) return;
            // Also de-dupe across kinds on same text (prefer earlier buckets)
            const textKey = 'T|' + text.toLowerCase();
            if (seen.has(textKey) && kind !== 'tab') return;
            seen.add(key);
            seen.add(textKey);
            const scope = preferredScope || classifyHref(href);
            const item = {
              kind: kind,
              text: text.slice(0, 100),
              href: (href || '').slice(0, 300),
              role: role || '',
              scope: scope,
            };
            if (kind === 'tab') buckets.tab.push(item);
            else if (kind === 'panel_option') buckets.panel_option.push(item);
            else if (kind === 'button') buckets.button.push(item);
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

          // --- 3. Links (all), classified by scope ---
          document.querySelectorAll('a[href]').forEach(a => {
            if (!visible(a)) return;
            const t = a.innerText || a.getAttribute('aria-label') || a.getAttribute('title') || '';
            push('link', t, a.href || '', a.getAttribute('role') || 'link', null);
          });

          // Merge in priority order: tabs → panel options → buttons → links
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
