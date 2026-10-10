"""The guardian: decides whether a cart may be paid under a mandate."""

from datetime import UTC, datetime
from typing import Any

from guardian.checks import run_hard_checks

# TODO: switch to leash_shared.models.Verdict once models.py lands.
Verdict = dict[str, Any]


def evaluate(
  mandate: dict[str, Any],
  cart: dict[str, Any],
  provenance: list[dict[str, Any]],
  now: datetime | None = None,
) -> Verdict:
  """Run the guardian on one cart.

  v1 is deterministic only: any failed hard check denies, and a clean cart is
  approved. Phase 3 adds a model pass that can only make an approve stricter.
  """
  checks = run_hard_checks(mandate, cart, now or datetime.now(UTC))
  failed = [c for c in checks if not c["passed"]]

  if failed:
    return {
      "decision": "deny",
      "reasons": [c["detail"] for c in failed],
      "checks": checks,
      "suspicious_sources": [],
      "model": None,
    }

  return {
    "decision": "approve",
    "reasons": ["Every hard check passed."],
    "checks": checks,
    "suspicious_sources": [],
    "model": None,
  }
