#!/usr/bin/env python3
"""Validate every PDF that was fetched via arxiv-search. For each slot, compare
the arXiv abstract page's title+authors against the bib reference in one_pager.md.
If the match is weak (no shared surname AND no title substring containment),
DELETE the PDF — it was a false positive from the loose title-search.

Reads the most recent fetch-*.json and only checks slots with via='arxiv-search:*'.
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LIBRARY_ROOT = Path("/Users/Drew/Desktop/Academic/library")
JOBS_DIR = Path("/tmp/papers-mcp-jobs")

_RATE_S = 3.0
_last = 0.0


def rate_limit() -> None:
    global _last
    dt = time.time() - _last
    if dt < _RATE_S:
        time.sleep(_RATE_S - dt)
    _last = time.time()


_META_RE = re.compile(
    r'<meta\b[^>]*?(?:name|property)\s*=\s*["\']([^"\']+)["\'][^>]*?content\s*=\s*["\']([^"\']*)["\']',
    re.IGNORECASE,
)


def fetch_arxiv_meta(arxiv_id: str) -> dict[str, list[str]]:
    rate_limit()
    url = f"https://arxiv.org/abs/{arxiv_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "papers-mcp/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read(400_000).decode("utf-8", errors="replace")
    except Exception:
        return {}
    out: dict[str, list[str]] = {}
    for m in _META_RE.finditer(data):
        k = m.group(1).lower()
        v = html.unescape(m.group(2)).strip()
        if v:
            out.setdefault(k, []).append(v)
    return out


def normalize(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def surnames_from_arxiv_meta(meta: dict[str, list[str]]) -> set[str]:
    out = set()
    for a in meta.get("citation_author", []):
        if "," in a:
            sn = a.split(",", 1)[0].strip()
        else:
            sn = a.strip().split()[-1] if a.strip() else ""
        sn = re.sub(r"[^a-zA-ZÀ-ſ]", "", sn).lower()
        if sn:
            out.add(sn)
    return out


def parse_section(text: str, header: str) -> str:
    pat = rf"^## {re.escape(header)}\s*\n(.+?)(?=^## |\Z)"
    m = re.search(pat, text, re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else ""


def title_from_ref(ref: str) -> str:
    m = re.search(r"\*([^*\n]{8,})\*", ref)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def surnames_from_ref(ref: str) -> set[str]:
    """Heuristic surname extractor: take everything before the first markdown italic
    block (the title) or before the first `\\textit/\\emph` LaTeX italic, whichever
    comes earliest. Tokenize on commas/and/et-al.
    """
    out: set[str] = set()
    if not ref:
        return out
    # Find author region boundaries.
    boundaries = []
    m = re.search(r"\*[^*\n]{4,}\*", ref)
    if m:
        boundaries.append(m.start())
    m = re.search(r"\\(?:textit|emph)\s*\{", ref)
    if m:
        boundaries.append(m.start())
    head = ref[:min(boundaries)] if boundaries else ref
    head = re.sub(r"\\\w+\{([^}]*)\}", r"\1", head)
    head = head.replace("{", "").replace("}", "")
    has_etal = bool(re.search(r"\bet\s+al\.?", head, re.IGNORECASE))
    head = re.sub(r"\bet\s+al\.?", "", head, flags=re.IGNORECASE)
    tokens = re.split(r",|\band\b", head, flags=re.IGNORECASE)
    for t in tokens:
        t = t.strip().strip(".")
        if not t:
            continue
        words = t.split()
        if not words:
            continue
        sn = words[-1]
        sn = re.sub(r"[^a-zA-ZÀ-ſ]", "", sn).lower()
        if sn and len(sn) >= 3:
            out.add(sn)
    return out


def slot_year(slot_name: str) -> int | None:
    m = re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", slot_name)
    return int(m.group(1)) if m else None


def arxiv_year(arxiv_id: str) -> int | None:
    m = re.match(r"(\d{2})(\d{2})\.", arxiv_id)
    if m:
        yy = int(m.group(1))
        return 2000 + yy if yy < 90 else 1900 + yy
    m = re.match(r"[a-z\-]+/(\d{2})(\d{2})", arxiv_id)
    if m:
        yy = int(m.group(1))
        return 2000 + yy if yy < 90 else 1900 + yy
    return None


def validate_match(slot: Path, arxiv_id: str) -> tuple[bool, str]:
    # Quick year sanity.
    sy = slot_year(slot.name)
    ay = arxiv_year(arxiv_id)
    if sy and ay and abs(sy - ay) > 1:
        return False, f"year mismatch (slot={sy}, arxiv={ay})"
    op = slot / "one_pager.md"
    ref = parse_section(op.read_text(errors="replace"), "Reference")
    bib_title = title_from_ref(ref)
    bib_surnames = surnames_from_ref(ref)
    meta = fetch_arxiv_meta(arxiv_id)
    if not meta:
        return False, "could not fetch arXiv meta"
    src_title = (meta.get("citation_title", [""])[0] or "").strip()
    src_surnames = surnames_from_arxiv_meta(meta)
    nt_b = normalize(bib_title)
    nt_s = normalize(src_title)
    title_match = bool(nt_b and nt_s and (nt_b in nt_s or nt_s in nt_b))
    author_overlap = bool(bib_surnames & src_surnames)
    if title_match and author_overlap:
        return True, f"title+author match (bib_surnames={sorted(bib_surnames)}, src_surnames={sorted(src_surnames)})"
    if title_match and not bib_surnames:
        return True, "title match (bib has no extractable surnames)"
    reasons = []
    if not title_match:
        reasons.append(f"title mismatch: bib='{nt_b[:60]}…' vs src='{nt_s[:60]}…'")
    if not author_overlap and bib_surnames and src_surnames:
        reasons.append(f"no author overlap: bib={sorted(bib_surnames)} vs src={sorted(src_surnames)[:5]}…")
    return False, "; ".join(reasons) or "weak match"


def main() -> int:
    files = sorted(JOBS_DIR.glob("fetch-*.json"))
    if not files:
        sys.exit("no fetch JSON found")
    bf = json.loads(files[-1].read_text())
    targets = [r for r in bf["results"]
               if r["status"] == "fetched" and (r.get("via") or "").startswith("arxiv-search")]
    print(f"validating {len(targets)} arxiv-search fetches")
    print()
    kept = 0
    removed = 0
    for r in targets:
        slot = LIBRARY_ROOT / r["slot"]
        via = r["via"]
        aid = via.split(":", 1)[1]
        ok, reason = validate_match(slot, aid)
        pdf = slot / f"{slot.name}.pdf"
        if ok:
            kept += 1
            print(f"  KEEP  {r['slot']}  ({reason[:100]})")
        else:
            if pdf.is_file():
                pdf.unlink()
            removed += 1
            print(f"  REMOVE {r['slot']}  ({reason[:160]})")
    print()
    print(f"=== kept: {kept}, removed: {removed} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
