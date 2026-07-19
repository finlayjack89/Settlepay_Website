"""Swappable LLMProvider interface (built now; default `inline`).

- inline (default): under /loop on Claude Max, the loop AGENT performs the
  reasoning. The provider hands over a structured prompt and records the
  agent-supplied output. With no responder injected it RAISES, so the loop knows
  it must supply the text — it never silently fabricates.
- api: Anthropic API implementation for the unattended cron/dashboard runtime.
  Built and callable now, but not exercised (no spend) during the build.
"""
from __future__ import annotations
import abc
from dataclasses import dataclass
from typing import Callable, Optional

from . import config


@dataclass
class LLMResult:
    text: str
    provider: str
    meta: Optional[dict] = None


class LLMProvider(abc.ABC):
    name = "base"

    @abc.abstractmethod
    def complete(self, prompt: str, *, purpose: str, max_words: Optional[int] = None,
                 schema: Optional[dict] = None) -> LLMResult:
        """`schema` (a JSON Schema dict) requests structured JSON output — honoured
        by providers that support it; free-text providers ignore it."""
        ...


class InlineResponseRequired(Exception):
    """Raised by InlineProvider when no responder is set: the loop agent itself
    must produce the output for this prompt (enrichment signal / draft)."""

    def __init__(self, purpose: str, prompt: str, max_words: Optional[int]):
        self.purpose, self.prompt, self.max_words = purpose, prompt, max_words
        super().__init__(f"inline provider needs the loop agent to supply '{purpose}' output")


class InlineProvider(LLMProvider):
    name = "inline"

    def __init__(self, responder: Optional[Callable[[str], str]] = None):
        self._responder = responder

    def complete(self, prompt, *, purpose, max_words=None, schema=None) -> LLMResult:
        if self._responder is None:
            raise InlineResponseRequired(purpose, prompt, max_words)
        return LLMResult(self._responder(prompt), self.name, {"purpose": purpose})


class LLMUnavailable(Exception):
    """The api provider cannot serve this call (no key, spend cap hit, or the
    provider errored after retries). Callers degrade gracefully — the pipeline
    must never hard-block on the LLM."""


class ApiProvider(LLMProvider):
    name = "api"

    def __init__(self, model: Optional[str] = None, client=None):
        # model id verified against ~/.claude/LLM_MODELS.md — override via ANTHROPIC_MODEL.
        self.model = model or config.ANTHROPIC_MODEL
        self._client = client

    def complete(self, prompt, *, purpose, max_words=None, schema=None) -> LLMResult:
        from . import spend  # local import: spend is DB-touching, llm stays importable without it

        if self._client is None and not config.ANTHROPIC_API_KEY:
            raise LLMUnavailable("ANTHROPIC_API_KEY not configured")
        try:
            spend.ensure_under_cap()
        except spend.SpendCapExceeded as e:
            raise LLMUnavailable(str(e)) from e
        client = self._client or self._default_client()
        try:
            msg = client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:  # SDK retries (max_retries=3) already exhausted here
            raise LLMUnavailable(f"anthropic call failed: {e}") from e
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        usage = getattr(msg, "usage", None)
        units_in = getattr(usage, "input_tokens", 0) or 0
        units_out = getattr(usage, "output_tokens", 0) or 0
        try:
            spend.record("anthropic", purpose=purpose, model=self.model,
                         units_in=units_in, units_out=units_out,
                         cost_gbp=spend.anthropic_cost_gbp(units_in, units_out))
        except Exception:
            pass  # metering must never fail the call that already succeeded
        return LLMResult(text, self.name,
                         {"purpose": purpose, "model": self.model,
                          "units_in": units_in, "units_out": units_out})

    def _default_client(self):
        import anthropic  # lazy; not needed for inline-only runs

        return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY,
                                   timeout=60, max_retries=3)


class GeminiProvider(LLMProvider):
    """Gemini via Vertex AI (bills the GCP credit; auth via ADC / runtime SA, no
    key). Thinking is DISABLED per call (Gemini 3 defaults it ON, billed at the
    output rate — the cost trap). Honours `schema` for structured JSON output.
    Same LLMUnavailable degrade contract as ApiProvider."""
    name = "gemini"

    def __init__(self, model: Optional[str] = None, client=None):
        # verified live on Vertex 2026-07-19; do not "correct" from memory.
        self.model = model or config.GEMINI_MODEL
        self._client = client

    def complete(self, prompt, *, purpose, max_words=None, schema=None) -> LLMResult:
        from . import spend
        from google.genai import types

        try:
            spend.ensure_under_cap()
        except spend.SpendCapExceeded as e:
            raise LLMUnavailable(str(e)) from e
        client = self._client or self._default_client()
        cfg = dict(thinking_config=types.ThinkingConfig(thinking_budget=0))
        if schema is not None:
            cfg["response_mime_type"] = "application/json"
            cfg["response_schema"] = schema
        try:
            r = client.models.generate_content(
                model=self.model, contents=prompt,
                config=types.GenerateContentConfig(**cfg))
        except Exception as e:
            raise LLMUnavailable(f"gemini call failed: {e}") from e
        try:
            text = (r.text or "").strip()
        except Exception:  # blocked / multi-part response has no simple .text
            text = ""
        u = getattr(r, "usage_metadata", None)
        units_in = getattr(u, "prompt_token_count", 0) or 0
        # thinking is billed at the output rate, so fold it into units_out
        units_out = (getattr(u, "candidates_token_count", 0) or 0) + \
                    (getattr(u, "thoughts_token_count", 0) or 0)
        try:
            spend.record("gemini", purpose=purpose, model=self.model,
                         units_in=units_in, units_out=units_out,
                         cost_gbp=spend.gemini_cost_gbp(self.model, units_in, units_out))
        except Exception:
            pass  # metering must never fail the call that already succeeded
        return LLMResult(text, self.name,
                         {"purpose": purpose, "model": self.model,
                          "units_in": units_in, "units_out": units_out})

    def _default_client(self):
        from google import genai  # lazy; only needed when gemini is the provider

        if not config.GEMINI_PROJECT:
            raise LLMUnavailable("GEMINI_PROJECT not configured")
        try:
            return genai.Client(vertexai=True, project=config.GEMINI_PROJECT,
                                location=config.GEMINI_LOCATION)
        except Exception as e:
            raise LLMUnavailable(f"gemini client init failed (ADC/Vertex): {e}") from e


def get_provider(name: Optional[str] = None, **kwargs) -> LLMProvider:
    name = name or config.LLM_PROVIDER
    if name == "inline":
        return InlineProvider(**kwargs)
    if name == "api":
        return ApiProvider(**kwargs)
    if name == "gemini":
        return GeminiProvider(**kwargs)
    raise ValueError(f"unknown LLM provider: {name!r}")


def draft_provider(**inline_kwargs) -> LLMProvider:
    """The provider for DRAFTING / FOLLOW-UP, per config.LLM_PROVIDER. gemini uses
    the workhorse GEMINI_MODEL (not the fast signal model); api uses Anthropic;
    anything else is the inline provisional fallback. One place, so both stages and
    the bench agree on how the provider is chosen."""
    if config.LLM_PROVIDER == "gemini":
        return get_provider("gemini", model=config.GEMINI_MODEL)
    if config.LLM_PROVIDER == "api":
        return get_provider("api")
    return get_provider("inline", **inline_kwargs)
