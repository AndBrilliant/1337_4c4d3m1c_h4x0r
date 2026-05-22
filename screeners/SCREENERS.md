# Manuscript Screener Suite

Two prompts, two stages, one workflow. Use both before submitting any physics manuscript to a peer-reviewed journal or arXiv-class repository. Both have track records of catching real bugs the author and working-Claude missed.

| Stage | File | What it catches | When to run |
|---|---|---|---|
| **1. Preprint screener** | `PREPRINT_SCREENER_PROMPT.md` | Crackpot tone, AI slop, branded "frameworks", overclaiming, missing disclosures, anything that reads as desk-reject by vibe alone | After draft is structurally complete, before any technical pass |
| **2. Preflight tech check** | `PREFLIGHT_REVIEW_PROMPT.md` | Internal numerical inconsistencies, wrong PDG/FLAG values, citation venues, dimensional analysis, scheme contradictions, unit errors, attribution mistakes, missing standard checks | After Stage 1 passes, and re-run after every fix round |

The two are not interchangeable. Stage 1 catches things a moderator would reject in 60 seconds without reading the math. Stage 2 catches things a referee would write back about three weeks in. **Both happen before peer review even sees the paper.**

---

## ⚠️ THE CONVERGENCE RULE — BINDING

**A manuscript is converged when, and only when, a fresh model running the full preflight prompt finds nothing in categories A through F.**

NOT converged:
- Working-Claude says "I checked and it looks ready"
- An automated dissent system stops surfacing issues
- All internal verification scripts pass
- The same model that found bugs last round finds nothing this round (it is biased now)

CONVERGED:
- A **fresh model** — different session at minimum, different vendor preferred
- Running the **full preflight prompt below verbatim**
- Returns **zero findings** in categories A, B, C, D, E, and F

Until that gate clears: do not submit. Do not call the paper "ready." Working-Claude's confidence is not the metric, has been wrong every time it has been offered, and the binding rule above exists because of that specific failure pattern.

---

## How we actually run this

This is the operational protocol. It is dumber than it sounds and works better than it should.

1. **Open a fresh ChatGPT session** (or Gemini, or Grok, or Claude in a separate browser tab — vendor variety matters across rounds, see below).
2. **Turn on extended thinking mode** ("think longer", "deep think", "reasoning", whatever the vendor calls it). This is critical. A short-thinking pass does not walk every category and just lists 2-3 things. An extended-thinking pass actually goes A → B → C → D → E → F and explicitly says "found nothing here" for clean categories.
3. **Paste the full preflight prompt verbatim** from `PREFLIGHT_REVIEW_PROMPT.md`. Do not edit it down. Do not paraphrase it. The bans on the post-hoc lecture and the publish-or-not verdict are doing structural work; weakening them resurfaces the easy escape hatches.
4. **Attach the latest patched PDF.** Always re-attach. Stale-snapshot reads are a real failure mode (we have evidence — round 3 wasted ~6 findings on a slightly older PDF the vendor's session had cached).
5. **Wait.** Extended thinking takes 5–25 minutes. Do not interrupt. The longer it thinks, the more thoroughly it walks the categories.
6. **Paste every finding back to working-Claude.** Every one, including the ones that look stupid. Working-Claude classifies each as: real bug / soft polish / vibe (out of scope) / stale (already fixed in a previous round).
7. **Real bugs get fixed and the manuscript recompiled in the same turn.** Soft polish goes in the same batch unless purely aesthetic. Vibe complaints get acknowledged once and dropped. Stale findings get noted and ignored.
8. **Run the preflight against a DIFFERENT fresh model for the next round.** Round N's bug-finder cannot also be Round N+1's verifier. Different vendors find different things. ChatGPT, Gemini, Grok, and Claude all have different blind spots and different obsessions; rotate them.
9. **Loop.** Until a fresh model returns zero findings in A–F.

The thing Andy keeps remarking on, accurately: **we keep expecting the model to go crazy and start hallucinating issues, and it has not done that yet.** Three rounds in, every round has surfaced new real bugs that earlier rounds missed. The "loop until it's just acting completely crazy really" stopping condition has not actually triggered. It just keeps finding good stuff. When it finally does start hallucinating, that is the signal we have actually converged — the model is reaching for things to flag because there is nothing real left.

---

## Track record

The Koide–Soddy paper (Brilliant 2026, MDPI Symmetry submission) is the first manuscript run through this system end-to-end. It is also the source of the convergence rule, which exists because three separate "looks ready" calls were wrong before the rule was put in place.

| # | Date | Model | Stage | Real bugs | Soft polish | Stale (already fixed) | Notes |
|---|---|---|---|---|---|---|---|
| 1 | 2026-04-08 | ChatGPT (think mode, ~20 min, casual prompt) | Preflight, partial | 1 (MS-bar pole-mass scheme contradiction) | 3 | 0 | Used a casual prompt, not the structured one. Caught only 1 of the bugs round 2 found, demonstrating that the structured prompt matters. |
| 2 | 2026-04-08 | ChatGPT (think mode, ~9 min, full preflight prompt) | Preflight, full | **9** (Q value off in 6th decimal from stale tau mass; two scale-prescription table values wrong; figure caption "four orders of magnitude" arithmetically wrong; FLAG citation venue wrong — EPJC 84/950 instead of PRD 113/014508; error budget total 0.814 vs 0.816 self-contradiction; abstract said "only μ★" while §5.3 said two hits; §5.3 miscount of "eight alternative lepton-derived"; §5.1 referenced wrong equation; §5.6 said "lattice 1σ" for c, b which are PDG) | 5 | 0 | 16/16 fixes applied. Recompiled 11 → 11 pages, 324 KB. |
| 3 | 2026-04-08 | Fresh model, full preflight prompt, ~9 min think | Preflight, full | **5 genuinely new** (Kocik attribution misattributed standard-Descartes reading to Kocik when his actual paper uses generalized intersecting circles — verified directly against arXiv:1201.2067; F^n loose null dimensionally invalid for n≠2 because F has units MeV^(1/2); 99.98% wrong attribution in §5.1 — actually 99.4% lattice + 0.39% α_s + 0.23% truncation + 0.015% lepton; n_f convention not stated in §4; Figure 1 caption falsely claimed k₄⁻ encloses for the lepton case where k₄⁻ is actually positive) | 6 | 6 stale (model was reading a slightly older snapshot) | 11/11 fixes applied. Recompiled 11 → 12 pages, 346 KB. |
| 4 | _next_ | _**different vendor required**, not the same one as round 3_ | Preflight, full | _TBD — must find zero in A–F to call converged_ | _TBD_ | _TBD_ | NOT YET RUN |

### Lessons captured the hard way

**From round 2:** Running the structured preflight prompt found 9 real bugs in a single 9-minute pass after rounds 1's casual prompt found only 1. The structure matters: banning the post-hoc lecture and the publish-verdict forces the model to actually walk the technical categories. Working-Claude had called convergence three times before this round and was wrong every time. The binding convergence rule was added immediately after round 2.

**From round 3:** A fresh-model rerun on the round-2-fixed manuscript found 5 *more* genuinely new bugs that round 2 missed entirely — including a citation/attribution error that required directly reading Kocik's actual paper to verify, a dimensional consistency issue that nobody had noticed across multiple earlier reviews, and a wrong percentage attribution. Different fresh models have different obsessions and find different things. **Each new round must use a different fresh model than the previous round** — ideally a different vendor entirely. Also: when uploading to a fresh model, always re-attach the latest patched PDF; round 3 caught real bugs but its model wasted effort on 6 already-fixed items because the attached PDF was a slightly older snapshot from a previous chat.

**Cost of this discipline:** ~3–5 model rounds, ~30 minutes each, ~2–3 hours total of working-Claude integration time.
**Cost of skipping it:** desk rejection, or worse, peer-review embarrassment for arithmetic errors a model could have found in 9 minutes. Or worse than that, a published paper with the wrong citation venue.

---

## Known failure modes

These are things that have actually gone wrong in this workflow, not things that might theoretically go wrong.

1. **Stale-PDF cache.** When you start a fresh session in a vendor's web UI, the upload box may or may not be reading the actual file you just dragged in. Sometimes it caches a previous version. **Always re-attach explicitly**, and if you can spot-check with a question like "what does the abstract say about Q?" before running the full prompt, do it.

2. **Same-vendor session bias.** Running round N+1 in a new ChatGPT session after round N was also ChatGPT does not give you full vendor independence. The training and prompting style overlap means the model will tend to find the same things and miss the same things. Switch vendors between rounds when possible.

3. **Working-Claude false convergence.** Working-Claude (the assistant doing the manuscript editing) will be wrong about convergence. This has happened three times in the Koide–Soddy workflow. Working-Claude's confidence is not the metric. Only a fresh-model preflight pass with zero findings is the metric. This is the entire reason the binding rule exists.

4. **The post-hoc escape hatch.** If you write your own prompt, you will leave room for the model to say "this is post-hoc numerology" and stop there without engaging with the technical content. The structured preflight prompt explicitly bans this escape hatch. Do not edit it out.

5. **The publish-verdict escape hatch.** Same idea. If you ask the model "should this be published?", the model will spend its tokens on a verdict instead of finding bugs. The structured prompt bans this. Do not edit it out either.

6. **Soft-finding fatigue.** After two rounds, it is tempting to dismiss soft polish items as "we've heard this before, ship it." Don't. Apply them. They are cheap and they compound.

7. **Round 4+ exhaustion.** This is the failure mode we are *expecting* but haven't hit yet. At some point a fresh model will start hallucinating problems just to fill the response, because the structured prompt makes it walk the categories whether or not anything is there. When that happens — when round N's findings are visibly worse than round N-1's, with strained reasoning and no real-bug hits — that is the convergence signal. Until then, keep looping.

---

## Prompt 1 — Preprint screener (Stage 1, vibe check)

Source file: `PREPRINT_SCREENER_PROMPT.md` (also lives in this directory).

This is a moderator simulation. It catches the things a desk editor flags in 60 seconds: tone, branded frameworks, AI slop, missing disclosures, overclaiming. Run this **before** the technical preflight. If the manuscript fails this stage, fix the framing before bothering with technical bug hunting.

Use it in a fresh chat with no memory of the manuscript:

```
You are a preprint screener for a major repository (arXiv/TechRxiv). You have 3-4 minutes per submission. You are NOT peer reviewing — you are screening for basic quality, appropriateness, and red flags.

Your job is to FLAG or PASS manuscripts. You are overworked, see hundreds of submissions, and have zero tolerance for:
- Promotional/marketing language
- Branded "frameworks" that sound like product launches
- Overclaiming without evidence
- Position papers disguised as research
- AI-generated slop
- Poor formatting or LaTeX errors
- Missing citations to relevant prior work

Your screening process:

1. READ THE TITLE — does it sound like a research paper or a TED talk? Red flags: "Revolutionary", "Paradigm", "Novel Framework", excessive branding.

2. READ THE ABSTRACT (30 seconds) — is there a clear, modest claim? Does it cite empirical grounding or just make assertions? Red flags: no hedging, promotional tone, buzzwords.

3. SKIM THE STRUCTURE (30 seconds) — does it have Intro, Methods/Theory, Results/Analysis, Discussion, Conclusion? Are there proper citations throughout? Red flags: manifesto structure, no related work, thin bibliography.

4. SPOT CHECK FOR RED FLAGS (2 minutes) — search for intensifiers ("very", "extremely", "precisely", "clearly", "obviously"), superlatives ("first", "novel", "unique", "breakthrough", "paradigm"), overclaiming ("This proves", "This demonstrates", "We establish"). Does the conclusion match what the evidence supports?

5. CHECK DISCLOSURES — AI use disclosed? Conflicts of interest? Data availability?

Output format:

DECISION: [PASS / FLAG FOR REVIEW / REJECT]

Title Assessment: [1-2 sentences]
Abstract Assessment: [2-3 sentences on tone, claims, grounding]
Red Flags Found: [list specific phrases/issues with line numbers if possible]
Missing Elements: [what's missing that should be there?]
Recommendation: [if FLAG/REJECT, what specific changes would allow acceptance?]

Now screen the following manuscript:
[paste manuscript]
```

For a tougher pass, the standalone `PREPRINT_SCREENER_PROMPT.md` file in this directory has variants for adversarial mode, physics-specific moderators, and CS/ML-specific moderators.

---

## Prompt 2 — Preflight technical check (Stage 2, bug hunt)

Source file: `PREFLIGHT_REVIEW_PROMPT.md` (also lives in this directory).

This is the structured technical-bug hunter. Use it after Stage 1 has passed. Run it in extended-thinking mode against a fresh model. Loop with a different vendor each round until clean.

**Adapt section 2 to your manuscript.** The version below is Koide-Soddy-specific (it bans the post-hoc lecture by citing the geometric uniqueness of F). For a different paper, replace section 2 with the equivalent rebuttal of whatever cheap dismissal your paper invites — but keep the structural ban on out-of-scope critique and the structural ban on the publish-verdict.

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
```
```
WHAT I ACTUALLY NEED YOU TO CHECK — go through the paper systematically 
and flag anything in any of these categories:

A. INTERNAL INCONSISTENCIES
   - Numbers that contradict each other across sections
   - Scheme/notation contradictions (pole mass vs MS-bar, etc.)
   - Cross-references that point at the wrong section, equation, or label
   - Definitions that change between sections without acknowledgment

B. FACTUAL / TECHNICAL ERRORS
   - Wrong physical constants, wrong PDG/FLAG values, wrong threshold conventions
   - QCD running mistakes (loops, nf, threshold matching)
   - Errors in propagating uncertainties
   - Mathematical errors in derivations or proofs
   - Misstated conventions (curvature signs, inner vs outer Soddy, etc.)

C. CITATION PROBLEMS
   - Cited papers that don't exist or have wrong years/authors/journals
   - Claims attributed to a source that doesn't make that claim
   - Missing citations where one is required by convention
   - Bibliography entries malformed for the claimed venue

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
   - Standard checks (consistency with known limits, sanity tests) a referee would expect
   - Robustness checks the paper claims to do but doesn't actually report

For each finding, give me:
- Section/line/equation reference
- Exact quote of the problem text
- Why a referee would flag it
- A specific suggested fix (give me the words, not "consider rewording")

If you find nothing in a category, say so explicitly. Don't pad.

Do not give me a verdict on whether the paper should be published. Do not 
critique the post-hoc framing. Do not lecture me about numerology. The 
author has already made his peace with all of that. Find the bugs.
```

---

## Quick reference

- **First time using this on a new paper?** Run Stage 1 (preprint screener) on the abstract + intro + conclusion. If it FLAGS, fix the framing before doing anything else.
- **Stage 1 passed?** Move to Stage 2. Run the preflight prompt against ChatGPT in extended thinking mode with the full PDF attached. Wait. Apply every finding.
- **Round 1 done?** Run round 2 against a different vendor (Gemini, Grok, Claude in another tab). Apply findings.
- **Still finding real bugs?** Keep looping. The convergence rule is binding.
- **Round N returned only soft polish, no real bugs?** Run round N+1 anyway, against yet another fresh model. Convergence is **zero findings in A–F**, not "only minor stuff left."
- **Round M is visibly hallucinating issues to fill space?** Now you are converged. Submit.

## Files in this directory

- `SCREENERS.md` — this file, the master combined doc
- `PREPRINT_SCREENER_PROMPT.md` — Stage 1 standalone, with adversarial and domain-specific variants
- `PREFLIGHT_REVIEW_PROMPT.md` — Stage 2 standalone, with full track record across rounds 1–3 of the Koide–Soddy paper

The standalone files are kept current alongside this combined doc. If you update the workflow, update all three.
