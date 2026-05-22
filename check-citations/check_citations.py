#!/usr/bin/env python3
"""
check-citations — graduated-consensus citation verifier (v2).

Pipeline per citation:
  1. Parse the .tex: extract every \\bibitem{key}... entry, and every
     \\cite{...} call in the body (with surrounding context).
  2. Cross-check orphans: cite-without-bibitem and bibitem-without-cite.
  3. Resolve evidence in this order:
       a) Local PDF at <refs_dir>/<key>.pdf if --refs-dir given.
       b) Fetch the canonical URL (DOI > arXiv > raw URL).
       c) If bibitem is ISBN-only with no URL, mark as "no-fetch" but
          still pass to LLMs (books are verifiable by prior knowledge).
  4. CLASSIFY THE FETCH BEFORE CALLING LLMs:
       - OK         → substantive content present; proceed to LLM verdict.
       - BLOCKED    → CAPTCHA, "Redirecting" stub, cookie wall, etc.
                      → HARD FAIL, skip LLMs (no model spend, no
                        prior-knowledge PASS).
       - HTTP_ERROR → 4xx/5xx                                     → HARD FAIL.
       - NETWORK    → timeout/DNS/etc.                            → HARD FAIL.
       - NO_URL     → ISBN-only book (no URL in bibitem)          → LLM verdict.
       - PDF        → local PDF was extracted                     → LLM verdict.
  5. For OK / NO_URL / PDF cases, send to opus / gpt-5.4 / deepseek
     in parallel for the 4-dimension JSON verdict.
  6. Aggregate. Unanimous PASS = clean. Any dissent or hard FAIL is
     surfaced.

Usage:
  python3 check_citations.py <paper.tex>
      [--refs-dir <dir>]    # look for <dir>/<key>.pdf for each bibitem
      [--report report.md]  # write Markdown report (else stdout)
      [--cap-usd 5.00]      # hard cost cap
      [--workers 3]         # parallel model calls per citation
      [--only KEY1,KEY2]    # subset for testing

The harness reuses api_client.py from
graduated_dissent_bench/harness — key loading, cost cap, dispatch.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Locate api_client.py (graduated_dissent_bench harness) ────────────
HARNESS = Path.home() / "Desktop/Academic/AI_Research/graduated_dissent_bench/harness"
if not (HARNESS / "api_client.py").is_file():
    sys.exit(
        f"[check-citations] api_client.py not found at {HARNESS}.\n"
        f"Edit HARNESS at the top of this file, or symlink the harness."
    )
sys.path.insert(0, str(HARNESS))
import api_client  # type: ignore

# v3: deterministic DOI / arXiv ID / title comparison (replaces the LLM
# "metadata_match" dimension, which the models hallucinated either way on).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from metadata_check import metadata_check, MetadataReport  # type: ignore

MODELS_TO_USE = ["opus", "gpt-5.4", "deepseek"]
PDFTOTEXT_BIN = shutil.which("pdftotext") or "/opt/homebrew/bin/pdftotext"

# ── .tex parsing ──────────────────────────────────────────────────────

CITE_RE = re.compile(r"\\cite[a-zA-Z]*\*?(?:\[[^\]]*\])?\{([^}]+)\}")
BIBITEM_SPLIT = re.compile(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
DOI_RE = re.compile(r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*|DOI:\s*)"
                    r"([0-9]{2}\.[0-9]{3,9}/[^\s,}\\]+)", re.IGNORECASE)
DOI_BARE_RE = re.compile(r"\b(10\.[0-9]{3,9}/[^\s,}\\]+)")
ARXIV_RE = re.compile(
    r"arXiv:\s*([a-z\-]+(?:\.[A-Z]{2})?/?[0-9]{4,7}|[0-9]{4}\.[0-9]{4,5})",
    re.IGNORECASE,
)
URL_RE = re.compile(r"\\url\{([^}]+)\}|(https?://[^\s,}\\]+)")
ISBN_RE = re.compile(r"ISBN[\s:-]*([0-9X\-]{10,17})", re.IGNORECASE)


def strip_tex_comments(text: str) -> str:
    out = []
    for line in text.splitlines():
        i = 0
        while i < len(line):
            if line[i] == "%" and (i == 0 or line[i - 1] != "\\"):
                break
            i += 1
        out.append(line[:i])
    return "\n".join(out)


def split_body_and_bib(tex: str) -> tuple[str, str]:
    m = re.search(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}",
                  tex, re.DOTALL)
    if not m:
        return tex, ""
    return tex[:m.start()] + tex[m.end():], m.group(0)


@dataclass
class BibItem:
    key: str
    raw: str
    doi: str = ""
    arxiv: str = ""
    url: str = ""
    isbn: str = ""

    def canonical_url(self) -> str:
        if self.doi:
            return f"https://doi.org/{self.doi.rstrip('.,;)')}"
        if self.arxiv:
            return f"https://arxiv.org/abs/{self.arxiv.rstrip('.,;)')}"
        if self.url:
            return self.url
        return ""


def parse_bibitems(bib: str) -> list[BibItem]:
    if not bib:
        return []
    parts = BIBITEM_SPLIT.split(bib)
    items: list[BibItem] = []
    for i in range(1, len(parts), 2):
        key = parts[i].strip()
        raw = parts[i + 1] if i + 1 < len(parts) else ""
        raw = re.split(r"\\end\{thebibliography\}", raw)[0].strip()
        bi = BibItem(key=key, raw=raw)
        if m := DOI_RE.search(raw):
            bi.doi = m.group(1)
        elif m := DOI_BARE_RE.search(raw):
            bi.doi = m.group(1)
        if m := ARXIV_RE.search(raw):
            bi.arxiv = m.group(1)
        if m := URL_RE.search(raw):
            bi.url = (m.group(1) or m.group(2) or "").rstrip(".,;)")
        if m := ISBN_RE.search(raw):
            bi.isbn = m.group(1)
        items.append(bi)
    return items


def find_cite_contexts(body: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for m in CITE_RE.finditer(body):
        keys = [k.strip() for k in m.group(1).split(",")]
        start = max(0, m.start() - 240)
        end = min(len(body), m.end() + 240)
        ctx = re.sub(r"\s+", " ", body[start:end]).strip()
        for k in keys:
            out.setdefault(k, []).append(ctx)
    return out


# ── PDF extraction ────────────────────────────────────────────────────

def extract_pdf_text(pdf_path: Path, max_chars: int = 12000) -> tuple[str, str]:
    """Return (text, error). Uses pdftotext (Poppler) for reliability.

    We grab the first ~12 KB because we need enough for title, authors,
    abstract, and usually the first content paragraph, so the LLMs can
    confirm both metadata AND that the cited claim is in the paper.
    """
    if not PDFTOTEXT_BIN or not Path(PDFTOTEXT_BIN).is_file():
        return "", (f"pdftotext binary not found at {PDFTOTEXT_BIN}; "
                    f"install poppler (brew install poppler)")
    try:
        result = subprocess.run(
            [PDFTOTEXT_BIN, "-q", "-layout", "-enc", "UTF-8",
             str(pdf_path), "-"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return "", f"pdftotext rc={result.returncode}: {result.stderr.strip()}"
        text = result.stdout
        # Collapse runs of whitespace but preserve paragraph breaks
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:max_chars], ""
    except subprocess.TimeoutExpired:
        return "", "pdftotext timeout (30s)"
    except Exception as e:  # noqa: BLE001
        return "", f"{type(e).__name__}: {e}"


# ── URL fetching ──────────────────────────────────────────────────────

TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
META_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\']([^"\']+)["\'][^>]+content=["\']'
    r"([^\"']+)[\"'][^>]*>",
    re.IGNORECASE,
)

# Patterns that prove a fetch was bot-blocked or returned a redirect stub.
# These must match either the page title or appear within the first ~2 KB
# of stripped content for the fetch to be classified as BLOCKED.
BLOCK_TITLE_RES = [
    re.compile(r"^\s*Redirecting\s*$", re.IGNORECASE),
    re.compile(r"Captcha", re.IGNORECASE),
    re.compile(r"Just a moment", re.IGNORECASE),
    re.compile(r"Access\s*Denied", re.IGNORECASE),
    re.compile(r"Attention\s*Required", re.IGNORECASE),
    re.compile(r"Bot\s*Verification", re.IGNORECASE),
    re.compile(r"Are you (a )?human", re.IGNORECASE),
    re.compile(r"checking your browser", re.IGNORECASE),
]
BLOCK_CONTENT_RES = [
    re.compile(r"cookieAbsent", re.IGNORECASE),
    re.compile(r"cookies?_not_supported", re.IGNORECASE),
    re.compile(r"Please enable (cookies|JavaScript)", re.IGNORECASE),
    re.compile(r"cf-(error|browser-verification)", re.IGNORECASE),
    re.compile(r"Radware", re.IGNORECASE),
    re.compile(r"PerimeterX", re.IGNORECASE),
    re.compile(r"DataDome", re.IGNORECASE),
]
# Final-URL patterns that signal a bot-block redirect target.
BLOCK_URL_RES = [
    re.compile(r"validate\.perfdrive\.com", re.IGNORECASE),
    re.compile(r"cookieAbsent", re.IGNORECASE),
    re.compile(r"/captcha", re.IGNORECASE),
]


def fetch_url(url: str, *, timeout: float = 25.0,
              max_bytes: int = 200_000) -> dict[str, Any]:
    out: dict[str, Any] = {
        "status": 0, "final_url": "", "title": "", "meta": {},
        "text_excerpt": "", "pdf": False, "error": "",
    }
    if not url:
        out["error"] = "no canonical URL available"
        return out
    req = urllib.request.Request(url, headers={
        "User-Agent": "check-citations/2.0 (academic citation verifier)",
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out["status"] = resp.status
            out["final_url"] = resp.url
            ctype = resp.headers.get("Content-Type", "").lower()
            data = resp.read(max_bytes)
            if "application/pdf" in ctype or out["final_url"].endswith(".pdf"):
                out["pdf"] = True
                out["text_excerpt"] = f"[PDF at {out['final_url']}; not parsed]"
                return out
            try:
                html = data.decode("utf-8", errors="replace")
            except Exception:
                html = data.decode("latin-1", errors="replace")
            for m in META_RE.finditer(html):
                name = m.group(1).lower()
                if name.startswith(("citation_", "dc.", "og:", "og:title",
                                    "twitter:title", "description")):
                    out["meta"][name] = m.group(2)
            tm = re.search(r"<title[^>]*>(.*?)</title>", html,
                           re.IGNORECASE | re.DOTALL)
            if tm:
                out["title"] = re.sub(r"\s+", " ", tm.group(1)).strip()
            # v3.1: keep the raw <head>-meta block so author extraction can
            # recover ALL citation_author values (META_RE-based dict
            # collapses duplicates to the last value, losing co-authors).
            head_m = re.search(r"<head\b[^>]*>(.*?)</head>", html, re.IGNORECASE | re.DOTALL)
            out["raw_meta_text"] = head_m.group(1)[:20000] if head_m else html[:20000]
            visible = SCRIPT_RE.sub("", html)
            visible = TAG_RE.sub(" ", visible)
            visible = re.sub(r"\s+", " ", visible).strip()
            out["text_excerpt"] = visible[:6000]
    except urllib.error.HTTPError as e:
        out["status"] = e.code
        out["error"] = f"HTTP {e.code}: {e.reason}"
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def classify_fetch(fetched: dict[str, Any], url: str) -> tuple[str, str]:
    """Return (classification, reason).

    classification ∈ {"ok", "blocked", "http_error", "network_error", "no_url", "pdf_passthrough"}.
    """
    if not url:
        return "no_url", "bibitem has no URL (ISBN-only or other non-online)"
    if fetched.get("error") and not fetched.get("status"):
        return "network_error", fetched["error"]
    status = fetched.get("status", 0)
    if status and status >= 400:
        return "http_error", f"HTTP {status}: {fetched.get('error', '')}"
    if fetched.get("pdf"):
        return "pdf_passthrough", "fetched a PDF directly; not parsed"
    title = fetched.get("title", "")
    text = fetched.get("text_excerpt", "")
    final = fetched.get("final_url", "")
    for pat in BLOCK_TITLE_RES:
        if pat.search(title):
            return "blocked", f"title matches bot-block pattern: {title[:120]!r}"
    for pat in BLOCK_URL_RES:
        if pat.search(final):
            return "blocked", f"final URL matches bot-block redirect: {final[:120]!r}"
    for pat in BLOCK_CONTENT_RES:
        if pat.search(text[:3000]):
            return "blocked", f"content matches bot-block pattern: {pat.pattern}"
    # Sanity check: HTTP 200 with almost no content is suspicious
    if status == 200 and len(text) < 200 and not fetched.get("meta"):
        return "blocked", f"HTTP 200 but content is only {len(text)} chars and no meta"
    return "ok", ""


# ── Evidence assembly ─────────────────────────────────────────────────

@dataclass
class Evidence:
    """Unified container of whatever we have for one bibitem."""
    source: str       # "pdf" | "url" | "none"
    pdf_path: Path | None = None
    fetched: dict[str, Any] | None = None
    pdf_text: str = ""
    pdf_error: str = ""
    classification: str = ""    # ok / blocked / http_error / network_error / no_url / pdf
    reason: str = ""

    @property
    def is_hard_fail(self) -> bool:
        return self.classification in {"blocked", "http_error", "network_error"}

    @property
    def text_for_prompt(self) -> str:
        if self.source == "pdf":
            return self.pdf_text or f"[pdftotext error: {self.pdf_error}]"
        if self.fetched:
            return self.fetched.get("text_excerpt", "") or \
                   (f"[ERROR: {self.fetched.get('error','')}]"
                    if self.fetched.get("error") else "(empty)")
        return "(no evidence)"

    @property
    def title_for_prompt(self) -> str:
        if self.source == "pdf":
            return f"[local PDF: {self.pdf_path.name if self.pdf_path else '?'}]"
        if self.fetched:
            return self.fetched.get("title", "") or "(none)"
        return "(none)"

    @property
    def meta_for_prompt(self) -> dict[str, str]:
        if self.fetched:
            return self.fetched.get("meta", {}) or {}
        return {}

    @property
    def status_for_prompt(self) -> int:
        if self.source == "pdf":
            return 200  # treat PDF as successful
        if self.fetched:
            return self.fetched.get("status", 0)
        return 0

    @property
    def final_url_for_prompt(self) -> str:
        if self.source == "pdf":
            return f"file://{self.pdf_path}" if self.pdf_path else ""
        if self.fetched:
            return self.fetched.get("final_url", "") or "(no fetch)"
        return ""


def gather_evidence(item: BibItem, refs_dir: Path | None) -> Evidence:
    # 1) Try local PDF
    if refs_dir:
        candidate = refs_dir / f"{item.key}.pdf"
        if candidate.is_file():
            text, err = extract_pdf_text(candidate)
            ev = Evidence(source="pdf", pdf_path=candidate,
                          pdf_text=text, pdf_error=err)
            ev.classification = "pdf"
            ev.reason = f"using local PDF: {candidate.name}"
            if err:
                # PDF extraction failed → hard fail
                ev.classification = "http_error"
                ev.reason = f"pdftotext failed on {candidate.name}: {err}"
            return ev
    # 2) Fall back to URL fetch
    url = item.canonical_url()
    if not url:
        ev = Evidence(source="none")
        ev.classification = "no_url"
        ev.reason = "ISBN-only or no URL in bibitem"
        return ev
    fetched = fetch_url(url)
    classification, reason = classify_fetch(fetched, url)
    # 3) Bot-block fallback: Playwright-driven headless Chromium recovers
    # the landing page metadata for Cloudflare-protected publishers (OUP,
    # APS, Elsevier, etc.) where urllib gets 403'd. Skipped if Playwright
    # is not installed.
    if classification in ("blocked", "http_error"):
        try:
            from browser_fetch import fetch_url_browser, playwright_available
        except ImportError:
            fetch_url_browser = None
            playwright_available = lambda: False  # noqa: E731
        if fetch_url_browser and playwright_available():
            b_fetched = fetch_url_browser(url)
            if not b_fetched.get("error") or b_fetched.get("status", 0) == 200:
                b_class, b_reason = classify_fetch(b_fetched, url)
                if b_class == "ok":
                    fetched = b_fetched
                    classification = "ok"
                    reason = f"(browser fallback) recovered from {classification}"
    ev = Evidence(source="url", fetched=fetched,
                  classification=classification, reason=reason)
    return ev


# ── Prompt + verdict ──────────────────────────────────────────────────

PROMPT_TMPL = """You are auditing a single citation in an academic paper.
Return ONLY a JSON object — no prose outside the JSON, no markdown fences.

INPUT: bibitem entry, evidence about the cited work, and the snippets of
the manuscript where the citation is invoked.

DOI / arXiv-ID / title matching has ALREADY been done deterministically
by a separate matcher (see PRE-COMPUTED METADATA below). It is INFORMATION
ONLY — do not redo that comparison.

Important: a metadata verdict of "FLAG" means the matcher couldn't reach
a decision because the bibitem lacked a DOI or arXiv ID (or the venue
returned no metadata) — it does NOT mean the citation is wrong, and it
must NOT be used to fail the `standard` dimension. A conference-proceedings
or journal paper without an arXiv preprint is still a perfectly archival
source.

Your job is ONLY the two dimensions that genuinely require reading: does
the cited paper support the manuscript's claim about it, and is the
source archival.

If the evidence text is empty / placeholder / unfetchable, mark
`supports_claim` as "N/A" rather than "FAIL" — absence of evidence is
not evidence of absence. Only mark `supports_claim` FAIL when you have
actual contradicting evidence from the cited work.

BIBITEM (key = {key}):
\"\"\"
{bibitem_raw}
\"\"\"

PRE-COMPUTED METADATA (from deterministic matcher, NOT to be re-judged):
  verdict   : {meta_verdict}
  rationale : {meta_rationale}

EVIDENCE SOURCE: {source_kind}
CANONICAL URL: {canonical_url}
FETCH STATUS: {status} ({final_url})
PAGE/PDF TITLE: {page_title}
PAGE META: {page_meta}
PAGE/PDF TEXT (first ~6-12 KB):
\"\"\"
{page_text}
\"\"\"

THE MANUSCRIPT CITES IT IN THESE CONTEXTS:
{contexts}

Evaluate these dimensions:
  A) supports_claim — Does the cited paper actually support what the
                      manuscript says about it in the quoted contexts?
                      Flag if the manuscript's claim looks unsupported,
                      overstated, or misattributed. Quote evidence verbatim.
  B) standard       — Is this an archival, citable source (journal,
                      conference, arXiv, book, Zenodo with DOI)?
                      Flag non-archival blog posts, dead links, or
                      marketing copy.

Return JSON of the form:
{{
  "verdict": "PASS" | "FLAG",
  "supports_claim":   {{"status": "PASS"|"FAIL"|"N/A", "note": "..."}},
  "standard":         {{"status": "PASS"|"FAIL"|"N/A", "note": "..."}},
  "overall_note": "<one-sentence summary>"
}}
verdict = PASS iff neither dimension is FAIL.
Be terse but specific in the notes.  Quote any mismatch verbatim."""


def build_prompt(item: BibItem, ev: Evidence,
                 contexts: list[str], meta_report: MetadataReport) -> str:
    ctx_block = "\n".join(f"  [{i+1}] {c}" for i, c in enumerate(contexts)) \
                or "  (none — possibly orphaned in body)"
    meta = json.dumps(ev.meta_for_prompt)[:1500]
    source_kind = {
        "pdf": "local PDF extracted via pdftotext",
        "url": "fetched URL landing page",
        "none": "no URL (ISBN-only or no online source)",
    }.get(ev.source, ev.source)
    return PROMPT_TMPL.format(
        key=item.key,
        bibitem_raw=item.raw[:2000],
        source_kind=source_kind,
        canonical_url=item.canonical_url() or "(none)",
        status=ev.status_for_prompt,
        final_url=ev.final_url_for_prompt,
        page_title=ev.title_for_prompt,
        page_meta=meta,
        page_text=ev.text_for_prompt[:12000],
        contexts=ctx_block,
        meta_verdict=meta_report.verdict,
        meta_rationale="; ".join(meta_report.rationale) or "(no rationale)",
    )


JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_verdict(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = JSON_OBJ_RE.search(text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {"verdict": "PARSE_ERROR", "raw": text[:800]}


def call_one(model: str, prompt: str, key: str) -> tuple[str, dict[str, Any]]:
    try:
        text = api_client.call_model(model, prompt,
                                     label=f"cite/{key}/{model}",
                                     temperature=0)
        return model, parse_verdict(text)
    except Exception as e:  # noqa: BLE001
        return model, {"verdict": "CALL_ERROR", "error": f"{type(e).__name__}: {e}"}


def hard_fail_verdict(ev: Evidence) -> dict[str, Any]:
    """Synthesize a FAIL verdict for citations whose evidence cannot be
    obtained. We do NOT call the LLMs in this case — they have a habit of
    passing "well-known" citations from prior knowledge even when the URL
    is dead, which defeats the audit.
    """
    return {
        "verdict": "FAIL",
        "url_resolves":   {"status": "FAIL", "note": ev.reason or ev.classification},
        "metadata_match": {"status": "FAIL", "note": "no evidence to compare against"},
        "supports_claim": {"status": "FAIL", "note": "no evidence to compare against"},
        "standard":       {"status": "N/A",  "note": "cannot assess without evidence"},
        "overall_note": (f"HARD FAIL — fetch classification "
                         f"{ev.classification!r}: {ev.reason}"),
        "_hard_fail": True,
    }


# ── Aggregation + report ──────────────────────────────────────────────

@dataclass
class CitationResult:
    key: str
    bibitem_raw: str
    canonical_url: str
    evidence: Evidence
    orphan_in_body: bool
    contexts: list[str]
    by_model: dict[str, dict[str, Any]] = field(default_factory=dict)
    hard_fail: bool = False
    meta_report: MetadataReport | None = None  # v3: deterministic metadata result

    @property
    def metadata_fail(self) -> bool:
        return bool(self.meta_report) and self.meta_report.verdict == "FAIL"

    @property
    def wrong_arxiv_same_paper(self) -> bool:
        return bool(self.meta_report) and self.meta_report.verdict == "WRONG_ARXIV_SAME_PAPER"

    @property
    def author_mismatch_same_paper(self) -> bool:
        return bool(self.meta_report) and self.meta_report.verdict == "AUTHOR_MISMATCH_SAME_PAPER"

    @property
    def unanimous_pass(self) -> bool:
        if (self.hard_fail or self.metadata_fail or
                self.wrong_arxiv_same_paper or self.author_mismatch_same_paper):
            return False
        verdicts = [v.get("verdict") for v in self.by_model.values()]
        return len(verdicts) == len(MODELS_TO_USE) and all(v == "PASS" for v in verdicts)

    @property
    def status_label(self) -> str:
        if self.hard_fail:
            return "✗ HARD FAIL (no evidence)"
        if self.metadata_fail:
            return "✗ METADATA FAIL (deterministic check)"
        if self.wrong_arxiv_same_paper:
            return "⚠ WRONG ARXIV ID — same paper, autofix available"
        if self.author_mismatch_same_paper:
            return "⚠ AUTHOR MISMATCH — same paper, bib author correction needed"
        if self.unanimous_pass:
            return "✓ unanimous PASS"
        return "⚠ dissent / FLAG"


def md_report(results: list[CitationResult], orphan_bib: list[str],
              orphan_cite: list[str], cost: dict, refs_dir: Path | None) -> str:
    lines: list[str] = []
    lines.append("# Citation verification report")
    lines.append("")
    lines.append(f"- models: {', '.join(MODELS_TO_USE)}")
    lines.append(f"- bibitems checked: {len(results)}")
    n_pass = sum(1 for r in results if r.unanimous_pass)
    n_hard = sum(1 for r in results if r.hard_fail)
    n_metafail = sum(1 for r in results if r.metadata_fail)
    n_autofix = sum(1 for r in results if r.wrong_arxiv_same_paper)
    n_authmis = sum(1 for r in results if r.author_mismatch_same_paper)
    n_soft = len(results) - n_pass - n_hard - n_metafail - n_autofix - n_authmis
    lines.append(f"- unanimous PASS: {n_pass}")
    lines.append(f"- metadata FAIL (deterministic — different paper): {n_metafail}")
    lines.append(f"- wrong arXiv ID but same paper (autofix): {n_autofix}")
    lines.append(f"- author mismatch (same paper, bib needs author fix): {n_authmis}")
    lines.append(f"- LLM dissent / FLAG (claim or archival): {n_soft}")
    lines.append(f"- HARD FAIL (no evidence — bot-block or 404): {n_hard}")
    lines.append(f"- API spend: ${cost.get('total_cost_usd', 0):.4f} "
                 f"(cap ${cost.get('cap_usd', 0):.2f})")
    if refs_dir:
        lines.append(f"- refs dir: `{refs_dir}`")
    lines.append("")
    if orphan_bib:
        lines.append("## Orphan bibitems (in bibliography, never cited)")
        for k in orphan_bib:
            lines.append(f"- `{k}`")
        lines.append("")
    if orphan_cite:
        lines.append("## Orphan cites (cited in body, no matching bibitem)")
        for k in orphan_cite:
            lines.append(f"- `{k}`")
        lines.append("")

    hard = [r for r in results if r.hard_fail]
    if hard:
        lines.append("## HARD FAILs — need local PDFs")
        lines.append("")
        lines.append("Put a PDF at `<refs_dir>/<key>.pdf` for each entry "
                     "below, then rerun with `--refs-dir <refs_dir>`.")
        lines.append("")
        for r in hard:
            lines.append(f"- **`{r.key}`** — {r.evidence.classification}: "
                         f"{r.evidence.reason}")
            lines.append(f"  - URL: {r.canonical_url or '(none)'}")
        lines.append("")

    # v3: special section for wrong-arxiv-id-same-paper autofixes
    autofix = [r for r in results if r.wrong_arxiv_same_paper]
    if autofix:
        lines.append("## Wrong arXiv ID, same paper — proposed autofixes")
        lines.append("")
        lines.append("The bibitem's `arXiv:` field points to a different paper, "
                     "but the resolved paper's title matches the bibitem title. "
                     "Apply the swap below to the bibliography. No body text "
                     "needs to change.")
        lines.append("")
        for r in autofix:
            mr = r.meta_report
            lines.append(f"- **`{r.key}`** — `arXiv:{mr.bib_arxiv}` "
                         f"→ `arXiv:{mr.suggested_arxiv}`")
            lines.append(f"  - bib title : {mr.bib_title!r}")
            lines.append(f"  - resolved  : {mr.src_title!r}")
        lines.append("")

    # v3.1: author-name mismatch on the same paper — bib needs author fix
    auth_mis = [r for r in results if r.author_mismatch_same_paper]
    if auth_mis:
        lines.append("## Author mismatch — same paper, bib author correction needed")
        lines.append("")
        lines.append("DOI/arXiv/title match (so the citation is to the right paper), "
                     "but the bib's authors don't match the source's authors. "
                     "Fix the bib entry; no body text change needed.")
        lines.append("")
        for r in auth_mis:
            mr = r.meta_report
            lines.append(f"- **`{r.key}`**")
            lines.append(f"  - bib authors    : {mr.bib_authors}"
                         f"{' + et al.' if mr.bib_etal else ''}")
            lines.append(f"  - source authors : {mr.src_authors}")
        lines.append("")

    # v3: deterministic metadata FAIL — the citation itself is wrong
    meta_fails = [r for r in results if r.metadata_fail]
    if meta_fails:
        lines.append("## Metadata FAILs (deterministic) — different paper than cited")
        lines.append("")
        lines.append("Citations where the bib's DOI/arXiv/title disagrees with the "
                     "resolved evidence. Either the bib entry is wrong, or the "
                     "manuscript should cite a different paper. LLMs not called.")
        lines.append("")
        for r in meta_fails:
            mr = r.meta_report
            lines.append(f"- **`{r.key}`**")
            for line in mr.rationale:
                lines.append(f"  - {line}")
            if mr.bib_title:
                lines.append(f"  - bib title : {mr.bib_title!r}")
            if mr.src_title:
                lines.append(f"  - resolved  : {mr.src_title!r}")
        lines.append("")

    # v3: bot-blocked URLs table for manual collection
    blocked = [r for r in results
               if r.evidence.classification in ("blocked", "http_error")]
    if blocked:
        lines.append("## Bot-blocked URLs — manual collection needed")
        lines.append("")
        lines.append("These citations could not be auto-verified because the "
                     "publisher's site refused our request (Cloudflare, "
                     "cookie wall, 403, etc.). Manually fetch a PDF from one "
                     "of the alternate-source columns and drop it at "
                     "`<refs_dir>/<key>.pdf`, then rerun.")
        lines.append("")
        lines.append("| key | blocked URL | suggested alternate sources |")
        lines.append("|---|---|---|")
        for r in blocked:
            url = r.canonical_url or "(none)"
            alts = "arXiv search · INSPIRE-HEP · NASA ADS · Sci-Hub · KEK preprints"
            lines.append(f"| `{r.key}` | {url} | {alts} |")
        lines.append("")

    lines.append("## Per-citation verdicts")
    for r in results:
        lines.append(f"\n### `{r.key}` — {r.status_label}")
        lines.append(f"- URL: {r.canonical_url or '(none)'}")
        ev = r.evidence
        if ev.source == "pdf":
            lines.append(f"- evidence: local PDF "
                         f"`{ev.pdf_path.name if ev.pdf_path else '?'}` "
                         f"(pdftotext)")
        else:
            lines.append(f"- evidence: {ev.classification} — {ev.reason or 'OK'}")
        if r.meta_report:
            lines.append(f"- metadata-check: **{r.meta_report.verdict}** — "
                         f"{'; '.join(r.meta_report.rationale)}")
        if r.orphan_in_body:
            lines.append(f"- ⚠ never cited in body")
        if r.hard_fail:
            lines.append(f"- **HARD FAIL** — LLMs not called (fetch "
                         f"unavailable; cannot let prior-knowledge PASS).")
            continue
        if r.metadata_fail:
            lines.append(f"- **METADATA FAIL** — LLMs not called "
                         f"(deterministic mismatch is dispositive).")
            continue
        for m, v in r.by_model.items():
            verdict = v.get("verdict", "?")
            note = v.get("overall_note") or v.get("error") or ""
            lines.append(f"  - **{m}** → {verdict} — {note}")
            if verdict not in ("PASS", "PARSE_ERROR", "CALL_ERROR", "N/A"):
                for dim in ("supports_claim", "standard"):
                    d = v.get(dim, {})
                    if d.get("status") == "FAIL":
                        lines.append(f"    - {dim} FAIL: {d.get('note','')}")
    return "\n".join(lines)


# ── Driver ────────────────────────────────────────────────────────────

def run(tex_path: Path, *, report_path: Path | None,
        cap_usd: float, workers: int,
        only: set[str] | None,
        refs_dir: Path | None) -> int:
    raw = tex_path.read_text(encoding="utf-8")
    text = strip_tex_comments(raw)
    body, bib = split_body_and_bib(text)
    bibitems = parse_bibitems(bib)
    cite_ctx = find_cite_contexts(body)

    bib_keys = {b.key for b in bibitems}
    cite_keys = set(cite_ctx.keys())
    orphan_bib = sorted(bib_keys - cite_keys)
    orphan_cite = sorted(cite_keys - bib_keys)

    print(f"[parse] {len(bibitems)} bibitems, "
          f"{len(cite_keys)} distinct keys cited", file=sys.stderr)
    print(f"[parse] {len(orphan_bib)} orphan bibitems, "
          f"{len(orphan_cite)} orphan cites", file=sys.stderr)
    if refs_dir:
        n_pdfs = sum(1 for b in bibitems if (refs_dir / f"{b.key}.pdf").is_file())
        print(f"[refs ] {n_pdfs}/{len(bibitems)} bibitems have local PDF "
              f"at {refs_dir}", file=sys.stderr)

    if only:
        bibitems = [b for b in bibitems if b.key in only]
        print(f"[filter] limited to {len(bibitems)} keys: "
              f"{sorted(only)}", file=sys.stderr)

    api_client.configure_tracker(cap_usd=cap_usd)
    api_client.load_keys()

    results: list[CitationResult] = []
    for idx, item in enumerate(bibitems, 1):
        ev = gather_evidence(item, refs_dir)
        url = item.canonical_url()
        print(f"\n──[{idx}/{len(bibitems)}] {item.key} "
              f"{'─' * max(0, 60 - len(item.key))}",
              file=sys.stderr)
        print(f"  bibitem    : {item.raw[:200].strip()}"
              f"{'…' if len(item.raw) > 200 else ''}",
              file=sys.stderr)
        print(f"  source     : {ev.source} ({ev.classification})",
              file=sys.stderr)
        if ev.source == "pdf":
            print(f"  pdf        : {ev.pdf_path.name if ev.pdf_path else '?'} "
                  f"({len(ev.pdf_text)} chars)", file=sys.stderr)
        elif ev.source == "url":
            print(f"  url        : {url}", file=sys.stderr)
            print(f"  HTTP       : {ev.fetched.get('status', 0)}  "
                  f"final={ev.fetched.get('final_url') or '(none)'}",
                  file=sys.stderr)
            if ev.fetched.get("title"):
                print(f"  title      : {ev.fetched['title'][:160]}",
                      file=sys.stderr)
        if ev.reason and ev.classification != "ok":
            print(f"  reason     : {ev.reason}", file=sys.stderr)
        ctxs = cite_ctx.get(item.key, [])
        for i, c in enumerate(ctxs, 1):
            print(f"  cite[{i}]    : …{c[:200]}…", file=sys.stderr)

        # v3: run deterministic metadata check up-front (DOI/arXiv/title)
        meta_report = metadata_check(
            item.raw,
            ev.fetched if ev.source == "url" else None,
            ev.pdf_path.name if ev.source == "pdf" and ev.pdf_path else None,
        )
        print(f"  meta-check : {meta_report.verdict} — "
              f"{'; '.join(meta_report.rationale)[:200]}",
              file=sys.stderr)

        if ev.is_hard_fail:
            print(f"  ▸ HARD FAIL — skipping LLM call (no evidence)",
                  file=sys.stderr)
            by_model = {m: hard_fail_verdict(ev) for m in MODELS_TO_USE}
            r = CitationResult(
                key=item.key, bibitem_raw=item.raw, canonical_url=url,
                evidence=ev, orphan_in_body=(item.key in orphan_bib),
                contexts=ctxs, by_model=by_model, hard_fail=True,
                meta_report=meta_report,
            )
            results.append(r)
            continue

        # If deterministic metadata FAIL, skip LLM — the citation points to
        # the wrong paper.  No amount of LLM reasoning will rescue it; the
        # bibitem needs to be fixed.
        if meta_report.verdict == "FAIL":
            print(f"  ▸ METADATA FAIL — skipping LLM call "
                  f"(deterministic mismatch, see rationale)",
                  file=sys.stderr)
            by_model = {m: {"verdict": "N/A",
                            "overall_note": "skipped — deterministic metadata FAIL"}
                        for m in MODELS_TO_USE}
            r = CitationResult(
                key=item.key, bibitem_raw=item.raw, canonical_url=url,
                evidence=ev, orphan_in_body=(item.key in orphan_bib),
                contexts=ctxs, by_model=by_model, hard_fail=False,
                meta_report=meta_report,
            )
            results.append(r)
            continue

        prompt = build_prompt(item, ev, ctxs, meta_report)
        by_model: dict[str, dict[str, Any]] = {}
        with cf.ThreadPoolExecutor(max_workers=min(workers, len(MODELS_TO_USE))) as ex:
            futs = {ex.submit(call_one, m, prompt, item.key): m
                    for m in MODELS_TO_USE}
            for f in cf.as_completed(futs):
                m, v = f.result()
                by_model[m] = v
                verdict = v.get("verdict", "?")
                note = (v.get("overall_note") or v.get("error") or "")[:140]
                print(f"  ▸ {m:9s} → {verdict:5s}  {note}",
                      file=sys.stderr)

        r = CitationResult(
            key=item.key, bibitem_raw=item.raw, canonical_url=url,
            evidence=ev, orphan_in_body=(item.key in orphan_bib),
            contexts=ctxs, by_model=by_model, hard_fail=False,
            meta_report=meta_report,
        )
        results.append(r)

        try:
            api_client.get_tracker().check(projected_cost=0.0)
        except api_client.BudgetExceeded as e:
            print(f"[budget] {e}", file=sys.stderr)
            break

    cost = api_client.get_tracker().summary()
    print(f"[cost] total ${cost['total_cost_usd']:.4f} of "
          f"${cost['cap_usd']:.2f}", file=sys.stderr)

    report = md_report(results, orphan_bib, orphan_cite, cost, refs_dir)
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        print(f"[done] report → {report_path}", file=sys.stderr)
    else:
        print(report)

    n_problems = sum(1 for r in results if not r.unanimous_pass)
    return 1 if n_problems or orphan_bib or orphan_cite else 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="check-citations",
                                  description=__doc__.splitlines()[0])
    ap.add_argument("tex", type=Path, help="Path to the .tex file.")
    ap.add_argument("--refs-dir", type=Path, default=None,
                    help="Directory containing <key>.pdf files. "
                         "If present, used in place of URL fetch.")
    ap.add_argument("--report", type=Path, default=None,
                    help="Write report to this Markdown file "
                         "(default: stdout).")
    ap.add_argument("--cap-usd", type=float, default=5.00,
                    help="Hard cost cap in USD. Default 5.00.")
    ap.add_argument("--workers", type=int, default=3,
                    help="Parallel model calls per citation. Default 3.")
    ap.add_argument("--only", type=str, default="",
                    help="Comma-separated bibitem keys to check "
                         "(default: all).")
    args = ap.parse_args()
    only = {k.strip() for k in args.only.split(",") if k.strip()} or None
    if not args.tex.is_file():
        sys.exit(f"[check-citations] no such file: {args.tex}")
    if args.refs_dir and not args.refs_dir.is_dir():
        sys.exit(f"[check-citations] --refs-dir is not a directory: "
                 f"{args.refs_dir}")
    return run(args.tex, report_path=args.report,
               cap_usd=args.cap_usd, workers=args.workers, only=only,
               refs_dir=args.refs_dir)


if __name__ == "__main__":
    sys.exit(main())
