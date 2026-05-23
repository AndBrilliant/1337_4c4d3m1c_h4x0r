#!/usr/bin/env python3
"""For every library slot without a PDF, try a chain of strategies to download
one and place it at <slot>/<slot>.pdf:

  1. arXiv direct — if the reference contains an arXiv ID.
  2. Crossref by DOI — extract DOI from ref or refer to source_page.txt, query
     api.crossref.org/works/<doi> to obtain a candidate arxiv-eprint or PDF link.
  3. arXiv title-search — search arxiv API by the paper title (preprint backup).
  4. Browser (Playwright) → publisher page → "PDF" link click — Cloudflare-safe.

Writes a JSON summary to /tmp/papers-mcp-jobs/fetch-<ts>.json.

Idempotent: skips slots that now have a PDF.
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
from pathlib import Path
from typing import Optional

LIBRARY_ROOT = Path("/Users/Drew/claude/paper-tools/literature")
CHECK_CITATIONS_DIR = Path("/Users/Drew/claude/paper-tools/check-citations")
JOBS_DIR = Path("/tmp/papers-mcp-jobs")
JOBS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(CHECK_CITATIONS_DIR))
try:
    from browser_fetch import fetch_url_browser, playwright_available  # type: ignore
except Exception:
    fetch_url_browser = None
    playwright_available = lambda: False

_ARXIV_RE = re.compile(r"(?:arXiv\s*:?\s*)([a-z\-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
_RATE_DEFAULT_S = 1.0
_RATE_ARXIV_S = 3.0
_last_fetch: dict[str, float] = {}


def rate_limit(host: str, min_s: float) -> None:
    t = _last_fetch.get(host, 0.0)
    dt = time.time() - t
    if dt < min_s:
        time.sleep(min_s - dt)
    _last_fetch[host] = time.time()


def slot_paths() -> list[Path]:
    out = []
    for topic in sorted(LIBRARY_ROOT.iterdir()):
        if not topic.is_dir() or topic.name.startswith(".") or topic.name == "OLD":
            continue
        for s in sorted(topic.iterdir()):
            if s.is_dir() and (s / "one_pager.md").is_file():
                out.append(s)
    return out


def parse_section(text: str, header: str) -> str:
    pat = rf"^## {re.escape(header)}\s*\n(.+?)(?=^## |\Z)"
    m = re.search(pat, text, re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else ""


def extract_arxiv(ref: str) -> Optional[str]:
    m = _ARXIV_RE.search(ref or "")
    return m.group(1) if m else None


def extract_doi(ref: str) -> Optional[str]:
    m = _DOI_RE.search(ref or "")
    return m.group(0).rstrip(".,;)") if m else None


def title_hint_from_ref(ref: str) -> Optional[str]:
    m = re.search(r"\*([^*\n]{8,})\*", ref or "")
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip()


def write_pdf(slot: Path, data: bytes) -> tuple[bool, str]:
    if not data or not data.startswith(b"%PDF"):
        return False, f"not a PDF (first bytes: {data[:8]!r})"
    dst = slot / f"{slot.name}.pdf"
    dst.write_bytes(data)
    return True, f"wrote {len(data)} bytes -> {dst.name}"


def try_arxiv(slot: Path, arxiv_id: str) -> tuple[bool, str]:
    rate_limit("arxiv.org", _RATE_ARXIV_S)
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "papers-mcp/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        return write_pdf(slot, data)
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def crossref_for_doi(doi: str) -> Optional[dict]:
    rate_limit("api.crossref.org", _RATE_DEFAULT_S)
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='/.()')}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "papers-mcp/1.0 (mailto:andrew@amb-aero.com)",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read(400_000)).get("message")
    except Exception:
        return None


def try_crossref(slot: Path, doi: str) -> tuple[bool, str]:
    msg = crossref_for_doi(doi)
    if not msg:
        return False, "crossref lookup failed"
    # Look for an arXiv eprint exposed by Crossref.
    relation = msg.get("relation", {}) or {}
    candidates = []
    for key in ("has-preprint", "is-preprint-of", "is-version-of"):
        for r in relation.get(key, []) or []:
            if isinstance(r, dict) and r.get("id"):
                v = r["id"]
                if "arxiv" in v.lower():
                    aid = re.sub(r".*arxiv[:/]*", "", v, flags=re.IGNORECASE)
                    candidates.append(aid.strip())
    # Try arXiv from Crossref candidates first.
    for aid in candidates:
        ok, msg2 = try_arxiv(slot, aid)
        if ok:
            return True, f"crossref→arxiv:{aid} ({msg2})"
    # Try direct PDF links from Crossref `link` array (often paywalled).
    for link in (msg.get("link") or []):
        u = link.get("URL")
        if not u:
            continue
        if "pdf" in (link.get("content-type") or "").lower() or u.lower().endswith(".pdf"):
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "papers-mcp/1.0"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = resp.read()
                ok, m2 = write_pdf(slot, data)
                if ok:
                    return True, f"crossref→pdflink ({m2})"
            except Exception:
                continue
    return False, "no usable preprint/PDF link in Crossref record"


def search_arxiv_by_title(title: str) -> Optional[str]:
    if not title or len(title) < 8:
        return None
    rate_limit("export.arxiv.org", _RATE_ARXIV_S)
    url = ("https://export.arxiv.org/api/query?search_query=ti:"
           + urllib.parse.quote('"' + title[:200] + '"')
           + "&max_results=5")
    req = urllib.request.Request(url, headers={"User-Agent": "papers-mcp/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read(200_000).decode("utf-8", errors="replace")
    except Exception:
        return None
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(data)
    except Exception:
        return None
    ns = {"a": "http://www.w3.org/2005/Atom"}
    norm_q = re.sub(r"[^a-z0-9 ]+", " ", title.lower())
    norm_q = re.sub(r"\s+", " ", norm_q).strip()
    for e in root.findall("a:entry", ns):
        t = (e.findtext("a:title", default="", namespaces=ns) or "").strip().replace("\n", " ")
        norm_t = re.sub(r"[^a-z0-9 ]+", " ", t.lower())
        norm_t = re.sub(r"\s+", " ", norm_t).strip()
        if norm_q and norm_t and (norm_q in norm_t or norm_t in norm_q):
            aid = (e.findtext("a:id", default="", namespaces=ns) or "").rsplit("/", 1)[-1]
            return re.sub(r"v\d+$", "", aid)
    return None


def try_browser_publisher(slot: Path, doi: Optional[str]) -> tuple[bool, str]:
    if not (fetch_url_browser and playwright_available()):
        return False, "playwright unavailable"
    if not doi:
        return False, "no DOI for publisher download"
    url = f"https://doi.org/{doi}"
    rate_limit(urllib.parse.urlsplit(url).hostname or "doi.org", _RATE_DEFAULT_S)
    download_dir = slot
    try:
        out = fetch_url_browser(url, download_dir=download_dir, key=slot.name)
    except Exception as e:  # noqa: BLE001
        return False, f"browser error: {e}"
    if out.get("downloaded") and out.get("pdf_path"):
        # browser_fetch already saved to slot/<slot>.pdf
        return True, f"browser publisher download ({Path(out['pdf_path']).name})"
    err = out.get("error") or "no PDF link clickable"
    return False, f"browser: {err[:200]}"


def process_slot(slot: Path) -> dict:
    rel = str(slot.relative_to(LIBRARY_ROOT))
    if (slot / f"{slot.name}.pdf").is_file():
        return {"slot": rel, "status": "have_pdf", "via": None}
    ref = parse_section((slot / "one_pager.md").read_text(errors="replace"), "Reference")
    arxiv_id = extract_arxiv(ref)
    doi = extract_doi(ref)
    title_hint = title_hint_from_ref(ref)

    # 1. arxiv direct
    if arxiv_id:
        ok, msg = try_arxiv(slot, arxiv_id)
        if ok:
            return {"slot": rel, "status": "fetched", "via": f"arxiv:{arxiv_id}", "msg": msg}
    # 2. Crossref → arxiv-or-pdf
    if doi:
        ok, msg = try_crossref(slot, doi)
        if ok:
            return {"slot": rel, "status": "fetched", "via": "crossref", "msg": msg}
    # 3. arXiv title-search
    if title_hint:
        aid = search_arxiv_by_title(title_hint)
        if aid:
            ok, msg = try_arxiv(slot, aid)
            if ok:
                return {"slot": rel, "status": "fetched", "via": f"arxiv-search:{aid}", "msg": msg}
    # 4. Browser publisher download
    if doi:
        ok, msg = try_browser_publisher(slot, doi)
        if ok:
            return {"slot": rel, "status": "fetched", "via": "browser", "msg": msg}
    return {"slot": rel, "status": "unfindable",
            "tried": {"arxiv_id": arxiv_id, "doi": doi, "title_hint": title_hint}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="Stop after N slots (0 = no limit)")
    ap.add_argument("--topic", default="", help="Restrict to this topic")
    args = ap.parse_args()

    job_id = f"fetch-{time.strftime('%Y%m%d-%H%M%S')}"
    log_path = JOBS_DIR / f"{job_id}.log"
    json_path = JOBS_DIR / f"{job_id}.json"
    log_f = open(log_path, "w", buffering=1)

    def log(msg: str) -> None:
        log_f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

    log(f"job_id: {job_id}")
    log(f"playwright_available: {playwright_available()}")

    all_slots = slot_paths()
    if args.topic:
        all_slots = [s for s in all_slots if s.parent.name == args.topic]
    missing = [s for s in all_slots if not (s / f"{s.name}.pdf").is_file()]
    log(f"total slots: {len(all_slots)}; missing PDFs: {len(missing)}")

    results = []
    for i, slot in enumerate(missing, 1):
        if args.limit and i > args.limit:
            break
        log(f"[{i}/{len(missing)}] {slot.relative_to(LIBRARY_ROOT)}")
        try:
            r = process_slot(slot)
        except Exception as e:  # noqa: BLE001
            r = {"slot": str(slot.relative_to(LIBRARY_ROOT)), "status": "error", "error": str(e)}
        log(f"  -> {r.get('status')} via={r.get('via')} msg={(r.get('msg') or r.get('tried') or '')!s:.200}")
        results.append(r)

    by_status: dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    log("=== SUMMARY ===")
    log(f"processed: {len(results)}")
    log(f"by status: {by_status}")
    json_path.write_text(json.dumps({"job_id": job_id, "by_status": by_status, "results": results}, indent=2))
    log(f"summary JSON: {json_path}")
    log_f.close()
    print(json_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
