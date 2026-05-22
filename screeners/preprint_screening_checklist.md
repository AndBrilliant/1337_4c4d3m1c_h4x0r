# Preprint & Manuscript Screening Checklist

Use this checklist before submitting to arXiv, TechRxiv, or journals. Based on documented rejection criteria from multiple sources.

## Technical Requirements

- [ ] PDF compiles without errors
- [ ] No missing figures or references
- [ ] All citations resolve correctly
- [ ] File names contain no special characters (spaces, ?, *)
- [ ] Images are high resolution
- [ ] Follows target venue's formatting guidelines

## Language Red Flags (Search & Fix)

### Intensifiers (remove or soften)
- [ ] "very", "really", "extremely", "totally"
- [ ] "precisely", "exactly", "completely", "perfectly"
- [ ] "clearly", "obviously", "undoubtedly", "certainly", "definitely"

### Superlatives (need proof or remove)
- [ ] "first", "novel", "unique", "unprecedented"
- [ ] "best", "largest", "most important"
- [ ] "breakthrough", "revolutionary", "paradigm shift"

### Overclaiming Language (hedge these)
- [ ] "This proves..." → "This suggests..."
- [ ] "This demonstrates..." → "This is consistent with..."
- [ ] "This shows that..." → "This indicates that..."
- [ ] "We establish..." → "We propose..."
- [ ] "cannot" / "always" / "never" → add qualifiers

### Promotional/Marketing Language
- [ ] Branded framework names (consider "pattern" instead of "Architecture")
- [ ] "We introduce the X Framework" → "We describe what we call X"
- [ ] Self-congratulatory phrasing
- [ ] Excessive self-citation

## Content Red Flags

### Scope & Novelty
- [ ] Clear statement of contribution
- [ ] Connects to existing literature (cites relevant prior work)
- [ ] Not a review/position paper without peer review (arXiv CS policy)
- [ ] Contains original research, not just commentary

### Methodology
- [ ] Methods clearly described
- [ ] Claims supported by evidence or formal argument
- [ ] Limitations explicitly acknowledged
- [ ] Assumptions stated

### Conclusions
- [ ] Conclusions match what evidence supports
- [ ] No overgeneralization from limited data
- [ ] Causal claims only from causal evidence

## Ethical & Disclosure

- [ ] AI tools disclosed if used significantly
- [ ] No plagiarism
- [ ] Author has rights to submit
- [ ] Conflicts of interest declared
- [ ] Data availability stated (if applicable)

## Formatting & Presentation

- [ ] Abstract under 1920 characters (arXiv)
- [ ] Professional, neutral tone throughout
- [ ] No informal language or slang
- [ ] No first person if journal prefers third
- [ ] No emotive language
- [ ] Tables and figures are clear and labeled

## Pre-Submission Final Check

- [ ] Read abstract aloud - does it sound like marketing?
- [ ] Check title - is it descriptive or promotional?
- [ ] Review all bold/italic text - are you emphasizing claims?
- [ ] Grep for red flag words one more time
- [ ] Have someone else skim it for tone

---

## Quick Grep Commands

```bash
# Intensifiers
grep -in "very\|really\|extremely\|totally\|precisely\|exactly\|completely" main.tex

# Superlatives
grep -in "first\|novel\|unique\|unprecedented\|breakthrough\|paradigm" main.tex

# Overclaiming
grep -in "this proves\|this demonstrates\|this shows\|we establish\|clearly\|obviously" main.tex

# Strong modals
grep -in "cannot\|must be\|always\|never\|certainly" main.tex
```

---

---

## Publication Strategy for Unknown Authors

### The Prestige Bias Problem

Empirical research documents significant bias in academic screening:
- **28% higher acceptance rate** for papers with prestigious author names visible (PNAS study)
- Famous authors + top institutions get significantly higher scores in single-blind review
- "Two papers essentially the same thing, but the paper from a famous group was accepted, the other rejected" (Nature)

Unknown authors face implicit tripwires that famous authors bypass:
| Flagged for unknowns | Famous authors get away with |
|---------------------|------------------------------|
| "Novel Framework" naming | DeepMind names everything (AlphaFold, GPT) |
| Promotional tone | Labs announce "breakthroughs" routinely |
| Thin empirical evidence | "We tried this" from Google = accepted |
| Position papers | Established researchers publish opinions |

### The Lineage Strategy

Build legitimacy through self-citation chain:

1. **Paper 1** (this one): Ultra-conservative, over-hedged, no branding, passes screening
2. **Paper 2**: Cites Paper 1, can be slightly bolder ("building on Brilliant 2026...")
3. **Paper 3**: Cites both, now you have a "research program"

Each paper with a DOI builds legitimacy for the next. Screeners can't reject on "vibes" when there's a paper trail.

### Why This Works

- If they reject for self-citation, that's a *documented* reason you can appeal
- "I cited my prior preprinted work, here's the DOI" forces articulation of actual issues
- Same strategy famous labs use (GPT-1 → GPT-2 → GPT-3 → GPT-4)
- You're doing it without institutional cover, so Paper 1 must be cleaner

### Practical Implications

- **Don't** put your bold claims in Paper 1
- **Do** establish terminology, frameworks, and DOIs first
- **Then** cite yourself to build from "established work"
- Changes perception from "crackpot" to "researcher with a program"

---

## Note on Documented vs. Inferred Red Flags

The language red flags (intensifiers, superlatives, overclaiming) are **documented** in sources below.

"Branding" and "promotional framework names" are **inferred** from:
- arXiv Oct 2025 policy rejecting "framework papers that are just prompt engineering"
- General "promotional language" warnings
- Observed screener behavior (not formally documented)

Unknown authors should avoid both documented AND inferred issues.

---

Sources:
- arXiv Moderation: https://info.arxiv.org/help/moderation/index.html
- Elsevier Rejection Reasons: https://www.elsevier.com/connect/8-reasons-i-rejected-your-article
- Words to Avoid: https://proofreading.org/blog/words-to-avoid-in-academic-writing/
- Desk Rejection Guide: https://ecrlife.org/why-desk-rejections-happen/
- Prestige Bias (PNAS): https://www.pnas.org/doi/10.1073/pnas.1707323114
- Prestige Bias (PMC): https://pmc.ncbi.nlm.nih.gov/articles/PMC7811873/
- arXiv Double Standards (Nature): https://www.nature.com/articles/nature.2016.19267
