#!/usr/bin/env python3
"""
Shared API client for the graduated dissent harness.

- Auto-loads API keys from ~/.keys/{openai,deepseek,anthropic} (matching
  gui/server.py) and into env vars so existing scripts that read
  OPENAI_API_KEY etc. keep working.
- Single entry point `call_model(name, prompt)` that dispatches to the
  right provider based on the model registry.
- Cost tracking via a process-wide CostTracker singleton, with a hard
  ceiling that aborts further calls before they happen.
- JSON-from-LLM parser robust to markdown fences and trailing commentary.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KEYS_DIR = Path.home() / ".keys"

MODELS: dict[str, dict[str, str]] = {
    "gpt-5.4": {"provider": "openai", "model_id": "gpt-5.4"},
    "deepseek": {"provider": "deepseek", "model_id": "deepseek-chat"},
    "opus": {"provider": "anthropic", "model_id": "claude-opus-4-6"},
    "sonnet": {"provider": "anthropic", "model_id": "claude-sonnet-4-6"},
    "gemini": {"provider": "gemini", "model_id": "gemini-2.5-pro"},
    "grok": {"provider": "xai", "model_id": "grok-4-fast-reasoning"},
    "mistral": {"provider": "mistral", "model_id": "mistral-large-latest"},
}

# Conservative prices in USD per million tokens (input, output).
# Sourced from public pricing pages as of early 2026; refine if needed.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-5.4":  (2.50, 10.00),
    "deepseek": (0.27, 1.10),
    "opus":     (15.00, 75.00),
    "sonnet":   (3.00, 15.00),
    "gemini":   (1.25, 10.00),
    "grok":     (0.20, 0.50),
    "mistral":  (2.00, 6.00),
}


# ── Key loading ───────────────────────────────────────────────────────

_KEYS_LOADED = False


def load_keys() -> dict[str, bool]:
    """Read keys from ~/.keys/{provider} into the env. Idempotent."""
    global _KEYS_LOADED
    status = {}
    for provider, env_var in [
        ("openai", "OPENAI_API_KEY"),
        ("deepseek", "DEEPSEEK_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("google", "GOOGLE_API_KEY"),
        ("xai", "XAI_API_KEY"),
        ("mistral", "MISTRAL_API_KEY"),
    ]:
        if os.environ.get(env_var):
            status[provider] = True
            continue
        keyfile = KEYS_DIR / provider
        if keyfile.is_file():
            key = keyfile.read_text().strip()
            if key:
                os.environ[env_var] = key
                status[provider] = True
            else:
                status[provider] = False
        else:
            status[provider] = False
    _KEYS_LOADED = True
    return status


# ── Cost tracking ─────────────────────────────────────────────────────

@dataclass
class CallRecord:
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_s: float
    label: str = ""


@dataclass
class CostTracker:
    cap_usd: float = 25.00
    calls: list[CallRecord] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def total(self) -> float:
        with self._lock:
            return sum(c.cost_usd for c in self.calls)

    def check(self, projected_cost: float = 0.0) -> None:
        """Raise if next call would exceed cap. Thread-safe."""
        with self._lock:
            running = sum(c.cost_usd for c in self.calls)
            if running + projected_cost > self.cap_usd:
                raise BudgetExceeded(
                    f"Cost cap ${self.cap_usd:.2f} would be exceeded "
                    f"(spent ${running:.4f}, projected +${projected_cost:.4f})"
                )

    def record(self, rec: CallRecord) -> None:
        with self._lock:
            self.calls.append(rec)

    def summary(self) -> dict[str, Any]:
        by_model: dict[str, dict[str, Any]] = {}
        for c in self.calls:
            m = by_model.setdefault(c.model, {
                "n_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            })
            m["n_calls"] += 1
            m["input_tokens"] += c.input_tokens
            m["output_tokens"] += c.output_tokens
            m["cost_usd"] += c.cost_usd
        return {
            "total_calls": len(self.calls),
            "total_cost_usd": round(self.total, 4),
            "cap_usd": self.cap_usd,
            "by_model": by_model,
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({
                "summary": self.summary(),
                "calls": [vars(c) for c in self.calls],
            }, indent=2),
            encoding="utf-8",
        )


class BudgetExceeded(RuntimeError):
    pass


_TRACKER: CostTracker | None = None


def get_tracker() -> CostTracker:
    global _TRACKER
    if _TRACKER is None:
        _TRACKER = CostTracker()
    return _TRACKER


def configure_tracker(cap_usd: float) -> CostTracker:
    global _TRACKER
    _TRACKER = CostTracker(cap_usd=cap_usd)
    return _TRACKER


def compute_cost(model: str, in_tok: int, out_tok: int) -> float:
    in_p, out_p = PRICES.get(model, (0.0, 0.0))
    return (in_tok * in_p + out_tok * out_p) / 1_000_000


# ── Provider callers ──────────────────────────────────────────────────

def _call_openai_compatible(model_id: str, prompt: str, *,
                            base_url: str | None,
                            api_key_env: str,
                            uses_max_completion_tokens: bool,
                            timeout_s: float = 180.0,
                            temperature: float | None = None) -> tuple[str, int, int]:
    import openai
    client_kwargs: dict[str, Any] = {
        "api_key": os.environ.get(api_key_env, ""),
        "timeout": timeout_s,
        "max_retries": 2,
    }
    if base_url:
        client_kwargs["base_url"] = base_url
    client = openai.OpenAI(**client_kwargs)
    kwargs: dict[str, Any] = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
    }
    if uses_max_completion_tokens:
        kwargs["max_completion_tokens"] = 4096
    else:
        kwargs["max_tokens"] = 4096
    if temperature is not None:
        kwargs["temperature"] = temperature
    response = client.chat.completions.create(**kwargs)
    text = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    in_tok = getattr(usage, "prompt_tokens", 0) if usage else 0
    out_tok = getattr(usage, "completion_tokens", 0) if usage else 0
    return text, in_tok, out_tok


def _call_anthropic(model_id: str, prompt: str, timeout_s: float = 240.0,
                    temperature: float | None = None) -> tuple[str, int, int]:
    import anthropic
    client = anthropic.Anthropic(timeout=timeout_s, max_retries=2)
    kwargs: dict[str, Any] = {
        "model": model_id,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    message = client.messages.create(**kwargs)
    text_parts = []
    for block in message.content:
        t = getattr(block, "text", None)
        if t:
            text_parts.append(t)
    text = "".join(text_parts)
    usage = getattr(message, "usage", None)
    in_tok = getattr(usage, "input_tokens", 0) if usage else 0
    out_tok = getattr(usage, "output_tokens", 0) if usage else 0
    return text, in_tok, out_tok


def call_model(name: str, prompt: str, *, label: str = "",
               temperature: float | None = None) -> str:
    """Call a model by registered name, tracking cost and enforcing the cap.

    temperature=None uses provider defaults (1.0). Pass temperature=0 for
    deterministic outputs (e.g. for the LLM-as-judge in scoring).
    """
    if not _KEYS_LOADED:
        load_keys()

    spec = MODELS[name]
    provider = spec["provider"]
    model_id = spec["model_id"]

    # Cheap pre-flight: estimate cost from prompt length only (output unknown).
    # Use 4 chars/token as a rough approximation for the input side.
    est_in_tok = max(1, len(prompt) // 4)
    est_out_tok = 4096  # worst-case max
    est_cost = compute_cost(name, est_in_tok, est_out_tok)
    get_tracker().check(projected_cost=est_cost)

    t0 = time.time()
    if provider == "anthropic":
        text, in_tok, out_tok = _call_anthropic(model_id, prompt, temperature=temperature)
    elif provider == "openai":
        text, in_tok, out_tok = _call_openai_compatible(
            model_id, prompt, base_url=None,
            api_key_env="OPENAI_API_KEY",
            uses_max_completion_tokens=True,  # GPT-5.4 needs max_completion_tokens
            temperature=temperature,
        )
    elif provider == "deepseek":
        text, in_tok, out_tok = _call_openai_compatible(
            model_id, prompt, base_url="https://api.deepseek.com",
            api_key_env="DEEPSEEK_API_KEY",
            uses_max_completion_tokens=False,
            temperature=temperature,
        )
    elif provider == "gemini":
        text, in_tok, out_tok = _call_openai_compatible(
            model_id, prompt,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key_env="GOOGLE_API_KEY",
            uses_max_completion_tokens=False,
            temperature=temperature,
        )
    elif provider == "xai":
        text, in_tok, out_tok = _call_openai_compatible(
            model_id, prompt, base_url="https://api.x.ai/v1",
            api_key_env="XAI_API_KEY",
            uses_max_completion_tokens=False,
            temperature=temperature,
        )
    elif provider == "mistral":
        text, in_tok, out_tok = _call_openai_compatible(
            model_id, prompt, base_url="https://api.mistral.ai/v1",
            api_key_env="MISTRAL_API_KEY",
            uses_max_completion_tokens=False,
            temperature=temperature,
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")

    duration = time.time() - t0
    cost = compute_cost(name, in_tok, out_tok)
    get_tracker().record(CallRecord(
        model=name, provider=provider,
        input_tokens=in_tok, output_tokens=out_tok,
        cost_usd=cost, duration_s=round(duration, 2), label=label,
    ))
    return text


# ── JSON parsing ──────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n```\s*$", re.DOTALL)


def parse_json(raw: str) -> dict[str, Any]:
    """Parse JSON from LLM output. Handles ```json fences, stray prose, and
    arbiter outputs truncated mid-string (when max_tokens cut off the response)."""
    if raw is None:
        return {"raw": "", "parse_error": True}
    text = raw.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip outer fence if present even without the closing ``` line.
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    # Try the largest balanced {...} substring.
    start = text.find("{")
    if start < 0:
        return {"raw": raw, "parse_error": True}
    end = text.rfind("}")
    if end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    # Truncated-output recovery: walk forward from the first '{' tracking brace
    # depth and string state, and prune the JSON to the last complete element.
    return _recover_truncated(text[start:], raw)


def _recover_truncated(text: str, original_raw: str) -> dict[str, Any]:
    """Best-effort recovery from JSON output truncated mid-token.

    Walks the text tracking brace/bracket depth and string state. Records
    the position+depth-snapshot every time we just finished a complete
    element at depth >= 1 (at a top-level comma OR an array-element comma).
    On failure, tries pruning at the latest such snapshot, then synthesizing
    the closing tokens to balance braces and brackets.
    """
    depth = 0
    stack: list[str] = []  # '{' or '['
    in_string = False
    escape = False
    last_was_value_close = False
    # snapshot = (cut_index, stack_at_that_point_as_list)
    last_snapshot: tuple[int, list[str]] | None = None

    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
                last_was_value_close = True
            continue
        if ch == '"':
            in_string = True
            last_was_value_close = False
            continue
        if ch in "{[":
            stack.append(ch)
            depth += 1
            last_was_value_close = False
        elif ch in "}]":
            if stack:
                stack.pop()
            depth -= 1
            last_was_value_close = True
        elif ch == ",":
            if depth >= 1 and last_was_value_close:
                last_snapshot = (i, list(stack))
            last_was_value_close = False
        else:
            if not ch.isspace():
                last_was_value_close = False

    if last_snapshot is None:
        return {"raw": original_raw, "parse_error": True, "truncated": True}

    cut, stack_at_cut = last_snapshot
    # Drop the comma and any trailing content, then close out balanced.
    closer = "".join("}" if c == "{" else "]" for c in reversed(stack_at_cut))
    candidate = text[:cut] + closer
    try:
        result = json.loads(candidate)
        if isinstance(result, dict):
            result["truncated"] = True
        return result
    except json.JSONDecodeError:
        return {"raw": original_raw, "parse_error": True, "truncated": True}


# ── Misc ──────────────────────────────────────────────────────────────

def severity_count(findings: list[dict]) -> dict[str, int]:
    counts = {"RETRACTION-WORTHY": 0, "MAJOR-REVISION": 0, "MINOR": 0}
    if not isinstance(findings, list):
        return counts
    for f in findings:
        if isinstance(f, dict):
            s = f.get("severity", "MINOR")
            if s in counts:
                counts[s] += 1
    return counts


if __name__ == "__main__":
    # Diagnostic: print key status and prices.
    status = load_keys()
    print("Key status:")
    for provider, ok in status.items():
        print(f"  {provider}: {'loaded' if ok else 'MISSING'}")
    print("\nPricing (USD per 1M tokens, input/output):")
    for m, (i, o) in PRICES.items():
        print(f"  {m}: input ${i}/M, output ${o}/M")
