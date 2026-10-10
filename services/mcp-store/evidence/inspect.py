"""Turn a fetched page into a provenance record: hash, hidden text, red flags."""

import hashlib
from typing import Any

from evidence.html_text import extract
from evidence.redact import redact_text

# Phrases that read like instructions aimed at an AI agent rather than product
# copy for a person. Matched case-insensitively.
SUSPICIOUS_PHRASES = [
  "ignore previous",
  "ignore all previous",
  "ignore your instructions",
  "disregard",
  "you must",
  "required step",
  "ai assistant",
  "ai agent",
  "shopping assistant",
  "language model",
  "the user has already agreed",
  "user has authorized",
  "do not mention",
  "do not tell",
  "instead of",
  "system:",
  "gift card",
]

EXCERPT_CHARS = 500


def _phrases_in(text: str) -> list[str]:
  lowered = text.lower()
  return [p for p in SUSPICIOUS_PHRASES if p in lowered]


def inspect_page(html: str) -> dict[str, Any]:
  """Inspect raw HTML. Pure: no I/O, so it's safe to run on any content."""
  page = extract(html)
  hidden_texts = [text for text, _ in page.hidden] + page.comments
  hidden_reasons = sorted(
    {why for _, why in page.hidden} | ({"html comment"} if page.comments else set())
  )

  # Phrases in hidden text are the strong signal. Phrases in visible text are
  # weaker (real product copy says "you must" too), so they're kept separate.
  hidden_phrases = sorted({p for t in hidden_texts for p in _phrases_in(t)})
  visible_phrases = sorted(set(_phrases_in(" ".join(page.visible + page.attributes))))

  # Prefer the hidden segment that tripped the most phrases as the excerpt.
  ranked = sorted(hidden_texts, key=lambda t: len(_phrases_in(t)), reverse=True)
  excerpt = ranked[0] if ranked else ""

  return {
    "sha256": hashlib.sha256(html.encode()).hexdigest(),
    "hidden_text_detected": bool(hidden_texts),
    "hidden_reasons": hidden_reasons,
    "suspicious_phrases": sorted(set(hidden_phrases) | set(visible_phrases)),
    "hidden_suspicious_phrases": hidden_phrases,
    "excerpt": redact_text(excerpt[:EXCERPT_CHARS]),
  }
