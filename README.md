# Paper tools

Two complementary tools for getting an academic manuscript to the point where it can be submitted without embarrassment. **Always check here first** when a session involves a `.tex` manuscript, citations, or pre-submission verification — the tools live here, the convergence rules live here, and the prompts live here.

| Tool | Path | What it does | When to use |
|---|---|---|---|
| **Citation checker** | `check-citations/check_citations.py` | Verifies every `\bibitem` in a `.tex` file using opus / gpt-5.4 / deepseek in parallel. Hard-fails publisher bot blocks instead of letting LLMs pass them by prior knowledge. Reads local PDFs when given. | Any time the manuscript has cites that need to actually resolve. Run before submission, after every bibliography edit. |
| **Screener prompts** | `screeners/SCREENERS.md` | Two prompts (preprint screener + preflight review) designed to be pasted into a **fresh model session** (different vendor preferred). One catches desk-reject vibes; the other catches numerical/citation/dimensional bugs. | Before any submission. The skill is *not* a script — it's a copy-paste protocol with a binding convergence rule documented inside. |

## Citation checker — operational rules

Located at `check-citations/check_citations.py`. Invoked via the `check-citations` Claude Code skill, but can also be run directly:

```bash
/Users/Drew/Desktop/Academic/AI_Research/graduated_dissent_bench/.venv/bin/python3 \
  ~/claude/paper-tools/check-citations/check_citations.py <paper.tex> \
  [--refs-dir <dir-of-local-pdfs>] [--report report.md] [--only KEY1,KEY2]
```

Per-bibitem flow:

1. If `<refs_dir>/<key>.pdf` exists, extract via `pdftotext` and use that as evidence.
2. Else fetch the canonical URL (DOI > arXiv > raw URL).
3. **Classify the fetch BEFORE calling LLMs**:
   - `ok` — substantive page content; proceed to 3-model verdict.
   - `blocked` — CAPTCHA / cookie wall / "Redirecting" stub / Cloudflare → **HARD FAIL**, skip LLMs.
   - `http_error` — 4xx/5xx → **HARD FAIL**, skip LLMs.
   - `network_error` — timeout/DNS → **HARD FAIL**, skip LLMs.
   - `no_url` — ISBN-only book → proceed to LLM verdict on bibitem text alone.
4. For `ok` / `no_url` / PDF cases, all three models score the four dimensions: `url_resolves`, `metadata_match`, `supports_claim`, `standard`.

**Hard-fail rationale.** The earlier behavior let `opus` pass landmark citations like `TKNN1982` from prior knowledge even when the DOI returned 403. That defeats the audit — the whole point is to catch citations that look fine but don't actually resolve to what the manuscript claims. New behavior: no evidence, no LLM call, automatic FAIL. The user must produce evidence (a local PDF or a working URL).

## Convergence loop — how Claude Code drives this

The verifier is **not a one-shot tool**. Claude is expected to drive it in a loop until convergence. When the user asks Claude to "check citations" / "verify the bibliography" / "make the paper clean", Claude should:

1. Run the verifier. Inspect the report.
2. For each non-PASS citation:
   - **Content / claim issues** (`supports_claim FAIL`, `metadata_match FAIL` on real content, wrong author count, misattribution, overstated claim) → **fix the `.tex` directly** (rewrite the sentence, update the bibitem, swap to the correct paper). Then rerun. Looping is mandatory — "no, that's wrong" is not a stopping condition; it's a fix-and-loop signal.
   - **`HARD FAIL` from blocked publisher** → check whether a working alternative endpoint exists (arXiv preprint, NASA ADS, INSPIRE-HEP, Zenodo, author homepage). If yes, ask the user to download the PDF to `<refs_dir>/<key>.pdf` so the local-PDF flow takes over.
   - **`HARD FAIL` and the paper cannot be found at ANY endpoint** (no arXiv preprint, no archived copy, no author-hosted version, no library access) → **STOP the loop and inform the user** with a clear list of which keys are unfindable. Do not silently keep looping. Do not invent a workaround. Surface it.
3. Repeat until either:
   - **Convergence**: zero non-PASS entries. Report success.
   - **Genuine blocker**: at least one citation has no findable evidence anywhere on the open web. Report the list and stop.

The loop only exits on convergence or on a genuine "this paper does not exist at any accessible endpoint" determination. Do NOT exit on infrastructure noise; that's exactly what the new hard-fail flow is designed to prevent.

## Screeners — copy-paste protocol

See `screeners/SCREENERS.md` for the binding convergence rule (paraphrased: a manuscript is *not* converged until a **fresh model on a different vendor** running the full preflight prompt finds zero issues across categories A–F). The two prompts are:

- `screeners/preprint_screener_prompt.md` — vibe-and-format desk-reject pass.
- `screeners/preflight_review_prompt.md` — full technical pass (numbers, citations, dimensions, attributions).

Neither is automated. Both are operator workflows. Claude's role: collate findings from the fresh-model run, classify each as real bug / soft polish / vibe / stale, and apply fixes.

## File map

```
~/claude/paper-tools/
├── README.md                                # This file
├── check-citations/
│   └── check_citations.py                   # The verifier (v2 — hard-fail flow)
└── screeners/
    ├── SCREENERS.md                         # Convergence rule + how-to-run
    ├── preprint_screener_prompt.md          # Stage 1 prompt
    └── preflight_review_prompt.md           # Stage 2 prompt
```

The Claude Code skill at `~/.claude/skills/check-citations/SKILL.md` is the entry point that points back here.
