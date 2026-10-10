"""The guardian: investigates a purchase attempt and recommends block or review.

It is advisory only. Deterministic checks in the api's checkout verifier and
the payment rail decide whether money moves; nothing the guardian returns can
issue a grant or override a failed check (AGENTS.md invariant 4).
"""

from datetime import UTC, datetime
from typing import Any

from guardian.checks import run_hard_checks

# TODO: switch to the agreed guardian findings model in leash_shared.models.
Verdict = dict[str, Any]


def evaluate(
  mandate: dict[str, Any],
  cart: dict[str, Any],
  provenance: list[dict[str, Any]],
  now: datetime | None = None,
) -> Verdict:
  """Investigate one purchase attempt.

  v1 runs deterministic checks only. Any failure recommends "block". With no
  findings it says "no_findings", which is not an approval: the api's own
  verification still has to pass.
  """
  checks = run_hard_checks(mandate, cart, now or datetime.now(UTC))
  failed = [c for c in checks if not c["passed"]]

  return {
    "recommendation": "block" if failed else "no_findings",
    "reasons": [c["detail"] for c in failed] or ["No findings from deterministic checks."],
    "checks": checks,
    "suspicious_sources": [],
    "model": None,
  }
