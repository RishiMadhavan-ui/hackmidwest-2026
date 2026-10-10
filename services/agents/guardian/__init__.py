"""The guardian: investigates a purchase attempt and recommends block or review.

It is advisory only. Deterministic checks in the api's checkout verifier and
the payment rail decide whether money moves; nothing the guardian returns can
issue a grant or override a failed check (AGENTS.md invariant 4).

Deterministic findings come first. The model then explains and can only make
the recommendation stricter. If the model fails, the recommendation is never
more permissive than "review".
"""

from datetime import UTC, datetime
from typing import Any

from guardian.checks import run_checks, suspicious_sources
from guardian.investigator import ModelRunner, build_prompt, investigate, run_strands
from leash_shared.llm import model_id

# TODO: switch to the agreed guardian findings model in leash_shared.models.
Findings = dict[str, Any]

_STRICTNESS = {"no_findings": 0, "review": 1, "block": 2}


def _stricter(a: str, b: str) -> str:
  return a if _STRICTNESS[a] >= _STRICTNESS[b] else b


def evaluate(
  mandate: dict[str, Any],
  checkout: dict[str, Any] | None = None,
  proposal: dict[str, Any] | None = None,
  provenance: list[dict[str, Any]] | None = None,
  trace: list[dict[str, Any]] | None = None,
  now: datetime | None = None,
  model_runner: ModelRunner | None = run_strands,
) -> Findings:
  """Investigate one purchase attempt. Pass model_runner=None to skip the model."""
  provenance = provenance or []
  trace = trace or []
  checks = run_checks(mandate, checkout, proposal, provenance, now or datetime.now(UTC))
  failed = [c for c in checks if not c["passed"]]
  sources = suspicious_sources(provenance)

  recommendation = "no_findings"
  for check in failed:
    recommendation = _stricter(recommendation, check["severity"])
  reasons = [c["detail"] for c in failed]

  model_meta: dict[str, Any] = {"status": "skipped"}
  explanation = None
  if model_runner is not None:
    prompt = build_prompt(mandate, checkout, proposal, trace, sources, checks)
    found, model_meta = investigate(prompt, runner=model_runner)
    if found is not None:
      # The model can raise the bar, never lower it.
      recommendation = _stricter(recommendation, found.recommendation)
      explanation = found.explanation
      if found.injection_suspected and not sources:
        reasons.append("The model suspects manipulation, but no hidden page text was recorded.")
      # Only cite sources we actually recorded; the model can't invent evidence.
      known = {s["url"] for s in sources}
      cited = [u for u in found.suspicious_source_urls if u in known]
      model_meta["cited_sources"] = cited
      model_meta["intent_match"] = found.intent_match
      model_meta["violated_constraints"] = found.violated_constraints
    elif recommendation == "no_findings":
      # No model and no deterministic findings: ask a human rather than stay quiet.
      recommendation = "review"
      reasons.append("Investigation model unavailable; a person should review this attempt.")
    model_meta.update({"provider": "akamai-inference", "model_id": model_id()})

  if not reasons:
    reasons = ["No findings."]

  return {
    "recommendation": recommendation,
    "authority": "advisory",
    "reasons": reasons,
    "explanation": explanation,
    "checks": checks,
    "suspicious_sources": sources,
    "checkout_id": (checkout or {}).get("checkout_id"),
    "model": model_meta,
  }
