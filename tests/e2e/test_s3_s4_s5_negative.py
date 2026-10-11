"""Hosted bypass checks. Full budget/expiry/replay policy vectors run locally
in api verifier/Graph tests and the real Redis rail suite; these HTTP checks do
not claim to be signed ASA delivery or direct access to private worker scopes.
"""
from conftest import command


def test_s3_operator_cannot_expand_fixed_demo_budget(api_as_user, namespace):
  row = api_as_user.get("/attack-lab/access").json()["namespace"]
  if not row["enabled"]:
    command(api_as_user, namespace + "/control", {"enabled": True, "expected_revision": row["revision"]})
  result = api_as_user.post(namespace + "/draft", json={
    "scenario": "legitimate_charger", "mode": "scripted", "max_cents": 1000000})
  assert result.status_code == 422, result.text


def test_s4_human_cannot_submit_agent_checkout_claim_as_payment(api_as_user):
  result = api_as_user.post("/payments", json={
    "mandate_id": "mnd_unknown", "checkout_id": "chk_unknown", "run_id": "run_unknown",
    "proposal": {"merchant_name": "Volt Supply Co.", "items": [{"name": "Charger",
      "sku": "CHG-65W", "quantity": 1, "unit_cents": 2999}], "total_cents": 2999}})
  assert result.status_code in (401, 403), result.text


def test_s5_foreign_or_unconfirmed_execution_never_spends(api_as_user, namespace):
  result = api_as_user.post(namespace + "/execute", json={
    "mandate_id": "mnd_unknown", "version": 1,
    "canonical_payload_hash": "0" * 64, "confirmed": False})
  assert result.status_code in (403, 404, 409, 422), result.text
