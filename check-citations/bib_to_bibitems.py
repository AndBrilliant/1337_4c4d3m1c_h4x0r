#!/usr/bin/env python3
"""Convert a BibTeX .bib file into an inlined `\\thebibliography` block
so the existing `\\bibitem`-only check_citations parser can process it.

Reads <input.tex> and <refs.bib>; writes <output.tex> with `\\bibliography{...}`
replaced by `\\begin{thebibliography}{99} ... \\end{thebibliography}`.

This is intentionally a small, tolerant parser tuned for the field set we
actually use (author, title, journal, volume, pages, year, eprint, doi, url,
howpublished, note, collaboration). Anything we don't recognize is dropped.
"""

import argparse
import re
import sys
from pathlib import Path


BRACE_FIELD = re.compile(r"(\w+)\s*=\s*\{", re.IGNORECASE)


def _read_braced(s: str, i: int) -> tuple[str, int]:
    assert s[i] == "{"
    depth = 0
    start = i + 1
    while i < len(s):
        c = s[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start:i], i + 1
        i += 1
    raise ValueError("unbalanced braces")


def parse_bib(text: str) -> list[dict]:
    entries = []
    i = 0
    while i < len(text):
        at = text.find("@", i)
        if at < 0:
            break
        # type{key,
        m = re.match(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text[at:])
        if not m:
            i = at + 1
            continue
        etype = m.group(1).lower()
        key = m.group(2)
        cur = at + m.end()
        # Find the matching close brace of the entry
        # Walk fields until top-level close.
        depth = 1
        fields: dict[str, str] = {}
        while cur < len(text) and depth > 0:
            # skip whitespace and commas
            while cur < len(text) and text[cur] in " \t\r\n,":
                cur += 1
            if cur >= len(text):
                break
            if text[cur] == "}":
                depth -= 1
                cur += 1
                break
            fm = BRACE_FIELD.match(text, cur)
            if not fm:
                # field = "quoted" or field = bareword,YEAR etc — handle quoted/bareword
                fm2 = re.match(r"(\w+)\s*=\s*", text[cur:])
                if not fm2:
                    cur += 1
                    continue
                name = fm2.group(1).lower()
                cur += fm2.end()
                # quoted "..."
                if cur < len(text) and text[cur] == '"':
                    end = text.find('"', cur + 1)
                    if end < 0:
                        break
                    fields[name] = text[cur + 1 : end]
                    cur = end + 1
                else:
                    # bareword until comma or close
                    end = cur
                    while end < len(text) and text[end] not in ",}":
                        end += 1
                    fields[name] = text[cur:end].strip()
                    cur = end
                continue
            name = fm.group(1).lower()
            cur = fm.end() - 1  # at '{'
            val, cur = _read_braced(text, cur)
            fields[name] = val
        entries.append({"type": etype, "key": key, **fields})
        i = cur
    return entries


def _clean(s: str) -> str:
    # collapse internal whitespace, leave LaTeX braces alone
    return re.sub(r"\s+", " ", s).strip()


def to_bibitem(e: dict) -> str:
    key = e["key"]
    author = _clean(e.get("author", ""))
    title = _clean(e.get("title", ""))
    journal = _clean(e.get("journal", ""))
    volume = _clean(e.get("volume", ""))
    pages = _clean(e.get("pages", ""))
    year = _clean(e.get("year", ""))
    eprint = _clean(e.get("eprint", ""))
    doi = _clean(e.get("doi", ""))
    url = _clean(e.get("url", ""))
    howpub = _clean(e.get("howpublished", ""))
    note = _clean(e.get("note", ""))
    publisher = _clean(e.get("publisher", ""))

    parts = []
    if author:
        parts.append(author + ".")
    if title:
        parts.append(title + ".")
    if journal:
        bits = [f"\\textit{{{journal}}}"]
        if year:
            bits.append(f"\\textbf{{{year}}}")
        if volume:
            bits.append(f"\\textit{{{volume}}}")
        if pages:
            bits.append(pages)
        parts.append(", ".join(bits) + ".")
    elif publisher:
        parts.append(f"{publisher}, {year}." if year else f"{publisher}.")
    elif howpub:
        parts.append(f"\\textit{{{howpub}}} \\textbf{{{year}}}." if year else f"\\textit{{{howpub}}}.")
    elif year:
        parts.append(f"\\textbf{{{year}}}.")

    if eprint:
        parts.append(f"arXiv:{eprint}.")
    if doi:
        parts.append(f"\\url{{https://doi.org/{doi}}}.")
    if url and not doi:
        parts.append(f"\\url{{{url}}}.")
    if note:
        parts.append(note + ".")

    body = " ".join(parts)
    return f"\\bibitem{{{key}}} {body}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tex", type=Path)
    ap.add_argument("bib", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    args = ap.parse_args()

    tex = args.tex.read_text()
    bib = args.bib.read_text()
    entries = parse_bib(bib)
    if not entries:
        print("no bib entries parsed", file=sys.stderr)
        return 1

    inline = "\\begin{thebibliography}{99}\n"
    for e in entries:
        inline += to_bibitem(e) + "\n\n"
    inline += "\\end{thebibliography}\n"

    # Replace \bibliography{...} (with optional \bibliographystyle{...} nearby).
    out = re.sub(r"\\bibliographystyle\{[^}]*\}\s*", "", tex)
    out, n = re.subn(r"\\bibliography\{[^}]*\}", lambda _m: inline, out)
    if n == 0:
        print("no \\bibliography{} command found in tex", file=sys.stderr)
        return 1

    args.output.write_text(out)
    print(f"wrote {args.output} with {len(entries)} bibitems", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
