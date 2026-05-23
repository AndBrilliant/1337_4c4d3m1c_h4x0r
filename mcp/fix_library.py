#!/usr/bin/env python3
"""Fix wrong-title and parser-noise issues in library one_pager.md `## Reference`
sections by RE-FETCHING each affected source page and parsing the full meta
(including multi-value citation_author tags) from the raw HTML.

For each slot with a FAIL or AUTHOR_MISMATCH verdict in the latest backfill,
rebuild a canonical reference of the form:

    <author 1>, <author 2>, …, and <author N>, *<Title>*, **<Venue Vol (Year) Pages>**; arXiv:<id>; doi:<doi>.

Preserves the original under `## Reference (was)` in the one_pager for audit.

Idempotent: re-running on already-fixed slots produces no diff.
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

LIBRARY_ROOT = Path("/Users/Drew/Desktop/Academic/library")
CHECK_CITATIONS_DIR = Path("/Users/Drew/claude/paper-tools/check-citations")
JOBS_DIR = Path("/tmp/papers-mcp-jobs")

sys.path.insert(0, str(CHECK_CITATIONS_DIR))
try:
    from browser_fetch import fetch_url_browser, playwright_available  # type: ignore
except Exception:
    fetch_url_browser = None
    playwright_available = lambda: False

_VERIFY_MARKER = "## Citation verification"
_REF_HDR = "## Reference"

_RATE_S = 1.0
_ARXIV_RATE_S = 3.0
_last_fetch: dict[str, float] = {}


def rate_limit(host: str, min_s: float) -> None:
    t = _last_fetch.get(host, 0.0)
    dt = time.time() - t
    if dt < min_s:
        time.sleep(min_s - dt)
    _last_fetch[host] = time.time()


def latest_backfill_json() -> Path:
    files = sorted(JOBS_DIR.glob("backfill-*.json"))
    if not files:
        sys.exit("no backfill JSON found")
    return files[-1]


def fetch_raw_html(url: str, timeout: float = 25.0) -> tuple[str, str, int]:
    """Return (final_url, html, status). Uses browser fallback for blocked sites."""
    from urllib.parse import urlsplit
    host = urlsplit(url).hostname or url
    rate_limit(host, _ARXIV_RATE_S if "arxiv.org" in host else _RATE_S)
    req = urllib.request.Request(url, headers={
        "User-Agent": "papers-mcp-fixer/1.0 (citation verifier)",
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            final = resp.url
            data = resp.read(800_000)
        try:
            html_text = data.decode("utf-8", errors="replace")
        except Exception:
            html_text = data.decode("latin-1", errors="replace")
    except urllib.error.HTTPError as e:
        status = e.code
        final = url
        html_text = ""
    except Exception:
        status = 0
        final = url
        html_text = ""

    # Sniff for bot-blocks / empty pages. Fall back to browser if so.
    title_m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    title = re.sub(r"\s+", " ", title_m.group(1)).strip().lower() if title_m else ""
    needs_browser = (
        status >= 400
        or not html_text
        or "just a moment" in title
        or "attention required" in title
        or title in {"sciencedirect", "redirecting", "loading"}
    )
    if needs_browser and fetch_url_browser and playwright_available():
        b = fetch_url_browser(url)
        if b.get("raw_meta_text"):
            return b.get("final_url") or url, "<head>" + b["raw_meta_text"] + "</head>", b.get("status") or 200
    return final, html_text, status


_META_RE = re.compile(
    r'<meta\b[^>]*?(?:name|property)\s*=\s*["\']([^"\']+)["\'][^>]*?content\s*=\s*["\']([^"\']*)["\']',
    re.IGNORECASE,
)
_META_RE_REV = re.compile(
    r'<meta\b[^>]*?content\s*=\s*["\']([^"\']*)["\'][^>]*?(?:name|property)\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def parse_meta_multi(html_text: str) -> dict[str, list[str]]:
    """Return meta tags as {key -> list of values}. Captures duplicate keys (e.g. multiple citation_author)."""
    out: dict[str, list[str]] = {}
    for m in _META_RE.finditer(html_text):
        k = m.group(1).lower()
        v = html.unescape(m.group(2)).strip()
        if v:
            out.setdefault(k, []).append(v)
    for m in _META_RE_REV.finditer(html_text):
        k = m.group(2).lower()
        v = html.unescape(m.group(1)).strip()
        if v and v not in out.get(k, []):
            out.setdefault(k, []).append(v)
    return out


def get_one(meta: dict[str, list[str]], *keys: str) -> Optional[str]:
    for k in keys:
        if k in meta and meta[k]:
            return meta[k][0]
    return None


def authors_from_meta(meta: dict[str, list[str]]) -> list[str]:
    raw = meta.get("citation_author") or meta.get("dc.creator") or meta.get("dc.creators") or []
    out: list[str] = []
    seen = set()
    for a in raw:
        a = a.strip()
        if not a:
            continue
        if "," in a:
            last, first = a.split(",", 1)
            name = f"{first.strip()} {last.strip()}".strip()
        else:
            name = a
        key = name.lower()
        if key not in seen:
            seen.add(key)
            out.append(name)
    return out


def build_canonical_reference(meta: dict[str, list[str]], fallback_arxiv: Optional[str] = None) -> Optional[str]:
    title = get_one(meta, "citation_title", "dc.title", "og:title")
    if not title:
        return None
    title = html.unescape(re.sub(r"\s+", " ", title).strip())

    authors = authors_from_meta(meta)
    if not authors:
        return None
    if len(authors) == 1:
        authors_str = authors[0]
    elif len(authors) == 2:
        authors_str = f"{authors[0]} and {authors[1]}"
    elif len(authors) <= 6:
        authors_str = ", ".join(authors[:-1]) + ", and " + authors[-1]
    else:
        authors_str = ", ".join(authors[:5]) + ", et al."

    venue = get_one(meta, "citation_journal_title", "dc.publisher", "prism.publicationName")
    vol = get_one(meta, "citation_volume", "prism.volume")
    yr_raw = get_one(meta, "citation_publication_date", "citation_year",
                     "dc.date", "dc.issued", "article:published_time", "prism.publicationDate")
    year = ""
    if yr_raw:
        ym = re.search(r"\d{4}", yr_raw)
        year = ym.group(0) if ym else ""
    fp = get_one(meta, "citation_firstpage", "prism.startingPage")
    lp = get_one(meta, "citation_lastpage", "prism.endingPage")
    pages = ""
    if fp and lp:
        pages = f"{fp}–{lp}"
    elif fp:
        pages = fp

    doi = get_one(meta, "citation_doi", "dc.identifier.doi", "prism.doi")
    if doi:
        doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    arxiv = get_one(meta, "citation_arxiv_id") or fallback_arxiv

    venue_part = ""
    if venue:
        chunks = [venue]
        if vol:
            chunks.append(str(vol))
        if year:
            chunks.append(f"({year})")
        if pages:
            chunks.append(pages)
        venue_part = "**" + " ".join(chunks) + "**"

    pieces = [authors_str, f"*{title}*"]
    if venue_part:
        pieces.append(venue_part)
    ref = ", ".join(pieces)
    tail: list[str] = []
    if arxiv:
        tail.append(f"arXiv:{arxiv}")
    if doi:
        tail.append(f"doi:{doi}")
    if tail:
        ref = ref.rstrip(".") + "; " + "; ".join(tail)
    if not ref.endswith("."):
        ref += "."
    return ref


def parse_section(text: str, header: str) -> str:
    pat = rf"^## {re.escape(header)}\s*\n(.+?)(?=^## |\Z)"
    m = re.search(pat, text, re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else ""


def replace_section(text: str, header: str, new_content: str) -> str:
    pat = rf"(^## {re.escape(header)}\s*\n)(.+?)(?=^## |\Z)"
    return re.sub(pat, lambda m: m.group(1) + new_content.rstrip() + "\n\n", text, count=1,
                  flags=re.MULTILINE | re.DOTALL)


def extract_arxiv_from_reference(ref: str) -> Optional[str]:
    m = re.search(r"(?:arXiv\s*:?\s*)([a-z\-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?", ref, re.IGNORECASE)
    return m.group(1) if m else None


def main() -> int:
    bf_json = latest_backfill_json()
    print(f"Using backfill: {bf_json}")
    bf = json.loads(bf_json.read_text())

    candidates = [r for r in bf["results"]
                  if r.get("verdict") in {"FAIL", "AUTHOR_MISMATCH_SAME_PAPER", "WRONG_ARXIV_SAME_PAPER"}]
    print(f"Candidates to fix: {len(candidates)}")
    print(f"playwright_available: {playwright_available()}")
    print()

    fixed = 0
    skipped: list[tuple[str, str]] = []

    for r in candidates:
        slot_rel = r["slot"]
        slot = LIBRARY_ROOT / slot_rel
        op = slot / "one_pager.md"
        if not op.is_file():
            skipped.append((slot_rel, "no one_pager"))
            continue
        op_text = op.read_text(errors="replace")
        old_ref = parse_section(op_text, "Reference")
        fallback_arxiv = extract_arxiv_from_reference(old_ref)
        url = r.get("source_url")
        if not url:
            skipped.append((slot_rel, "no source_url in backfill record"))
            continue

        final_url, raw_html, status = fetch_raw_html(url)
        if not raw_html or status >= 400:
            skipped.append((slot_rel, f"fetch failed (status {status})"))
            continue
        meta = parse_meta_multi(raw_html)
        new_ref = build_canonical_reference(meta, fallback_arxiv=fallback_arxiv)
        if not new_ref:
            n_authors = len(meta.get("citation_author") or meta.get("dc.creator") or [])
            skipped.append((slot_rel, f"no usable meta (citation_authors={n_authors})"))
            continue
        if old_ref.strip() == new_ref.strip():
            skipped.append((slot_rel, "already canonical"))
            continue

        # Strip any prior "(was)" block.
        op_text = re.sub(
            rf"\n*## Reference \(was\).*?(?=\n## |\Z)", "",
            op_text, flags=re.DOTALL,
        )
        op_text = replace_section(op_text, "Reference", new_ref)
        op_text = op_text.replace(
            f"{_REF_HDR}\n{new_ref.rstrip()}\n\n",
            f"{_REF_HDR}\n{new_ref.rstrip()}\n\n## Reference (was)\n{old_ref.rstrip()}\n\n",
            1,
        )
        op.write_text(op_text)
        fixed += 1
        print(f"  fixed: {slot_rel}")
        print(f"    old: {old_ref[:160]}")
        print(f"    new: {new_ref[:160]}")
        print()

    print(f"=== fixed: {fixed} ===")
    print(f"=== skipped: {len(skipped)} ===")
    for slot, reason in skipped:
        print(f"    {slot}  ({reason})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
