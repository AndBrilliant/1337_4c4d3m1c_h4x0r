# Expected behavior on `tiny_paper.tex`

This is what a clean citation-checker run on `examples/tiny_paper.tex` should
produce.  Use it to confirm your setup is working end-to-end.

## How to run

```sh
# from the repo root, after running setup.sh + setup_keys.py
source .venv/bin/activate
python3 check-citations/check_citations.py examples/tiny_paper.tex --cap-usd 0.50
```

Expected total cost: **about $0.10–$0.30** depending on which models are
configured.  The `--cap-usd 0.50` flag aborts further LLM calls if the running
cost would exceed 50 cents — generous for three citations, change for larger
papers.

If you only want to test the deterministic plumbing without spending API
credits, restrict to one bibitem (skips most LLM calls):

```sh
python3 check-citations/check_citations.py examples/tiny_paper.tex \
    --only koide1982 --cap-usd 0.10
```

## What the report should contain

### 1. Orphan citations (cited in body but no `\bibitem` exists)

The body cites `\cite{nonexistent_key}` but no `\bibitem{nonexistent_key}`
appears in the bibliography — should be flagged here.

### 2. Orphan bibitems (`\bibitem` entries that are never cited)

`orphan_pass` (the Maldacena 1998 entry) is included in the bibliography but
never referenced in the body — should be flagged here.

### 3. Per-citation verdicts

| key | expected verdict | reason |
|---|---|---|
| `koide1982`  | PASS or AUTHOR_MISMATCH_SAME_PAPER | The DOI `10.1007/BF02817096` correctly resolves to Koide's 1982 Lett. Nuovo Cim. paper.  Title matches. |
| `orphan_pass` | (skipped) | Counted only as an orphan bibitem above; no per-citation check. |
| `wrong_doi`  | FAIL | Bibitem text claims Hawking's 1975 "Particle Creation by Black Holes" but `10.1038/nature12373` resolves to a 2013 Nature paper on a completely different topic.  Deterministic title mismatch triggers FAIL without an LLM call. |

If the report shows that **exact pattern** — one orphan cite, one orphan
bibitem, one FAIL, and a clean verdict on `koide1982` — your setup is correct.

## Common issues

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: api_client` | You skipped `setup.sh`.  Run it from the repo root. |
| `[check-citations] no such file: examples/tiny_paper.tex` | You're not in the repo root.  `cd` to wherever you cloned this repo. |
| `Anthropic API key not found` | Run `python3 setup_keys.py` and configure at least `anthropic`. |
| Every citation FAILs with "blocked" | Cloudflare on the DOI host; the Playwright browser fallback isn't installed.  Run `python3 -m playwright install chromium`. |
| Cost cap tripped mid-run | Default cap is $5.00 per paper.  For bigger bibliographies, raise via `--cap-usd 10.00`. |
