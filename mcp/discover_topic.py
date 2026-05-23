#!/usr/bin/env python3
"""Discover papers on a given physics topic that aren't yet in the library.

Workflow:
  1. Read existing arXiv IDs + DOIs + slot-name-shaped fingerprints from the
     target topic folder.
  2. Query INSPIRE-HEP and arXiv for papers matching --query.
  3. Dedupe candidates against (1) by arXiv ID, DOI, and normalized title.
  4. For each new candidate: pick a slot name (firstauthor_year[_suffix]),
     fetch the PDF from arXiv, write a stub one_pager.md.
  5. Append summary JSON to /tmp/papers-mcp-jobs/discover-<ts>.json.

Default: dry-run, just prints the candidate list.  Pass --add to actually
materialize new slots.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

LIBRARY_ROOT = Path("/Users/Drew/claude/paper-tools/literature")
JOBS_DIR = Path("/tmp/papers-mcp-jobs")
JOBS_DIR.mkdir(parents=True, exist_ok=True)

_ARXIV_ID_RE = re.compile(r"(?:arXiv\s*:?\s*)([a-z\-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
_RATE_DEFAULT_S = 1.0
_RATE_ARXIV_S = 3.0
_RATE_INSPIRE_S = 0.5
_last_fetch: dict[str, float] = {}


def rate_limit(host: str, min_s: float) -> None:
    t = _last_fetch.get(host, 0.0)
    dt = time.time() - t
    if dt < min_s:
        time.sleep(min_s - dt)
    _last_fetch[host] = time.time()


def normalize_title(t: str) -> str:
    t = re.sub(r"[^a-z0-9]+", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def existing_fingerprints(topic: str) -> tuple[set[str], set[str], set[str], set[str]]:
    """Return (arxiv_ids, dois, normalized_titles, slot_names) across the WHOLE
    library — dedup must be global so a paper sitting in symmetry_math/ doesn't
    get re-added under koide/.  slot_names only collects from the target topic
    (used to disambiguate when creating new slots).
    """
    arxiv: set[str] = set()
    dois: set[str] = set()
    titles: set[str] = set()
    slots: set[str] = set()
    if not LIBRARY_ROOT.is_dir():
        return arxiv, dois, titles, slots
    for topic_dir in sorted(LIBRARY_ROOT.iterdir()):
        if not topic_dir.is_dir() or topic_dir.name.startswith(".") or topic_dir.name == "OLD":
            continue
        for slot in sorted(topic_dir.iterdir()):
            if not slot.is_dir():
                continue
            op = slot / "one_pager.md"
            if not op.is_file():
                continue
            if topic_dir.name == topic:
                slots.add(slot.name)
            text = op.read_text(errors="replace")
            for m in _ARXIV_ID_RE.finditer(text):
                arxiv.add(m.group(1).lower())
            for m in _DOI_RE.finditer(text):
                dois.add(m.group(0).rstrip(".,;)").lower())
            h = re.search(r"^# .+?—\s*(.+)$", text, re.MULTILINE)
            if h:
                titles.add(normalize_title(h.group(1)))
            ref_m = re.search(r"^## Reference\s*\n(.+?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
            if ref_m:
                for tm in re.finditer(r"\*([^*\n]{8,})\*", ref_m.group(1)):
                    titles.add(normalize_title(tm.group(1)))
    return arxiv, dois, titles, slots


def query_arxiv(q: str, max_results: int = 200) -> list[dict]:
    rate_limit("export.arxiv.org", _RATE_ARXIV_S)
    url = (f"https://export.arxiv.org/api/query?search_query={urllib.parse.quote(q)}"
           f"&max_results={max_results}&sortBy=relevance")
    req = urllib.request.Request(url, headers={"User-Agent": "papers-mcp/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read(1_000_000).decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        print(f"  arXiv error: {e}", file=sys.stderr)
        return []
    try:
        root = ET.fromstring(data)
    except Exception:
        return []
    ns = {"a": "http://www.w3.org/2005/Atom",
          "arxiv": "http://arxiv.org/schemas/atom"}
    out = []
    for e in root.findall("a:entry", ns):
        aid = (e.findtext("a:id", default="", namespaces=ns) or "").rsplit("/", 1)[-1]
        aid = re.sub(r"v\d+$", "", aid)
        title = (e.findtext("a:title", default="", namespaces=ns) or "").strip().replace("\n", " ")
        title = re.sub(r"\s+", " ", title)
        pub = (e.findtext("a:published", default="", namespaces=ns) or "")[:10]
        authors = [a.findtext("a:name", default="", namespaces=ns) for a in e.findall("a:author", ns)]
        doi = e.findtext("arxiv:doi", default="", namespaces=ns) or ""
        out.append({
            "arxiv_id": aid,
            "title": title,
            "authors": [a for a in authors if a],
            "date": pub,
            "year": pub[:4] if pub else "",
            "doi": doi,
            "source": "arxiv",
        })
    return out


def query_inspire(q: str, size: int = 250) -> list[dict]:
    rate_limit("inspirehep.net", _RATE_INSPIRE_S)
    url = (f"https://inspirehep.net/api/literature?q={urllib.parse.quote(q)}"
           f"&size={size}&fields=titles,authors,arxiv_eprints,dois,publication_info")
    req = urllib.request.Request(url, headers={
        "User-Agent": "papers-mcp/1.0",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read(5_000_000))
    except Exception as e:  # noqa: BLE001
        print(f"  INSPIRE error: {e}", file=sys.stderr)
        return []
    out = []
    for hit in data.get("hits", {}).get("hits", []) or []:
        meta = hit.get("metadata", {}) or {}
        titles = meta.get("titles") or []
        title = titles[0].get("title", "") if titles else ""
        authors = []
        for a in meta.get("authors") or []:
            full = a.get("full_name", "")
            if "," in full:
                last, first = full.split(",", 1)
                authors.append(f"{first.strip()} {last.strip()}")
            else:
                authors.append(full)
        eprints = meta.get("arxiv_eprints") or []
        aid = (eprints[0].get("value") if eprints else "") or ""
        dois = meta.get("dois") or []
        doi = (dois[0].get("value") if dois else "") or ""
        pi = meta.get("publication_info") or []
        venue = ""
        year = ""
        if pi:
            j = pi[0]
            venue = j.get("journal_title") or j.get("title") or ""
            year = str(j.get("year") or "")
        out.append({
            "arxiv_id": aid,
            "title": title,
            "authors": authors,
            "year": year,
            "venue": venue,
            "doi": doi,
            "source": "inspire",
        })
    return out


_NAME_PUNCT_RE = re.compile(r"[^a-zA-ZÀ-ſ]+")


def first_surname(author_name: str) -> str:
    if "," in author_name:
        sn = author_name.split(",", 1)[0]
    else:
        parts = author_name.strip().split()
        sn = parts[-1] if parts else ""
    sn = _NAME_PUNCT_RE.sub("", sn).lower()
    return sn


def slot_name_for(candidate: dict, existing_slots: set[str]) -> str:
    authors = candidate.get("authors") or []
    if not authors:
        base = "unknown"
    elif len(authors) <= 2:
        base = "_".join(first_surname(a) for a in authors if first_surname(a))
    else:
        base = first_surname(authors[0])
    year = candidate.get("year") or ""
    name = f"{base}_{year}" if year else base
    if name not in existing_slots:
        return name
    suffix = "a"
    while f"{name}_{suffix}" in existing_slots:
        suffix = chr(ord(suffix) + 1)
    return f"{name}_{suffix}"


_ONE_PAGER_TEMPLATE = """# {h1}

## Reference
{authors}, *{title}*{venue_part}{tail}

## Source
Discovered via {source} ({query!r}, fetched {date}); tier pending.

## Beyond-abstract summary
**Stub** — auto-imported by discover_topic.py. Full summary not yet written.

## Status
{status}
"""


def fmt_authors(names: list[str]) -> str:
    names = [n for n in (names or []) if n.strip()]
    if not names:
        return "Unknown author"
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    if len(names) <= 5:
        return ", ".join(names[:-1]) + ", and " + names[-1]
    return ", ".join(names[:3]) + ", et al."


def build_one_pager(candidate: dict, query: str, source: str) -> str:
    title = candidate.get("title", "").strip()
    authors_str = fmt_authors(candidate.get("authors") or [])
    venue = candidate.get("venue", "")
    year = candidate.get("year", "")
    venue_part = ""
    if venue and year:
        venue_part = f", **{venue} ({year})**"
    elif venue:
        venue_part = f", **{venue}**"
    elif year:
        venue_part = f" ({year})"
    tail_bits = []
    if candidate.get("arxiv_id"):
        tail_bits.append(f"arXiv:{candidate['arxiv_id']}")
    if candidate.get("doi"):
        tail_bits.append(f"doi:{candidate['doi']}")
    tail = "; " + "; ".join(tail_bits) + "." if tail_bits else "."
    short = title[:80]
    h1 = f"{(candidate.get('authors') or ['Unknown'])[0].split()[-1]} {year or ''} — {short}".strip()
    return _ONE_PAGER_TEMPLATE.format(
        h1=h1,
        authors=authors_str,
        title=title,
        venue_part=venue_part,
        tail=tail,
        source=source,
        query=query,
        date=time.strftime("%Y-%m-%d"),
        status="preprint" if candidate.get("arxiv_id") else "pending",
    )


def try_arxiv_pdf(slot: Path, arxiv_id: str) -> tuple[bool, str]:
    rate_limit("arxiv.org", _RATE_ARXIV_S)
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "papers-mcp/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        if not data.startswith(b"%PDF"):
            return False, f"not a PDF (first bytes: {data[:8]!r})"
        dst = slot / f"{slot.name}.pdf"
        dst.write_bytes(data)
        return True, f"wrote {len(data)} bytes"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True, help="Library topic folder, e.g. koide")
    ap.add_argument("--query", action="append", required=True,
                    help="Search term. Can be passed multiple times; results are unioned. "
                         "For arXiv-style use 'ti:Koide' or 'abs:\"Koide formula\"'. "
                         "INSPIRE will get a relaxed version too.")
    ap.add_argument("--max-arxiv", type=int, default=200)
    ap.add_argument("--max-inspire", type=int, default=250)
    ap.add_argument("--add", action="store_true",
                    help="Materialize new slots + fetch PDFs. Default: dry-run, just list.")
    ap.add_argument("--limit", type=int, default=0,
                    help="If --add, cap how many new slots to materialize (0 = no cap).")
    args = ap.parse_args()

    job_id = f"discover-{args.topic}-{time.strftime('%Y%m%d-%H%M%S')}"
    print(f"job_id: {job_id}")
    print(f"topic: {args.topic}")
    print(f"queries: {args.query}")

    arxiv_ids, dois, titles, slots = existing_fingerprints(args.topic)
    print(f"existing: {len(slots)} slots, {len(arxiv_ids)} arxiv IDs, {len(dois)} DOIs, {len(titles)} titles")

    candidates: list[dict] = []
    seen_keys: set[str] = set()
    for q in args.query:
        for c in query_arxiv(q, max_results=args.max_arxiv):
            k = c["arxiv_id"].lower() or normalize_title(c["title"])
            if k and k not in seen_keys:
                seen_keys.add(k)
                candidates.append(c)
        for c in query_inspire(q, size=args.max_inspire):
            k = c["arxiv_id"].lower() or (c.get("doi") or "").lower() or normalize_title(c["title"])
            if k and k not in seen_keys:
                seen_keys.add(k)
                candidates.append(c)
    print(f"total candidates (deduped): {len(candidates)}")

    # Build a list of mandatory keywords drawn from the queries — drop common
    # search-syntax prefixes (ti:, abs:, t, a, …) and the connectives.
    kw_tokens = set()
    for q in args.query:
        for tok in re.split(r"\s+", q):
            tok = re.sub(r"^[a-z]{1,4}:", "", tok)
            tok = tok.strip(' "\'')
            if tok and len(tok) >= 4 and tok.lower() not in {"and", "or", "not"}:
                kw_tokens.add(tok.lower())

    new_candidates: list[dict] = []
    dropped_irrelevant = 0
    for c in candidates:
        aid = (c.get("arxiv_id") or "").lower()
        doi = (c.get("doi") or "").lower()
        nt = normalize_title(c.get("title") or "")
        if aid and aid in arxiv_ids:
            continue
        if doi and doi in dois:
            continue
        if nt and any(nt in t or t in nt for t in titles if len(t) > 12):
            continue
        # Topic-relevance check: at least one keyword token must appear in the title.
        if kw_tokens and not any(k in nt for k in kw_tokens):
            dropped_irrelevant += 1
            continue
        new_candidates.append(c)
    if dropped_irrelevant:
        print(f"(dropped {dropped_irrelevant} candidates whose title contained none of {sorted(kw_tokens)})")
    print(f"new candidates (not in library): {len(new_candidates)}")
    print()

    if not args.add:
        print("--- listing first 40 new candidates (use --add to materialize) ---")
        for c in new_candidates[:40]:
            print(f"  [{c['source']}] arXiv:{c.get('arxiv_id') or '—':<18}  {c.get('year','—')}  "
                  f"{(c.get('authors') or ['?'])[0][:30]:<30}  {c.get('title','')[:80]}")
        if len(new_candidates) > 40:
            print(f"  ... and {len(new_candidates) - 40} more")
        return 0

    print("=== Materializing new slots ===")
    added = 0
    skipped = []
    materialized = []
    topic_dir = LIBRARY_ROOT / args.topic
    topic_dir.mkdir(parents=True, exist_ok=True)
    for c in new_candidates:
        if args.limit and added >= args.limit:
            break
        sn = slot_name_for(c, slots)
        slot = topic_dir / sn
        if slot.exists():
            skipped.append((sn, "slot already exists (race)"))
            continue
        slot.mkdir(parents=True)
        op_text = build_one_pager(c, args.query[0], c["source"])
        (slot / "one_pager.md").write_text(op_text)
        pdf_status = "no arxiv id"
        if c.get("arxiv_id"):
            ok, msg = try_arxiv_pdf(slot, c["arxiv_id"])
            pdf_status = msg if ok else f"FAILED: {msg}"
        added += 1
        slots.add(sn)
        materialized.append({"slot": f"{args.topic}/{sn}", "candidate": c, "pdf": pdf_status})
        print(f"  + {args.topic}/{sn}  ({pdf_status[:60]})")

    summary = {
        "job_id": job_id,
        "topic": args.topic,
        "queries": args.query,
        "existing_slots": len(slots) - added,
        "candidates_total": len(candidates),
        "candidates_new": len(new_candidates),
        "added": added,
        "skipped": skipped,
        "materialized": materialized,
    }
    json_path = JOBS_DIR / f"{job_id}.json"
    json_path.write_text(json.dumps(summary, indent=2))
    print()
    print(f"=== added: {added} ===")
    print(f"summary: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
