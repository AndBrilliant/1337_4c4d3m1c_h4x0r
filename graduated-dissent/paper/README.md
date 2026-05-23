# Steelmanning LLM Review — IJPRAI submission

LaTeX source and compiled PDF of the graduated-dissent benchmark paper.

**Title:** *Steelmanning LLM Review: Severity Calibration Through Adversarial Self-Challenge*

**Author:** Andrew Michael Brilliant (Applied Dynamics Research, Sapporo, Japan)

**Venue target:** International Journal of Pattern Recognition and Artificial Intelligence (IJPRAI)

## What's here

| File | What it is |
|---|---|
| `Steelmanning_LLM_Review_IJPRAI.pdf` | Compiled paper |
| `main.tex` | Author manuscript source |
| `sample.bib` | Bibliography |
| `ws-ijprai.cls`, `ws-ijprai.bst`, `ws-ijprai_bib.tex` | IJPRAI's World Scientific template files |
| `ws-ijprai.pdf`, `ws-ijprai_bib.pdf` | Reference rendering of the template |
| `ijpraif1.eps`, `ijpraif1.pdf` | IJPRAI title-page logo |
| `main/gao.{eps,pdf}`, `main/wang.{eps,pdf}` | Figures cited in the body |

## Building

```sh
cd graduated-dissent/paper
pdflatex main.tex
bibtex   main
pdflatex main.tex
pdflatex main.tex
```

Produces `main.pdf`. The pre-built `Steelmanning_LLM_Review_IJPRAI.pdf` is
the canonical version distributed with the repo so readers don't need a
LaTeX toolchain just to see the paper.

## How this paper relates to the toolkit

The benchmark numbers reported in `graduated-dissent/SKILL.md` (GD 7/10
detection at 0/19 FP in-family, 10/10 / 2/19 out-of-family) come from this
paper. The harness code that produced them is at
`$GD_REPO/harness/` — see the skill for the run protocol.
