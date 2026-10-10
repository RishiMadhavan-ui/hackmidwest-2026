"""Guardian's Strands plumbing with a scripted fixture model (no live inference)."""

import json

import pytest
from scripted_model import ScriptedModel

import guardian.investigator as investigator_mod
from guardian.investigator import ModelFindings, run_strands
from leash_shared import llm

FINDINGS = {
  "intent_match": "mismatch",
  "injection_suspected": True,
  "recommendation": "block",
  "explanation": "The user asked for a charger; the checkout is a monthly subscription.",
  "violated_constraints": ["No subscriptions."],
  "suspicious_source_urls": ["http://store.test/products/chg-65w"],
}


def use_models(monkeypatch, *models):
  queue = list(models)
  monkeypatch.setattr(llm, "make_model", lambda role: queue.pop(0))


def test_structured_output_through_strands(monkeypatch):
  use_models(monkeypatch, ScriptedModel([[("ModelFindings", FINDINGS)], "done"]))
  found = run_strands("prompt")
  assert found == ModelFindings(**FINDINGS)


def test_plain_json_fallback_when_structured_output_fails(monkeypatch):
  # First agent never calls the structured-output tool; the retry answers with
  # JSON in plain text, validated by the same Pydantic model.
  stubborn = ScriptedModel(["I refuse to use tools."] * 10)
  plain = ScriptedModel([f"Here you go: {json.dumps(FINDINGS)}"])
  use_models(monkeypatch, stubborn, plain)
  assert run_strands("prompt").recommendation == "block"


def test_fallback_with_garbage_is_invalid_output(monkeypatch):
  use_models(
    monkeypatch, ScriptedModel(["no tools"] * 10), ScriptedModel(['{"recommendation": "approve"}'])
  )
  found, meta = investigator_mod.investigate("prompt", runner=run_strands)
  assert found is None
  assert meta["status"] == "invalid_output"


def test_no_inference_config_is_unavailable(monkeypatch):
  monkeypatch.delenv("INFERENCE_API_KEY", raising=False)
  monkeypatch.delenv("INFERENCE_BASE_URL", raising=False)
  found, meta = investigator_mod.investigate("prompt", runner=run_strands)
  assert found is None
  assert meta == {"status": "unavailable", "error": "RuntimeError"}


@pytest.fixture(autouse=True)
def _fast_timeout(monkeypatch):
  monkeypatch.setattr(investigator_mod, "MODEL_TIMEOUT_SECONDS", 10)
