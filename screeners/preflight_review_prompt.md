# Ultimate Preflight Tech Check Prompt

Use this when running a paper past a fresh model (ChatGPT, Gemini, Grok, Claude-on-the-side) for desk-rejection-grade error catching. Bars the post-hoc lecture, redirects to actual technical bugs.

Attach the PDF or paste the .tex source after the prompt.

---

## ⚠️ CONVERGENCE RULE — BINDING

**A paper is converged when, and only when, a fresh model running the full preflight prompt finds nothing in categories A through F.**

NOT converged:
- Working-Claude says "I checked and it looks ready"
- The dissent system stops finding things
- All internal automated checks pass
- The same model that found bugs last round finds nothing this round (it's biased now)

CONVERGED:
- A **fresh model** (different session at minimum, different vendor preferred)
- Running the **full prompt below verbatim**
- Returns **zero findings** in categories A, B, C, D, E, and F

Until that gate clears, do not submit. Until that gate clears, do not call the paper "ready." Working-Claude's confidence is not the metric.

---

```
I'm submitting this physics paper to a peer-reviewed journal. I need a 
PREFLIGHT TECHNICAL REVIEW to catch errors that would cause desk 
rejection or referee-grade objections. I do NOT need a critique of the 
paper's epistemic framing.

CONTEXT YOU MUST ACCEPT BEFORE READING:

1. The paper is an empirical observation, not a derivation. The author 
   knows this. The abstract, §6 (Caveats), and §4.3 (order of operations) 
   already disclose that the numerical match was noticed after the 
   geometric computation, that no mechanism is claimed, that the Monte 
   Carlo is descriptive not inferential, and that the prior family is 
   chosen, not unique. Do not flag any of this as a finding. It is not.

2. "Post-hoc" complaints are out of scope. Every comparison between a 
   derived quantity and a measured quantity happens after the measurement 
   exists; that is the only order in which such comparisons can be made. 
   "Post-hoc" only has teeth when the test was selected from a basis of 
   candidates to match the data. The quantity F here is geometrically 
   determined by Kocik's Descartes-circle framework — there are exactly 
   two Soddy curvatures (k₄⁺ and k₄⁻), and the paper takes the outer one 
   and reports it. There is no basis of candidates being searched. If you 
   feel the urge to write "this is post-hoc numerology," resist it — the 
   author has heard it, the manuscript addresses it, and repeating it is 
   not useful technical review.

3. The venue is MDPI Symmetry (or a similar specialist journal). The 
   author is not asking whether the result is true or important. The 
   author is asking whether the manuscript is internally consistent, 
   factually correct, properly cited, and free of the kinds of errors a 
   real referee would write back about.

WHAT I ACTUALLY NEED YOU TO CHECK — go through the paper systematically 
and flag anything in any of these categories:

A. INTERNAL INCONSISTENCIES
   - Numbers that contradict each other across sections (e.g., 
     F = 9.7528 in eq X but F² = 95.1134 elsewhere, where 9.7528² ≠ 95.1134)
   - Scheme/notation contradictions (e.g., calling something "pole mass" 
     in one place and "MS-bar" in another)
   - Cross-references that point at the wrong section, equation, or label
   - Definitions that change between sections without acknowledgment

B. FACTUAL / TECHNICAL ERRORS
   - Wrong physical constants, wrong PDG/FLAG values, wrong threshold 
     conventions
   - QCD running mistakes (wrong number of loops, wrong nf at a given 
     scale, wrong threshold matching)
   - Errors in propagating uncertainties
   - Mathematical errors in derivations or proofs
   - Misstated conventions (e.g., curvature sign conventions, which 
     Soddy circle is "inner" vs "outer")

C. CITATION PROBLEMS
   - Cited papers that don't exist or have wrong years/authors/journals
   - Claims attributed to a source that doesn't make that claim
   - Missing citations where one is required by convention
   - Bibliography entries that are malformed for the claimed venue

D. CLAIMS THAT EXCEED WHAT THE DATA SUPPORTS
   - Statements stronger than the §6 Caveats permit
   - Numerical comparisons that gloss over a real systematic
   - Implicit predictions the author hasn't explicitly disclaimed

E. DESK-REJECTION VECTORS (style/format)
   - Tone that reads as crackpot regardless of content
   - Length inappropriate for the venue
   - Missing required declarations (conflicts, funding, data availability)
   - Bad figure captions or unreadable figures
   - Anything that would make a desk editor stop reading in 60 seconds

F. THINGS A REFEREE WOULD ASK FOR THAT AREN'T THERE
   - Standard checks (e.g., consistency with known limits, sanity tests) 
     a referee would expect to see
   - Robustness checks the paper claims to do but doesn't actually report

For each finding, give me:
- Section/line/equation reference
- Exact quote of the problem text
- Why a referee would flag it
- A specific suggested fix (not "consider rewording" — give me the words)

If you find nothing in a category, say so explicitly. Don't pad.

Do not give me a verdict on whether the paper should be published. Do not 
critique the post-hoc framing. Do not lecture me about numerology. The 
author has already made his peace with all of that. Find the bugs.
```

---

## Track record

| # | Date | Model | Version reviewed | Real bugs | Soft polish | Vibe (out of scope) | Status |
|---|---|---|---|---|---|---|---|
| 1 | 2026-04-08 | ChatGPT (think mode, 20 min, casual prompt) | v4.2 (post-MS-bar, pre-fix) | 1 (MS-bar pole mass scheme contradiction) | 3 (Fig 2 wording, m_μ+m_τ explanation, abstract verb) | 1 (post-hoc framing) | Round 1 — partial coverage |
| 2 | 2026-04-08 | ChatGPT (think mode, ~9 min, full preflight prompt) | v4.2 (post-MS-bar fix) | **9 confirmed** (Q value, table values, figure caption "4 orders", FLAG citation venue, error budget 0.814 vs 0.816, abstract self-contradiction, §5.3 miscount, §5.1 wrong Eq ref, §5.6 lattice→PDG) | 5 (R-Z desc, repo cite, soften verbs, §3 explicit convention, Fig 2 explicit) | 0 | 16/16 fixes applied. Recompiled 11 pages 324 KB. |
| 3 | 2026-04-08 | Fresh model (full preflight prompt, ~9 min think) | v4.2 (round-2-applied PDF, but model read STALE snapshot for ~6 items) | **5 genuinely new** (Kocik attribution misattributed standard-Descartes reading to Kocik when his actual paper uses generalized intersecting circles; F^n loose null dimensionally invalid for n≠2; 99.98% wrong attribution in §5.1; n_f convention not stated in §4; Figure 1 caption falsely claimed k₄⁻ encloses for lepton case) | 6 (abstract F definition tightening, §6 'supportive of both lines' soften, §7 'if more than coincidence' soften, §5 opening convention statement, §5.4 rejection counts breakdown, Prop 1 'after Kocik' attribution drop) | 6 stale (already-fixed bugs from round 2 — model was reading a pre-round-2 PDF) | 11/11 fixes applied. Recompiled 12 pages 346 KB. |
| 4 | 2026-04-09 | Fresh model, full preflight prompt (different vendor from round 3) | v4.2 post-round-3 PDF (correctly uploaded by author) | **5 genuinely new** (F vs k_4^- notation drift in §3 opening; sample-size language mismatch §5.4 vs computational note; charm threshold contradiction in §4 prose vs §5.1 table; Kocik over-attribution still in "within Kocik's framework" / "We extend Kocik's construction" phrases; Coxeter [10] missing page range) | 7 (analytic m_2 branch formula, per-prior denominators, Fig 2 "context only" framing, §6 supportive softening, §7 if-coincidence softening, Author Contributions MDPI req, Keywords MDPI req) | 0 | 12/12 findings addressed. Saved as v4_3.tex, 428 lines. |
| 5 | _next_ | _**another different vendor**, not Gemini/Grok/Claude/ChatGPT whichever ran round 4_ | v4.3 | _TBD_ | _TBD_ | _TBD_ | NOT YET RUN |

**Key lesson from round 2:** Running the same preflight prompt that rounds 1 missed found *9 real bugs in one shot*, including a wrong arithmetic computation (Q value), three wrong table values, a wrong figure caption, and a wrong journal citation. Confidence-from-the-inside is unreliable. The convergence rule above exists because of this specific failure.

**Key lesson from round 3:** The fresh-model rerun found *5 genuinely new bugs* that round 2 missed entirely — including a citation/attribution error (Kocik's actual construction is generalized intersecting circles, not standard mutually-tangent Descartes — verified directly against arXiv:1201.2067), a dimensional consistency issue (F^n for n≠2 is not unit-invariant and cannot be used in look-elsewhere accounting), and a wrong percentage attribution (99.98% claimed for lattice m_s alone, actually 99.4%; the rest is α_s and truncation). Different fresh models find different bugs. **Each new round must use a different fresh model than the previous round.** Also, when uploading to a fresh model, always re-attach the latest patched PDF — round 3 caught real bugs but its model also wasted effort on 6 already-fixed items because the attached PDF was a slightly older snapshot.

## Usage protocol

1. Run the prompt verbatim on a **fresh model session** (different vendor preferred over different session of same vendor).
2. Paste each finding back to working-Claude.
3. Working-Claude classifies: real bug, soft polish, vibe (out of scope).
4. Real bugs get fixed immediately and the manuscript recompiled.
5. Soft polish items get fixed in the same batch unless they're truly aesthetic-only.
6. Vibe complaints get acknowledged once and then dropped.
7. After all fixes are in, **run the preflight prompt against ANOTHER fresh model.** Round N's bug-fixer cannot also be Round N+1's verifier.
8. Repeat until a fresh model returns zero findings in categories A–F.
9. Only then is the paper "converged" and ready to submit.

**Cost of this discipline:** ~3 model rounds, ~30 minutes each = 1.5 hours total.
**Cost of skipping it:** real desk rejection or peer-review embarrassment for errors a model could have found in 9 minutes.
