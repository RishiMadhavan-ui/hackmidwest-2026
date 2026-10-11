"""Opt-in acceptance through the human/operator API, never worker credentials.

Requires an explicitly isolated demo account and local payment rail. This suite
may mutate only that account's Attack Lab namespace. Live mode additionally
requires real inference; scripted mode labels model choices as fixtures.
"""
import os
import time

import httpx
import pytest


def pytest_collection_modifyitems(config, items):
  needed = [name for name in ("API_URL", "USER_TOKEN") if not os.getenv(name)]
  reason = None
  if os.getenv("LEASH_E2E") != "1" or os.getenv("LEASH_E2E_ISOLATED") != "1":
    reason = "Opt in with LEASH_E2E=1 and LEASH_E2E_ISOLATED=1 on an isolated local-rail demo account"
  elif needed:
    reason = "Missing " + ", ".join(needed)
  elif os.getenv("E2E_AGENT_MODE", "scripted") not in {"live", "scripted"}:
    reason = "E2E_AGENT_MODE must be live or scripted"
  if reason:
    for item in items:
      item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def api_as_user():
  with httpx.Client(base_url=os.environ["API_URL"],
                    headers={"Authorization": "Bearer " + os.environ["USER_TOKEN"]}, timeout=15) as client:
    access = client.get("/attack-lab/access")
    assert access.status_code == 200, access.text
    assert access.json()["operator_authorized"] and access.json()["server_enabled"]
    yield client


def command(client, path, body):
  # 429 rejects before the effect. Never retry an ambiguous 5xx/timeout or start
  # another purchase after one; its durable run/outcome must be inspected.
  until = time.monotonic() + 65
  while True:
    result = client.post(path, json=body)
    if result.status_code != 429 or time.monotonic() >= until:
      assert result.is_success, result.text
      return result.json()
    time.sleep(2)


@pytest.fixture(scope="session")
def namespace(api_as_user):
  result = command(api_as_user, "/attack-lab/namespaces", {})
  row = result["namespace"]
  assert row["rail"] == "local_payment_rail_simulator"
  return "/attack-lab/namespaces/" + row["id"]


def run_scenario(client, namespace, scenario):
  row = client.get("/attack-lab/access").json()["namespace"]
  if not row["enabled"]:
    command(client, namespace + "/control", {"enabled": True, "expected_revision": row["revision"]})
  mode = os.getenv("E2E_AGENT_MODE", "scripted")
  draft = command(client, namespace + "/draft", {"scenario": scenario, "mode": mode})
  mandate = draft["mandate"]
  assert draft["requires_confirmation"]
  launch = command(client, namespace + "/execute", {
    "mandate_id": mandate["id"], "version": mandate["version"],
    "canonical_payload_hash": mandate["canonical_payload_hash"], "confirmed": True})
  run_id = launch["run_id"]
  assert "credential" not in launch and "launch_id" not in launch
  end = time.monotonic() + 135
  while time.monotonic() < end:
    history = client.get(namespace + "/history").json()
    run = next(row for row in history["runs"] if row["run_id"] == run_id)
    if run["state"] == "terminal":
      break
    time.sleep(1)
  else:
    command(client, namespace + f"/runs/{run_id}/stop", {})
    pytest.fail("Graph did not reach its bounded terminal state")
  attempts = [row for row in history["attempts"] if row["run_id"] == run_id]
  return {"mandate": mandate, "run": run, "attempts": attempts, "namespace": namespace}


@pytest.fixture(scope="module")
def attack_session(api_as_user, namespace):
  result = run_scenario(api_as_user, namespace, "signature_attack")
  yield result
  command(api_as_user, namespace + "/cleanup", {})
