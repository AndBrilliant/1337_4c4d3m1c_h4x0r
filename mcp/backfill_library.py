#!/usr/bin/env python3
"""Backfill the literature library:
  1. For each topic (koide first), scan slots.
  2. If slot has no PDF, try arXiv fetch → browser fallback.
  3. For every slot, verify the `## Reference` citation via metadata_check.
  4. Save source page text + a '## Citation verification' block in the one_pager.

Idempotent: skips slots whose one_pager already has a verification block
unless --reverify is passed.

Outputs:
  /tmp/papers-mcp-jobs/backfill-<timestamp>.log   (live progress)
  /tmp/papers-mcp-jobs/backfill-<timestamp>.json  (final summary)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

LIBRARY_ROOT = Path("/Users/Drew/Desktop/Academic/library")
CHECK_CITATIONS_DIR = Path("/Users/Drew/claude/paper-tools/check-citations")
JOBS_DIR = Path("/tmp/papers-mcp-jobs")
JOBS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(CHECK_CITATIONS_DIR))
from metadata_check import metadata_check  # type: ignore
try:
    from browser_fetch import fetch_url_browser, playwright_available  # type: ignore
except Exception:
    fetch_url_browser = None
    playwright_available = lambda: False

# ---------------------------------------------------------------------------

PRIORITY_TOPICS = ["koide"]
SKIP_DIRS = {".git", "OLD"}
RATE_DEFAULT_S = 1.0
RATE_ARXIV_S = 3.0

_ARXIV_RE = re.compile(r"(?:arXiv\s*:?\s*)([a-z\-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
_VERIFY_MARKER = "## Citation verification"
_META_RE = re.compile(r'<meta\s+(?:name|property)=["\']([^"\']+)["\']\s+content=["\']([^"\']*)["\']', re.IGNORECASE)
_SCRIPT_RE = re.compile(r"<script\b.*?</script>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

last_fetch_at: dict[str, float] = {}


def rate_limit(host: str, min_s: float) -> None:
    t = last_fetch_at.get(host, 0.0)
    dt = time.time() - t
    if dt < min_s:
        time.sleep(min_s - dt)
    last_fetch_at[host] = time.time()


def topic_dirs() -> list[Path]:
    out = []
    for p in sorted(LIBRARY_ROOT.iterdir()):
        if not p.is_dir() or p.name in SKIP_DIRS or p.name.startswith("."):
            continue
        out.append(p)
    # Priority topics first, preserving the given order.
    pr_map = {t: i for i, t in enumerate(PRIORITY_TOPICS)}
    out.sort(key=lambda d: (pr_map.get(d.name, 9999), d.name))
    return out


def slot_paths(topic_dir: Path) -> list[Path]:
    return sorted(
        c for c in topic_dir.iterdir()
        if c.is_dir() and (c / "one_pager.md").is_file()
    )


def slot_has_pdf(slot: Path) -> bool:
    return (slot / f"{slot.name}.pdf").is_file()


def parse_section(text: str, header: str) -> str:
    pat = rf"^## {re.escape(header)}\s*\n(.+?)(?=^## |\Z)"
    m = re.search(pat, text, re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else ""


def has_verify_block(text: str) -> bool:
    return _VERIFY_MARKER in text


def strip_verify_block(text: str) -> str:
    return re.sub(rf"\n*{re.escape(_VERIFY_MARKER)}.*\Z", "", text, flags=re.DOTALL)


_ARXIV_PREPRINT_EMPH_RE = re.compile(r"\\emph\{\s*arXiv[^}]*\}", re.IGNORECASE)
_ARXIV_REF_RE = re.compile(r"\barXiv\s*:?\s*[a-z0-9./-]+(?:v\d+)?", re.IGNORECASE)
_DOI_REF_RE = re.compile(r"\bdoi\s*:?\s*10\.\d{4,9}/[^\s,;]+", re.IGNORECASE)
_URL_REF_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def md_to_pseudo_latex(text: str) -> str:
    """Convert one_pager markdown to bibitem-shaped LaTeX for metadata_check.

    - Strip raw `{X}` LaTeX case-preservation braces (nested braces break the
      title regex which uses `[^{}]*`).
    - Convert markdown `**X**` to `\\textbf{X}` and `*X*` to `\\emph{X}`. We use
      `\\emph` (not `\\textit`) because metadata_check's title extractor matches
      `\\emph` first; this gives the real title priority over leftover noise.
    - Strip noise that bibtex-style refs leave in the bib body: the literal
      `\\emph{arXiv preprint arXiv:...}`, bare arXiv ID/DOI/URL strings that the
      author-extractor would otherwise tokenize as fake surnames.
    """
    text = re.sub(r"\{([A-Za-z]+)\}", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", text)
    text = re.sub(r"(?<![*])\*([^*\n]+)\*(?![*])", r"\\emph{\1}", text)
    text = _ARXIV_PREPRINT_EMPH_RE.sub("", text)
    text = _ARXIV_REF_RE.sub("", text)
    text = _DOI_REF_RE.sub("", text)
    text = _URL_REF_RE.sub("", text)
    return text


def extract_canonical_url(ref: str) -> Optional[str]:
    m = _ARXIV_RE.search(ref or "")
    if m:
        return f"https://arxiv.org/abs/{m.group(1)}"
    m = _DOI_RE.search(ref or "")
    if m:
        return f"https://doi.org/{m.group(0).rstrip('.,;)')}"
    m = re.search(r"https?://\S+", ref or "")
    if m:
        return m.group(0).rstrip(".,;)")
    return None


def extract_arxiv_id(ref: str) -> Optional[str]:
    m = _ARXIV_RE.search(ref or "")
    return m.group(1) if m else None


def host_of(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).hostname or url
    except Exception:
        return url


def fetch_plain(url: str, timeout: float = 25.0, max_bytes: int = 400_000) -> dict:
    out = {"status": 0, "final_url": "", "title": "", "meta": {},
           "text_excerpt": "", "pdf": False, "error": "", "raw_meta_text": ""}
    if not url:
        out["error"] = "no URL"
        return out
    rate_limit(host_of(url), RATE_ARXIV_S if "arxiv.org" in url else RATE_DEFAULT_S)
    req = urllib.request.Request(url, headers={
        "User-Agent": "papers-mcp-backfill/1.0 (citation verifier)",
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out["status"] = resp.status
            out["final_url"] = resp.url
            ctype = resp.headers.get("Content-Type", "").lower()
            data = resp.read(max_bytes)
            if "application/pdf" in ctype or out["final_url"].lower().endswith(".pdf"):
                out["pdf"] = True
                out["text_excerpt"] = f"[PDF at {out['final_url']}]"
                return out
            try:
                html = data.decode("utf-8", errors="replace")
            except Exception:
                html = data.decode("latin-1", errors="replace")
            for m in _META_RE.finditer(html):
                name = m.group(1).lower()
                if name.startswith(("citation_", "dc.", "og:", "twitter:title", "description")):
                    out["meta"][name] = m.group(2)
            tm = _TITLE_RE.search(html)
            if tm:
                out["title"] = re.sub(r"\s+", " ", tm.group(1)).strip()
            head_m = re.search(r"<head\b[^>]*>(.*?)</head>", html, re.IGNORECASE | re.DOTALL)
            out["raw_meta_text"] = (head_m.group(1) if head_m else html)[:20000]
            visible = _SCRIPT_RE.sub("", html)
            visible = _TAG_RE.sub(" ", visible)
            visible = re.sub(r"\s+", " ", visible).strip()
            out["text_excerpt"] = visible[:8000]
    except urllib.error.HTTPError as e:
        out["status"] = e.code
        out["error"] = f"HTTP {e.code}: {e.reason}"
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    return out


_LOW_INFO_TITLES = {"sciencedirect", "redirecting", "just a moment...", "loading",
                    "checking your browser", "access denied", "page not found"}


def needs_browser(fetched: dict) -> bool:
    if not fetched:
        return False
    if fetched.get("error") and not fetched.get("status"):
        return True
    s = fetched.get("status", 0)
    if s and s >= 400:
        return True
    if s == 200 and len(fetched.get("text_excerpt") or "") < 200 and not fetched.get("meta"):
        return True
    title = (fetched.get("title") or "").strip().lower()
    if "just a moment" in title or "attention required" in title:
        return True
    if title in _LOW_INFO_TITLES:
        return True
    meta = fetched.get("meta") or {}
    if not any(k.startswith(("citation_title", "dc.title", "og:title", "citation_doi"))
               for k in meta):
        if len(fetched.get("text_excerpt") or "") < 1500:
            return True
    return False


def fetch_crossref_by_doi(doi: str) -> dict:
    """Use api.crossref.org/works/<doi> to synthesize a meta dict in the
    same shape fetch_url returns. No Cloudflare. Free, polite UA.
    """
    import json as _json
    out = {"status": 0, "final_url": "", "title": "", "meta": {},
           "text_excerpt": "", "pdf": False, "error": "", "raw_meta_text": ""}
    doi_clean = doi.lstrip("doi:").strip().rstrip(".,;)")
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi_clean, safe='/.()')}"
    rate_limit("api.crossref.org", RATE_DEFAULT_S)
    req = urllib.request.Request(url, headers={
        "User-Agent": "papers-mcp/1.0 (mailto:andrew@amb-aero.com)",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            out["status"] = resp.status
            out["final_url"] = resp.url
            data = resp.read(400_000)
        msg = _json.loads(data).get("message", {})
        title = (msg.get("title") or [""])[0]
        out["title"] = title
        meta = out["meta"]
        if title:
            meta["citation_title"] = title
        if msg.get("DOI"):
            meta["citation_doi"] = msg["DOI"]
        for a in msg.get("author", []) or []:
            family = a.get("family", "")
            given = a.get("given", "")
            if family:
                name = f"{family}, {given}".strip(", ")
                meta.setdefault("citation_author", name)
        # Stash all authors in raw_meta_text so the multi-author parser sees them all.
        author_lines = []
        for a in msg.get("author", []) or []:
            family = a.get("family", "")
            given = a.get("given", "")
            if family:
                author_lines.append(f'<meta name="citation_author" content="{family}, {given}" />')
        if (msg.get("container-title") or [""])[0]:
            ct = msg["container-title"][0]
            meta["citation_journal_title"] = ct
            author_lines.append(f'<meta name="citation_journal_title" content="{ct}" />')
        if msg.get("volume"):
            meta["citation_volume"] = msg["volume"]
            author_lines.append(f'<meta name="citation_volume" content="{msg["volume"]}" />')
        if msg.get("page"):
            pg = msg["page"]
            if "-" in pg:
                fp, lp = pg.split("-", 1)
                meta["citation_firstpage"] = fp
                meta["citation_lastpage"] = lp
                author_lines.append(f'<meta name="citation_firstpage" content="{fp}" />')
                author_lines.append(f'<meta name="citation_lastpage" content="{lp}" />')
            else:
                meta["citation_firstpage"] = pg
                author_lines.append(f'<meta name="citation_firstpage" content="{pg}" />')
        try:
            year = msg.get("issued", {}).get("date-parts", [[None]])[0][0]
            if year:
                meta["citation_publication_date"] = str(year)
                author_lines.append(f'<meta name="citation_publication_date" content="{year}" />')
        except Exception:
            pass
        if title:
            author_lines.append(f'<meta name="citation_title" content="{title}" />')
        if msg.get("DOI"):
            author_lines.append(f'<meta name="citation_doi" content="{msg["DOI"]}" />')
        out["raw_meta_text"] = "\n".join(author_lines)
        out["text_excerpt"] = title  # so needs_browser is happy
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    return out


_DOI_FROM_URL_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/(.+)$", re.IGNORECASE)


def search_arxiv_by_title(title: str, max_results: int = 5) -> Optional[str]:
    """Return an arXiv ID whose title is a substring match (either direction) of `title`."""
    if not title or len(title) < 8:
        return None
    rate_limit("export.arxiv.org", RATE_ARXIV_S)
    url = ("https://export.arxiv.org/api/query?search_query=ti:"
           + urllib.parse.quote('"' + title[:200] + '"')
           + f"&max_results={max_results}")
    req = urllib.request.Request(url, headers={"User-Agent": "papers-mcp/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read(200_000).decode("utf-8", errors="replace")
    except Exception:
        return None
    import xml.etree.ElementTree as _ET
    try:
        root = _ET.fromstring(data)
    except Exception:
        return None
    ns = {"a": "http://www.w3.org/2005/Atom"}
    norm_query = re.sub(r"[^a-z0-9 ]+", " ", title.lower())
    norm_query = re.sub(r"\s+", " ", norm_query).strip()
    for e in root.findall("a:entry", ns):
        t = (e.findtext("a:title", default="", namespaces=ns) or "").strip().replace("\n", " ")
        norm_t = re.sub(r"[^a-z0-9 ]+", " ", t.lower())
        norm_t = re.sub(r"\s+", " ", norm_t).strip()
        if norm_query and norm_t and (norm_query in norm_t or norm_t in norm_query):
            aid = (e.findtext("a:id", default="", namespaces=ns) or "").rsplit("/", 1)[-1]
            return re.sub(r"v\d+$", "", aid)
    return None


def fetch_with_fallback(url: str, *, title_hint: Optional[str] = None) -> tuple[dict, str]:
    """Return (fetched_dict, engine_label).
    engine in {urllib, browser, crossref, arxiv-search}.
    title_hint enables an arXiv title-search fallback when nothing else works.
    """
    fetched = fetch_plain(url)
    engine = "urllib"
    if needs_browser(fetched) and fetch_url_browser and playwright_available():
        rate_limit(host_of(url), RATE_DEFAULT_S)
        fetched = fetch_url_browser(url)
        engine = "browser"
    if needs_browser(fetched):
        # Fallback A: Crossref by DOI.
        doi: Optional[str] = None
        m = _DOI_FROM_URL_RE.match(url)
        if m:
            doi = m.group(1)
        else:
            doi = (fetched.get("meta", {}) or {}).get("citation_doi")
        if doi:
            cr = fetch_crossref_by_doi(doi)
            if cr.get("title"):
                return cr, "crossref"
        # Fallback B: arXiv title-search using the hint.
        if title_hint:
            aid = search_arxiv_by_title(title_hint)
            if aid:
                arx = fetch_plain(f"https://arxiv.org/abs/{aid}")
                if arx.get("meta"):
                    return arx, "arxiv-search"
    return fetched, engine


def fetch_arxiv_pdf(arxiv_id: str, dest: Path) -> tuple[bool, str]:
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    rate_limit("arxiv.org", RATE_ARXIV_S)
    req = urllib.request.Request(url, headers={"User-Agent": "papers-mcp-backfill/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        if not data.startswith(b"%PDF"):
            return False, f"not a PDF response (first bytes: {data[:8]!r})"
        dest.write_bytes(data)
        return True, f"wrote {len(data)} bytes"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def format_verify_block(verdict: str, rationale: list[str], final_url: str,
                        used_browser: bool, meta: dict, suggested_arxiv: Optional[str]) -> str:
    lines = ["", _VERIFY_MARKER, "",
             f"- **Verdict:** `{verdict}`",
             f"- **Checked:** {time.strftime('%Y-%m-%d %H:%M')}  ({'browser' if used_browser else 'urllib'})",
             f"- **Source URL:** {final_url or '(none)'}"]
    if suggested_arxiv:
        lines.append(f"- **Suggested arXiv (autofix):** {suggested_arxiv}")
    if rationale:
        lines.append("- **Rationale:**")
        for r in rationale:
            lines.append(f"  - {r}")
    if meta:
        keys = [k for k in meta if k.startswith(("citation_title", "citation_author", "citation_doi", "citation_journal_title", "dc.title", "dc.creator"))]
        if keys:
            lines.append("- **Source meta (subset):**")
            for k in sorted(keys)[:8]:
                lines.append(f"  - `{k}`: {meta[k][:200]}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------


@dataclass
class SlotResult:
    slot: str
    had_pdf: bool
    pdf_fetched: Optional[str] = None  # "arxiv" / "browser" / None
    pdf_fetch_error: Optional[str] = None
    verify_skipped: bool = False
    verdict: Optional[str] = None
    rationale: list[str] = field(default_factory=list)
    source_url: Optional[str] = None
    used_browser: bool = False
    suggested_arxiv: Optional[str] = None


def process_slot(slot: Path, *, log, reverify: bool, fetch_pdf: bool) -> SlotResult:
    rel = str(slot.relative_to(LIBRARY_ROOT))
    res = SlotResult(slot=rel, had_pdf=slot_has_pdf(slot))
    op = slot / "one_pager.md"
    text = op.read_text(errors="replace")
    ref = parse_section(text, "Reference")
    arxiv_id = extract_arxiv_id(ref)

    # PDF fetch
    if fetch_pdf and not res.had_pdf and arxiv_id:
        dst = slot / f"{slot.name}.pdf"
        log(f"  [pdf] arxiv:{arxiv_id} -> {rel}/{slot.name}.pdf")
        ok, msg = fetch_arxiv_pdf(arxiv_id, dst)
        if ok:
            res.pdf_fetched = "arxiv"
            log(f"        OK ({msg})")
        else:
            res.pdf_fetch_error = msg
            log(f"        FAIL ({msg})")

    # Verify
    if not reverify and has_verify_block(text):
        res.verify_skipped = True
        return res

    url = extract_canonical_url(ref)
    fetched: dict = {}
    engine = "none"
    title_hint = None
    m_title = re.search(r"\*([^*\n]{8,})\*", ref or "")
    if m_title:
        title_hint = re.sub(r"\s+", " ", m_title.group(1)).strip()
    if url:
        fetched, engine = fetch_with_fallback(url, title_hint=title_hint)
    elif title_hint:
        aid = search_arxiv_by_title(title_hint)
        if aid:
            fetched = fetch_plain(f"https://arxiv.org/abs/{aid}")
            engine = "arxiv-search"
    res.source_url = (fetched.get("final_url") if fetched else "") or url
    res.used_browser = (engine == "browser")

    if not ref:
        res.verdict = "NO_REFERENCE"
        res.rationale = ["one_pager has no '## Reference' section"]
    else:
        bibitem_raw = md_to_pseudo_latex(ref)
        report = metadata_check(bibitem_raw, fetched or None)
        res.verdict = report.verdict
        res.rationale = list(report.rationale)
        res.suggested_arxiv = getattr(report, "suggested_arxiv", None)

    # Save source_page.txt
    if fetched and (fetched.get("text_excerpt") or fetched.get("raw_meta_text")):
        body = [f"# Source page for {slot.name}\n",
                f"Fetched: {time.strftime('%Y-%m-%d %H:%M')}  ({'browser' if res.used_browser else 'urllib'})\n",
                f"URL: {fetched.get('final_url') or url}\n",
                f"Status: {fetched.get('status')}\n",
                f"Title: {fetched.get('title','')}\n\n## Meta tags\n"]
        for k, v in (fetched.get("meta") or {}).items():
            body.append(f"- `{k}`: {v}\n")
        body.append("\n## Visible text\n\n")
        body.append(fetched.get("text_excerpt", ""))
        (slot / "source_page.txt").write_text("".join(body))

    # Save verification block
    block = format_verify_block(
        verdict=res.verdict or "FLAG",
        rationale=res.rationale,
        final_url=res.source_url or "",
        used_browser=res.used_browser,
        meta=(fetched.get("meta") or {}) if fetched else {},
        suggested_arxiv=res.suggested_arxiv,
    )
    new_text = strip_verify_block(text).rstrip() + "\n" + block
    op.write_text(new_text)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topics", nargs="*", default=None,
                    help="Restrict to these topic names (in order). Default: all, koide first.")
    ap.add_argument("--reverify", action="store_true",
                    help="Re-run verification even if a Citation verification block already exists.")
    ap.add_argument("--no-fetch-pdf", action="store_true",
                    help="Skip PDF fetching; only verify citations.")
    ap.add_argument("--dry-run", action="store_true",
                    help="List slots that would be processed; do not fetch or write.")
    args = ap.parse_args()

    job_id = f"backfill-{time.strftime('%Y%m%d-%H%M%S')}"
    log_path = JOBS_DIR / f"{job_id}.log"
    json_path = JOBS_DIR / f"{job_id}.json"
    log_f = open(log_path, "w", buffering=1)

    def log(msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        log_f.write(line + "\n")

    log(f"job_id: {job_id}")
    log(f"library: {LIBRARY_ROOT}")
    log(f"args: {vars(args)}")
    log(f"playwright_available: {playwright_available()}")

    if args.topics:
        topics = [LIBRARY_ROOT / t for t in args.topics if (LIBRARY_ROOT / t).is_dir()]
    else:
        topics = topic_dirs()
    log(f"topics ({len(topics)}): {[t.name for t in topics]}")

    all_results: list[SlotResult] = []
    for ti, topic in enumerate(topics, 1):
        slots = slot_paths(topic)
        log(f"\n=== [{ti}/{len(topics)}] {topic.name}/  ({len(slots)} slots) ===")
        for si, slot in enumerate(slots, 1):
            rel = str(slot.relative_to(LIBRARY_ROOT))
            if args.dry_run:
                log(f"  [{si}/{len(slots)}] {rel}  (dry-run)")
                continue
            log(f"  [{si}/{len(slots)}] {rel}")
            try:
                r = process_slot(slot, log=log, reverify=args.reverify, fetch_pdf=not args.no_fetch_pdf)
                tag = "SKIP" if r.verify_skipped else (r.verdict or "?")
                if r.pdf_fetched:
                    tag += f" +pdf:{r.pdf_fetched}"
                log(f"    -> {tag}")
                all_results.append(r)
            except Exception as e:  # noqa: BLE001
                log(f"    -> ERROR: {type(e).__name__}: {e}")

    # Summary
    by_verdict: dict[str, int] = {}
    pdf_fetched = sum(1 for r in all_results if r.pdf_fetched)
    pdf_failed = sum(1 for r in all_results if r.pdf_fetch_error)
    skipped = sum(1 for r in all_results if r.verify_skipped)
    for r in all_results:
        v = "SKIP" if r.verify_skipped else (r.verdict or "?")
        by_verdict[v] = by_verdict.get(v, 0) + 1
    log("\n=== SUMMARY ===")
    log(f"slots processed: {len(all_results)}")
    log(f"PDFs fetched: {pdf_fetched}")
    log(f"PDF fetch failed: {pdf_failed}")
    log(f"verify-skipped (already done): {skipped}")
    log("verdicts: " + ", ".join(f"{k}={v}" for k, v in sorted(by_verdict.items())))

    summary = {
        "job_id": job_id,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "library": str(LIBRARY_ROOT),
        "topics": [t.name for t in topics],
        "totals": {
            "slots_processed": len(all_results),
            "pdf_fetched": pdf_fetched,
            "pdf_failed": pdf_failed,
            "verify_skipped": skipped,
            "by_verdict": by_verdict,
        },
        "results": [
            {
                "slot": r.slot,
                "had_pdf": r.had_pdf,
                "pdf_fetched": r.pdf_fetched,
                "pdf_fetch_error": r.pdf_fetch_error,
                "verify_skipped": r.verify_skipped,
                "verdict": r.verdict,
                "rationale": r.rationale,
                "source_url": r.source_url,
                "used_browser": r.used_browser,
                "suggested_arxiv": r.suggested_arxiv,
            }
            for r in all_results
        ],
    }
    json_path.write_text(json.dumps(summary, indent=2))
    log(f"summary JSON: {json_path}")
    log_f.close()
    print(json_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
