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


# MDPI / journal-of-record style: `Authors. Plain-text Title. \textit{Venue}
# \textbf{Year}, \textit{Volume}, pages, \url{...}.`  The first \textit{} is
# the VENUE here, not the title — confusion this regex disambiguates.
#
# Key signal: a \textbf{<4-digit year>} follows the first \textit{}.  When
# that's true we know the first \textit{} is a venue (journal, "arXiv",
# "Zenodo", etc.) and the title is plain text BEFORE it.
_MDPI_VENUE_YEAR_RE = re.compile(
    r"\\textit\s*\{[^}]*\}\s*\\textbf\s*\{\s*\d{4}\s*\}",
    re.IGNORECASE,
)
_FIRST_TEXTIT_RE = re.compile(r"\\textit\s*\{", re.IGNORECASE)
# Boundary between authors and title in MDPI: the LAST occurrence of
# "<capital>.\s+(?=[A-Z0-9])" before the first \textit{}.  After the last
# author entry, there's an initial like "D." or "V.", then a space, then the
# title-start capital letter.  Author lists internally have "<initial>.<initial>."
# (e.g., "J.C.") with no space between, so those don't match.
_INITIAL_TITLE_BOUNDARY_RE = re.compile(
    r"(?<=[A-Z])\.\s+(?=[A-Z0-9])",
)


def is_mdpi_journal_bibitem(raw: str) -> bool:
    """Detect MDPI-style journal-article bibitem.

    Returns True if the FIRST \\textit{} is followed by \\textbf{<year>} —
    in that case \\textit{} is the venue, not the title.  Books and other
    `\\textit{Title}` patterns return False (\\textbf{year} is absent).
    """
    if "\\newblock" in raw:
        return False
    return bool(_MDPI_VENUE_YEAR_RE.search(raw))


def extract_mdpi_title(raw: str) -> str | None:
    """Title for MDPI-style journal articles: plain text between author block
    and the venue \\textit{}.  See ``is_mdpi_journal_bibitem``.
    """
    work = re.sub(r"^\s*\\bibitem\s*(?:\[[^\]]*\])?\s*\{[^}]+\}\s*", "", raw, count=1)
    m_venue = _FIRST_TEXTIT_RE.search(work)
    if not m_venue:
        return None
    before_venue = work[:m_venue.start()].rstrip().rstrip(",").rstrip()
    # Find the LAST "<initial>.\s+(?=capital)" boundary — that's where the
    # title starts after the author list.
    boundaries = list(_INITIAL_TITLE_BOUNDARY_RE.finditer(before_venue))
    if not boundaries:
        return None
    title_start = boundaries[-1].end()
    title = before_venue[title_start:].strip().rstrip(".").rstrip()
    return title or None


def extract_mdpi_authors_region(raw: str) -> str | None:
    """Author segment for MDPI-style journal articles: everything from start of
    bibitem up to (but not including) the title-start boundary.
    """
    work = re.sub(r"^\s*\\bibitem\s*(?:\[[^\]]*\])?\s*\{[^}]+\}\s*", "", raw, count=1)
    m_venue = _FIRST_TEXTIT_RE.search(work)
    if not m_venue:
        return None
    before_venue = work[:m_venue.start()].rstrip().rstrip(",").rstrip()
    boundaries = list(_INITIAL_TITLE_BOUNDARY_RE.finditer(before_venue))
    if not boundaries:
        return None
    return before_venue[:boundaries[-1].start() + 1]  # keep the trailing period


# MDPI venue/volume/pages extraction — used by the journal cross-check.
_MDPI_VENUE_RE = re.compile(r"\\textit\s*\{([^}]+)\}\s*\\textbf\s*\{\s*(\d{4})\s*\}", re.IGNORECASE)
_MDPI_VOLUME_RE = re.compile(
    r"\\textbf\s*\{\s*\d{4}\s*\}\s*,\s*\\textit\s*\{([^}]+)\}",
    re.IGNORECASE,
)
_MDPI_PAGES_RE = re.compile(
    r"\\textit\s*\{[^}]+\}\s*,\s*(\d+)(?:--?(\d+))?",
    re.IGNORECASE,
)


def extract_mdpi_journal_meta(raw: str) -> dict:
    """Return {venue, year, volume, first_page, last_page} from an MDPI bibitem.

    Only fields actually present are included.  No keys when not MDPI.
    """
    out: dict[str, str] = {}
    m = _MDPI_VENUE_RE.search(raw)
    if not m:
        return out
    out["venue"] = m.group(1).strip()
    out["year"] = m.group(2)
    m = _MDPI_VOLUME_RE.search(raw)
    if m:
        out["volume"] = m.group(1).strip()
    m = _MDPI_PAGES_RE.search(raw)
    if m:
        out["first_page"] = m.group(1)
        if m.group(2):
            out["last_page"] = m.group(2)
    return out


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
      0. MDPI / journal-of-record format: `Authors. Title. \\textit{Venue}
         \\textbf{Year}, ...` — first \\textit is the VENUE, title is plain
         text before it.  Detected via ``is_mdpi_journal_bibitem``.
      1. \\newblock-delimited second segment (natbib convention).
      2. \\emph{...} content.
      3. \\textit{...} content.
    Returns None if no candidate was found.
    """
    # Rule 0: MDPI journal-article format.  Must come first because the FIRST
    # \textit{} in MDPI is the venue, not the title — checking rule 3 first
    # would extract "Phys. Lett. B" or "arXiv" as the title and FAIL the bib
    # against the source page's real title.
    if is_mdpi_journal_bibitem(raw):
        t = extract_mdpi_title(raw)
        if t:
            return t

    # Rule 1: natbib \newblock convention.
    parts = re.split(r"\\newblock", raw)
    if len(parts) >= 2:
        cand = parts[1].strip()
        # Strip the trailing period and the venue text that sometimes follows
        # within the same \newblock when the bib was hand-formatted.
        cand = re.split(r"\\emph\{|\\textit\{|\n\\", cand)[0]
        cand = cand.rstrip(". \n")
        if cand:
            return cand
    # Rules 2 + 3: italic-delimited title (book convention, or fallback).
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


def _surnames_from_head(head: str) -> tuple[list[str], bool]:
    """Strip LaTeX, split on author separators, return (surnames, has_etal).
    Shared by all bibitem-format branches in ``extract_bib_authors``.

    Handles two author-list conventions:
      - MDPI:  ``Surname, J.; Surname, K.; Surname, L.``  (semicolon between
        authors; surname-comma-initial within each entry)
      - natbib: ``First Last, First Last, and First Last``  (comma or "and"
        between authors)

    Detected by looking for ``; ``: if present, the list uses MDPI style and
    we split on ``;`` first (so initials like "J.C." don't get tokenized as
    a fake surname).
    """
    head = re.sub(r"\\[a-zA-Z]+\*?\{([^{}]*)\}", r"\1", head)
    head = re.sub(r"\\[a-zA-Z]+\*?", " ", head)
    head = head.replace("{", "").replace("}", "")
    head = head.replace("~", " ")
    has_etal = bool(_ETAL_RE.search(head))
    head = _ETAL_RE.sub("", head)

    if ";" in head:
        # MDPI form: split on ";", each chunk is one author "Surname, Initials".
        author_chunks = re.split(r";\s*", head)
    else:
        # natbib / standard form: split on commas + "and".
        author_chunks = re.split(r",\s*|\s+and\s+", head)

    surnames: list[str] = []
    for t in author_chunks:
        t = t.strip(".  ")
        if not t:
            continue
        # Skip parenthesized collaboration tags like "(LSND Collaboration)".
        if re.match(r"^\s*\(", t):
            continue
        sn = _surname_of(t)
        if sn and len(sn) >= 2:
            surnames.append(sn)
    return surnames, has_etal


def extract_bib_authors(bibitem_raw: str) -> tuple[list[str], bool]:
    """Return (list of surnames, has_etal_truncation).

    Bib entries vary wildly.  Heuristics in priority order to isolate the
    AUTHORS slot:

      1. ``\\newblock`` is present → take everything before the first one
         (natbib convention).
      2. ``\\bibitem`` is followed by an inline-quoted title — physics-style
         bibs structure as ``Authors, ``Title,'' Venue ...``.  Take the slot
         up to the first opening LaTeX quote (`` `` `` or just `` ` ``).
      3. ``\\textit{Title}`` or ``\\emph{Title}`` marks an italic title (book
         convention).  Take the slot up to the first such command.
      4. Fallback: the whole bibitem (lossy — caller may get title/venue
         words mixed in as fake "authors").

    Without these markers the previous implementation would consume the
    entire bibitem and emit title words, journal abbreviations, and series
    names as bogus "authors".  See v3.1 regression: jumper2021 → ['jumper',
    'alphafold'], barut1979 → ['barut', 'formula', 'physrevlett'].
    """
    # Rule 0: MDPI journal-article boundary — the title is plain text BEFORE
    # the first \textit{} (which is the venue).  Author block is everything
    # up to the "<initial>.\s+(?=capital)" title-start boundary.
    if is_mdpi_journal_bibitem(bibitem_raw):
        mdpi_authors = extract_mdpi_authors_region(bibitem_raw)
        if mdpi_authors:
            return _surnames_from_head(mdpi_authors)

    # Trim leading "\bibitem[...]{key}" first so its key tokens don't leak in.
    raw = re.sub(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{[^}]+\}\s*", "", bibitem_raw)

    # Rule 1: \newblock boundary (natbib).
    if "\\newblock" in raw:
        head = re.split(r"\\newblock", raw, maxsplit=1)[0]
    else:
        # Rule 2: opening LaTeX quote `` (or single ` ) marks an inline title.
        m = re.search(r"``|(?<![\\a-zA-Z])`(?![\\a-zA-Z])", raw)
        # Rule 3: \textit{ or \emph{ marks an italicized title (books).
        # BUT skip \textit{et al.} / \emph{et al.} — those are LaTeX-styled
        # author-list markers, not the title.  Without this skip, an inline
        # ``J. Jumper \textit{et al.}, ``Title,'' ...`` would cut off "et al."
        # from the author segment, losing the et-al signal that downstream
        # heuristics rely on.
        m_italic = None
        for cand in re.finditer(r"\\(?:textit|emph)\s*\{([^{}]*)\}", raw):
            if re.fullmatch(r"\s*et\s+al\.?\s*", cand.group(1), re.IGNORECASE):
                continue
            m_italic = cand
            break
        # Rule 4: fall through; use whichever boundary comes first; else all.
        candidates = [p.start() for p in (m, m_italic) if p]
        head = raw[:min(candidates)] if candidates else raw

    return _surnames_from_head(head)


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
      - ``"JOURNAL_FIELD_MISMATCH"`` (v3.3)
                        — DOI/arXiv/title all match (right paper) but one
                          of the journal coordinates (venue name, year,
                          volume, first page) in the bib disagrees with the
                          publisher's metadata.  Right paper, wrong journal
                          coordinates in the bib — fix the bib volume/page
                          numbers without touching body text.

    Journal-field comparisons (v3.3) populate ``bib_venue/bib_year/
    bib_volume/bib_first_page`` and the corresponding ``src_*`` slots when
    available so reports can show "bib says X, source says Y" deterministically.
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
    # v3.3 — journal-coordinate fields populated only when both sides expose them.
    bib_venue: str | None = None
    bib_year: str | None = None
    bib_volume: str | None = None
    bib_first_page: str | None = None
    src_venue: str | None = None
    src_year: str | None = None
    src_volume: str | None = None
    src_first_page: str | None = None
    journal_field_mismatches: list[str] = field(default_factory=list)


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
    # If the bib uses `et al.` AND the source exposes only 1–2 authors, the
    # source metadata is almost certainly partial (e.g., Nature exposes only
    # the senior author in `citation_author` tags despite 30+-author papers).
    # We cannot reliably check against partial data — skip the check.
    # Justification: jumper2021 — Nature returns ['hassabis'] only; bib has
    # 'Jumper et al.' First author IS Jumper but Hassabis is the senior
    # corresponding author Nature chose to expose. Both are real authors of
    # the same paper. Flagging this as a "mismatch" misleads the user.
    if r.bib_etal and len(src_set) <= 2:
        r.rationale.append(
            f"authors check SKIPPED: bib has 'et al.' and source meta exposes "
            f"only {len(src_set)} author(s) {sorted(src_set)} — source list is "
            f"partial; cannot decide"
        )
        return
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


def _normalize_venue(v: str) -> str:
    """Normalize a journal name for substring comparison.
    Lowercase, drop punctuation and 'the/and', collapse whitespace.  Catches
    "Phys. Lett. B" == "Physics Letters B".
    """
    v = re.sub(r"[^a-zA-Z0-9 ]+", " ", (v or "").lower())
    v = re.sub(r"\b(?:the|and|of|in|for)\b", "", v)
    v = re.sub(r"\bphys\b", "physics", v)
    v = re.sub(r"\brev\b", "review", v)
    v = re.sub(r"\blett\b", "letters", v)
    v = re.sub(r"\bmod\b", "modern", v)
    v = re.sub(r"\bj\b", "journal", v)
    v = re.sub(r"\bint\b", "international", v)
    v = re.sub(r"\beur\b", "european", v)
    return re.sub(r"\s+", " ", v).strip()


def _check_journal_fields(r: MetadataReport) -> None:
    """Apply per-coordinate journal-field comparisons.  Only runs after the
    paper-identity rules have established a tentative ``PASS``.  Downgrades
    to ``JOURNAL_FIELD_MISMATCH`` when bib coordinates disagree with the
    publisher's metadata.

    Compares: venue (canonical name), year, volume, first-page.  Skips any
    field where either side is missing.  arXiv-only bibs (venue=='arXiv'
    on the bib side) are skipped because the corresponding source fields
    don't exist meaningfully.
    """
    # arXiv-only bibitems don't have journal coordinates to check.
    if r.bib_venue and r.bib_venue.strip().lower() in {"arxiv", "preprint",
                                                       "arxiv preprint",
                                                       "zenodo"}:
        return
    if r.verdict != "PASS":
        return
    mismatches: list[str] = []

    # Year — strong signal; bib should be the publication year.
    if r.bib_year and r.src_year:
        if r.bib_year.strip()[:4] != r.src_year.strip()[:4]:
            mismatches.append(f"year: bib={r.bib_year!r} vs src={r.src_year!r}")

    # Volume — exact-string compare after stripping leading zeros.
    if r.bib_volume and r.src_volume:
        bv = r.bib_volume.strip().lstrip("0") or "0"
        sv = r.src_volume.strip().lstrip("0") or "0"
        if bv != sv:
            mismatches.append(f"volume: bib={r.bib_volume!r} vs src={r.src_volume!r}")

    # First page.
    if r.bib_first_page and r.src_first_page:
        bp = r.bib_first_page.strip().lstrip("0") or "0"
        sp = r.src_first_page.strip().lstrip("0") or "0"
        if bp != sp:
            mismatches.append(f"first_page: bib={r.bib_first_page!r} vs src={r.src_first_page!r}")

    # Venue — substring containment in either direction on the canonical form.
    if r.bib_venue and r.src_venue:
        bv = _normalize_venue(r.bib_venue)
        sv = _normalize_venue(r.src_venue)
        if bv and sv and (bv not in sv and sv not in bv):
            mismatches.append(f"venue: bib={r.bib_venue!r} vs src={r.src_venue!r}")

    if mismatches:
        r.journal_field_mismatches = mismatches
        r.rationale.append("JOURNAL FIELD MISMATCH: " + "; ".join(mismatches))
        r.verdict = "JOURNAL_FIELD_MISMATCH"


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
    # v3.3 — journal coordinates from MDPI-style bibitems.
    bib_jmeta = extract_mdpi_journal_meta(bibitem_raw)
    r.bib_venue = bib_jmeta.get("venue")
    r.bib_year = bib_jmeta.get("year")
    r.bib_volume = bib_jmeta.get("volume")
    r.bib_first_page = bib_jmeta.get("first_page")

    if fetched:
        meta = fetched.get("meta") or {}
        r.src_doi   = extract_meta_doi(meta) or extract_doi(fetched.get("text_excerpt", "") or "")
        r.src_title = extract_meta_title(meta) or fetched.get("title")
        # arXiv ID from the resolved URL is more reliable than from meta.
        r.src_arxiv = (extract_final_url_arxiv(fetched.get("final_url", ""))
                       or extract_arxiv(fetched.get("text_excerpt", "") or ""))
        r.src_authors = extract_source_authors(fetched)
        # Source journal coordinates from common meta keys.
        r.src_venue = meta.get("citation_journal_title") or meta.get("prism.publicationName")
        _src_year_raw = (meta.get("citation_publication_date")
                          or meta.get("citation_year") or meta.get("dc.date")
                          or meta.get("prism.publicationDate") or "")
        if _src_year_raw:
            _m_y = re.search(r"\d{4}", _src_year_raw)
            r.src_year = _m_y.group(0) if _m_y else None
        r.src_volume = meta.get("citation_volume") or meta.get("prism.volume")
        r.src_first_page = (meta.get("citation_firstpage")
                             or meta.get("prism.startingPage"))
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
            _check_journal_fields(r)
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
            _check_journal_fields(r)
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
                _check_journal_fields(r)
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
