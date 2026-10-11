"""Hosted positive acceptance: a persisted authorization, never a paid claim."""
from conftest import command, run_scenario


def test_s1_legitimate_charger_authorized(api_as_user, namespace):
  result = run_scenario(api_as_user, namespace, "legitimate_charger")
  approved = [row for row in result["attempts"] if row["authorization_status"] == "authorized"]
  assert len(approved) == 1, result
  assert approved[0]["state"] == "authorized"
  assert approved[0]["rail"] == "local_payment_rail_simulator"
  assert approved[0]["mandate_version"] == result["mandate"]["version"]
  command(api_as_user, namespace + "/cleanup", {})
