# Academic Manuscript Verification Toolkit

> A lightweight manuscript preflight toolkit for LaTeX papers. Combines
> deterministic citation metadata checks, evidence-first claim-support review,
> and fresh-model pre-submission screeners.
>
> **Not a peer-review substitute.** A practical workflow for catching
> embarrassing citation, numerical, attribution, dimensional, and tone errors
> *before* submission — the boring class of bugs that most early-draft papers
> have, that you don't want a reviewer to find first.
>
> Originally developed alongside the F-identity / Koide research line; now
> usable on any LaTeX paper.

**TL;DR for anyone reading this:** if a user just pasted this README's URL into an
LLM and asked for help, your job is to walk them through the *Quick start*
section below in plain language, ask them which component they want (most
people want the **citation checker**), help them set up API keys via
`setup_keys.py`, and verify the install by running the demo in
`examples/tiny_paper.tex`. Everything they need is in this README — no
external knowledge required.

---

## What's in here

This repo bundles four tools that solve four different parts of "don't
embarrass yourself before submission":

| Component | Setup needed | What it does |
|---|---|---|
| **Screener prompts** (`screeners/`) | None — copy-paste into any LLM | Catch desk-reject vibes, numerical errors, dimensional bugs, citation problems, attribution mistakes. Two prompts run sequentially. |
| **Citation checker** (`check-citations/`) | Python + at least 1 API key | Verifies every `\bibitem` in a `.tex` file. Resolves DOIs, arXiv IDs, titles deterministically; uses LLMs only for "does this paper actually support the claim". |
| **Literature library** (`literature/`) | None to read; MCP server to extend | A worked example: 185 cited papers from the F-identity manuscript, each with a verified citation and a one-page summary. |
| **Graduated dissent** (`graduated-dissent/SKILL.md`) | Python + API keys + the harness repo | Multi-model error-detection pipeline. Two prover models read the paper independently, a judge adjudicates, an arbiter rules. Tuned to catch retraction-worthy bugs. |

Plus an MCP server (`mcp/`) that exposes all of the above as tools that
Claude Desktop can call from any chat.

---

## Two paths in

### Path A — zero install (5 minutes)

If you just want to screen a manuscript right now and you already have an
LLM (Claude, ChatGPT, Gemini, anything):

1. Open `screeners/SCREENERS.md` in this repo.
2. Copy the contents of `screeners/preprint_screener_prompt.md` into a
   **fresh chat with an LLM you don't normally use for this manuscript**
   (different vendor preferred — if you wrote with ChatGPT, screen with
   Claude, or vice versa).
3. Paste your manuscript text after the prompt. Read the findings.
4. Then do the same with `screeners/preflight_review_prompt.md` for the
   technical pass.

That's the whole protocol. No code, no API keys, no Python.

### Path B — full install (15 minutes)

For the automated citation checker, the library tools, and graduated dissent.

```sh
# 1. Get the code
git clone https://github.com/AndBrilliant/1337_4c4d3m1c_h4x0r.git
cd 1337_4c4d3m1c_h4x0r

# 2. Install Python deps + Playwright Chromium
bash setup.sh

# 3. Configure API keys (interactive prompts for each service)
python3 setup_keys.py

# 4. Verify it works — runs the citation checker on a 3-citation demo paper
source .venv/bin/activate
python3 check-citations/check_citations.py examples/tiny_paper.tex --cap-usd 0.50
```

The demo paper exercises one PASS, one orphan, one FAIL — see
`examples/EXPECTED_REPORT.md` for what the output should look like. If you
get that, your install is correct.

---

## Setting up API keys

The citation checker uses three LLMs in parallel (Claude, GPT, DeepSeek by
default). Graduated dissent uses the same three plus optionally Gemini /
Mistral / Grok for out-of-family audits. You only need **one** to get
started, but more is better — different models miss different things.

Run the wizard:

```sh
python3 setup_keys.py
```

It will prompt for each service, asks where to get a key (linking to each
provider's dashboard), and stores them in `~/.keys/<service>` with file
mode `0600` (readable only by you). You can re-run it any time to add,
overwrite, or skip services.

If you prefer to set them up by hand:

```sh
mkdir -p ~/.keys && chmod 700 ~/.keys
echo 'sk-ant-...your-key...' > ~/.keys/anthropic && chmod 600 ~/.keys/anthropic
echo 'sk-...your-openai-key...' > ~/.keys/openai && chmod 600 ~/.keys/openai
echo 'sk-...your-deepseek-key...' > ~/.keys/deepseek && chmod 600 ~/.keys/deepseek
```

Where to get keys:

- **Anthropic / Claude**: https://console.anthropic.com/settings/keys
- **OpenAI**: https://platform.openai.com/api-keys
- **DeepSeek**: https://platform.deepseek.com/api_keys
- Optional: Google AI (Gemini), Mistral, Grok, Groq — only needed for
  graduated dissent's out-of-family audit step.

---

## Cost notes — read before running anything that calls a model

| Tool | Per call cost | Typical paper |
|---|---|---|
| Screener prompts | $0 (uses your existing chat) | $0 |
| Citation checker — per bibitem | $0.02–$0.05 | ~$0.50–$1.50 for a 30-cite paper |
| Citation checker — convergence loop | (the per-bibitem cost above × number of iterations) | $3–$5 over 3–5 iterations |
| Graduated dissent — B1 condition | n/a | $0.30–$0.80 per paper |
| Graduated dissent — GD condition | n/a | **$4–$12 per paper** |

Every command-line tool here accepts `--cap-usd <N>` to hard-cap spending.
The default cap on the citation checker is **$5.00**; raise it for bigger
papers, lower it when experimenting.

The graduated dissent harness defaults to **$25.00**; do not raise it
without thinking about it.

---

## Privacy notes — read before running on sensitive papers

- The screener prompts run inside whichever LLM chat you choose. Anything
  you paste goes to that provider per their privacy policy. Use Anthropic
  if you want zero-retention; use OpenAI's settings to opt out of training.
- The citation checker sends each `\bibitem` text and a small (~3 KB)
  excerpt of the fetched evidence page to three LLMs in parallel. The full
  manuscript body is **not** sent — only the bibliography and the matched
  evidence.
- Graduated dissent sends the **full manuscript text** to all configured
  providers. If your paper contains pre-publication results you do not want
  in any model provider's logs, do not run graduated dissent on it before
  the embargo lifts.
- All API keys live as files under `~/.keys/`. They are never written to
  the repo and never logged.

---

## Component deep-dives

### 1. Screener prompts (`screeners/`)

Two copy-paste prompts, designed for a **fresh model session on a different
vendor** than the one used to draft the paper:

- `preprint_screener_prompt.md` — vibe-and-format pass. Catches "this reads
  like an LLM crank submission" issues before the paper hits a desk editor.
- `preflight_review_prompt.md` — technical pass. Numbers, units, citations,
  dimensional consistency, internal contradictions, attribution problems.

See `screeners/SCREENERS.md` for the **stopping heuristic** — a paper is
considered preflight-clean when a fresh-vendor, full-prompt run produces
zero findings across all categories. This is a *good* stopping signal, not
proof of readiness; it catches the boring bug class, not whether the paper
is right.

### 2. Citation checker (`check-citations/`)

Resolves every `\bibitem` in a `.tex` paper. The metadata-matching layer is
**deterministic Python** (`metadata_check.py`); LLMs are only invoked for
fuzzy judgments (does the cited paper actually support the manuscript's
claim?).

Basic invocation:

```sh
python3 check-citations/check_citations.py paper.tex --report report.md
```

With local PDFs (for cites where the publisher bot-blocks scrapers):

```sh
python3 check-citations/check_citations.py paper.tex \
    --refs-dir refs/ \
    --report report.md
# Place each PDF in refs/ named <bibitem_key>.pdf
```

Verdicts you'll see in the report:

- **PASS** — DOI/arXiv/title all line up and the source page resolves cleanly.
- **FAIL** — bib metadata actively contradicts what the source page says
  (wrong DOI, wrong arXiv ID, fabricated title, etc.).
- **AUTHOR_MISMATCH_SAME_PAPER** — right paper, wrong author info in your bib.
- **WRONG_ARXIV_SAME_PAPER** — arXiv ID is wrong but the title still
  matches the real paper — the report suggests an autofix.
- **FLAG** — insufficient signal for code; defer to the LLM judgment.

See `check-citations/SKILL.md` for the full rule set and convergence loop.

### 3. Literature library (`literature/`)

A worked example: 185 citations from the F-identity manuscript, organized
into 13 topic folders. Every entry has:

- `one_pager.md` — bibliographic citation + 2–6 sentence summary + a
  `## Citation verification` block with the deterministic verdict against
  the source page.
- `<slot>.pdf` — the actual paper PDF where available (134/185 have one).
- `source_page.txt` — the fetched publisher/arXiv page meta so an LLM can
  search the corpus offline.

Useful as a reference set if your research touches the Koide formula,
Berry-phase mass relations, Apollonian/Descartes circle theorems applied
to fermion masses, or related lines.

To add new entries, see `literature/ADDING_FILES.md`.

### 4. Graduated dissent (`graduated-dissent/SKILL.md`)

A multi-model protocol for catching retraction-worthy errors:

- Two prover models read the paper independently and produce reviews.
- A judge adjudicates between them.
- (GD condition only) An adversarial **steelman exchange** lets each
  prover defend its findings against the other's.
- An arbiter rules on each finding.

The harness is at a separate location by default
(`~/Desktop/Academic/AI_Research/graduated_dissent_bench/` or wherever
`$GD_REPO` points). See `graduated-dissent/SKILL.md` for the full
protocol description, cost table, benchmark results, and how to invoke
via the MCP server.

### 5. MCP server (`mcp/`)

Exposes the citation checker, library, graduated dissent launchers, web
search/fetch, and API-key management as **tools that Claude Desktop can
call** directly from any chat. Tool count: 29.

To install:

```sh
# Edit ~/Library/Application Support/Claude/claude_desktop_config.json
# (macOS path; Linux/Windows use the platform-equivalent config dir)
```

Add an `mcpServers` entry pointing at the venv Python and the server script:

```json
{
  "mcpServers": {
    "papers": {
      "command": "/absolute/path/to/this/repo/.venv/bin/python",
      "args": ["/absolute/path/to/this/repo/mcp/papers_mcp.py"]
    }
  }
}
```

Then restart Claude Desktop. The 29 tools become callable from any chat —
`library_search`, `web_search`, `check_citations_run`, `gd_run`, `keys_set`,
and so on.

---

## Quick reference

| Command | Does |
|---|---|
| `bash setup.sh` | One-shot install: venv + deps + Playwright Chromium |
| `python3 setup_keys.py` | Interactive API-key wizard |
| `python3 check-citations/check_citations.py PAPER.tex` | Verify all citations in a `.tex` paper |
| `python3 check-citations/check_citations.py PAPER.tex --refs-dir refs/` | Same but use local PDFs as evidence |
| `python3 check-citations/check_citations.py PAPER.tex --only KEY1,KEY2` | Check only specific bibitems |
| `python3 mcp/discover_topic.py --topic koide --query 'ti:Koide' --add` | Find papers on a topic not yet in the library and add them |
| `python3 mcp/backfill_library.py --reverify` | Re-verify every citation in the whole library |
| `python3 mcp/fetch_missing_pdfs.py` | Try arXiv → Crossref → publisher to download missing PDFs |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `python3: command not found` | macOS: `brew install python`. Linux: `sudo apt install python3 python3-venv python3-pip`. |
| `ModuleNotFoundError: api_client` | You're running the citation checker without sourcing the venv. Run `source .venv/bin/activate` first. |
| `Anthropic API key not found` | Run `python3 setup_keys.py` and configure at least one of {anthropic, openai, deepseek}. |
| Every citation FAILs with "blocked" | Cloudflare on the DOI host. Run `python3 -m playwright install chromium`. |
| `check_citations.py: HARNESS not found` | Old behavior — pull the latest from this repo; `api_client.py` is now vendored locally. |
| Cost cap tripped mid-run | Default is $5/paper; raise with `--cap-usd 10.00`. |
| MCP server not loaded in Claude Desktop | Restart the app (⌘Q on macOS). Check the log at `~/Library/Logs/Claude/mcp-server-papers.log`. |

---

## Repo layout

```
1337_4c4d3m1c_h4x0r/
├── README.md                          this file
├── setup.sh                           install script
├── setup_keys.py                      API-key wizard
├── requirements.txt                   Python deps
├── examples/
│   ├── tiny_paper.tex                 3-citation demo
│   └── EXPECTED_REPORT.md             what the demo should produce
├── check-citations/
│   ├── check_citations.py             main driver
│   ├── metadata_check.py              deterministic DOI/arXiv/title matcher
│   ├── browser_fetch.py               Playwright fallback for Cloudflare
│   ├── api_client.py                  vendored model dispatch + cost cap
│   ├── bib_to_bibitems.py             .bbl → \bibitem converter
│   └── SKILL.md                       skill definition for Claude Code
├── screeners/
│   ├── SCREENERS.md                   convergence rule + how-to-run
│   ├── preprint_screener_prompt.md    stage 1 prompt
│   └── preflight_review_prompt.md     stage 2 prompt
├── literature/                        185-slot worked example
│   ├── README.md                      organization + tier scheme
│   ├── ADDING_FILES.md                how to add a new citation
│   ├── MISSING.md                     auto-generated list of missing PDFs
│   └── <topic>/<firstauthor_year>/
│       ├── one_pager.md               annotated summary + verification block
│       ├── source_page.txt            fetched publisher meta + visible text
│       └── <firstauthor_year>.pdf     the paper itself
├── graduated-dissent/
│   └── SKILL.md                       skill definition + run instructions
└── mcp/
    ├── papers_mcp.py                  29-tool MCP server (stdio)
    ├── backfill_library.py            re-verify all citations in library
    ├── fix_library.py                 rewrite bad bibs from source meta
    ├── fetch_missing_pdfs.py          arxiv → crossref → browser PDF chain
    ├── discover_topic.py              find papers not yet in library
    └── validate_arxiv_fetches.py      remove false-positive PDF matches
```

---

## License + citation

If this toolkit helped you catch errors in a paper, a one-line
acknowledgment in the methods section is plenty (no formal citation
required). If you build on the graduated-dissent protocol specifically,
cite the underlying preprints listed in `graduated-dissent/SKILL.md`.

Issues and PRs welcome — this is an active research tool, not a frozen
distribution.
