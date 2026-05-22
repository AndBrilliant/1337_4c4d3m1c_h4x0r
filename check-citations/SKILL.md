---
name: check-citations
description: Verify every citation in a LaTeX paper. v3.2 (2026-05-22) — DOI / arXiv ID / title matching is DETERMINISTIC in code (see metadata_check.py). Author surname check (v3.1) is hardened against title/journal false positives (v3.2). LLMs used only for fuzzy claim-support / archival judgments. Playwright browser fallback (browser_fetch.py) auto-recovers metadata for Cloudflare-protected publishers (Oxford, Elsevier) that bot-block urllib. Detects "wrong arXiv ID but same paper" with autofix; "metadata FAIL" (no LLM call) when bib actually points to a different paper. Drive in a loop. Use when the user asks to "check citations", "verify the bibliography", or "make sure every reference resolves" in a .tex paper.
---

# check-citations (v3.2)

Verifies every citation in a LaTeX manuscript. The metadata-matching layer is **deterministic code** (`metadata_check.py`); LLMs are reserved for fuzzy judgments (claim support, archival quality).

**Code lives at `~/claude/paper-tools/check-citations/`** — `check_citations.py` (driver) and `metadata_check.py` (deterministic matcher). The companion screener prompts live next door at `~/claude/paper-tools/screeners/`.

## When to invoke

- "check citations in tmp.tex"
- "verify the bibliography for <paper>"
- "make sure every reference resolves"
- "find orphaned citations"
- "make the paper clean" (when context is a .tex with cites)

## v3 design — what's deterministic vs LLM

The previous version asked LLMs four questions per citation, including "does the bibitem's metadata match what the evidence reports?" — a fuzzy judgment models hallucinated either way on. v3 splits the job:

**Deterministic (code in `metadata_check.py`, every rule justified inline):**
- `url_resolves` — HTTP status check (already deterministic).
- DOI match — case-folded exact-equality after whitespace strip.
- arXiv ID match — case-folded equality after stripping `vN` version suffix.
- Title match — aggressive normalization (strip LaTeX / punctuation / whitespace; lowercase) then **substring containment in either direction**. Rejected alternatives (Levenshtein with threshold, word-overlap fraction) are noted in the docstring of `normalize_title()`.
- **Author match (v3.1)** — extract surnames from both bib and source. The bib's *first* surname must appear in the source's surname set; if the bib lists multiple distinct authors (not truncated by `et al.`), all of them must appear. Catches the "wrong first author" class of error (e.g. bib says `Jiayi Li et al.` for a paper actually by `Jiayi Ye et al.`). Triggers `FAIL` separately from title — the same paper can match by DOI/arXiv/title but still have a fabricated author list.

**LLM (3 models in parallel, only when deterministic check doesn't already decide it):**
- `supports_claim` — does the cited paper actually support the manuscript's specific claim? Quote evidence.
- `standard` — archival source? (rule is fuzzy because GitHub-without-DOI is borderline depending on venue policy.)

## What it does

1. Parses `\bibitem{key}` entries and every `\cite{...}` call in the body.
2. Reports **orphans**: bibitems never cited, and cites with no bibitem.
3. For each bibitem, resolves evidence: local PDF at `<refs_dir>/<key>.pdf` if `--refs-dir` is given, otherwise the canonical URL (DOI > arXiv > raw URL).
4. **Classifies the fetch BEFORE calling LLMs**:
   - `ok` — substantive content, proceed.
   - `blocked` — Cloudflare / cookie wall / "Redirecting" stub → **HARD FAIL**, no LLM call.
   - `http_error` — 4xx/5xx → **HARD FAIL**.
   - `network_error` — timeout/DNS → **HARD FAIL**.
   - `no_url` — ISBN-only book → LLM still called on bibitem text alone.
5. **Runs the deterministic metadata check.** Outcomes:
   - `PASS` — DOI or arXiv ID exact-match (and title matches if both IDs and titles present), or title substring containment. → Proceed to LLM `supports_claim` / `standard`.
   - `FAIL` — DOI/arXiv/title actively disagree → **no LLM call**, the citation points to a different paper than the bib claims. Surfaced in the "Metadata FAILs" section of the report.
   - `WRONG_ARXIV_SAME_PAPER` — arXiv IDs differ but titles agree → autofix surfaced (swap the eprint, no body text change needed).
   - `FLAG` — insufficient signal for code to decide; LLM `supports_claim` runs as usual.
6. Aggregates: PASS = deterministic PASS + unanimous LLM PASS. FAIL = anything else.

**Why the hard-fail behavior matters.** Previous versions let `opus` pass landmark citations from prior knowledge even when the URL returned 403, because "the model knows it's a real paper." Defeats the audit. New rule: no evidence, no LLM verdict, automatic FAIL. Drop a PDF at `<refs_dir>/<key>.pdf` to recover.

## BINDING — run this in a convergence loop, not one-shot

When invoking this skill, you (the assistant) are expected to drive it as a loop. The loop **uses the deterministic verdict to decide which kind of fix is needed**:

1. Run the verifier; read the report.
2. For each non-PASS entry, classify by the deterministic verdict and act:

   | Deterministic verdict | Action |
   |---|---|
   | `FAIL` (different paper) | **Hallucinated cite — present alternative candidates to the user.** Search arXiv / INSPIRE / Google Scholar for what the surrounding manuscript text actually wants to cite. Surface 1–3 options for the user to pick. Don't auto-replace. |
   | `WRONG_ARXIV_SAME_PAPER` | **Auto-apply the eprint swap.** Don't bother the user — same paper, just a wrong-ID typo. Update the bib and rerun. |
   | `PASS` + LLM `supports_claim` FAIL | **Wording or numerical mismatch.** Present a before/after rewrite to the user, **one at a time**, for approval. The user must approve each rewrite before it lands in the .tex. |
   | `PASS` + LLM `standard` FAIL | Non-archival source (GitHub w/o DOI, etc.). Tell the user; recommend Zenodo deposit. Not auto-fixable. |
   | `HARD FAIL` (bot-block) | Goes into the **Bot-blocked URLs table at the end of the report** for the user to manually grab PDFs. Do NOT keep looping on these — surface, stop, wait for the user. |
   | `HARD FAIL` (404 / true unfindable) | Surface as unfindable. Stop the loop. |

3. Continue until convergence: zero non-PASS entries, or the only remaining items are user-blocked (manual PDF needed / source genuinely doesn't exist).

The only stopping conditions are: (a) convergence, (b) the remaining issues all require user action you cannot take on your own.

## How to invoke

API keys load automatically from `~/.keys/{anthropic,openai,deepseek}`.

```bash
VENV=/Users/Drew/Desktop/Academic/AI_Research/graduated_dissent_bench/.venv/bin/python3
SCRIPT=~/claude/paper-tools/check-citations/check_citations.py

# Default: full report to stdout, $5 cap, 3 models in parallel
$VENV $SCRIPT <path/to/paper.tex>

# Write a Markdown report
$VENV $SCRIPT paper.tex --report report.md

# Use local PDFs in addition to URLs (recommended for any paper with
# bot-blocked publishers — APS, Elsevier, T&F, Springer paywall, etc.)
$VENV $SCRIPT paper.tex --refs-dir <dir>/refs

# Spot-check a subset of keys
$VENV $SCRIPT paper.tex --only Shulga2026,FLAG2024

# Raise the cap for a long bibliography
$VENV $SCRIPT paper.tex --cap-usd 15.00
```

### Argument summary

| flag         | default | meaning                                                       |
|--------------|---------|---------------------------------------------------------------|
| `<tex>`      | required| Path to the manuscript .tex                                    |
| `--refs-dir` | none    | Directory of `<key>.pdf` files. Used in place of URL fetch.   |
| `--report`   | stdout  | Write Markdown report to this path                            |
| `--cap-usd`  | 5.00    | Hard cost ceiling; harness aborts before exceeding            |
| `--workers`  | 3       | Parallel model calls per citation                             |
| `--only`     | (all)   | Comma-separated bibitem keys to verify (debugging)            |

### Cost expectation

Cheaper than v2 — deterministic verdicts skip LLM calls. HARD FAILs and metadata FAILs are free. Citations that reach the LLM cost ~$0.02–$0.05 (3 models × cached prompt). A 30-entry bibliography typically lands at $0.50–$1.50 per pass. Plan ~$3–$5 for a full convergence loop.

## Browser-automation fallback (v3.2)

When `fetch_url()` classifies as `blocked` or `http_error`, the driver auto-invokes `browser_fetch.fetch_url_browser()` (Playwright + headless Chromium). This defeats Cloudflare's "Just a moment..." JS challenge that protects many publishers and returns the landing page's metadata (title, citation_* tags, body text) — sufficient for the deterministic metadata check to PASS.

**Install once per machine:**
```bash
pip install playwright              # in the bench venv
python -m playwright install chromium
```

If Playwright is not installed, the driver still works — the bot-blocked entries just remain HARD FAIL and the user must grab a PDF.

**What the browser fallback handles:**
- Cloudflare interstitial challenge (defeats with anti-detection flags + navigator.webdriver spoof + viewport sizing + real UA).
- OneTrust cookie-consent banners (clicks "Accept All" / similar on Oxford, Elsevier, Springer, T&F).
- Recovers landing-page metadata cleanly — the citation checker only needs that.

**What it does NOT handle:**
- Direct PDF GETs through Cloudflare (OUP, Elsevier 403 `/article-pdf/...` URLs even with valid session cookies). The user must grab those manually in a real browser.
- Real paywalls (paid content like vintage APS PRL articles). No bypass; user needs institutional access or to purchase.

## Publisher access notes (updated as we learn)

Document publisher behaviors here so future runs save time. Add a row per new publisher hit.

| Publisher | Behavior | Best workaround |
|---|---|---|
| **Oxford Academic** (`academic.oup.com`) — NAR, PTP, BJPS, etc. | Cloudflare + OneTrust. Direct PDF URLs 403 even from authenticated browser sessions. Landing page scrapes cleanly with the browser fallback. | Browser fallback handles metadata. PDFs: user grabs in real browser. |
| **APS Journals** (`journals.aps.org`) — PR, PRL, PRD, etc. | Vintage papers (pre-~1980) paywalled at ~$35. Intermittent CF block on landing pages. APS sometimes double-charges; refund via `cust-serv@aps.org`. | PDG (PR D) is CC-BY at `pdg.lbl.gov/2024/download/db2024.pdf`. Other APS papers: institutional sub or purchase. |
| **Science / AAAS** (`science.org`) | CF + 1y embargo for some. | Mirrored copies on institutional repos (e.g. osc2015 at U Dundee). |
| **PNAS** (`pnas.org`) | CF on landing; PDFs open after 6mo embargo. | PMC mirrors: `pmc.ncbi.nlm.nih.gov/articles/PMC<id>/pdf/<filename>.pdf` (often serves a 1.8KB redirect; use the PMC landing instead). OSF preprints from author also work. |
| **Elsevier / ScienceDirect** | Heavy CF, returns "Redirecting" stub even from browser. | Author-hosted PDFs (e.g. Mayo & Spanos 2011 at `errorstatistics.com`). |
| **University of Chicago Press** (`journals.uchicago.edu`) — Phil Sci, etc. | Paywalled. | PhilSci-Archive preprints (`philsci-archive.pitt.edu`) — but PhilSci itself bot-blocks direct PDF curls; user grabs in browser. |
| **PDG** (Particle Data Group) | Always free, CC-BY 4.0. | `https://pdg.lbl.gov/<year>/download/db<year>.pdf` |
| **arXiv** | Open, friendly to curl. | No fallback needed. |
| **viXra** | Open, used for non-arXiv preprints (e.g. Brannen, Kosinov). | Direct PDF URL works with curl. |
| **TechRxiv** | Migrating (May 2026), bot-blocks downloads. | Cross-posted copies on Preprints.org work. |
| **PhilSci-Archive** (`philsci-archive.pitt.edu`) | Bot-blocks direct PDF curls; landing page works in real browser. | User grabs in browser. |
| **errorstatistics.com** (Mayo's blog) | Open, friendly to curl. Hosts free PDFs of most Mayo/Spanos papers. | `/wp-content/uploads/...` URL pattern; the `/mayo-publications/` page indexes them. |

## Underlying assumptions

- `pdftotext` (Poppler) must be on PATH. macOS: `brew install poppler`.
- The harness expects `api_client.py` at `~/Desktop/Academic/AI_Research/graduated_dissent_bench/harness/api_client.py`.
- Keys at `~/.keys/{anthropic,openai,deepseek}` via `api_client.load_keys()`.
- `--cap-usd` enforced by the shared `CostTracker`.
- Playwright + Chromium for the browser fallback (optional but recommended; install per above).

## Related tools

- `~/claude/paper-tools/check-citations/bib_to_bibitems.py` — converts a BibTeX `.bib` file to an inline `\thebibliography` block so the `\bibitem`-only parser can process BibTeX papers. Use with `<tex> <bib> -o <output.tex>` then run the checker on the output.
- `~/claude/paper-tools/check-citations/browser_fetch.py` — Playwright fallback. Can also be invoked standalone for ad-hoc URL fetches: `python browser_fetch.py <url> [download_dir] [key]`.
- `~/claude/paper-tools/screeners/` — preprint and preflight screener prompts, designed to be pasted into a fresh model session (different vendor preferred). Use after this skill converges and before submission.
- `~/Desktop/Academic/library/` — the unified citation library (one_pager.md + PDF per slot). See its `ADDING_FILES.md`.

## When to redirect the user

- If the user wants verification against an archival-only policy (no preprints), the `standard` dimension already flags non-archival sources; harden the prompt if needed.
