#!/usr/bin/env python3
"""Interactive API-key wizard.

Stores keys at ~/.keys/<service> with mode 0600 — the convention shared by
the citation checker, graduated dissent harness, and the papers MCP server.

Run:

    python3 setup_keys.py

Re-runs are safe: existing keys are kept unless you choose to overwrite.

You only need:
  * one of {anthropic, openai, deepseek} to run the citation checker
    (it queries three models in parallel — more is better, but one suffices
    if you adjust MODELS_TO_USE in check_citations.py).
  * the same plus the graduated_dissent_bench requirements (anthropic,
    openai, deepseek by default) to run graduated dissent.
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

SERVICES = [
    ("anthropic",
     "Anthropic / Claude API key  (starts with 'sk-ant-')",
     "Used by: citation checker (claude-opus model), graduated dissent (arbiter)",
     "https://console.anthropic.com/settings/keys"),
    ("openai",
     "OpenAI API key  (starts with 'sk-')",
     "Used by: citation checker (gpt-5.4 model), graduated dissent (prover A, baselines)",
     "https://platform.openai.com/api-keys"),
    ("deepseek",
     "DeepSeek API key  (starts with 'sk-')",
     "Used by: citation checker (deepseek model), graduated dissent (prover B, judge)",
     "https://platform.deepseek.com/api_keys"),
    ("google",
     "Google AI / Gemini API key",
     "Used by: out-of-family audits in graduated dissent (optional)",
     "https://aistudio.google.com/apikey"),
    ("groq",
     "Groq API key",
     "Used by: optional fast inference fallback",
     "https://console.groq.com/keys"),
    ("mistral",
     "Mistral API key",
     "Used by: out-of-family audits in graduated dissent (optional)",
     "https://console.mistral.ai/api-keys/"),
    ("xai",
     "xAI / Grok API key",
     "Used by: out-of-family audits in graduated dissent (optional)",
     "https://console.x.ai/"),
]

KEYS_DIR = Path(os.environ.get("PAPERS_KEYS_DIR") or "~/.keys").expanduser()


def yes(prompt: str, default: bool = True) -> bool:
    d = "[Y/n]" if default else "[y/N]"
    ans = input(f"{prompt} {d} ").strip().lower()
    if not ans:
        return default
    return ans.startswith("y")


def store(service: str, key: str) -> None:
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    p = KEYS_DIR / service
    p.write_text(key.strip() + "\n")
    p.chmod(0o600)


def existing_keys() -> dict[str, int]:
    out: dict[str, int] = {}
    if not KEYS_DIR.is_dir():
        return out
    for p in KEYS_DIR.iterdir():
        if p.is_file() and not p.name.startswith("."):
            try:
                out[p.name] = len(p.read_text().strip())
            except Exception:
                pass
    return out


def main() -> int:
    print("=" * 70)
    print("  papers-toolkit — API key wizard")
    print("=" * 70)
    print()
    print(f"Keys are stored as files under {KEYS_DIR} (mode 0600).")
    print("They never leave your machine.  Anthropic / OpenAI / DeepSeek are")
    print("the only services that paid model calls actually go to, per the")
    print("descriptions below.")
    print()

    have = existing_keys()
    if have:
        print(f"Found {len(have)} existing key(s) under {KEYS_DIR}:")
        for k, n in sorted(have.items()):
            print(f"  - {k}  ({n} chars)")
        print()

    for svc, desc, used_by, url in SERVICES:
        cur = have.get(svc)
        if cur:
            print(f"--- {svc} ---  (already configured, {cur} chars)")
            print(f"    {used_by}")
            if not yes("    Overwrite?", default=False):
                print()
                continue
        else:
            print(f"--- {svc} ---")
            print(f"    {desc}")
            print(f"    {used_by}")
            print(f"    Get one at: {url}")
            if not yes("    Configure now?", default=svc in {"anthropic", "openai", "deepseek"}):
                print()
                continue
        key = getpass.getpass(f"    Paste {svc} key (hidden input): ").strip()
        if not key:
            print("    (empty input — skipped)")
            print()
            continue
        store(svc, key)
        print(f"    Saved to {KEYS_DIR / svc}")
        print()

    final = existing_keys()
    print()
    print("=" * 70)
    print(f"  Stored keys: {len(final)}")
    for k, n in sorted(final.items()):
        print(f"    - {k}  ({n} chars)")
    print("=" * 70)
    print()
    print("Done.  To verify, run:")
    print()
    print("    cd", Path(__file__).resolve().parent)
    print("    source .venv/bin/activate")
    print("    python3 check-citations/check_citations.py examples/tiny_paper.tex")
    print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n(interrupted)")
        sys.exit(130)
