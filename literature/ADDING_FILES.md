# Adding files to this library

This document tells a future human or bot exactly how to add a new citation to this library. Follow it verbatim — the existing conventions are load-bearing for the citation-checker workflow and for the per-topic `TOC.md` indexing.

## TL;DR

For each new paper:

1. Pick or create a **topic folder** at the top level (e.g. `koide/`, `berry_phase/`, `llm_self_correction/`).
2. Create a **citation slot** inside it: `<topic>/<firstauthor_year[_suffix]>/`.
3. Drop two files inside the slot:
   - `<slot_name>.pdf` — the paper's PDF (filename **must match the folder name**)
   - `one_pager.md` — annotated summary, format below
4. Append a line to the topic folder's `TOC.md` under the right tier.
5. If you're adding many at once, regenerate `MISSING.md` at the repo root (snippet at the bottom).
6. Commit with a message like `Add <topic>/<slot_name> — <one-line description>`.

That's it. The citation-checker (`~/claude/paper-tools/check-citations/`) and the per-paper `refs/` workflows pick this up automatically when you point them here.

---

## Folder layout

```
library/
├── README.md                       ← repo-level intro
├── MISSING.md                      ← auto-generated list of slots without a PDF
├── ADDING_FILES.md                 ← this file
├── RESEARCH_REPORT_*.md            ← verbatim source reports, one per topic family
└── <topic>/                        ← e.g. koide/, berry_phase/, llm_self_correction/
    ├── TOC.md                      ← curated index with tier rankings
    ├── RESEARCH_REPORT_*.md        ← optional source report for this topic
    └── <slot_name>/                ← <firstauthor_year[_suffix]>
        ├── <slot_name>.pdf         ← the paper itself
        └── one_pager.md            ← annotated summary
```

## Slot naming

- Pattern: `firstauthor_year[_suffix]` (snake_case, lowercase).
- Two authors: `firstauthor_secondauthor_year` (e.g. `kane_mele_2005`).
- Three+ authors: `firstauthor_year` only (don't list all).
- Year is the original publication year (preprint year if pre-publication).
- Suffix when needed to disambiguate same author/year:
  - Journal: `_plb`, `_prd`, `_prl`, `_jhep` (lowercase journal abbrev)
  - Book vs paper: `_book`
  - Review article: `_review`
  - Thesis: `_thesis`
  - Conference vs journal version of same work: `_proc` or `_preprint`
- The PDF filename inside the slot **must match the slot folder name** (`koide_1990/koide_1990.pdf`).

## one_pager.md format

Pattern of the existing entries (most rigorous: `berry_phase/atala_2013/one_pager.md`). Required headers, in this order:

```markdown
# <Author> et al. <Year> — <Short descriptive title>

## Reference
<Full bibliographic citation>, including authors, *italic title*, **bold venue volume (year) pages**; arXiv:<id> (if any); DOI: <doi> (if any).

## Source
<Which manuscript / topic family this belongs to>, tier <★ / ✦ / ○> — <one-sentence rationale for the tier ranking>.

## Beyond-abstract summary
<2–6 sentence prose summary going beyond the abstract — what's actually in the paper, what's the technical claim, how it differs from related work>.

## Use in <manuscript-name> manuscript
<Where and how the paper is cited in our work — section reference + role>.

## Sub-citations (one level down)
<Optional. List the most important refs the paper itself cites. Use numbered list with bold author names. Add a build note if metadata was reconstructed without web fetch>.

## Status
<Optional. Peer-reviewed venue and publication-date info, or "preprint only," or "withdrawn".>
```

### Minimum acceptable one_pager (stub form)

For a citation added in haste — fill in the rest later:

```markdown
# <Author> et al. <Year> — <Title>

## Reference
<Full bibliographic citation>

## Source
<Which manuscript / topic>, tier <pending>.

## Beyond-abstract summary
**Stub** — added <date>, summary not yet written.
```

Stubs are tolerated but should be replaced with full one_pagers before the topic gets cited externally.

## Tier rankings used in TOC.md

- **★ (Tier 1):** explicit prior art, directly cited in the manuscript text. Must engage and supersede or contextualize.
- **✦ (Tier 2):** supporting reference, cited for context or methodology.
- **○ (Tier 3):** background reading, not cited or only cited in passing.

## Adding to TOC.md

Append a line under the right tier, format:

```markdown
- [Author Year](slot_name/one_pager.md) — *Title*, **Venue Vol (Year) Pages** [arXiv:id]. <One-sentence relevance note>.
```

## Where to find PDFs when adding

Order of preference (cheapest first):

1. Local copy already on disk: check `~/Desktop/Academic/**/refs/`, `~/Downloads/`, and any submission-package `refs/` folders. The matcher script at `/tmp/fill_library.py` (or a fresh equivalent) automates this.
2. arXiv: if the `one_pager.md` references `arXiv:<id>`, fetch from `https://arxiv.org/pdf/<id>` (3-second rate limit between fetches).
3. INSPIRE-HEP: `https://inspirehep.net/api/literature?q=doi:<doi>&fields=arxiv_eprints,external_system_identifiers` — find arXiv eprint or KEK preprint scan ID.
4. KEK preprint scans: `https://lib-extopc.kek.jp/preprints/PDF/<YY>/<YYMM>/<YYMMNNN>.pdf` (pre-arXiv-era papers; pattern is `89-12-199` → `1989/8912/8912199.pdf`).
5. Publisher site (DOI redirect): usually paywalled / bot-blocked; requires institutional access. Last resort.

If a paper is genuinely unfindable after exhausting 1–5, leave the slot PDF-less and `MISSING.md` will pick it up on regeneration.

## Regenerating MISSING.md

```bash
cd ~/Desktop/Academic/library && python3 -c "
from pathlib import Path
slots = sorted({op.parent for op in Path('.').rglob('one_pager.md')})
missing = [s for s in slots if not (s / f'{s.name}.pdf').exists()]
have    = [s for s in slots if (s / f'{s.name}.pdf').exists()]
out = ['# Missing PDFs', '',
       f'Generated $(date +%F) — {len(have)}/{len(slots)} slots have a PDF; **{len(missing)} still missing**.',
       '',
       'Most missing entries are pre-arXiv-era papers (publisher-paywalled, no preprint) or textbooks. To add: drop the PDF into the slot folder named \`<slot_name>.pdf\` and \`git add\` + commit.',
       '',
       '| Slot | Notes |', '|---|---|']
for s in missing:
    out.append(f'| \`{s}\` | |')
Path('MISSING.md').write_text('\n'.join(out) + '\n')
print(f'wrote MISSING.md with {len(missing)} entries')
"
```

## Where the citation-checker lives

`~/claude/paper-tools/check-citations/check_citations.py` — runs 3 LLMs in parallel per citation, hard-fails publisher bot-blocks, supports `--refs-dir` to use local PDFs in place of URL fetches. Read `~/claude/paper-tools/README.md` for the full loop pattern.

## Commit conventions

- Single new paper: `Add <topic>/<slot_name> — <title or one-line>`
- Bulk add: `Add <topic>/: <N> new citations from <source paper or report>`
- Update / fix: `Fix <topic>/<slot_name>: <what changed>`
- Removal (rare; e.g., truly withdrawn): `Drop <topic>/<slot_name> (truly withdrawn, no source)`

Never force-push to `main`. Never commit publisher PDFs to a public repo without checking copyright — this library is currently **private** for that reason; if it ever becomes public, audit first.
