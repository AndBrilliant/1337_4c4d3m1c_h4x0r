#!/usr/bin/env python3
"""papers_mcp — MCP server bundling:
  * Literature library CRUD/search over ~/claude/paper-tools/literature
  * check-citations launcher
  * graduated dissent launcher
  * background job management for the long-running tools

Driven over stdio by Claude Desktop.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

import sys
import urllib.parse
import xml.etree.ElementTree as ET

import requests
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config

LIBRARY_ROOT = Path(os.environ.get("LITLIB_ROOT", "/Users/Drew/claude/paper-tools/literature")).expanduser()
CHECK_CITATIONS_DIR = Path("/Users/Drew/claude/paper-tools/check-citations")
CHECK_CITATIONS_PY = CHECK_CITATIONS_DIR / "check_citations.py"
CHECK_CITATIONS_PYTHON = Path("/Users/Drew/Desktop/Academic/AI_Research/graduated_dissent_bench/.venv/bin/python3")
GD_REPO = Path("/Users/Drew/Desktop/Academic/AI_Research/graduated_dissent_bench")
GD_PIPELINE_PY = GD_REPO / "harness" / "run_pipeline.py"
GD_PYTHON = GD_REPO / ".venv" / "bin" / "python3"

# Make metadata_check + browser_fetch importable from this server.
sys.path.insert(0, str(CHECK_CITATIONS_DIR))
try:
    from metadata_check import metadata_check as _metadata_check  # type: ignore
except Exception as _e:  # noqa: BLE001
    _metadata_check = None  # type: ignore
try:
    from browser_fetch import fetch_url_browser as _fetch_url_browser, playwright_available as _playwright_available  # type: ignore
except Exception:
    _fetch_url_browser = None  # type: ignore
    _playwright_available = lambda: False  # type: ignore

JOBS_DIR = Path("/tmp/papers-mcp-jobs")
JOBS_DIR.mkdir(parents=True, exist_ok=True)

ARXIV_LAST_FETCH = {"t": 0.0}
ARXIV_RATE_S = 3.0

server = FastMCP("papers")

# ---------------------------------------------------------------------------
# Helpers


def _err(msg: str) -> str:
    return f"Error: {msg}"


def _topic_dirs() -> list[Path]:
    if not LIBRARY_ROOT.is_dir():
        return []
    out = []
    for p in sorted(LIBRARY_ROOT.iterdir()):
        if not p.is_dir() or p.name.startswith(".") or p.name == "OLD":
            continue
        out.append(p)
    return out


def _resolve_slot(slot: str) -> Optional[Path]:
    """Accept `topic/slot_name`, absolute slot path, or bare `slot_name` (search topics)."""
    p = Path(slot)
    if p.is_absolute() and p.is_dir():
        return p
    if "/" in slot:
        cand = LIBRARY_ROOT / slot
        return cand if cand.is_dir() else None
    for topic in _topic_dirs():
        cand = topic / slot
        if cand.is_dir():
            return cand
    return None


def _slot_pdf(slot_path: Path) -> Optional[Path]:
    p = slot_path / f"{slot_path.name}.pdf"
    return p if p.is_file() else None


def _slot_one_pager(slot_path: Path) -> Optional[Path]:
    p = slot_path / "one_pager.md"
    return p if p.is_file() else None


def _slot_paths(topic: Optional[str] = None) -> list[Path]:
    topics = [LIBRARY_ROOT / topic] if topic else _topic_dirs()
    slots: list[Path] = []
    for t in topics:
        if not t.is_dir():
            continue
        for child in sorted(t.iterdir()):
            if not child.is_dir():
                continue
            if (child / "one_pager.md").is_file():
                slots.append(child)
    return slots


def _parse_one_pager_title(text: str) -> str:
    m = re.search(r"^# (.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _parse_one_pager_section(text: str, header: str) -> str:
    pat = rf"^## {re.escape(header)}\s*\n(.+?)(?=^## |\Z)"
    m = re.search(pat, text, re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else ""


def _git(args: list[str]) -> tuple[int, str]:
    r = subprocess.run(["git", "-C", str(LIBRARY_ROOT)] + args, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


# ---------------------------------------------------------------------------
# Library tools


@server.tool(description="List all topic folders with slot and PDF counts.")
def library_list_topics() -> str:
    if not LIBRARY_ROOT.is_dir():
        return _err(f"library root not found: {LIBRARY_ROOT}")
    lines = [f"Library root: {LIBRARY_ROOT}", ""]
    for topic in _topic_dirs():
        slots = [c for c in topic.iterdir() if c.is_dir() and (c / "one_pager.md").is_file()]
        with_pdf = sum(1 for s in slots if _slot_pdf(s))
        lines.append(f"  {topic.name}/  — {len(slots)} slots, {with_pdf} with PDF")
    return "\n".join(lines)


@server.tool(description="List paper slots. Optionally filter by topic name. Returns one line per slot with title.")
def library_list_papers(topic: str = "") -> str:
    slots = _slot_paths(topic if topic else None)
    if not slots:
        return f"(no slots found{' in topic ' + topic if topic else ''})"
    out = []
    for s in slots:
        op_text = (s / "one_pager.md").read_text(errors="replace")
        title = _parse_one_pager_title(op_text) or "(no title)"
        pdf = "[PDF]" if _slot_pdf(s) else "[----]"
        out.append(f"{pdf} {s.relative_to(LIBRARY_ROOT)} — {title}")
    return "\n".join(out)


@server.tool(description="Read one_pager.md for a slot. Accepts 'topic/slot_name' or bare 'slot_name'.")
def library_get_paper(slot: str) -> str:
    sp = _resolve_slot(slot)
    if not sp:
        return _err(f"slot not found: {slot}")
    op = _slot_one_pager(sp)
    if not op:
        return _err(f"no one_pager.md in {sp}")
    pdf = _slot_pdf(sp)
    header = f"Slot: {sp.relative_to(LIBRARY_ROOT)}\nPDF: {pdf.name if pdf else 'MISSING'}\n" + "-" * 60 + "\n"
    return header + op.read_text(errors="replace")


@server.tool(description="Full-text search across one_pager.md and TOC.md files. Case-insensitive substring match; returns slot path, matched line, line number.")
def library_search(query: str, limit: int = 20) -> str:
    if not query.strip():
        return _err("empty query")
    results: list[str] = []
    q = query.lower()
    for topic in _topic_dirs():
        files = list(topic.rglob("one_pager.md")) + list(topic.glob("TOC.md"))
        for fp in files:
            try:
                lines = fp.read_text(errors="replace").splitlines()
            except Exception:
                continue
            for i, line in enumerate(lines, start=1):
                if q in line.lower():
                    rel = fp.relative_to(LIBRARY_ROOT)
                    results.append(f"{rel}:{i}: {line.strip()}")
                    if len(results) >= limit:
                        return "\n".join(results) + f"\n... (capped at {limit})"
    return "\n".join(results) if results else "(no matches)"


@server.tool(description="Find a paper by arXiv ID or DOI. Searches one_pager.md files for the identifier.")
def library_find(arxiv_id: str = "", doi: str = "") -> str:
    needle = arxiv_id.strip() or doi.strip()
    if not needle:
        return _err("provide arxiv_id or doi")
    hits = []
    for slot in _slot_paths():
        text = (slot / "one_pager.md").read_text(errors="replace")
        if needle.lower() in text.lower():
            hits.append(str(slot.relative_to(LIBRARY_ROOT)))
    return "\n".join(hits) if hits else "(not found)"


_ONE_PAGER_TEMPLATE = """# {title}

## Reference
{reference}

## Source
{source}, tier {tier}.

## Beyond-abstract summary
{beyond_abstract}

## Use in {manuscript} manuscript
{use_in}

## Status
{status}
"""


@server.tool(
    description=(
        "Create a new paper slot. Writes one_pager.md following the ADDING_FILES.md format. "
        "Does NOT append to TOC (use library_toc_append separately). "
        "slot_name pattern: firstauthor_year[_suffix] (snake_case, lowercase)."
    )
)
def library_add_paper(
    topic: str,
    slot_name: str,
    reference: str,
    title: str,
    beyond_abstract: str = "**Stub** — summary not yet written.",
    source: str = "F-identity",
    tier: str = "pending",
    manuscript: str = "F-identity",
    use_in: str = "**Stub** — citation context not yet written.",
    status: str = "preprint",
    verify: bool = True,
) -> str:
    if not re.fullmatch(r"[a-z0-9_]+", slot_name):
        return _err(f"slot_name must be snake_case lowercase: {slot_name}")
    topic_dir = LIBRARY_ROOT / topic
    if not topic_dir.is_dir():
        return _err(f"topic does not exist: {topic} (use library_create_topic)")
    slot_dir = topic_dir / slot_name
    if slot_dir.exists():
        return _err(f"slot already exists: {slot_dir.relative_to(LIBRARY_ROOT)}")
    slot_dir.mkdir(parents=True)
    op = slot_dir / "one_pager.md"
    op.write_text(
        _ONE_PAGER_TEMPLATE.format(
            title=title,
            reference=reference,
            source=source,
            tier=tier,
            beyond_abstract=beyond_abstract,
            manuscript=manuscript,
            use_in=use_in,
            status=status,
        )
    )
    msg = f"Created slot: {slot_dir.relative_to(LIBRARY_ROOT)}\n  one_pager.md written ({op.stat().st_size} bytes)\n  PDF: missing — use library_attach_pdf or library_fetch_arxiv"
    if verify:
        try:
            verify_out = library_verify_citation(f"{topic}/{slot_name}", save=True, save_source=True, browser=False)  # type: ignore[misc]
            msg += "\n\nAuto-verification:\n" + "\n".join("  " + l for l in verify_out.splitlines())
        except Exception as e:  # noqa: BLE001
            msg += f"\n\nAuto-verification failed: {e}"
    return msg


@server.tool(description="Create a new top-level topic folder with an empty TOC.md.")
def library_create_topic(topic: str) -> str:
    if not re.fullmatch(r"[a-z0-9_]+", topic):
        return _err(f"topic must be snake_case lowercase: {topic}")
    td = LIBRARY_ROOT / topic
    if td.exists():
        return _err(f"topic already exists: {topic}")
    td.mkdir(parents=True)
    (td / "TOC.md").write_text(f"# {topic} — Table of contents\n\n## Tier 1 (★)\n\n## Tier 2 (✦)\n\n## Tier 3 (○)\n")
    return f"Created topic: {topic}/"


@server.tool(description="Append a line under the given tier in a topic's TOC.md. tier in {1,2,3}.")
def library_toc_append(topic: str, slot_name: str, title: str, venue: str = "", arxiv_id: str = "", note: str = "", tier: int = 2) -> str:
    if tier not in (1, 2, 3):
        return _err("tier must be 1, 2, or 3")
    toc = LIBRARY_ROOT / topic / "TOC.md"
    if not toc.is_file():
        return _err(f"TOC.md not found in topic: {topic}")
    label = (slot_name.replace("_", " ").title()).strip()
    arxiv_part = f" [arXiv:{arxiv_id}]" if arxiv_id else ""
    line = f"- [{label}]({slot_name}/one_pager.md) — *{title}*"
    if venue:
        line += f", **{venue}**"
    line += f"{arxiv_part}."
    if note:
        line += f" {note}"
    header_pat = {1: r"^## Tier 1.*$", 2: r"^## Tier 2.*$", 3: r"^## Tier 3.*$"}[tier]
    body = toc.read_text()
    m = re.search(header_pat, body, re.MULTILINE)
    if not m:
        body = body.rstrip() + f"\n\n## Tier {tier}\n"
        m = re.search(rf"^## Tier {tier}.*$", body, re.MULTILINE)
    insert_at = m.end()
    new_body = body[:insert_at] + "\n" + line + body[insert_at:]
    toc.write_text(new_body)
    return f"Appended to {topic}/TOC.md under tier {tier}:\n  {line}"


@server.tool(description="Copy a PDF from a local source path into a slot, renaming it to <slot_name>.pdf.")
def library_attach_pdf(slot: str, source_path: str) -> str:
    sp = _resolve_slot(slot)
    if not sp:
        return _err(f"slot not found: {slot}")
    src = Path(source_path).expanduser()
    if not src.is_file():
        return _err(f"source not a file: {src}")
    dst = sp / f"{sp.name}.pdf"
    if dst.exists():
        return _err(f"PDF already exists at {dst.relative_to(LIBRARY_ROOT)}; remove first if intentional")
    shutil.copy2(src, dst)
    return f"Attached: {src} -> {dst.relative_to(LIBRARY_ROOT)} ({dst.stat().st_size} bytes)"


@server.tool(description="Fetch a PDF from arXiv given an arXiv ID (e.g. '1234.5678' or 'cond-mat/0501001') and place it in the slot. Honors 3-second rate limit.")
def library_fetch_arxiv(slot: str, arxiv_id: str) -> str:
    sp = _resolve_slot(slot)
    if not sp:
        return _err(f"slot not found: {slot}")
    dst = sp / f"{sp.name}.pdf"
    if dst.exists():
        return _err(f"PDF already exists at {dst.relative_to(LIBRARY_ROOT)}; remove first if intentional")
    aid = arxiv_id.strip().lstrip("arXiv:").lstrip("arxiv:")
    elapsed = time.time() - ARXIV_LAST_FETCH["t"]
    if elapsed < ARXIV_RATE_S:
        time.sleep(ARXIV_RATE_S - elapsed)
    url = f"https://arxiv.org/pdf/{aid}"
    try:
        r = requests.get(url, timeout=60, headers={"User-Agent": "papers-mcp/1.0 (literature management)"}, allow_redirects=True)
        ARXIV_LAST_FETCH["t"] = time.time()
    except Exception as e:
        return _err(f"fetch failed: {e}")
    if r.status_code != 200:
        return _err(f"HTTP {r.status_code} from {url}")
    if not r.content.startswith(b"%PDF"):
        return _err(f"not a PDF response from {url} (first 16 bytes: {r.content[:16]!r})")
    dst.write_bytes(r.content)
    return f"Fetched arXiv:{aid} -> {dst.relative_to(LIBRARY_ROOT)} ({dst.stat().st_size} bytes)"


@server.tool(description="Regenerate MISSING.md at the library root, listing all slots without a PDF.")
def library_regenerate_missing() -> str:
    slots = _slot_paths()
    missing = [s for s in slots if not _slot_pdf(s)]
    have = [s for s in slots if _slot_pdf(s)]
    lines = [
        "# Missing PDFs",
        "",
        f"Generated {time.strftime('%Y-%m-%d')} — {len(have)}/{len(slots)} slots have a PDF; **{len(missing)} still missing**.",
        "",
        "To add a missing PDF: drop the file in the slot folder named `<slot_name>.pdf`, then commit.",
        "",
        "| Slot | Notes |",
        "|---|---|",
    ]
    for s in missing:
        lines.append(f"| `{s.relative_to(LIBRARY_ROOT)}` | |")
    target = LIBRARY_ROOT / "MISSING.md"
    target.write_text("\n".join(lines) + "\n")
    return f"Wrote {target.relative_to(LIBRARY_ROOT)} ({len(missing)} missing of {len(slots)} slots)"


@server.tool(description="Validate naming, PDF/folder name match, and required one_pager.md headers across the whole library.")
def library_validate() -> str:
    problems: list[str] = []
    required = ["## Reference", "## Source", "## Beyond-abstract summary"]
    for slot in _slot_paths():
        rel = str(slot.relative_to(LIBRARY_ROOT))
        if not re.fullmatch(r"[a-z0-9_]+", slot.name):
            problems.append(f"  [naming] {rel}: slot folder name not snake_case lowercase")
        pdf = _slot_pdf(slot)
        any_pdf = list(slot.glob("*.pdf"))
        if any_pdf and not pdf:
            problems.append(f"  [pdf-name] {rel}: contains PDF(s) {[p.name for p in any_pdf]} but none named {slot.name}.pdf")
        op = (slot / "one_pager.md").read_text(errors="replace")
        for h in required:
            if h not in op:
                problems.append(f"  [headers] {rel}: missing '{h}'")
    if not problems:
        return f"OK — {len(_slot_paths())} slots validated"
    return f"Found {len(problems)} issue(s):\n" + "\n".join(problems)


@server.tool(description="Run `git status` in the library repo.")
def library_git_status() -> str:
    rc, out = _git(["status", "--short", "--branch"])
    return out or "(clean)"


@server.tool(description="Stage all changes and commit with the given message. Follows the convention from ADDING_FILES.md.")
def library_git_commit(message: str) -> str:
    if not message.strip():
        return _err("commit message required")
    rc, out = _git(["add", "-A"])
    if rc != 0:
        return _err(f"git add failed: {out}")
    rc, out = _git(["commit", "-m", message])
    return out


# ---------------------------------------------------------------------------
# API key management — files under ~/.keys/<service>, mode 0600.
# Matches the convention already used by graduated_dissent_bench/gui/server.py.

KEYS_DIR = Path(os.environ.get("PAPERS_KEYS_DIR", "~/.keys")).expanduser()
_KEY_SERVICES = {
    "anthropic", "openai", "deepseek", "google", "groq", "mistral",
    "xai", "crossref", "semantic_scholar", "openalex",
}


def _key_path(service: str) -> Path:
    return KEYS_DIR / service


@server.tool(
    description=(
        "Store an API key for a service. Writes ~/.keys/<service> with mode 0600. "
        "Common services: anthropic, openai, deepseek, google, groq, mistral, xai, "
        "crossref, semantic_scholar, openalex."
    )
)
def keys_set(service: str, key: str) -> str:
    s = service.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]+", s):
        return _err(f"service must be snake_case lowercase: {service!r}")
    if not key.strip():
        return _err("empty key")
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    p = _key_path(s)
    p.write_text(key.strip() + "\n")
    p.chmod(0o600)
    return f"Stored {s} key at {p} (mode {oct(p.stat().st_mode & 0o777)})"


@server.tool(
    description=(
        "List which services have an API key configured under ~/.keys/. Does NOT print the key values."
    )
)
def keys_list() -> str:
    if not KEYS_DIR.is_dir():
        return f"(no keys directory at {KEYS_DIR})"
    lines = [f"Keys directory: {KEYS_DIR}", ""]
    files = sorted(p for p in KEYS_DIR.iterdir() if p.is_file() and not p.name.startswith("."))
    if not files:
        lines.append("(no keys stored)")
    for p in files:
        try:
            n = len(p.read_text().strip())
            mode = oct(p.stat().st_mode & 0o777)
        except Exception:
            n, mode = 0, "?"
        flag = "" if mode == "0o600" else f"  WARNING: mode {mode} (should be 0o600)"
        lines.append(f"  {p.name}  ({n} chars){flag}")
    return "\n".join(lines)


@server.tool(description="Delete the stored API key for a service.")
def keys_delete(service: str) -> str:
    s = service.strip().lower()
    p = _key_path(s)
    if not p.is_file():
        return f"(no key stored for {s})"
    p.unlink()
    return f"Deleted key for {s}"


@server.tool(
    description=(
        "Verify a service's stored key is present and non-empty. Returns OK/MISSING and the character length. "
        "Does NOT print the key value."
    )
)
def keys_check(service: str) -> str:
    s = service.strip().lower()
    p = _key_path(s)
    if not p.is_file():
        return f"MISSING: no key for {s} at {p}"
    n = len(p.read_text().strip())
    return f"OK: {s} key present ({n} chars at {p})"


def _load_key(service: str) -> Optional[str]:
    p = _key_path(service)
    if not p.is_file():
        return os.environ.get(f"{service.upper()}_API_KEY")
    return p.read_text().strip() or None


# ---------------------------------------------------------------------------
# Web fetch + search + verification


_META_RE = re.compile(r'<meta\s+(?:name|property)=["\']([^"\']+)["\']\s+content=["\']([^"\']*)["\']', re.IGNORECASE)
_SCRIPT_RE = re.compile(r"<script\b.*?</script>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _fetch_url_plain(url: str, timeout: float = 25.0, max_bytes: int = 400_000) -> dict:
    import urllib.error, urllib.request
    out = {"status": 0, "final_url": "", "title": "", "meta": {},
           "text_excerpt": "", "pdf": False, "error": "", "raw_meta_text": ""}
    if not url:
        out["error"] = "no URL"
        return out
    req = urllib.request.Request(url, headers={
        "User-Agent": "papers-mcp/1.0 (citation verifier)",
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out["status"] = resp.status
            out["final_url"] = resp.url
            ctype = resp.headers.get("Content-Type", "").lower()
            data = resp.read(max_bytes)
            if "application/pdf" in ctype or out["final_url"].lower().endswith(".pdf"):
                out["pdf"] = True
                out["text_excerpt"] = f"[PDF at {out['final_url']}]"
                return out
            try:
                html = data.decode("utf-8", errors="replace")
            except Exception:
                html = data.decode("latin-1", errors="replace")
            for m in _META_RE.finditer(html):
                name = m.group(1).lower()
                if name.startswith(("citation_", "dc.", "og:", "twitter:title", "description")):
                    out["meta"][name] = m.group(2)
            tm = _TITLE_RE.search(html)
            if tm:
                out["title"] = re.sub(r"\s+", " ", tm.group(1)).strip()
            head_m = re.search(r"<head\b[^>]*>(.*?)</head>", html, re.IGNORECASE | re.DOTALL)
            out["raw_meta_text"] = (head_m.group(1) if head_m else html)[:20000]
            visible = _SCRIPT_RE.sub("", html)
            visible = _TAG_RE.sub(" ", visible)
            visible = re.sub(r"\s+", " ", visible).strip()
            out["text_excerpt"] = visible[:8000]
    except urllib.error.HTTPError as e:
        out["status"] = e.code
        out["error"] = f"HTTP {e.code}: {e.reason}"
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    return out


@server.tool(
    description=(
        "Fetch a URL and return title, meta, and visible text. "
        "If browser=True, uses headless Chromium (handles Cloudflare/Elsevier/Oxford bot blocks). "
        "Returns up to 8000 chars of visible text."
    )
)
def web_fetch(url: str, browser: bool = False) -> str:
    if browser:
        if not (_fetch_url_browser and _playwright_available()):
            return _err("Playwright/browser_fetch not available")
        r = _fetch_url_browser(url)
    else:
        r = _fetch_url_plain(url)
    if r.get("error"):
        return f"status: {r.get('status')}\nerror: {r['error']}\nfinal_url: {r.get('final_url','')}"
    lines = [
        f"status: {r.get('status')}",
        f"final_url: {r.get('final_url')}",
        f"title: {r.get('title')}",
    ]
    meta = r.get("meta") or {}
    if meta:
        lines.append("meta:")
        for k in sorted(meta):
            lines.append(f"  {k}: {meta[k][:300]}")
    lines.append("text_excerpt:")
    lines.append(r.get("text_excerpt", "")[:6000])
    return "\n".join(lines)


@server.tool(
    description=(
        "Search arXiv and/or Crossref for papers matching a free-text query. "
        "source in {arxiv, crossref, both}. Returns top results with title, authors, year, arxiv_id, DOI."
    )
)
def web_search(query: str, source: str = "both", limit: int = 10) -> str:
    if not query.strip():
        return _err("empty query")
    src = source.lower()
    blocks: list[str] = []
    if src in ("arxiv", "both"):
        try:
            url = (
                "https://export.arxiv.org/api/query?search_query="
                + urllib.parse.quote(query)
                + f"&max_results={limit}&sortBy=relevance"
            )
            r = requests.get(url, timeout=20, headers={"User-Agent": "papers-mcp/1.0"})
            if r.status_code == 200:
                root = ET.fromstring(r.text)
                ns = {"a": "http://www.w3.org/2005/Atom"}
                blocks.append(f"=== arXiv ({len(root.findall('a:entry', ns))} hits) ===")
                for e in root.findall("a:entry", ns):
                    title = (e.findtext("a:title", default="", namespaces=ns) or "").strip().replace("\n", " ")
                    summary = (e.findtext("a:summary", default="", namespaces=ns) or "").strip()[:240].replace("\n", " ")
                    aid = (e.findtext("a:id", default="", namespaces=ns) or "").rsplit("/", 1)[-1]
                    pub = (e.findtext("a:published", default="", namespaces=ns) or "")[:10]
                    authors = [a.findtext("a:name", default="", namespaces=ns) for a in e.findall("a:author", ns)]
                    blocks.append(f"  arXiv:{aid}  ({pub})  {title}")
                    blocks.append(f"    authors: {', '.join(authors[:6])}{'…' if len(authors) > 6 else ''}")
                    if summary:
                        blocks.append(f"    abstract: {summary}…")
            else:
                blocks.append(f"=== arXiv: HTTP {r.status_code} ===")
        except Exception as e:  # noqa: BLE001
            blocks.append(f"=== arXiv error: {e} ===")
    if src in ("crossref", "both"):
        try:
            url = (
                "https://api.crossref.org/works?query="
                + urllib.parse.quote(query)
                + f"&rows={limit}"
            )
            r = requests.get(url, timeout=20, headers={"User-Agent": "papers-mcp/1.0 (mailto:andrew@amb-aero.com)"})
            if r.status_code == 200:
                data = r.json()
                items = data.get("message", {}).get("items", [])
                blocks.append(f"=== Crossref ({len(items)} hits) ===")
                for it in items:
                    title = (it.get("title") or [""])[0]
                    doi = it.get("DOI", "")
                    year = ""
                    try:
                        year = str((it.get("issued", {}).get("date-parts") or [[None]])[0][0] or "")
                    except Exception:
                        pass
                    container = (it.get("container-title") or [""])[0]
                    authors = it.get("author", []) or []
                    auth_str = ", ".join(
                        f"{a.get('family', '')}" + (f" {a.get('given', '')[:1]}." if a.get("given") else "")
                        for a in authors[:4]
                    )
                    blocks.append(f"  DOI:{doi}  ({year})  {title}")
                    if container:
                        blocks.append(f"    venue: {container}")
                    if auth_str:
                        blocks.append(f"    authors: {auth_str}{'…' if len(authors) > 4 else ''}")
            else:
                blocks.append(f"=== Crossref: HTTP {r.status_code} ===")
        except Exception as e:  # noqa: BLE001
            blocks.append(f"=== Crossref error: {e} ===")
    return "\n".join(blocks) if blocks else "(no results)"


_ARXIV_ID_RE = re.compile(r"(?:arXiv\s*:?\s*)([a-z\-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)


def _extract_url_from_reference(text: str) -> Optional[str]:
    m = _ARXIV_ID_RE.search(text or "")
    if m:
        return f"https://arxiv.org/abs/{m.group(1)}"
    m = _DOI_RE.search(text or "")
    if m:
        return f"https://doi.org/{m.group(0).rstrip('.,;)')}"
    m = re.search(r"https?://\S+", text or "")
    if m:
        return m.group(0).rstrip(".,;)")
    return None


_ARXIV_PREPRINT_EMPH_RE = re.compile(r"\\emph\{\s*arXiv[^}]*\}", re.IGNORECASE)
_LOW_INFO_TITLES = {"sciencedirect", "redirecting", "just a moment...", "loading",
                    "checking your browser", "access denied", "page not found"}


def _arxiv_search_title(title: str, max_results: int = 5) -> Optional[str]:
    """Search arXiv by title; return an arXiv ID with a substring-matching title."""
    if not title or len(title) < 8:
        return None
    try:
        elapsed = time.time() - ARXIV_LAST_FETCH["t"]
        if elapsed < ARXIV_RATE_S:
            time.sleep(ARXIV_RATE_S - elapsed)
        url = ("https://export.arxiv.org/api/query?search_query=ti:"
               + urllib.parse.quote('"' + title[:200] + '"')
               + f"&max_results={max_results}")
        r = requests.get(url, timeout=20, headers={"User-Agent": "papers-mcp/1.0"})
        ARXIV_LAST_FETCH["t"] = time.time()
        if r.status_code != 200:
            return None
        root = ET.fromstring(r.text)
    except Exception:
        return None
    ns = {"a": "http://www.w3.org/2005/Atom"}
    norm_q = re.sub(r"[^a-z0-9 ]+", " ", title.lower())
    norm_q = re.sub(r"\s+", " ", norm_q).strip()
    for e in root.findall("a:entry", ns):
        t = (e.findtext("a:title", default="", namespaces=ns) or "").strip().replace("\n", " ")
        norm_t = re.sub(r"[^a-z0-9 ]+", " ", t.lower())
        norm_t = re.sub(r"\s+", " ", norm_t).strip()
        if norm_q and norm_t and (norm_q in norm_t or norm_t in norm_q):
            aid = (e.findtext("a:id", default="", namespaces=ns) or "").rsplit("/", 1)[-1]
            return re.sub(r"v\d+$", "", aid)
    return None


def _crossref_by_doi(doi: str) -> dict:
    """Return a fetched-shaped dict synthesized from Crossref. No Cloudflare on api.crossref.org."""
    out = {"status": 0, "final_url": "", "title": "", "meta": {},
           "text_excerpt": "", "pdf": False, "error": "", "raw_meta_text": ""}
    doi_clean = doi.lstrip("doi:").strip().rstrip(".,;)")
    try:
        url = f"https://api.crossref.org/works/{urllib.parse.quote(doi_clean, safe='/.()')}"
        r = requests.get(url, timeout=20, headers={
            "User-Agent": "papers-mcp/1.0 (mailto:andrew@amb-aero.com)",
            "Accept": "application/json",
        })
        if r.status_code != 200:
            out["error"] = f"HTTP {r.status_code}"
            return out
        msg = r.json().get("message", {})
        out["status"] = 200
        out["final_url"] = url
        title = (msg.get("title") or [""])[0]
        out["title"] = title
        meta = out["meta"]
        if title:
            meta["citation_title"] = title
        if msg.get("DOI"):
            meta["citation_doi"] = msg["DOI"]
        author_lines = []
        for a in msg.get("author", []) or []:
            family = a.get("family", "")
            given = a.get("given", "")
            if family:
                name = f"{family}, {given}".strip(", ")
                meta.setdefault("citation_author", name)
                author_lines.append(f'<meta name="citation_author" content="{family}, {given}" />')
        if (msg.get("container-title") or [""])[0]:
            ct = msg["container-title"][0]
            meta["citation_journal_title"] = ct
            author_lines.append(f'<meta name="citation_journal_title" content="{ct}" />')
        if msg.get("volume"):
            meta["citation_volume"] = msg["volume"]
        if msg.get("page"):
            pg = msg["page"]
            if "-" in pg:
                fp, lp = pg.split("-", 1)
                meta["citation_firstpage"] = fp
                meta["citation_lastpage"] = lp
            else:
                meta["citation_firstpage"] = pg
        try:
            year = msg.get("issued", {}).get("date-parts", [[None]])[0][0]
            if year:
                meta["citation_publication_date"] = str(year)
        except Exception:
            pass
        out["raw_meta_text"] = "\n".join(author_lines)
        out["text_excerpt"] = title
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    return out


_DOI_FROM_URL_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/(.+)$", re.IGNORECASE)


def _verify_fetch_with_fallback(url: str, *, title_hint: Optional[str] = None) -> tuple[dict, str]:
    """Return (fetched_dict, engine_label) — urllib → browser → crossref → arxiv-search."""
    fetched = _fetch_url_plain(url)
    engine = "urllib"
    if _needs_browser_fallback(fetched) and _fetch_url_browser and _playwright_available():
        fetched = _fetch_url_browser(url)
        engine = "browser"
    if _needs_browser_fallback(fetched):
        doi: Optional[str] = None
        m = _DOI_FROM_URL_RE.match(url)
        if m:
            doi = m.group(1)
        else:
            doi = (fetched.get("meta", {}) or {}).get("citation_doi")
        if doi:
            cr = _crossref_by_doi(doi)
            if cr.get("title"):
                return cr, "crossref"
        if title_hint:
            aid = _arxiv_search_title(title_hint)
            if aid:
                arx = _fetch_url_plain(f"https://arxiv.org/abs/{aid}")
                if arx.get("meta"):
                    return arx, "arxiv-search"
    return fetched, engine


def _needs_browser_fallback(fetched: dict) -> bool:
    if not fetched:
        return False
    if fetched.get("error") and not fetched.get("status"):
        return True
    s = fetched.get("status", 0)
    if s and s >= 400:
        return True
    if s == 200 and len(fetched.get("text_excerpt") or "") < 200 and not fetched.get("meta"):
        return True
    title = (fetched.get("title") or "").strip().lower()
    if "just a moment" in title or "attention required" in title:
        return True
    if title in _LOW_INFO_TITLES:
        return True
    meta = fetched.get("meta") or {}
    if not any(k.startswith(("citation_title", "dc.title", "og:title", "citation_doi")) for k in meta):
        if len(fetched.get("text_excerpt") or "") < 1500:
            return True
    return False


_ARXIV_REF_RE = re.compile(r"\barXiv\s*:?\s*[a-z0-9./-]+(?:v\d+)?", re.IGNORECASE)
_DOI_REF_RE = re.compile(r"\bdoi\s*:?\s*10\.\d{4,9}/[^\s,;]+", re.IGNORECASE)
_URL_REF_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def _markdown_to_pseudo_latex(text: str) -> str:
    """Convert one_pager markdown into bibitem-shaped LaTeX for metadata_check.
    See backfill_library.md_to_pseudo_latex docstring for the rationale.
    """
    text = re.sub(r"\{([A-Za-z]+)\}", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", text)
    text = re.sub(r"(?<![*])\*([^*\n]+)\*(?![*])", r"\\emph{\1}", text)
    text = _ARXIV_PREPRINT_EMPH_RE.sub("", text)
    text = _ARXIV_REF_RE.sub("", text)
    text = _DOI_REF_RE.sub("", text)
    text = _URL_REF_RE.sub("", text)
    return text


_VERIFY_MARKER = "## Citation verification"


def _strip_verify_block(text: str) -> str:
    return re.sub(rf"\n*{re.escape(_VERIFY_MARKER)}.*\Z", "", text, flags=re.DOTALL)


def _format_verify_block(verdict: str, rationale: list[str], final_url: str, used_browser: bool, fetched_meta: dict, suggested_arxiv: Optional[str]) -> str:
    lines = [
        "",
        _VERIFY_MARKER,
        "",
        f"- **Verdict:** `{verdict}`",
        f"- **Checked:** {time.strftime('%Y-%m-%d %H:%M')}  ({'browser' if used_browser else 'urllib'})",
        f"- **Source URL:** {final_url or '(none)'}",
    ]
    if suggested_arxiv:
        lines.append(f"- **Suggested arXiv (autofix):** {suggested_arxiv}")
    if rationale:
        lines.append("- **Rationale:**")
        for r in rationale:
            lines.append(f"  - {r}")
    if fetched_meta:
        keys = [k for k in fetched_meta if k.startswith(("citation_title", "citation_author", "citation_doi", "citation_journal_title", "dc.title", "dc.creator"))]
        if keys:
            lines.append("- **Source meta (subset):**")
            for k in sorted(keys)[:8]:
                lines.append(f"  - `{k}`: {fetched_meta[k][:200]}")
    return "\n".join(lines) + "\n"


@server.tool(
    description=(
        "Verify a paper's citation by fetching the source page (arXiv/DOI/URL) and running the deterministic metadata_check. "
        "verdicts: PASS, FAIL, FLAG, WRONG_ARXIV_SAME_PAPER, AUTHOR_MISMATCH_SAME_PAPER. "
        "save=True appends a '## Citation verification' block to one_pager.md (replacing any prior block). "
        "save_source=True also saves the fetched page to <slot>/source_page.txt for searchability. "
        "browser=True forces headless Chromium fetch (use for Cloudflare-blocked publishers)."
    )
)
def library_verify_citation(slot: str, save: bool = True, save_source: bool = True, browser: bool = False) -> str:
    if _metadata_check is None:
        return _err("metadata_check.py not importable")
    sp = _resolve_slot(slot)
    if not sp:
        return _err(f"slot not found: {slot}")
    op = _slot_one_pager(sp)
    if not op:
        return _err(f"no one_pager.md in {sp}")
    text = op.read_text(errors="replace")
    ref = _parse_one_pager_section(text, "Reference")
    if not ref:
        return _err(f"no '## Reference' section in {sp.relative_to(LIBRARY_ROOT)}")
    title = _parse_one_pager_title(text)
    bibitem_raw = _markdown_to_pseudo_latex(ref)
    url = _extract_url_from_reference(ref) or _extract_url_from_reference(title)
    used_browser = False
    fetched: dict = {}
    engine = "none"
    title_hint = None
    m_title = re.search(r"\*([^*\n]{8,})\*", ref or "")
    if m_title:
        title_hint = re.sub(r"\s+", " ", m_title.group(1)).strip()
    if url:
        if browser:
            if not (_fetch_url_browser and _playwright_available()):
                return _err("browser requested but Playwright not available")
            fetched = _fetch_url_browser(url)
            used_browser = True
            engine = "browser"
        else:
            fetched, engine = _verify_fetch_with_fallback(url, title_hint=title_hint)
            used_browser = (engine == "browser")
    elif title_hint:
        aid = _arxiv_search_title(title_hint)
        if aid:
            fetched = _fetch_url_plain(f"https://arxiv.org/abs/{aid}")
            engine = "arxiv-search"
    # If a local PDF is present, prefer it: metadata_check treats it as
    # ground-truth evidence and returns PASS without needing source-page meta.
    pdf_basename = None
    pdf_path = _slot_pdf(sp)
    if pdf_path:
        pdf_basename = pdf_path.name
    report = _metadata_check(bibitem_raw, fetched or None, pdf_basename)
    if save_source and fetched and (fetched.get("text_excerpt") or fetched.get("raw_meta_text")):
        body = []
        body.append(f"# Source page for {sp.name}\n")
        body.append(f"Fetched: {time.strftime('%Y-%m-%d %H:%M')}  ({'browser' if used_browser else 'urllib'})\n")
        body.append(f"URL: {fetched.get('final_url') or url}\n")
        body.append(f"Status: {fetched.get('status')}\n")
        body.append(f"Title: {fetched.get('title','')}\n\n")
        body.append("## Meta tags\n")
        for k, v in (fetched.get("meta") or {}).items():
            body.append(f"- `{k}`: {v}\n")
        body.append("\n## Visible text\n\n")
        body.append(fetched.get("text_excerpt", ""))
        (sp / "source_page.txt").write_text("".join(body))
    if save:
        block = _format_verify_block(
            verdict=report.verdict,
            rationale=report.rationale,
            final_url=(fetched.get("final_url") if fetched else "") or (url or ""),
            used_browser=used_browser,
            fetched_meta=(fetched.get("meta") or {}) if fetched else {},
            suggested_arxiv=getattr(report, "suggested_arxiv", None),
        )
        new_text = _strip_verify_block(text).rstrip() + "\n" + block
        op.write_text(new_text)
    summary = [
        f"slot: {sp.relative_to(LIBRARY_ROOT)}",
        f"verdict: {report.verdict}",
        f"source: {(fetched.get('final_url') if fetched else '') or url or '(none)'}",
        f"engine: {'browser' if used_browser else 'urllib'}",
    ]
    if getattr(report, "suggested_arxiv", None):
        summary.append(f"suggested_arxiv: {report.suggested_arxiv}")
    if report.rationale:
        summary.append("rationale:")
        summary += [f"  - {r}" for r in report.rationale]
    return "\n".join(summary)


_JOURNAL_CANONICAL = {
    "physical review letters": "Phys. Rev. Lett.",
    "phys rev lett": "Phys. Rev. Lett.",
    "physics letters b": "Phys. Lett. B",
    "phys lett b": "Phys. Lett. B",
    "physical review d": "Phys. Rev. D",
    "phys rev d": "Phys. Rev. D",
    "physical review b": "Phys. Rev. B",
    "phys rev b": "Phys. Rev. B",
    "modern physics letters a": "Mod. Phys. Lett. A",
    "mod phys lett a": "Mod. Phys. Lett. A",
    "international journal of modern physics a": "Int. J. Mod. Phys. A",
    "int j mod phys a": "Int. J. Mod. Phys. A",
    "european physical journal c": "Eur. Phys. J. C",
    "eur phys j c": "Eur. Phys. J. C",
    "european physical journal special topics": "Eur. Phys. J. ST",
    "eur phys j special topics": "Eur. Phys. J. ST",
    "progress of theoretical physics": "Prog. Theor. Phys.",
    "prog theor phys": "Prog. Theor. Phys.",
    "journal of high energy physics": "JHEP",
    "jhep": "JHEP",
    "nuclear physics b": "Nucl. Phys. B",
    "nucl phys b": "Nucl. Phys. B",
    "lettere al nuovo cimento": "Lett. Nuovo Cim.",
    "lett nuovo cim": "Lett. Nuovo Cim.",
    "letters in mathematical physics": "Lett. Math. Phys.",
    "z phys c": "Z. Phys. C",
    "zeitschrift fur physik c": "Z. Phys. C",
    "reviews of modern physics": "Rev. Mod. Phys.",
    "rev mod phys": "Rev. Mod. Phys.",
    "nature physics": "Nat. Phys.",
    "nature": "Nature",
    "science": "Science",
    "advances in neural information processing systems": "NeurIPS",
    "neurips": "NeurIPS",
    "iclr": "ICLR",
    "icml": "ICML",
    "naacl": "NAACL",
    "emnlp": "EMNLP",
    "acl": "ACL",
}


def _canon_journal(j: Optional[str]) -> Optional[str]:
    if not j:
        return None
    norm = re.sub(r"[^\w\s]+", "", j.lower()).strip()
    norm = re.sub(r"\s+", " ", norm)
    return _JOURNAL_CANONICAL.get(norm, j.strip())


def _slot_journal(slot: Path) -> tuple[Optional[str], str]:
    """Return (journal, source) for a slot. source ∈ {meta, ref, none}."""
    op = (slot / "one_pager.md").read_text(errors="replace")
    src = slot / "source_page.txt"
    if src.is_file():
        st = src.read_text(errors="replace")
        m = re.search(r"^- `citation_journal_title`:\s*(.+)$", st, re.MULTILINE)
        if m:
            return m.group(1).strip(), "meta"
    m = re.search(r"`citation_journal_title`:\s*([^\n]+)", op)
    if m:
        return m.group(1).strip(), "meta"
    ref_m = re.search(r"^## Reference\s*\n(.+?)(?=^## |\Z)", op, re.MULTILINE | re.DOTALL)
    if ref_m:
        ref = ref_m.group(1)
        for pat in [
            r"→\s*\*\*?\*([^*]+)\*",
            r"→\s*\*([^*]+)\*",
            r"\*\*\*([^*]+?)\*\s+\*\*",
        ]:
            m = re.search(pat, ref)
            if m:
                v = m.group(1).strip()
                if "arxiv" not in v.lower():
                    return v, "ref"
        for m in re.finditer(r"\*\*([^*]+)\*\*", ref):
            v = m.group(1).strip()
            if "arxiv" in v.lower() or re.match(r"^\d", v):
                continue
            v = re.split(r"\s+\d{1,3}\s", v, maxsplit=1)[0]
            v = re.split(r"\s+\(\d{4}\)", v, maxsplit=1)[0]
            return v.strip(), "ref"
    return None, "none"


def _slot_year(slot: Path) -> Optional[int]:
    """Pull year from slot name (e.g. koide_1983 -> 1983) or from one_pager."""
    m = re.search(r"(?:^|[_-])(19\d{2}|20\d{2})(?:$|[_-])", slot.name)
    if m:
        return int(m.group(1))
    op = (slot / "one_pager.md").read_text(errors="replace")
    m = re.search(r"\((19\d{2}|20\d{2})\)", op)
    return int(m.group(1)) if m else None


def _verdict_of(slot: Path) -> Optional[str]:
    op = (slot / "one_pager.md").read_text(errors="replace")
    m = re.search(r"^- \*\*Verdict:\*\* `([A-Z_]+)`", op, re.MULTILINE)
    return m.group(1) if m else None


@server.tool(
    description=(
        "Summary statistics for a topic (or the whole library if topic is empty). "
        "group_by in {journal, year, decade, verdict, has_pdf}. Returns a sorted count table. "
        "Journals are canonicalized (Phys. Rev. Lett. = Physical Review Letters = phys rev lett, etc.)."
    )
)
def library_stats(topic: str = "", group_by: str = "journal") -> str:
    gb = group_by.lower()
    if gb not in {"journal", "year", "decade", "verdict", "has_pdf"}:
        return _err(f"group_by must be one of journal/year/decade/verdict/has_pdf; got {group_by!r}")
    slots = _slot_paths(topic or None)
    if not slots:
        return f"(no slots{' in topic ' + topic if topic else ''})"
    from collections import Counter
    counts: Counter = Counter()
    arxiv_only = 0
    untagged = 0
    no_year = 0
    for s in slots:
        if gb == "journal":
            j, _src = _slot_journal(s)
            if not j:
                op = (s / "one_pager.md").read_text(errors="replace")
                if re.search(r"arXiv:", op):
                    arxiv_only += 1
                else:
                    untagged += 1
                continue
            if "arxiv" in j.lower():
                arxiv_only += 1
                continue
            counts[_canon_journal(j)] += 1
        elif gb == "year":
            y = _slot_year(s)
            if y:
                counts[str(y)] += 1
            else:
                no_year += 1
        elif gb == "decade":
            y = _slot_year(s)
            if y:
                counts[f"{(y // 10) * 10}s"] += 1
            else:
                no_year += 1
        elif gb == "verdict":
            counts[_verdict_of(s) or "(none)"] += 1
        elif gb == "has_pdf":
            counts["with PDF" if _slot_pdf(s) else "without PDF"] += 1
    label = f"{topic or 'library (all topics)'}"
    n = len(slots)
    lines = [f"=== {label}: {n} slots, group_by={gb} ===", ""]
    if gb == "year" or gb == "decade":
        items = sorted(counts.items())
    else:
        items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    width = max((len(k) for k in counts), default=10)
    for k, v in items:
        bar = "#" * v
        lines.append(f"  {v:4d}  {k:<{width}}  {bar}")
    if gb == "journal":
        if arxiv_only:
            lines.append(f"  ----  arXiv-only (no journal venue identified): {arxiv_only}")
        if untagged:
            lines.append(f"  ----  no venue tag extractable:                {untagged}")
    if gb in {"year", "decade"} and no_year:
        lines.append(f"  ----  no year extractable: {no_year}")
    return "\n".join(lines)


@server.tool(
    description=(
        "List all slots that are missing a PDF, optionally filtered to a topic. "
        "Returns one path per line. Use this to drive bulk fetches."
    )
)
def library_list_missing(topic: str = "") -> str:
    missing = [s for s in _slot_paths(topic or None) if not _slot_pdf(s)]
    if not missing:
        return "(none missing)"
    return "\n".join(str(s.relative_to(LIBRARY_ROOT)) for s in missing)


# ---------------------------------------------------------------------------
# Background jobs


def _job_meta_path(jid: str) -> Path:
    return JOBS_DIR / f"{jid}.json"


def _job_log_path(jid: str) -> Path:
    return JOBS_DIR / f"{jid}.log"


def _start_job(kind: str, argv: list[str], cwd: Optional[Path] = None, env: Optional[dict] = None) -> dict:
    jid = f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    log = _job_log_path(jid)
    with open(log, "wb") as lf:
        proc = subprocess.Popen(
            argv,
            stdout=lf,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=str(cwd) if cwd else None,
            env={**os.environ, **(env or {})},
            start_new_session=True,
        )
    meta = {
        "job_id": jid,
        "kind": kind,
        "pid": proc.pid,
        "argv": argv,
        "cwd": str(cwd) if cwd else None,
        "log": str(log),
        "started": time.time(),
    }
    _job_meta_path(jid).write_text(json.dumps(meta, indent=2))
    return meta


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@server.tool(description="List background jobs known to this server, with status.")
def job_list() -> str:
    out = []
    for mp in sorted(JOBS_DIR.glob("*.json")):
        try:
            m = json.loads(mp.read_text())
        except Exception:
            continue
        running = _is_running(m["pid"])
        age = int(time.time() - m["started"])
        out.append(f"{m['job_id']}  pid={m['pid']}  age={age}s  {'RUNNING' if running else 'DONE'}  kind={m['kind']}")
    return "\n".join(out) if out else "(no jobs)"


@server.tool(description="Get status of a job by ID. Returns running/done, exit info if available, and last log line.")
def job_status(job_id: str) -> str:
    mp = _job_meta_path(job_id)
    if not mp.is_file():
        return _err(f"unknown job: {job_id}")
    m = json.loads(mp.read_text())
    running = _is_running(m["pid"])
    log = _job_log_path(job_id)
    tail_line = ""
    if log.is_file():
        try:
            tail = log.read_text(errors="replace").rstrip().splitlines()
            tail_line = tail[-1] if tail else ""
        except Exception:
            pass
    age = int(time.time() - m["started"])
    return (
        f"job_id: {m['job_id']}\nkind: {m['kind']}\npid: {m['pid']}  "
        f"{'RUNNING' if running else 'DONE'}  age: {age}s\n"
        f"log: {m['log']}\nargv: {' '.join(shlex.quote(a) for a in m['argv'])}\n"
        f"last line: {tail_line}"
    )


@server.tool(description="Return the last N lines of a job's log.")
def job_tail(job_id: str, lines: int = 50) -> str:
    log = _job_log_path(job_id)
    if not log.is_file():
        return _err(f"no log for {job_id}")
    text = log.read_text(errors="replace")
    arr = text.splitlines()
    return "\n".join(arr[-lines:])


@server.tool(description="Kill a running job by ID (SIGTERM).")
def job_kill(job_id: str) -> str:
    mp = _job_meta_path(job_id)
    if not mp.is_file():
        return _err(f"unknown job: {job_id}")
    m = json.loads(mp.read_text())
    if not _is_running(m["pid"]):
        return f"already not running: {job_id}"
    try:
        os.killpg(os.getpgid(m["pid"]), signal.SIGTERM)
    except Exception as e:
        return _err(f"kill failed: {e}")
    return f"sent SIGTERM to {job_id} (pid {m['pid']})"


# ---------------------------------------------------------------------------
# Citation checker


@server.tool(
    description=(
        "Launch the citation checker on a .tex file. Runs in the background; "
        "returns a job_id. Use job_status / job_tail to monitor. "
        "Cost-capped at cap_usd. If only='KEY1,KEY2' is given, only those bibitems are checked."
    )
)
def check_citations_run(
    tex_path: str,
    refs_dir: str = "",
    only: str = "",
    cap_usd: float = 5.0,
    report_path: str = "",
) -> str:
    tex = Path(tex_path).expanduser()
    if not tex.is_file():
        return _err(f"tex not found: {tex}")
    if not CHECK_CITATIONS_PYTHON.is_file():
        return _err(f"checker venv python not found: {CHECK_CITATIONS_PYTHON}")
    if not CHECK_CITATIONS_PY.is_file():
        return _err(f"checker script not found: {CHECK_CITATIONS_PY}")
    argv = [str(CHECK_CITATIONS_PYTHON), str(CHECK_CITATIONS_PY), str(tex), "--cap-usd", str(cap_usd)]
    if refs_dir:
        rd = Path(refs_dir).expanduser()
        if not rd.is_dir():
            return _err(f"refs_dir not a dir: {rd}")
        argv += ["--refs-dir", str(rd)]
    if only:
        argv += ["--only", only]
    if report_path:
        argv += ["--report", str(Path(report_path).expanduser())]
    meta = _start_job("check-citations", argv, cwd=tex.parent)
    return (
        f"Launched check-citations.\n"
        f"  job_id: {meta['job_id']}\n"
        f"  log: {meta['log']}\n"
        f"  cmd: {' '.join(shlex.quote(a) for a in argv)}\n"
        f"Use job_status / job_tail to monitor."
    )


# ---------------------------------------------------------------------------
# Graduated dissent


_GD_CONDITIONS = {"b1", "b2", "b3", "gd"}


@server.tool(
    description=(
        "Launch a graduated-dissent pipeline run on a single paper.txt. "
        "condition in {b1, b2, b3, gd}. Runs in the background; returns a job_id. "
        "Cost-capped at cap_usd."
    )
)
def gd_run(
    paper_path: str,
    paper_id: str,
    condition: str,
    out_dir: str = "",
    cap_usd: float = 25.0,
) -> str:
    paper = Path(paper_path).expanduser()
    if not paper.is_file():
        return _err(f"paper not found: {paper}")
    cond = condition.lower()
    if cond not in _GD_CONDITIONS:
        return _err(f"condition must be one of {sorted(_GD_CONDITIONS)}, got {condition}")
    if not GD_PIPELINE_PY.is_file():
        return _err(f"gd pipeline not found: {GD_PIPELINE_PY}")
    if not GD_PYTHON.is_file():
        return _err(f"gd venv python not found: {GD_PYTHON}")
    od = Path(out_dir).expanduser() if out_dir else GD_REPO / "data" / "mcp_runs" / paper_id
    od.mkdir(parents=True, exist_ok=True)
    argv = [
        str(GD_PYTHON), str(GD_PIPELINE_PY),
        "--paper", str(paper),
        "--paper-id", paper_id,
        "--condition", cond,
        "--out-dir", str(od),
        "--cap", str(cap_usd),
    ]
    meta = _start_job(f"gd-{cond}", argv, cwd=GD_REPO)
    return (
        f"Launched graduated-dissent ({cond}).\n"
        f"  job_id: {meta['job_id']}\n"
        f"  out_dir: {od}\n"
        f"  log: {meta['log']}\n"
        f"  cmd: {' '.join(shlex.quote(a) for a in argv)}\n"
        f"Use job_status / job_tail to monitor."
    )


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    server.run()
