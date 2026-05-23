# Literature Review — F-identity Manuscript

> **Project:** `f_identity/` — *The F-identity: a cross-domain geometric bridge from charged leptons to light-quark masses* (Brilliant 2026).
> **Compiled:** 2026-05-19
> **Source material:** Claude web research mode report on *Cross-Domain Citations Linking Condensed-Matter Mathematics to Fermion Mass Relations*, archived in this folder as [`RESEARCH_REPORT_cross_domain.md`](RESEARCH_REPORT_cross_domain.md).

This `literature/` folder collects every manuscript cited in the source report. Each manuscript has its own subfolder containing a `one_pager.md` summary. Unlike the prior `bosons_r_us/literature/` and `quarkscrew/literature/` reviews — which split into two research lineages (categorical/Z₃ vs. mainstream Koide) — the current paper *crosses domains*, so the folder is organized into ten subject categories matching §1–§10 of the source report.

## What's new here: sub-citations one level deep

Every `one_pager.md` in this folder includes a **`## Sub-citations (one level down)`** section. For each paper P that the F-identity manuscript cites, that section lists P's *own* references with two pieces of information per entry:

1. **Topic** — a one-sentence summary of what the sub-cited paper is about.
2. **Role in P** — what P uses that reference for in its argument.

This second-level loop is the distinguishing feature of this literature folder vs. the prior two. The goal is to make the citation chain inspectable: when a reviewer asks "what does Kocik (2012) lean on?", the answer is in `koide_geometric/kocik_2012/one_pager.md` without leaving the repo.

Sub-citation lists were assembled from each paper's published bibliography (arXiv/journal). Where a reference is mathematically central to P's argument it is marked **★**; where it is supporting or background it is left unmarked.

## Folder layout

```
literature/
├── README.md                              ← this file
├── RESEARCH_REPORT_cross_domain.md        ← source report, verbatim (spans all 10 categories)
├── descartes_apollonian/                  ← §1 — Apollonian gaskets / Soddy in CM
│   ├── TOC.md
│   └── <paper>/one_pager.md
├── berry_phase/                           ← §2 — Berry phase fixing mass/spectrum parameters
├── c3_symmetry/                           ← §3 — C₃ symmetry in CM (graphene, moiré, etc.)
├── z2_particle_hole/                      ← §4 — Z₂ symmetry as particle–hole / matter–antimatter
├── geometric_means/                       ← §5 — Geometric-mean exact relations in EMT
├── curvature_root_m/                      ← §6 — Curvature κ = √m as a physical variable
├── koide_geometric/                       ← §7 — Koide formula in CM / geometric language
├── rg_invariant_ratios/                   ← §8 — Scale-free / RG-invariant mass ratios
├── cross_domain_reviews/                  ← §9 — HEP↔CM review articles
└── eft_bridge/                            ← §10 — EFT methods bridging CM and HEP
```

The split is by **subject category** (the report's §-numbering), not by research lineage. Several papers appear in more than one category in the source report; the canonical copy lives in the first category where it is named ★, and other categories link to it.

---

## Source Report — Cross-domain citations (Claude web research mode)

- **File:** [`RESEARCH_REPORT_cross_domain.md`](RESEARCH_REPORT_cross_domain.md)
- **Source:** Claude web research mode, 2026-05-18
- **Length:** ~3,400 words plus citation lists across ten categories

**Beyond-abstract summary.** A targeted bibliography keyed to the ten cross-domain hooks of the F-identity manuscript: (1) Descartes/Apollonian → CM, (2) Berry phases fixing observables, (3) C₃ symmetry in CM, (4) Z₂ as particle–hole, (5) geometric-mean exact relations in effective-medium theory, (6) curvature κ=√m as a CM-native variable, (7) prior geometric/symmetry readings of Koide, (8) RG-invariant mass ratios, (9) HEP↔CM review articles, (10) EFTs bridging the two domains. The report identifies eleven Tier-1 citations forming the spine of the paper (Koide 1983, Foot 1994, Sumino 2009, Kocik 2012, Shulga 2026, Satija 2016, Leutwyler 1996, Xiao–Chang–Niu 2010, Kane–Mele 2005, Dykhne 1971, Volovik 2003) and gives a staged decision rule for PRL- vs. PRD- vs. review-length papers. The Satija 2016 mapping from the integer Apollonian gasket to the Hofstadter butterfly (with explicit D₃ symmetry and integer bends) is flagged as the single most important CM-side anchor; Kocik 2012 as the most direct geometric prior art for κ=√m; Shulga 2026 as the immediate competitor that independently derives δ=2/9 from a compact-cycle Green-function model.

**Major sections.**
1. **TL;DR** — three sentences naming the three indispensable citations (Satija, Kocik+Foot+Sumino+Shulga, Leutwyler).
2. **Key Findings** — organization principle and tier scheme (★/✦/†).
3. **Details (§1–§10)** — see folder layout above; each section gives full bibliographic data and a relevance note per paper.
4. **Recommendations** — eleven Tier-1 must-cites in paper order; staged decision rule for paper length; benchmarks that would change the citation set under specific referee challenges.
5. **Caveats** — preprint vs. journal status of Kocik and Shulga; Dykhne page-range error in secondary sources; Matheron in French; precise meaning of Leutwyler's scheme-independence claim; Sumino mechanism vs. geometric reading; Volovik 210 GeV provenance; Berry-phase non-integer-rational novelty (Shulga as sole precedent).

---

## How to use this index

1. Browse the per-category `TOC.md` files for one-line hooks per manuscript.
2. Open the relevant `<manuscript>/one_pager.md` for a structured summary, plus the **sub-citations** section showing what that manuscript itself cites and why.
3. The `RESEARCH_REPORT_cross_domain.md` is the primary source — individual one-pagers were derived from it and may be slightly compressed.
4. When citing in the final paper, prefer the original journal/arXiv reference quoted in each one-pager.

## Build status

- **2026-05-19** — All 45 one_pagers complete across all 10 categories. Breakdown:
  - **Verified bibliographies (from PDFs):** Kocik 2012, Foot 1994, Sumino 2009, Shulga 2026, Kane–Mele 2005, Leutwyler 1996, Satija 2016 EPJ ST, Xiao–Chang–Niu 2010, Ortix et al. 2012, Castro Neto et al. 2009, Schnyder et al. 2008, Altland–Zirnbauer 1997, Kitaev 2009, Fu–Kane 2007, Li–Ma 2006, Kartavtsev 2011, Rivero–Gsponer 2005, Volovik 2014 (partial). 18 papers.
  - **Training-knowledge reconstruction (with build-note caveats):** All pre-arXiv papers (TKNN 1982, Zak 1989, Koide 1983 PLB, Dykhne 1971, Matheron 1967, Hashin-Shtrikman 1962/63, Wilson-Kogut 1974, Nambu-Jona-Lasinio 1961, Helfrich 1973), all books (Satija book, Milton 2002, Ashcroft-Mermin 1976, Volovik 2003 book), and a few arXiv papers whose PDFs were cached but not fully extracted (Jauregui 2015, Atala 2013, Tse-MacDonald 2010, Andrade 2005, Mackenzie 2010, Yang-Liu 2017, Gasser-Leutwyler 1982, Pelissetto-Vicari 2002, Jüttner et al. 2017, Gonze 2016, Hasan-Kane 2010, Qi-Zhang 2011, Volovik-Zubkov 2014, Tsuji et al. 2023, Shankar 1994, Polchinski 1992, Mackenzie 2010). 27 papers.
  - **Placeholder pending specific paper selection:** TDBG / moiré C₃ Berry-curvature-dipole entry in §3.
