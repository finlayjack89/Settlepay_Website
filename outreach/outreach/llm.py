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
    def complete(self, prompt: str, *, purpose: str, max_words: Optional[int] = None) -> LLMResult:
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

    def complete(self, prompt, *, purpose, max_words=None) -> LLMResult:
        if self._responder is None:
            raise InlineResponseRequired(purpose, prompt, max_words)
        return LLMResult(self._responder(prompt), self.name, {"purpose": purpose})


class ApiProvider(LLMProvider):
    name = "api"

    def __init__(self, model: Optional[str] = None, client=None):
        # NOTE: confirm the model id against ~/.claude/LLM_MODELS.md before going live.
        self.model = model or "claude-sonnet-4-6"
        self._client = client

    def complete(self, prompt, *, purpose, max_words=None) -> LLMResult:
        client = self._client or self._default_client()
        msg = client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        return LLMResult(text, self.name, {"purpose": purpose, "model": self.model})

    @staticmethod
    def _default_client():
        import anthropic  # lazy; not a build dependency

        return anthropic.Anthropic()


def get_provider(name: Optional[str] = None, **kwargs) -> LLMProvider:
    name = name or config.LLM_PROVIDER
    if name == "inline":
        return InlineProvider(**kwargs)
    if name == "api":
        return ApiProvider(**kwargs)
    raise ValueError(f"unknown LLM provider: {name!r}")
