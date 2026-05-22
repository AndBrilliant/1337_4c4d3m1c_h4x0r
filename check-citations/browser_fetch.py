"""Browser-automation fallback fetcher for the citation verifier.

Cloudflare and similar bot-blockers reject the stdlib's urllib User-Agent
string with HTTP 403 even when the underlying resource is open-access (see
the Oxford OUP / APS / Elsevier cases in the v3.x reports). A real browser
engine with JS execution passes those challenges because Cloudflare's check
involves a JS-executed challenge token.

Implementation: Playwright + Chromium. Same return shape as `fetch_url()`
so callers can drop it in as a fallback.

What works:
  - **HTML scrape of landing pages** through Cloudflare/OneTrust walls.
    Defeats "Just a moment..." JS challenges using anti-detection flags
    (--disable-blink-features=AutomationControlled, navigator.webdriver
    spoof, viewport sizing, real UA). Confirmed against Oxford Academic
    (OUP), APS, and similar. Recovers title + citation_* meta tags +
    visible body text — everything the metadata_check needs.
  - **Cookie consent dismissal** (OneTrust banner used by OUP, Elsevier,
    Springer, T&F). Dismisses common variants before clicking PDF links.

What does NOT work (without stealth plugins like playwright-stealth):
  - **Direct PDF GET through Cloudflare**. Even with valid session cookies
    from a JS-cleared landing page, OUP and similar block bare
    .pdf URL requests with a fresh 'Just a moment...' challenge. This
    appears to be a per-URL CF rule, not a per-session one.
  - **Click-to-download** in a headless context often does not fire the
    download event (the link may open in a new tab handled outside our
    context). For these, the user needs to grab the PDF in a real browser.

Install once per machine:
    pip install playwright
    python -m playwright install chromium

Publisher access notes (updated as we learn):
  - **Oxford Academic (academic.oup.com)** — Cloudflare + OneTrust.
    Landing pages scrape cleanly after the JS challenge resolves (~1 sec
    with anti-detection flags). Direct PDF URLs always 403 — user must
    grab manually in browser. Unpaywall flags many OUP papers as OA but
    the PDF is still CF-walled.
  - **APS Journals (journals.aps.org)** — Less aggressive than OUP but
    intermittent. Vintage papers (1950s–1970s) are paywalled (~$35/each).
    APS sometimes double-charges (the "Purchased Articles" cache misses).
    Customer service refunds on request: cust-serv@aps.org.
  - **Science (science.org)** — Some content has free-after-1y access.
    Reproducibility paper (osc2015) has an open mirror at U Dundee
    (https://discovery.dundee.ac.uk/...).
  - **PNAS (pnas.org)** — Open after 6mo. PMC mirrors served via direct
    PDF link (https://pmc.ncbi.nlm.nih.gov/articles/PMCxxxxxx/pdf/...)
    are often the cleanest grab. OSF author-hosted preprints work too.
  - **Elsevier (sciencedirect.com)** — Heavy CF. Returns "Redirecting"
    stub even with browser. Best fallback: author-hosted copy (e.g.
    Mayo & Spanos 2011 at errorstatistics.com/wp-content/...).
  - **PMC / EuropePMC** — Open-access mirror of NIH-funded papers; URL
    pattern is /articles/PMC<id>/pdf/<filename>.pdf. Sometimes the
    direct PDF URL serves a 1.8KB redirect stub; use the landing page
    via this browser fetcher instead.
  - **Mayo's blog (errorstatistics.com)** — Hosts free PDFs of most
    Mayo/Spanos papers (and other severity-related work). The blog's
    /mayo-publications/ index lists them.
  - **viXra** — Carl Brannen and other independents host non-arXiv
    preprints here (e.g. brannen2006 at vixra:0702.0052).
  - **arXiv** — Open and friendly to curl. No browser fallback needed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any


# UA of a recent Chrome on macOS. Cloudflare's challenge checks both UA
# string AND JS-execution capability; the UA alone is insufficient.
REAL_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
           "AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/120.0.0.0 Safari/537.36")

# Flags that defeat the cheapest layer of bot detection. Without these,
# even Playwright Chromium gets stuck on Cloudflare's "Just a moment..."
# challenge indefinitely.
CHROME_ANTIBOT_FLAGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
]

# JS snippet that removes navigator.webdriver = true (most common headless
# signal Cloudflare and similar look for).
HIDE_WEBDRIVER_JS = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
)

# Common cookie-consent dismissal selectors. OneTrust is the dominant
# vendor on academic publisher sites (OUP, Elsevier, Springer, T&F).
CONSENT_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "button:has-text('Accept All')",
    "button:has-text('Accept All Cookies')",
    "button:has-text('Accept')",
    ".onetrust-close-btn-handler",
    "[aria-label='Close']",
]


def playwright_available() -> bool:
    """Cheap check — Playwright importable and Chromium installed."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False
    return True


def fetch_url_browser(url: str, *, timeout_ms: int = 30_000,
                      download_dir: Path | None = None,
                      key: str | None = None) -> dict[str, Any]:
    """Fetch URL via headless Chromium. Same return shape as fetch_url().

    Extra fields when a PDF is downloaded successfully:
      - ``pdf_path``: absolute path to the saved PDF
      - ``downloaded``: True if a file was saved
    """
    out: dict[str, Any] = {
        "status": 0, "final_url": "", "title": "", "meta": {},
        "text_excerpt": "", "pdf": False, "error": "",
        "raw_meta_text": "", "pdf_path": "", "downloaded": False,
        "engine": "playwright",
    }
    if not url:
        out["error"] = "no canonical URL available"
        return out
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        out["error"] = ("playwright not installed; "
                        "pip install playwright && python -m playwright install chromium")
        return out

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=CHROME_ANTIBOT_FLAGS)
            ctx = browser.new_context(
                user_agent=REAL_UA,
                accept_downloads=True,
                viewport={"width": 1280, "height": 800},
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            ctx.add_init_script(HIDE_WEBDRIVER_JS)

            page = ctx.new_page()
            try:
                response = page.goto(url, timeout=timeout_ms,
                                     wait_until="domcontentloaded")
            except Exception as e:
                # `page.goto` raises "Download is starting" for direct PDF
                # URLs.  Cloudflare-protected publishers (OUP, Elsevier)
                # additionally 403 the direct PDF URL even with valid
                # session cookies — so attempting this path is generally
                # futile.  Surface clearly.
                msg = str(e)
                if "Download is starting" in msg:
                    out["error"] = ("URL serves a PDF directly; auto-download "
                                    "through Cloudflare is unreliable. Grab "
                                    "this PDF manually in a real browser.")
                else:
                    out["error"] = f"goto: {msg[:200]}"
                ctx.close()
                browser.close()
                return out

            if response is None:
                out["error"] = "page.goto returned None"
                ctx.close()
                browser.close()
                return out

            out["status"] = response.status
            out["final_url"] = page.url

            # Wait briefly for Cloudflare challenge JS to resolve. The
            # antibot flags + webdriver-hide are usually enough for it to
            # clear in <2s; allow up to 8s before giving up.
            for _ in range(8):
                page.wait_for_timeout(1000)
                title = page.title()
                if title and "just a moment" not in title.lower() \
                        and "attention required" not in title.lower():
                    break

            # Dismiss cookie consent if present. The PDF-download click
            # path needs this; the HTML-scrape path doesn't but harmless.
            for sel in CONSENT_SELECTORS:
                try:
                    page.locator(sel).click(timeout=1500)
                    break
                except Exception:
                    continue

            out["title"] = page.title()
            out["final_url"] = page.url

            # Pull meta tags. mirror fetch_url's behavior (citation_*, dc.*,
            # og:*, twitter:title, description).
            for m in page.locator("meta").all():
                try:
                    name = (m.get_attribute("name") or
                            m.get_attribute("property") or "").lower()
                    content = m.get_attribute("content") or ""
                except Exception:
                    continue
                if not name or not content:
                    continue
                if name.startswith(("citation_", "dc.", "og:",
                                    "twitter:title", "description")):
                    out["meta"][name] = content

            # raw_meta_text mirrors fetch_url's <head> capture so the v3.1
            # author re-scan path still works.
            try:
                out["raw_meta_text"] = page.eval_on_selector(
                    "head", "el => el.innerHTML"
                )[:20000]
            except Exception:
                pass

            try:
                body_text = page.inner_text("body")
                out["text_excerpt"] = re.sub(r"\s+", " ", body_text).strip()[:6000]
            except Exception as e:  # noqa: BLE001
                out["text_excerpt"] = ""

            # Optional: attempt PDF download by clicking the article's
            # "PDF" link. Many publishers' download links open in a new
            # tab or are intercepted; failures here are silent — the
            # primary use is HTML scrape, not file capture.
            if download_dir:
                for sel in ['a.article-pdfLink', 'a[href*=".pdf"]:has-text("PDF")',
                            'a.pdf-link']:
                    try:
                        with page.expect_download(timeout=10000) as dl_info:
                            page.locator(sel).first.click(timeout=5000)
                        dl = dl_info.value
                        download_dir = Path(download_dir)
                        download_dir.mkdir(parents=True, exist_ok=True)
                        target = download_dir / (f"{key}.pdf" if key
                                                 else dl.suggested_filename)
                        dl.save_as(str(target))
                        out["pdf"] = True
                        out["pdf_path"] = str(target)
                        out["downloaded"] = True
                        break
                    except Exception:
                        continue

            ctx.close()
            browser.close()
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    return out


if __name__ == "__main__":
    # CLI smoke test: python browser_fetch.py <url> [download_dir] [key]
    if len(sys.argv) < 2:
        print("usage: python browser_fetch.py <url> [download_dir] [key]",
              file=sys.stderr)
        sys.exit(2)
    url = sys.argv[1]
    ddir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    key = sys.argv[3] if len(sys.argv) > 3 else None
    result = fetch_url_browser(url, download_dir=ddir, key=key)
    import json
    printable = {k: (v[:300] + "…" if isinstance(v, str) and len(v) > 300 else v)
                 for k, v in result.items()}
    print(json.dumps(printable, indent=2))
