---
name: graduated-dissent
description: Run the Graduated Dissent multi-model error-detection pipeline on a scientific manuscript. v1 — adversarial steelman protocol between two prover models, a judge, and an arbiter, all reading the paper independently to surface retraction-worthy errors before submission. Use when the user asks to "run graduated dissent on this paper", "check this paper for retraction-worthy bugs", "do a multi-model error audit on the manuscript", or compares against a baseline like single-model review (B1/B2) or naive ensemble (B3). Reads paper.txt; outputs JSON trace with prover reviews, judge ruling, steelman exchange (GD only), and arbiter verdict per finding, plus token/cost stats. Not free — budget $1–$15 per paper depending on condition and length. Drive in a loop only when comparing conditions; single-paper runs are one-shot.
---

# graduated-dissent (v1)

A multi-model protocol for catching errors in scientific manuscripts. Two
**prover** models read the paper independently and produce reviews. A
**judge** model adjudicates between them. In the full GD condition, a
**steelman exchange** lets each prover argue against the other's findings
before a final **arbiter** decides which findings stand.

The aim: catch the class of mistakes that a single model misses (because
it confidently hallucinates one way) and that naive ensembling also misses
(because the disagreement just gets averaged into noise). The adversarial
exchange forces models to commit to specific objections, surfaces real
disagreement, and lets the arbiter rule on substance instead of vibes.

**Code lives at `~/Desktop/Academic/AI_Research/graduated_dissent_bench/harness/`** — the
canonical runtime is `run_pipeline.py`. The companion paper (Brilliant 2026,
IJPRAI submission) is in the same repo at `paper/main.tex`. Override via
`$GD_REPO` environment variable when running elsewhere.

## When to invoke

- "run graduated dissent on `paper.txt`"
- "check this paper for retraction-worthy bugs"
- "audit this manuscript with multiple models"
- "what would a multi-model review find in this paper?"
- "compare B3 (naive ensemble) vs GD on this paper"
- "run the full graduated-dissent benchmark condition on `<paper>`"

## The four conditions

| Code | Name | Models per paper | What it does |
|---|---|---|---|
| **B1** | Single-model, no rubric | 1 | Liang-2024 baseline — one prover gives a flat review. |
| **B2** | Single-model, severity rubric | 1 | Same prover with an explicit severity scale (minor/major/retraction-worthy). |
| **B3** | Naive ensemble | 3 + arbiter | Two provers + judge pool their findings to the arbiter, no exchange. |
| **GD** | Full graduated dissent | 3 + arbiter + steelman | The full protocol: prover A and B produce reviews, judge adjudicates, then each prover writes a **steelman** of the other's strongest objection, then the arbiter sees both the original disagreement and the steelman before ruling. |

The empirically-interesting condition is **GD**. The others exist as ablations
for the paper. Default to GD unless the user asks for a specific baseline.

## How to invoke

### Via the papers MCP server (background, recommended)

The `papers` MCP server (in this repo) wraps the harness and runs it as a
detached background job, so the conversation isn't blocked while it churns
through 5–30 minutes of model calls. Tool name: **`gd_run`**.

```
gd_run(
    paper_path="/abs/path/to/paper.txt",
    paper_id="2405.01133v3",      # arbitrary stable ID for output dirs
    condition="gd",                # one of b1, b2, b3, gd
    out_dir="",                    # optional; defaults under $GD_REPO/data/mcp_runs/
    cap_usd=25.0,                  # hard cost ceiling
)
```

Returns a `job_id`. Use `job_status(job_id)` and `job_tail(job_id, lines=50)`
to monitor.

### Via the harness CLI directly

```sh
cd ~/Desktop/Academic/AI_Research/graduated_dissent_bench
.venv/bin/python harness/run_pipeline.py \
    --paper data/spot/text_detectable/<id>/paper.txt \
    --paper-id <id> \
    --condition gd \
    --out-dir data/spot/outputs/your_run/ \
    --cap 25.0
```

## Inputs the harness expects

- **`paper.txt`** — the manuscript as plain text. Use `pdftotext`, `pandoc -t
  plain`, or LaTeX-to-text conversion to produce it. The harness does not
  parse PDFs or .tex directly — it expects pre-extracted text.
- **`paper-id`** — any short stable identifier; used to name output files.
- **`--cap`** — hard cost cap in USD. Default 25 in the harness; the MCP
  wrapper exposes the same flag.

API keys come from `~/.keys/{anthropic,openai,deepseek}`. If the user has
not configured those, run `python3 ~/claude/paper-tools/setup_keys.py` first
or set them via the MCP `keys_set` tool.

## Outputs

A JSON file under the chosen `--out-dir`:

```
<out-dir>/<paper_id>/<condition>.json
```

Contents:

- **Prover reviews** (one per prover model) — each with findings tagged by
  severity (minor / major / retraction-worthy) and section.
- **Judge ruling** — which findings the judge thinks are real vs spurious.
- **Steelman exchange** (GD only) — each prover's strongest objection to
  the other's controversial findings.
- **Arbiter verdict** — final per-finding ruling that the user reads.
- **Token + cost stats** — per-model breakdown so users can see where the
  money went.

The arbiter verdicts are the user-facing output. The prover/judge/steelman
trace is auditable but rarely useful to read end-to-end.

## Cost notes — read before running

Typical per-paper costs:

| Condition | Median cost (one 10–15 page paper) |
|---|---|
| B1 | $0.30–$0.80 |
| B2 | $0.40–$1.00 |
| B3 | $1.50–$4.00 |
| GD | $4–$12 |

For sweeps (multiple papers, multiple conditions) use the `--cap` flag
aggressively and start with a single paper end-to-end before scaling up.
The harness does not refund — once a model call returns, the cost is sunk.

## What graduated dissent is good at

- **Numerical/equation errors** the authors didn't catch in proof.
- **Citation/attribution problems** where the paper cites work that doesn't
  say what the paper claims it says.
- **Dimensional inconsistencies** (units, scaling laws, scheme contradictions).
- **Logical gaps** between sections — claim made in §3 contradicts claim
  made in §5.
- **Overstated claims** — abstract claims X but body only supports a weaker
  Y.

## What it's NOT good at

- **Plagiarism** — that's a different tool (textual overlap, not semantic).
- **Statistical analysis correctness** when methods are described only in a
  supplement the harness wasn't given.
- **Domain-specific intuition** in niche subfields the models have never
  read.  GD will report no concerns; that's not the same as the paper
  being correct.
- **Predicting acceptance** — GD scores correctness, not novelty or fit.

## Convergence loop pattern (only when comparing conditions)

For the benchmark paper: run B1, B2, B3, GD on the same set of papers in
sequence and compare detection rates against ground-truth retractions /
controls. Loop is per-condition, not per-paper.

For a single paper a user wants checked, just run GD once.

## Track record (v6 benchmark, n=10 retracted papers + 19 controls)

| Condition | Detection | False positives |
|---|---|---|
| B1 | 3/10 (30%) | n/a |
| B2 | 4/10 (40%) | 3/19 (16%) |
| B3 | 3/10 (30%) | 1/19 (5%) |
| **GD** | **7/10 (70%)** | **0/19 (0%)** |

OOF audit (Grok 4 + Mistral Large 2 majority on findings, models disjoint
from the GD evaluation pipeline): GD detects 10/10 retracted (in-fam 7/10),
2/19 FP on controls (in-fam 0/19). Direction (GD > B3 specificity) holds;
absolute "0/19" claim does not survive independent audit. Cohen κ in-fam vs
OOF: 0.40.
