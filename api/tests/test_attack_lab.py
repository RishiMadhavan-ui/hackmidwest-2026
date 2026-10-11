"""Real JWT/SQL/HTTP operator authorization; no executor, provider or shared DB."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
import unittest
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

import test_r02_postgres as fixture

TEST_DSN, auth, db, app = fixture.TEST_DSN, fixture.auth, fixture.db, fixture.app


@unittest.skipUnless(TEST_DSN, "Set LEASH_TEST_DATABASE_URL to disposable localhost PostgreSQL")
class AttackLabTests(unittest.TestCase):
  setUpClass = classmethod(fixture.PostgresAuthorityTests.setUpClass.__func__)
  tearDownClass = classmethod(fixture.PostgresAuthorityTests.tearDownClass.__func__)
  tearDown = fixture.PostgresAuthorityTests.tearDown
  request = fixture.PostgresAuthorityTests.request

  def setUp(self):
    fixture.PostgresAuthorityTests.setUp(self)
    env = patch.dict(os.environ, {"ATTACK_LAB_OPERATOR_IDS": f"{self.owner},{self.other_owner}",
                                 "ATTACK_LAB_ENABLED": "1", "CORS_ORIGINS": "http://localhost:3000"})
    env.start()
    self.addCleanup(env.stop)

  def create(self, *, token=None):
    response = self.request("POST", "/attack-lab/namespaces", token=token or self.user_token, body={})
    self.assertEqual(response.status_code, 200, response.text)
    return response.json()["namespace"]

  def control(self, namespace, enabled=True, *, token=None, revision=None):
    return self.request("POST", f'/attack-lab/namespaces/{namespace["id"]}/control',
      token=token or self.user_token, body={"enabled": enabled, "expected_revision": revision or namespace["revision"]})

  def test_lab_001_002_all_control_and_execution_routes_require_real_operator_jwt(self):
    for token in (None, self.agent_token, self.other_agent_token, "claim-admin", "static-human-demo-" + "d"*32):
      for path, body in [("/attack-lab/namespaces", {}),
        ("/attack-lab/namespaces/lab_missing/control", {"enabled": True, "expected_revision": 1}),
        ("/attack-lab/namespaces/lab_missing/scenarios", {"scenario": "signature_attack"}),
        *[(f"/attack-lab/namespaces/lab_missing/{action}", {}) for action in ["reset", "replays", "tamper", "simulate-authorization"]]]:
        with self.subTest(token_type=bool(token), path=path):
          headers = {"Authorization": "Bearer " + token} if token else {}
          self.assertEqual(self.client.post(path, headers=headers, json=body).status_code, 401)
      headers = {"Authorization": "Bearer " + token} if token else {}
      self.assertEqual(self.client.get("/attack-lab/access", headers=headers).status_code, 401)

  def test_lab_002_non_operator_and_signed_role_claim_cannot_elevate(self):
    with patch.dict(os.environ, {"ATTACK_LAB_OPERATOR_IDS": self.other_owner}):
      claimed = jwt.encode({"sub": str(self.auth_id), "exp": auth.datetime.now(auth.timezone.utc)+timedelta(minutes=5),
                            "role": "admin"}, auth.JWT_SECRET, algorithm=auth.JWT_ALG)
      for token in (self.user_token, claimed):
        self.assertEqual(self.request("GET", "/attack-lab/access", token=token).status_code, 403)
        self.assertEqual(self.request("POST", "/attack-lab/namespaces", token=token, body={}).status_code, 403)

  def test_lab_004_missing_invalid_disabled_flags_cannot_be_overridden(self):
    for value in ("0", "", "true", "garbage"):
      with patch.dict(os.environ, {"ATTACK_LAB_ENABLED": value, "NEXT_PUBLIC_ATTACK_LAB": "1", "STORE_EVIL_MODE": "1"}):
        self.assertFalse(self.request("GET", "/attack-lab/access", token=self.user_token).json()["server_enabled"])
        self.assertEqual(self.request("POST", "/attack-lab/namespaces", token=self.user_token, body={}).status_code, 403)
    with db.get_conn() as conn:
      self.assertEqual(conn.execute("SELECT count(*) AS n FROM attack_lab_namespaces WHERE operator_user_id=%s", (self.owner,)).fetchone()["n"], 0)

  def test_lab_002_invalid_or_empty_allowlist_fails_closed(self):
    for value, status in [("",403), ("*",503), ("admin@example.com",503), (self.owner+",garbage",503)]:
      with patch.dict(os.environ, {"ATTACK_LAB_OPERATOR_IDS": value}):
        self.assertEqual(self.request("GET", "/attack-lab/access", token=self.user_token).status_code, status)

  def test_lab_002_ambiguous_human_agent_or_service_credential_is_rejected(self):
    with patch.dict(os.environ, {"STORE_API_TOKEN": self.user_token}):
      self.assertEqual(self.request("GET", "/attack-lab/access", token=self.user_token).status_code, 403)
    with db.get_conn() as conn:
      fixture.bind_agent(conn, user_id=self.owner, agent_id=self.agent_id,
                         token=self.user_token, modes=("live",))
    self.assertEqual(self.request("GET", "/attack-lab/access", token=self.user_token).status_code, 403)

  def test_namespace_is_empty_isolated_and_control_changes_are_audited(self):
    namespace = self.create()
    self.assertNotEqual(namespace["demo_user_id"], self.owner)
    self.assertFalse(namespace["enabled"])
    self.assertEqual(namespace["rail"], "local_payment_rail_simulator")
    enabled = self.control(namespace).json()
    self.assertTrue(enabled["namespace"]["enabled"])
    self.assertFalse(enabled["execution_available"])
    with db.get_conn() as conn:
      demo = conn.execute("SELECT * FROM leash_users WHERE id=%s", (namespace["demo_user_id"],)).fetchone()
      self.assertIsNone(demo["auth_user_id"])
      for table in ("leash_agents", "mandate_heads", "payment_operations"):
        self.assertEqual(conn.execute(f"SELECT count(*) AS n FROM {table} WHERE user_id=%s", (demo["id"],)).fetchone()["n"], 0)
      events = conn.execute("SELECT record FROM audit_events WHERE user_id=%s AND record->>'type' LIKE 'attack_lab.%%' ORDER BY sequence", (self.owner,)).fetchall()
      self.assertEqual([row["record"]["type"] for row in events], ["attack_lab.namespace.created", "attack_lab.control.changed"])
      self.assertFalse(events[-1]["record"]["data"]["execution_available"])

  def test_lab_005_007_foreign_namespace_and_real_user_ids_rejected(self):
    mine = self.create()
    foreign = self.create(token=self.other_user_token)
    for target in (foreign["id"], self.other_owner, "lab_missing"):
      self.assertEqual(self.control({**mine, "id": target}).status_code, 404)
      for action in ("reset", "replays", "tamper", "simulate-authorization"):
        self.assertEqual(self.request("POST", f"/attack-lab/namespaces/{target}/{action}", token=self.user_token, body={}).status_code, 404)
    self.assertFalse(self.request("GET", "/attack-lab/access", token=self.other_user_token).json()["namespace"]["enabled"])

  def test_lab_006_007_no_operator_override_can_enable_effects_or_select_rail(self):
    namespace = self.create()
    self.assertEqual(self.control(namespace).status_code, 200)
    for action in ("reset", "replays", "tamper", "simulate-authorization", "scenarios"):
      body = {"scenario": "signature_attack"} if action == "scenarios" else {}
      response = self.request("POST", f'/attack-lab/namespaces/{namespace["id"]}/{action}', token=self.user_token, body=body)
      self.assertEqual(response.status_code, 503, response.text)
      for extra in ({"rail": "live", "card_token": "foreign"}, {"user_id": self.other_owner}, {"url": "http://api:8000"}):
        response = self.request("POST", f'/attack-lab/namespaces/{namespace["id"]}/{action}', token=self.user_token, body={**body, **extra})
        self.assertEqual(response.status_code, 422)

  def test_disable_works_with_server_flag_off_and_old_revision_conflicts(self):
    namespace = self.create()
    namespace = self.control(namespace).json()["namespace"]
    with patch.dict(os.environ, {"ATTACK_LAB_ENABLED": "invalid"}):
      disabled = self.control(namespace, False)
      self.assertEqual(disabled.status_code, 200, disabled.text)
      self.assertFalse(disabled.json()["namespace"]["enabled"])
      self.assertEqual(self.control(disabled.json()["namespace"], True).status_code, 403)
    self.assertEqual(self.control(namespace, False).status_code, 409)

  def test_lab_008_distributed_mutation_budget_and_idempotent_namespace_creation(self):
    def create(_):
      with TestClient(app) as client:
        return client.post("/attack-lab/namespaces", headers={"Authorization": "Bearer "+self.user_token}, json={})
    with ThreadPoolExecutor(max_workers=8) as pool:
      responses = list(pool.map(create, range(8)))
    self.assertEqual(sorted(r.status_code for r in responses), [200]*5 + [429]*3)
    self.assertEqual(len({r.json()["namespace"]["id"] for r in responses if r.status_code == 200}), 1)
    # A new API client shares the durable counter, not a per-process dictionary.
    self.assertEqual(create(None).status_code, 429)

  def test_lab_008_streamed_payload_bound_and_extra_fields(self):
    self.assertEqual(self.client.post("/attack-lab/namespaces", headers={"Authorization":"Bearer "+self.user_token},
                                    content=(b"x"*32768 for _ in range(3))).status_code, 413)
    self.assertEqual(self.request("POST", "/attack-lab/namespaces", token=self.user_token,
                                  body={"operator": True, "demo_user_id": self.other_owner}).status_code, 422)

  def test_lab_009_cookie_origin_expired_and_revoked_session_denial(self):
    self.assertEqual(self.client.post("/attack-lab/namespaces", headers={"Cookie":"session="+self.user_token}, json={}).status_code, 401)
    self.assertEqual(self.client.post("/attack-lab/namespaces", headers={"Authorization":"Bearer "+self.user_token,
                                    "Origin":"https://attacker.example"}, json={}).status_code, 403)
    expired = jwt.encode({"sub": str(self.auth_id), "exp": 1}, auth.JWT_SECRET, algorithm=auth.JWT_ALG)
    self.assertEqual(self.request("GET", "/attack-lab/access", token=expired).status_code, 401)
    self.assertEqual(self.request("POST", "/auth/logout", token=self.user_token).status_code, 204)
    self.assertEqual(self.request("GET", "/attack-lab/access", token=self.user_token).status_code, 401)

  def test_namespace_scope_and_history_cannot_be_reassigned_or_deleted(self):
    namespace = self.create()
    from test_r02_postgres import psycopg
    for statement, actor in (("UPDATE attack_lab_namespaces SET operator_user_id=%s WHERE id=%s", self.other_owner),
                            ("DELETE FROM attack_lab_namespaces WHERE operator_user_id=%s AND id=%s", self.owner)):
      with self.assertRaises(psycopg.errors.CheckViolation), db.get_conn() as conn:
        conn.execute(statement, (actor, namespace["id"]))


if __name__ == "__main__":
  unittest.main()
