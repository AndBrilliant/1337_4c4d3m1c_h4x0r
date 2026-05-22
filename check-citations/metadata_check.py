"""Deterministic metadata-match checks for the citation verifier.

The point of this module: the LLMs were being asked "do the authors / title /
year in the bibitem match what the evidence reports?"  That's a fuzzy
judgment call the models can hallucinate either way on.  Replace it with code
that the human (Drew) and the audit-trail author (Claude) can both reason
about deterministically:

    - DOI match  : exact string equality after case-folding + whitespace strip
    - arXiv ID   : exact equality of the id form (no version suffix), lower-case
    - Title      : aggressive normalization (strip LaTeX / punctuation /
                   whitespace, lowercase) then SUBSTRING containment in either
                   direction (handles "Title" vs "Title: Subtitle" gracefully
                   without committing to a brittle similarity threshold)

Each rule is justified in its docstring.  Rejected alternatives are noted so
the next reader (or LLM) doesn't quietly reintroduce them.

The module is pure: no network, no LLM calls.  Inputs are the bibitem raw
text and a `fetched_meta` dict (the page-meta scrape produced by
`fetch_url()` in check_citations.py).  Outputs are a `MetadataReport`
dataclass that the main script either prints to the report or hands to LLMs
as a pre-computed input.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable


# ── Extraction patterns ─────────────────────────────────────────────────
# Both extractors run over the bibitem RAW text. Conventions vary across
# bibtex styles, so the patterns are deliberately wide.

# DOI: 10.<registrant>/<suffix>. RFC 3986 allows almost any printable
# character in the suffix, but in practice DOIs avoid spaces and quote
# characters. We restrict to the practical character class to avoid
# overrunning into trailing prose.
DOI_RE = re.compile(
    r"\b10\.\d{4,9}/[\w.\-;()/<>+\[\]:#]+",
    re.IGNORECASE,
)

# arXiv: pre-2007 IDs look like "hep-ph/9712333", post-2007 like "1212.0572"
# or "2410.02736" or "2601.15812". We accept both. The optional "v\d+" tail
# is stripped during normalization.
ARXIV_RE = re.compile(
    r"(?:arXiv\s*:?\s*)([a-z\-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?",
    re.IGNORECASE,
)

# Title from a bibitem: we look for the first \emph{...} or \textit{...} or
# the second \newblock block (a common natbib convention: authors \newblock
# title \newblock venue). Fall back to any italicized run.
TEX_TITLE_PATS = [
    re.compile(r"\\newblock\s*([^\n\\]+?)(?=\.\s*\\newblock|\\newblock|$)", re.DOTALL),
    re.compile(r"\\emph\{([^}]+)\}"),
    re.compile(r"\\textit\{([^}]+)\}"),
]


# ── Normalization ───────────────────────────────────────────────────────

def _strip_latex(s: str) -> str:
    """Remove LaTeX markup that survives in titles.

    Why: bib entries carry things like ``{K}oide``, ``\\emph{...}``,
    ``\\\"{o}``, math mode ``$Q=2/3$``, escaped ampersands.  None of these
    appear in HTML titles fetched from arXiv / Crossref, so we strip them
    before comparing.  We deliberately do NOT try to render math; we drop it.
    """
    # Math mode → drop completely (titles with math are rare; comparing math
    # across rendering layers is unreliable; better to omit and rely on the
    # rest of the title to match).
    s = re.sub(r"\$[^$]+\$", " ", s)
    # \command{arg} → arg (keep the argument).
    s = re.sub(r"\\[a-zA-Z]+\*?\{([^{}]*)\}", r"\1", s)
    # Leftover \command (no braces) → drop.
    s = re.sub(r"\\[a-zA-Z]+\*?", " ", s)
    # Bare braces → drop.
    s = s.replace("{", "").replace("}", "")
    return s


def normalize_title(s: str) -> str:
    """Aggressive title normalization for substring-containment matching.

    Justification of each step:
      - Decode HTML entities (``&amp;`` → ``&``, ``&#34;`` → ``"``) so the
        scraped title and the bib title are on equal footing.
      - Strip LaTeX (see _strip_latex).
      - Lowercase everything.  Different sources use Title Case, sentence
        case, ALL CAPS interchangeably; case carries no semantic content
        for matching.
      - Replace any non-alphanumeric character with a single space.  This
        handles colons, dashes, smart quotes, en/em dashes, etc.
      - Collapse runs of whitespace to a single space.
      - Strip outer whitespace.

    Rejected alternative: word-level set comparison with overlap threshold.
    That fails on titles that share most words by chance (e.g. "Improving
    factuality and reasoning in language models" vs "Improving reasoning
    in language models") because the rare-word signal is lost.  Substring
    containment is conservative — it rejects same-topic-different-paper
    pairs, which is what we want.
    """
    s = (s.replace("&amp;", "&")
          .replace("&#34;", '"').replace("&quot;", '"')
          .replace("&#39;", "'").replace("&apos;", "'")
          .replace("&lt;", "<").replace("&gt;", ">")
          .replace("‐", "-").replace("‑", "-")
          .replace("‒", "-").replace("–", "-")
          .replace("—", "-").replace("‘", "'")
          .replace("’", "'").replace("“", '"')
          .replace("”", '"'))
    s = _strip_latex(s)
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_doi(s: str) -> str:
    """DOIs match iff their case-folded, whitespace-stripped strings are
    exactly equal.

    Justification: the DOI handbook (RFC 8224 §2.4) explicitly states DOIs
    are case-insensitive for resolution, but registrars supply them in a
    canonical form.  Any transformation beyond casefold+strip risks false
    positives (a slash could become a hyphen, etc.).  Exact case-folded
    equality is the right rule.
    """
    return s.strip().lower()


def normalize_arxiv(s: str) -> str:
    """arXiv IDs match iff the bare id (no version suffix, lowercase) is
    equal.

    Justification: arXiv IDs are canonical paper identifiers; the version
    suffix (v1, v2, v3) refers to revisions of the same paper.  For "same
    paper?" comparisons, we strip the version.  Case-folding handles the
    inconsistent capitalization of the old-style category prefix (``hep-ph``
    vs ``HEP-PH``).
    """
    s = s.strip().lower()
    s = re.sub(r"v\d+$", "", s)
    return s


# ── Extraction helpers ──────────────────────────────────────────────────

def extract_doi(text: str) -> str | None:
    m = DOI_RE.search(text or "")
    if not m:
        return None
    # Trim trailing punctuation/period that often glues onto the DOI in bib
    # entries — e.g. "10.1016/...072." has a trailing period.
    return m.group(0).rstrip(".,;)")


def extract_arxiv(text: str) -> str | None:
    m = ARXIV_RE.search(text or "")
    return m.group(1) if m else None


def extract_bibitem_title(raw: str) -> str | None:
    """Best-effort guess of the bib entry's title.

    Heuristic order:
      1. \\newblock-delimited second segment (natbib convention).
      2. \\emph{...} content.
      3. \\textit{...} content.
    Returns None if no candidate was found.
    """
    # natbib bib entries are typically:  Authors. \newblock Title. \newblock Venue.
    # We want the SECOND chunk (the title), so we split by \newblock and pick [1].
    parts = re.split(r"\\newblock", raw)
    if len(parts) >= 2:
        cand = parts[1].strip()
        # Strip the trailing period and the venue text that sometimes follows
        # within the same \newblock when the bib was hand-formatted.
        cand = re.split(r"\\emph\{|\\textit\{|\n\\", cand)[0]
        cand = cand.rstrip(". \n")
        if cand:
            return cand
    for pat in TEX_TITLE_PATS[1:]:
        m = pat.search(raw)
        if m:
            return m.group(1).strip()
    return None


def extract_meta_title(meta: dict) -> str | None:
    """Pull a paper title from the scraped HTML meta dict.

    Preference order (most reliable first):
      - ``citation_title`` (Google Scholar convention; used by arXiv, IEEE,
        Springer, MDPI, etc.)
      - ``dc.title`` (Dublin Core; used by Crossref)
      - ``og:title`` (OpenGraph; often the page title which includes
        publisher branding — least reliable)
    """
    for key in ("citation_title", "dc.title", "og:title"):
        if meta.get(key):
            return meta[key].strip()
    return None


def extract_meta_doi(meta: dict) -> str | None:
    for key in ("citation_doi", "dc.identifier", "prism.doi"):
        v = meta.get(key)
        if v and v.lower().startswith("10."):
            return v
        if v and "doi.org/" in v:
            return v.split("doi.org/", 1)[1]
    return None


# ── Author extraction ───────────────────────────────────────────────────
# v3.1 — surname-based author comparison catches the "wrong first author"
# class of bug (e.g. `Jiayi Li et al.` for a paper actually by `Jiayi Ye et al.`).

# Particles that are sometimes lowercase and form compound surnames.
# We keep the LAST word as the surname for simplicity; this loses the
# particle in compound surnames ("van der Berg" → "Berg") which is a known
# false-positive risk but avoids the false-negative risk of failing to find
# a known-surname match when capitalization or spacing varies.
_AUTHOR_SEPARATORS = re.compile(r",\s*|\s+and\s+", re.IGNORECASE)
_ETAL_RE = re.compile(r"\bet\s+al\.?", re.IGNORECASE)


def _surname_of(name: str) -> str:
    """Reduce a name string to a lowercase surname token.

    Handles both ``"Last, First"`` (arXiv citation_author convention) and
    ``"First Last"`` (bib display convention).  The rule is intentionally
    simple — take the surname slot in the obvious way:

      - If the string contains a comma, surname is everything before the
        first comma.
      - Otherwise, surname is the last whitespace-separated word.

    Then lowercase, strip non-alphanumerics, return.

    Rejected alternatives:
      - Trying to honor surname particles ("van", "de", "der") — too many
        edge cases (lowercase "van" in Dutch convention, capitalized "Van"
        in American convention).  A last-word heuristic loses precision on
        these but the comparison rule still works for the common case.
      - Full name comparison — first-name spelling and abbreviation varies
        too much across sources (M. vs Mingqian vs M.~Q.).  Surnames are
        stable.
    """
    n = name.strip()
    if "," in n:
        n = n.split(",", 1)[0]
    else:
        # Last whitespace token.  Drop trailing initials (rare in this slot).
        parts = n.split()
        n = parts[-1] if parts else ""
    n = re.sub(r"[^A-Za-zÀ-ſ]", "", n).lower()
    return n


def extract_bib_authors(bibitem_raw: str) -> tuple[list[str], bool]:
    """Return (list of surnames, has_etal_truncation).

    Bib entries vary wildly.  We take the AUTHORS slot as everything up to
    the first ``\\newblock`` (natbib convention: authors are the first
    \\newblock-separated chunk), or up to the first period followed by a
    capital letter (sentence-style bibs).  Then split on commas and "and".
    """
    # First \newblock-delimited block is the authors slot in natbib bibs.
    parts = re.split(r"\\newblock", bibitem_raw, maxsplit=1)
    head = parts[0]
    # Trim leading "\bibitem[...]{key}" if present.
    head = re.sub(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{[^}]+\}\s*", "", head)
    # Strip LaTeX commands (e.g. \emph{}, \\&)
    head = re.sub(r"\\[a-zA-Z]+\*?\{([^{}]*)\}", r"\1", head)
    head = re.sub(r"\\[a-zA-Z]+\*?", " ", head)
    head = head.replace("{", "").replace("}", "")
    # Strip tildes which are LaTeX non-breaking spaces.
    head = head.replace("~", " ")
    has_etal = bool(_ETAL_RE.search(head))
    head = _ETAL_RE.sub("", head)
    # Split on commas + "and"
    tokens = [t.strip(".  ") for t in _AUTHOR_SEPARATORS.split(head) if t.strip(".  ")]
    surnames = []
    for t in tokens:
        sn = _surname_of(t)
        if sn and len(sn) >= 2:  # ignore one-letter or empty fragments
            surnames.append(sn)
    return surnames, has_etal


def extract_source_authors(fetched: dict) -> list[str]:
    """Return surnames from ``citation_author`` meta tags.

    The HTML scraper currently only stores ONE value per meta name in
    `out["meta"]` (it overwrites duplicates), which means a page with
    multiple ``<meta name="citation_author">`` tags loses all but the last.
    To recover the full author list, we also scan the raw text excerpt for
    every ``citation_author`` content.
    """
    meta = fetched.get("meta") or {}
    raw_excerpt = fetched.get("text_excerpt", "") or ""
    raw_html_meta = fetched.get("raw_meta_text", "") or ""
    # The fetcher in check_citations.py uses META_RE which keeps only the
    # last match per name. So re-scan whatever raw content we still have.
    candidates: list[str] = []
    if meta.get("citation_author"):
        candidates.append(meta["citation_author"])
    # Re-scan the visible-text excerpt for citation_author (arXiv abstract
    # pages don't render these, so the result will usually be empty; that's
    # fine — we fall back to the single meta value).
    candidates += re.findall(
        r'citation_author"\s*content="([^"]+)"',
        raw_html_meta or raw_excerpt,
        flags=re.I,
    )
    surnames: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        sn = _surname_of(c)
        if sn and sn not in seen:
            seen.add(sn)
            surnames.append(sn)
    return surnames


def extract_final_url_arxiv(final_url: str) -> str | None:
    """Recover an arXiv ID from a fetched URL, e.g.
    ``https://arxiv.org/abs/2410.02736``.  Returns None if not an arXiv URL.
    """
    m = re.search(r"arxiv\.org/(?:abs|pdf)/([a-z\-]+/\d{7}|\d{4}\.\d{4,5})",
                  final_url or "", re.I)
    return m.group(1) if m else None


# ── Comparison API ──────────────────────────────────────────────────────

@dataclass
class MetadataReport:
    """Deterministic per-citation metadata result.

    `verdict` is the rolled-up outcome.  Possible values:
      - ``"PASS"``      — DOI and/or title match cleanly AND authors agree
                          (or author check was inconclusive on both sides).
      - ``"FLAG"``      — neither DOI nor title was extractable on at least
                          one side; we have to defer to the LLM-judged
                          ``supports_claim`` for any final ruling.
      - ``"FAIL"``      — extracted on both sides but they disagree (title
                          or author).
      - ``"WRONG_ARXIV_SAME_PAPER"``
                        — the bib's arXiv ID resolves to a different paper,
                          but the TITLE of the resolved paper matches the
                          bib's title; the fix is "swap the eprint" rather
                          than "the citation is wrong."
      - ``"AUTHOR_MISMATCH_SAME_PAPER"`` (v3.1)
                        — DOI/arXiv/title all match, but the bib's first
                          author surname is not present in the source's
                          author list (or the bib's author set is not a
                          subset of source's).  Right paper, fabricated
                          author info.  Fixable in the bib without touching
                          body text.
    """
    verdict: str = "PASS"
    rationale: list[str] = field(default_factory=list)
    bib_doi: str | None = None
    bib_arxiv: str | None = None
    bib_title: str | None = None
    bib_authors: list[str] = field(default_factory=list)
    bib_etal: bool = False
    src_doi: str | None = None
    src_arxiv: str | None = None
    src_title: str | None = None
    src_authors: list[str] = field(default_factory=list)
    # If WRONG_ARXIV_SAME_PAPER, the corrected eprint to use:
    suggested_arxiv: str | None = None


def _check_authors(r: MetadataReport) -> None:
    """Apply the author-surname check.  Only runs after the paper-identity
    rules have already established a tentative ``PASS``.  Downgrades to
    ``AUTHOR_MISMATCH_SAME_PAPER`` when the bib's authors disagree with
    the source.

    Rule:
      - If we have no bib authors OR no source authors, return silently
        (can't decide — leave the existing verdict).
      - The bib's *first* surname MUST appear in the source's surname set.
        Justification: the first author is almost always the corresponding
        / lead author and is the most semantically meaningful name.
        Different sources order author lists differently or use different
        first-name spellings, but the first author identity is stable.
      - If the bib lists multiple authors AND the bib does NOT use
        ``et al.``, all bib surnames must appear in the source's set.
        Otherwise (et al. is used), only the first-surname check applies —
        we can't reject papers just because the bib truncated.
    """
    if not r.bib_authors or not r.src_authors:
        return
    src_set = set(r.src_authors)
    if r.bib_authors[0] not in src_set:
        r.rationale.append(
            f"AUTHOR MISMATCH: bib first author surname '{r.bib_authors[0]}' "
            f"not in source authors {sorted(src_set)}"
        )
        r.verdict = "AUTHOR_MISMATCH_SAME_PAPER"
        return
    if not r.bib_etal and len(r.bib_authors) > 1:
        bib_set = set(r.bib_authors)
        missing = bib_set - src_set
        if missing:
            r.rationale.append(
                f"AUTHOR MISMATCH: bib authors {sorted(missing)} not in "
                f"source authors {sorted(src_set)}"
            )
            r.verdict = "AUTHOR_MISMATCH_SAME_PAPER"
            return
    # All checks passed — append a small positive note for the audit trail.
    r.rationale.append(
        f"authors OK: bib first '{r.bib_authors[0]}' ∈ source "
        f"{sorted(src_set)[:5]}{'…' if len(src_set)>5 else ''}"
    )


def metadata_check(bibitem_raw: str, fetched: dict | None,
                   pdf_path_basename: str | None = None) -> MetadataReport:
    """Apply the deterministic checks. Pure function.

    Returns a MetadataReport with `verdict ∈ {"PASS","FLAG","FAIL",
    "WRONG_ARXIV_SAME_PAPER"}` plus rationale strings explaining every
    decision (no hidden logic).
    """
    r = MetadataReport()
    r.bib_doi    = extract_doi(bibitem_raw)
    r.bib_arxiv  = extract_arxiv(bibitem_raw)
    r.bib_title  = extract_bibitem_title(bibitem_raw)
    r.bib_authors, r.bib_etal = extract_bib_authors(bibitem_raw)

    if fetched:
        meta = fetched.get("meta") or {}
        r.src_doi   = extract_meta_doi(meta) or extract_doi(fetched.get("text_excerpt", "") or "")
        r.src_title = extract_meta_title(meta) or fetched.get("title")
        # arXiv ID from the resolved URL is more reliable than from meta.
        r.src_arxiv = (extract_final_url_arxiv(fetched.get("final_url", ""))
                       or extract_arxiv(fetched.get("text_excerpt", "") or ""))
        r.src_authors = extract_source_authors(fetched)
    elif pdf_path_basename:
        # When evidence is a local PDF, we don't have HTML meta.  Trust that
        # the PDF the user provided matches the bibitem (their explicit
        # claim by naming the file <key>.pdf).  Defer to LLM judgment for
        # the supports_claim dimension.
        r.rationale.append("evidence is a local PDF; deferring metadata to LLM contents-check")
        r.verdict = "PASS"
        return r

    # ── Rule 1: DOI exact match (strongest signal) ──────────────────────
    if r.bib_doi and r.src_doi:
        if normalize_doi(r.bib_doi) == normalize_doi(r.src_doi):
            r.rationale.append(f"DOI exact-match (case-folded): {normalize_doi(r.bib_doi)}")
            r.verdict = "PASS"
            _check_authors(r)
            return r
        else:
            r.rationale.append(
                f"DOI mismatch: bib={normalize_doi(r.bib_doi)!r} vs "
                f"src={normalize_doi(r.src_doi)!r}"
            )
            r.verdict = "FAIL"
            return r

    # ── Rule 2: arXiv ID match ──────────────────────────────────────────
    if r.bib_arxiv and r.src_arxiv:
        if normalize_arxiv(r.bib_arxiv) == normalize_arxiv(r.src_arxiv):
            r.rationale.append(f"arXiv ID exact-match: {normalize_arxiv(r.bib_arxiv)}")
            # Even when IDs agree, the bib title can be a fabrication for a
            # real paper (the Krolikowski2014 case: bib says
            # "Two options for the Koide-like formula" at arXiv:1404.5705,
            # but 1404.5705 is actually "Component sizes for large quantum
            # erdos renyi graph"). Cross-check titles when both present.
            if r.bib_title and r.src_title:
                t_bib = normalize_title(r.bib_title)
                t_src = normalize_title(r.src_title)
                if t_bib and t_src and (t_bib not in t_src) and (t_src not in t_bib):
                    r.rationale.append(
                        f"...but TITLES disagree at that ID: bib='{t_bib[:80]}' vs "
                        f"src='{t_src[:80]}' → bib title is fabricated for a real paper"
                    )
                    r.verdict = "FAIL"
                    return r
            r.verdict = "PASS"
            _check_authors(r)
            return r
        else:
            # arXiv IDs differ — check whether titles agree (wrong ID, same
            # paper) or disagree (different paper entirely).
            t_bib  = normalize_title(r.bib_title or "")
            t_src  = normalize_title(r.src_title or "")
            r.rationale.append(
                f"arXiv ID mismatch: bib={r.bib_arxiv} vs src={r.src_arxiv}"
            )
            if t_bib and t_src and (t_bib in t_src or t_src in t_bib):
                r.rationale.append(f"...but titles match: '{t_bib}' ⊆ '{t_src}'")
                r.verdict = "WRONG_ARXIV_SAME_PAPER"
                r.suggested_arxiv = r.src_arxiv
                return r
            r.rationale.append("titles ALSO disagree → different paper entirely")
            r.verdict = "FAIL"
            return r

    # ── Rule 3: title substring-containment ─────────────────────────────
    if r.bib_title and r.src_title:
        t_bib = normalize_title(r.bib_title)
        t_src = normalize_title(r.src_title)
        if t_bib and t_src:
            if t_bib in t_src or t_src in t_bib:
                r.rationale.append(
                    f"title substring-match: '{t_bib[:80]}' ⊆ '{t_src[:80]}'"
                )
                r.verdict = "PASS"
                _check_authors(r)
                return r
            r.rationale.append(
                f"title MISMATCH (neither is substring of the other): "
                f"bib='{t_bib[:80]}' vs src='{t_src[:80]}'"
            )
            r.verdict = "FAIL"
            return r

    # ── Otherwise: insufficient extraction, defer to LLM ────────────────
    missing = []
    if not r.bib_doi   and not r.bib_arxiv:   missing.append("bib lacks DOI and arXiv ID")
    if not r.bib_title:                       missing.append("bib title not extractable")
    if fetched and not (r.src_doi or r.src_arxiv or r.src_title):
        missing.append("evidence has no extractable DOI/arXiv/title")
    r.rationale.append("insufficient deterministic signal — " +
                       ("; ".join(missing) if missing else "no extractor matched"))
    r.verdict = "FLAG"
    return r
