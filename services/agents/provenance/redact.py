"""Strip card numbers, CVVs, and credentials before anything leaves the process.

Over-redaction is fine; a leaked PAN is not. Everything that goes into a trace
event, a log line, or CLI output passes through redact() first.
"""

import re
from typing import Any

REDACTED = "[REDACTED]"

# Keys whose values are secret no matter what they look like.
_SECRET_KEYS = {
  "cvv",
  "cvv2",
  "cvc",
  "cvc2",
  "security_code",
  "authorization",
  "api_key",
  "apikey",
  "token",
  "access_token",
  "secret",
  "password",
}
# Keys that hold a card number. The value keeps its last four digits so the UI
# can still say which card was used.
_PAN_KEYS = {"pan", "card_number", "cardnumber", "number"}

# 13-19 digits, optionally grouped by spaces or dashes: every card brand's PAN
# length. This also catches some non-card numbers (like epoch milliseconds);
# that's the safe direction to be wrong in.
_PAN_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_CVV_RE = re.compile(
  r"(?i)\b(cvv2?|cvc2?|security[ _-]?code)\b([\"']?\s*[:=]?\s*[\"']?)(\d{3,4})(?!\d)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")


def _mask_pan(match: re.Match[str]) -> str:
  digits = re.sub(r"\D", "", match.group(0))
  return f"[CARD ****{digits[-4:]}]"


def redact_text(text: str) -> str:
  text = _BEARER_RE.sub(f"Bearer {REDACTED}", text)
  text = _CVV_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
  return _PAN_RE.sub(_mask_pan, text)


def _redact_pan_value(value: Any) -> Any:
  digits = re.sub(r"\D", "", str(value))
  if 12 <= len(digits) <= 19:
    return f"[CARD ****{digits[-4:]}]"
  return redact(value)


def redact(value: Any) -> Any:
  """Return a deep copy of value with secrets masked."""
  if isinstance(value, dict):
    out = {}
    for key, item in value.items():
      norm = str(key).lower().replace("-", "_")
      if norm in _SECRET_KEYS:
        out[key] = REDACTED
      elif norm in _PAN_KEYS:
        out[key] = _redact_pan_value(item)
      else:
        out[key] = redact(item)
    return out
  if isinstance(value, (list, tuple)):
    return [redact(item) for item in value]
  if isinstance(value, str):
    return redact_text(value)
  return value
