"""Actual SQL/HTTP tests against an explicitly selected disposable local database."""

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
from pathlib import Path
import sys
from threading import Barrier, Event
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime  # noqa: E402,F401
import auth  # noqa: E402
import db  # noqa: E402
import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from nacl.signing import SigningKey  # noqa: E402

from authority_errors import AuthorityError  # noqa: E402
from main import app  # noqa: E402
from mandate_service import utc_now  # noqa: E402
from principals import bind_agent, ensure_user, leash_user_id  # noqa: E402

TEST_DSN = os.environ.get("LEASH_TEST_DATABASE_URL", "")


@unittest.skipUnless(TEST_DSN, "Set LEASH_TEST_DATABASE_URL to a disposable local leash_test* database")
class PostgresAuthorityTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    params = conninfo_to_dict(TEST_DSN)
    if params.get("host") not in {"localhost", "127.0.0.1", "::1"} or not params.get("dbname", "").startswith("leash_test"):
      raise RuntimeError("Refusing tests outside a disposable localhost leash_test* database")
    cls.schema = "r02_test_" + uuid4().hex
    with psycopg.connect(TEST_DSN) as conn:
      conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
    cls.db_patch = patch.object(db, "DATABASE_URL", make_conninfo(TEST_DSN, options=f"-c search_path={cls.schema}"))
    cls.db_patch.start()
    cls.secret_patch = patch.object(auth, "JWT_SECRET", "isolated-local-r02-jwt-test-secret")
    cls.secret_patch.start()
    cls.env_patch = patch.dict(os.environ, {
      "MANDATE_SIGNING_KEY":base64.b64encode(bytes(SigningKey.generate())).decode(),
      "USER_TOKEN":"", "AGENT_TOKEN_SHOPPER":"r02-local-agent-credential-" + "x"*32,
    })
    cls.env_patch.start()
    cls.legacy_auth_id = uuid4()
    with db.get_conn() as conn:
      # Adopt Cameron's already-existing table/account without rewriting UUIDs.
      conn.execute((Path(__file__).resolve().parents[2]/"db/migrations/0001_users.sql").read_text(),prepare=False)
      conn.execute("INSERT INTO users (id,email,password_hash) VALUES (%s,%s,%s)",
                   (cls.legacy_auth_id,"legacy@example.com","unused-test-password-hash"))
    db.init_db()
    db.init_db()  # Migrations must be restart/idempotency safe.

  @classmethod
  def tearDownClass(cls):
    cls.env_patch.stop()
    cls.secret_patch.stop()
    cls.db_patch.stop()
    with psycopg.connect(TEST_DSN) as conn:
      conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))

  def setUp(self):
    app.dependency_overrides.clear()
    self.client = TestClient(app)
    self.auth_id = uuid4()
    self.owner = leash_user_id(str(self.auth_id))
    self.agent_id = "agt_" + uuid4().hex
    self.agent_token = "local-agent-" + uuid4().hex
    self.other_auth_id = uuid4()
    self.other_owner = leash_user_id(str(self.other_auth_id))
    self.other_agent_id = "agt_" + uuid4().hex
    self.other_agent_token = "other-agent-" + uuid4().hex
    with db.get_conn() as conn:
      for uid in (self.auth_id, self.other_auth_id):
        conn.execute("INSERT INTO users (id,email,password_hash) VALUES (%s,%s,%s)",
                     (uid,f"{uid.hex}@example.com","unused-test-password-hash"))
        ensure_user(conn,leash_user_id(str(uid)),str(uid))
      bind_agent(conn,user_id=self.owner,agent_id=self.agent_id,token=self.agent_token,modes=("live",))
      bind_agent(conn,user_id=self.other_owner,agent_id=self.other_agent_id,token=self.other_agent_token,modes=("live",))
    self.user_token = auth.create_access_token(str(self.auth_id),f"{self.auth_id.hex}@example.com")
    self.other_user_token = auth.create_access_token(str(self.other_auth_id),f"{self.other_auth_id.hex}@example.com")
    self.proposal = {"description":"Buy a USB-C laptop charger for under $40. No subscriptions.",
                     "category":"laptop_charger","max_cents":3999,
                     "product_constraints":[{"name":"connector","operator":"equals","value":"USB-C"}]}

  def tearDown(self):
    self.client.close()

  def request(self,method,path,*,token=None,body=None):
    return self.client.request(method,path,headers={"Authorization":"Bearer " + (token or self.agent_token)},json=body)

  def draft(self, proposal=None):
    result = self.request("POST","/mandates/propose",body=proposal or self.proposal)
    self.assertEqual(result.status_code,201,result.text)
    return result.json()

  def binding(self, draft):
    return {"version":draft["version"],"canonical_payload_hash":draft["canonical_payload_hash"]}

  def active(self,draft=None):
    draft = draft or self.draft()
    result = self.request("POST",f'/mandates/{draft["id"]}/approve',token=self.user_token,
                          body={**self.binding(draft),"confirmed":True})
    self.assertEqual(result.status_code,200,result.text)
    return result.json()

  def run_body(self, mandate, mode="live"):
    return {"id":"run_" + uuid4().hex,"mandate_id":mandate["id"],"agent_mode":mode,
            "model":"reported-model","provider":"reported-provider"}

  def payment_setup(self):
    active = self.active()
    run = self.run_body(active)
    self.assertEqual(self.request("POST", "/agent-runs", body=run).status_code, 201)
    env = patch.dict(os.environ, {"STORE_URL": "http://isolated-store.test", "STORE_API_TOKEN": "s" * 32})
    env.start()
    self.addCleanup(env.stop)
    return active, run, {"mandate_id": active["id"], "run_id": run["id"], "checkout_id": "ckt_charger"}

  def payment_direct(self, body):
    from payment_service import request_payment
    from principals import Principal
    from leash_shared.models import PaymentProposal
    with db.get_conn() as conn:
      return request_payment(conn, PaymentProposal.model_validate(body), Principal("agent", self.owner, self.agent_id))

  def payment_operation(self, run):
    with db.get_conn() as conn:
      return conn.execute("SELECT * FROM payment_operations WHERE run_id=%s", (run["id"],)).fetchone()

  def crash_preflight(self, body):
    with patch("payment_service._fetch_store_checkout", side_effect=RuntimeError("simulated worker crash")):
      with self.assertRaises(RuntimeError):
        self.payment_direct(body)

  def test_payment_identity_is_committed_before_fetch_and_full_evidence_is_immutable(self):
    from test_payment_service import _store_checkout
    active, run, body = self.payment_setup()
    def fetch(_):
      operation = self.payment_operation(run)  # A separate real connection.
      self.assertEqual(operation["state"], "prepared")
      self.assertEqual(operation["mandate_hash"], active["canonical_payload_hash"])
      for key in ("instrument_reference", "issuance_key", "authorization_event_id"):
        self.assertIsInstance(operation[key], type(uuid4()))
      self.assertTrue(operation["grant_reference"].startswith("grt_"))
      return _store_checkout()
    with patch("payment_service._fetch_store_checkout", side_effect=fetch), patch("payment_service._seed_grant") as seed, patch("payment_service._bind_store") as bind:
      response = self.payment_direct(body)
      seed.assert_not_called()
      bind.assert_not_called()
    with db.get_conn() as conn:
      observation = conn.execute("SELECT * FROM checkout_observations WHERE payment_id=%s", (response.id,)).fetchone()
      self.assertEqual(observation["snapshot"]["items"][0]["sku"], "CHG-65W")
      self.assertEqual(observation["source_facts"], _store_checkout())
      self.assertEqual(observation["run_id"], run["id"])
      self.assertEqual(observation["evidence_assessment"]["merchant_ownership"], "unverified")
      self.assertFalse(observation["evidence_assessment"]["financial_authority"])
      events = conn.execute("SELECT record FROM audit_events WHERE record->'data'->>'payment_id'=%s ORDER BY sequence", (response.id,)).fetchall()
      self.assertEqual([row["record"]["type"] for row in events],
                       ["payment.operation.prepared", "payment.operation.checkout_observed", "payment.denied", "payment.operation.blocked"])
    for statement in ("UPDATE checkout_observations SET source_hash=repeat('0',64) WHERE payment_id=%s",
                      "DELETE FROM checkout_observations WHERE payment_id=%s",
                      "UPDATE payment_operations SET issuance_key=gen_random_uuid() WHERE id=%s",
                      "DELETE FROM payment_operations WHERE id=%s",
                      "UPDATE payment_attempts SET status='approved' WHERE id=%s",
                      "DELETE FROM payment_attempts WHERE id=%s"):
      with self.subTest(statement=statement), self.assertRaises(psycopg.errors.CheckViolation), db.get_conn() as conn:
        conn.execute(statement, (response.id,))

  def test_crash_after_prepare_resumes_read_only_with_all_original_references(self):
    from test_payment_service import _store_checkout
    _, run, body = self.payment_setup()
    self.crash_preflight(body)
    first = self.payment_operation(run)
    with patch("payment_service._fetch_store_checkout", return_value=_store_checkout()) as fetch:
      result = self.payment_direct(body)
      again = self.payment_direct(body)
    final = self.payment_operation(run)
    self.assertEqual(first["id"], result.id)
    self.assertEqual(result, again)
    self.assertEqual(fetch.call_count, 1)
    for key in ("id", "grant_reference", "instrument_reference", "issuance_key", "authorization_event_id"):
      self.assertEqual(first[key], final[key])
    self.assertEqual(final["state"], "blocked")
    self.assertEqual(final["revision"], 2)

  def test_unresolved_operation_blocks_another_checkout_and_another_run(self):
    active, _, body = self.payment_setup()
    self.crash_preflight(body)
    next_run = self.run_body(active)
    self.assertEqual(self.request("POST", "/agent-runs", body=next_run).status_code, 201)
    with patch("payment_service._fetch_store_checkout") as fetch:
      for candidate in ({**body, "checkout_id": "ckt_other"}, {**body, "run_id": next_run["id"]}):
        result = self.request("POST", "/payments", body=candidate)
        self.assertEqual(result.status_code, 409, result.text)
      fetch.assert_not_called()

  def test_payment_retry_cannot_change_agent_claims(self):
    from test_payment_service import _store_checkout
    _, _, body = self.payment_setup()
    with patch("payment_service._fetch_store_checkout", return_value=_store_checkout()) as fetch:
      self.assertEqual(self.request("POST", "/payments", body=body).status_code, 200)
      changed = {**body, "proposal": {"merchant_name": "spoofed", "total_cents": 2999,
                    "items": [{"name": "charger", "sku": "CHG-65W", "quantity": 1, "unit_cents": 2999}]}}
      self.assertEqual(self.request("POST", "/payments", body=changed).status_code, 409)
      self.assertEqual(fetch.call_count, 1)

  def test_concurrent_identical_payment_requests_commit_one_outcome(self):
    from test_payment_service import _store_checkout
    _, run, body = self.payment_setup()
    barrier = Barrier(2)
    def fetch(_):
      barrier.wait(timeout=10)
      return _store_checkout()
    with patch("payment_service._fetch_store_checkout", side_effect=fetch), ThreadPoolExecutor(max_workers=2) as pool:
      results = list(pool.map(lambda _: self.payment_direct(body), range(2)))
    self.assertEqual(results[0], results[1])
    with db.get_conn() as conn:
      self.assertEqual(conn.execute("SELECT count(*) n FROM payment_operations WHERE run_id=%s", (run["id"],)).fetchone()["n"], 1)
      self.assertEqual(conn.execute("SELECT count(*) n FROM checkout_observations WHERE run_id=%s", (run["id"],)).fetchone()["n"], 1)
      self.assertEqual(conn.execute("SELECT count(*) n FROM payment_attempts WHERE run_id=%s", (run["id"],)).fetchone()["n"], 1)

  def test_concurrent_changed_checkout_evidence_cannot_overwrite_original(self):
    from test_payment_service import _store_checkout
    from leash_shared.models import canonical_json
    import hashlib
    _, _, body = self.payment_setup()
    barrier = Barrier(2)
    def fetch(_):
      store = _store_checkout()
      store["line_items"][0]["name"] = "Charger " + uuid4().hex
      store["facts_hash"] = hashlib.sha256(canonical_json({key: store[key] for key in (
        "checkout_id", "currency", "line_items", "mcc", "merchant_descriptor", "recurring", "total_cents"
      )}).encode()).hexdigest()
      barrier.wait(timeout=10)
      return store
    def call(_):
      try:
        self.payment_direct(body)
        return 200
      except AuthorityError as error:
        return error.status
    with patch("payment_service._fetch_store_checkout", side_effect=fetch), ThreadPoolExecutor(max_workers=2) as pool:
      self.assertEqual(sorted(pool.map(call, range(2))), [200, 409])

  def test_merchant_error_is_persisted_and_replayed_without_another_fetch(self):
    _, run, body = self.payment_setup()
    with patch("payment_service._fetch_store_checkout", side_effect=AuthorityError(502, "Trusted merchant unreachable")) as fetch:
      for _ in range(2):
        response = self.request("POST", "/payments", body=body)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "Trusted merchant unreachable"})
      self.assertEqual(fetch.call_count, 1)
    operation = self.payment_operation(run)
    self.assertEqual(operation["state"], "blocked")
    self.assertEqual(operation["error_status"], 502)

  def test_database_failure_before_prepare_commit_prevents_merchant_fetch(self):
    from payment_service import request_payment
    from principals import Principal
    from leash_shared.models import PaymentProposal
    _, run, body = self.payment_setup()
    class FailedCommit:
      def __init__(self, conn): self.conn = conn
      def execute(self, *args, **kwargs): return self.conn.execute(*args, **kwargs)
      def commit(self): raise psycopg.OperationalError("simulated commit failure")
    with patch("payment_service._fetch_store_checkout") as fetch:
      with self.assertRaises(psycopg.OperationalError), db.get_conn() as conn:
        request_payment(FailedCommit(conn), PaymentProposal.model_validate(body), Principal("agent", self.owner, self.agent_id))
      fetch.assert_not_called()
    self.assertIsNone(self.payment_operation(run))

  def test_final_transaction_failure_preserves_prepared_identity_without_partial_evidence(self):
    from test_payment_service import _store_checkout
    _, run, body = self.payment_setup()
    with patch("payment_service._fetch_store_checkout", return_value=_store_checkout()), patch("payment_service._persist", side_effect=RuntimeError("simulated final transaction failure")):
      with self.assertRaises(RuntimeError): self.payment_direct(body)
    original = self.payment_operation(run)
    self.assertEqual(original["state"], "prepared")
    with db.get_conn() as conn:
      self.assertIsNone(conn.execute("SELECT payment_id FROM checkout_observations WHERE payment_id=%s", (original["id"],)).fetchone())
    with patch("payment_service._fetch_store_checkout", return_value=_store_checkout()):
      self.assertEqual(self.payment_direct(body).id, original["id"])

  def test_run_stop_during_fetch_cancels_prepared_operation_and_prevents_finalization(self):
    self.assert_payment_control_race("run")

  def test_account_stop_during_fetch_cancels_prepared_operation_and_prevents_finalization(self):
    self.assert_payment_control_race("account")

  def test_mandate_replacement_during_fetch_cancels_old_operation(self):
    self.assert_payment_control_race("replace")

  def test_mandate_revocation_during_fetch_cancels_old_operation(self):
    self.assert_payment_control_race("revoke")

  def assert_payment_control_race(self, control):
    from test_payment_service import _store_checkout
    active, run, body = self.payment_setup()
    entered, release = Event(), Event()
    def fetch(_):
      entered.set()
      self.assertTrue(release.wait(10))
      return _store_checkout()
    with patch("payment_service._fetch_store_checkout", side_effect=fetch), patch("workflow_control.stop_rail", return_value={"status": "pending"}), ThreadPoolExecutor(max_workers=1) as pool:
      future = pool.submit(lambda: self.request("POST", "/payments", body=body))
      try:
        self.assertTrue(entered.wait(10))
        if control == "run":
          response = self.request("POST", f"/agent-runs/{run['id']}/stop", token=self.user_token)
        elif control == "account":
          response = self.request("POST", "/killswitch", token=self.user_token, body={"on": True})
        elif control == "replace":
          response = self.request("PATCH", f"/mandates/{active['id']}", token=self.user_token,
                                  body={**self.binding(active), "proposal": self.proposal})
        else:
          response = self.request("POST", f"/mandates/{active['id']}/revoke", token=self.user_token, body=self.binding(active))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.payment_operation(run)["state"], "cancelled")
      finally:
        release.set()
      self.assertEqual(future.result(timeout=10).status_code, 409)
    with db.get_conn() as conn:
      self.assertIsNone(conn.execute("SELECT payment_id FROM checkout_observations WHERE run_id=%s", (run["id"],)).fetchone())

  def test_unknown_operation_blocks_replacement_across_mandate_versions_and_survives_stop(self):
    from payment_operations import mark_reconciling
    active, run, body = self.payment_setup()
    self.crash_preflight(body)
    original = self.payment_operation(run)
    with db.get_conn() as conn:
      mark_reconciling(conn, original["id"], self.owner, expected_revision=1)
    self.assertEqual(self.request("POST", "/payments", body=body).status_code, 409)
    replacement = self.request("PATCH", f"/mandates/{active['id']}", token=self.user_token,
                               body={**self.binding(active), "proposal": self.proposal})
    self.assertEqual(replacement.status_code, 200, replacement.text)
    next_active = self.active(replacement.json())
    next_run = self.run_body(next_active)
    self.assertEqual(self.request("POST", "/agent-runs", body=next_run).status_code, 201)
    with patch("payment_service._fetch_store_checkout") as fetch:
      response = self.request("POST", "/payments", body={**body, "run_id": next_run["id"]})
      self.assertEqual(response.status_code, 409, response.text)
      fetch.assert_not_called()
    self.assertEqual(self.request("POST", f"/agent-runs/{run['id']}/stop", token=self.user_token).status_code, 200)
    self.assertEqual(self.payment_operation(run)["state"], "reconciling")
    with db.get_conn() as conn:
      with self.assertRaises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute("UPDATE payment_operations SET state='blocked',revision=revision+1 WHERE id=%s", (original["id"],))

  def test_blocked_subscription_allows_clean_candidate_under_unchanged_mandate(self):
    from test_payment_service import _store_checkout
    active, run, body = self.payment_setup()
    with patch("payment_service._fetch_store_checkout", return_value=_store_checkout(subscription=True)):
      attacked = self.payment_direct({**body, "checkout_id": "ckt_sub"})
    self.assertIn("subscription_prohibited", attacked.reasons)
    with patch("payment_service._fetch_store_checkout", return_value=_store_checkout()):
      charger = self.payment_direct(body)
    self.assertNotEqual(attacked.id, charger.id)
    self.assertEqual(charger.status, "blocked")  # Independent owner/freeze and financial gates remain.
    self.assertEqual(self.request("GET", f"/mandates/{active['id']}").json()["canonical_payload_hash"], active["canonical_payload_hash"])

  def test_checkout_secrets_are_rejected_before_persisting_source_or_snapshot(self):
    from test_payment_service import _store_checkout
    from leash_shared.models import canonical_json
    import hashlib
    _, run, body = self.payment_setup()
    store = _store_checkout()
    store["line_items"][0]["attributes"].append({"name": "api_key", "value": "private-test-secret"})
    store["facts_hash"] = hashlib.sha256(canonical_json({key: store[key] for key in (
      "checkout_id", "currency", "line_items", "mcc", "merchant_descriptor", "recurring", "total_cents"
    )}).encode()).hexdigest()
    with patch("payment_service._fetch_store_checkout", return_value=store):
      response = self.request("POST", "/payments", body=body)
    self.assertEqual(response.status_code, 502, response.text)
    with db.get_conn() as conn:
      self.assertIsNone(conn.execute("SELECT payment_id FROM checkout_observations WHERE run_id=%s", (run["id"],)).fetchone())
      events = conn.execute("SELECT record FROM audit_events WHERE user_id=%s", (self.owner,)).fetchall()
      self.assertNotIn("private-test-secret", str(events))

  def test_mandate_expiry_after_fetch_cancels_operation_before_evidence_commit(self):
    from test_payment_service import _store_checkout
    from datetime import datetime
    active, run, body = self.payment_setup()
    clock = [utc_now()]
    def fetch(_):
      clock[0] = datetime.fromisoformat(active["valid_until"]) + timedelta(seconds=1)
      return _store_checkout()
    with patch("payment_service.utc_now", side_effect=lambda: clock[0]), patch("payment_service._fetch_store_checkout", side_effect=fetch):
      self.assertEqual(self.request("POST", "/payments", body=body).status_code, 409)
    self.assertEqual(self.payment_operation(run)["state"], "cancelled")

  def test_run_stop_cancels_only_its_prepared_operation(self):
    active, first_run, first_body = self.payment_setup()
    self.crash_preflight(first_body)
    _, other_run, other_body = self.payment_setup()
    self.crash_preflight(other_body)
    self.assertEqual(self.request("POST", f"/agent-runs/{first_run['id']}/stop", token=self.user_token).status_code, 200)
    self.assertEqual(self.payment_operation(first_run)["state"], "cancelled")
    self.assertEqual(self.payment_operation(other_run)["state"], "prepared")
    self.assertEqual(self.request("GET", f"/mandates/{active['id']}").json()["status"], "active")

  def test_account_stop_preserves_unknown_financial_outcome(self):
    from payment_operations import mark_reconciling
    _, run, body = self.payment_setup()
    self.crash_preflight(body)
    operation = self.payment_operation(run)
    with db.get_conn() as conn:
      mark_reconciling(conn, operation["id"], self.owner, expected_revision=1)
    with patch("workflow_control.stop_rail", return_value={"status": "pending"}):
      self.assertEqual(self.request("POST", "/killswitch", token=self.user_token, body={"on": True}).status_code, 200)
    self.assertEqual(self.payment_operation(run)["state"], "reconciling")

  def test_database_constraints_reject_parallel_scope_and_forged_owner_bindings(self):
    _, run, body = self.payment_setup()
    self.crash_preflight(body)
    columns = "id,user_id,agent_id,run_id,mandate_id,mandate_version,mandate_hash,checkout_id,request_hash,grant_reference,instrument_reference,issuance_key,authorization_event_id,state"
    for forged_owner in (False, True):
      with self.subTest(forged_owner=forged_owner), self.assertRaises(psycopg.errors.ForeignKeyViolation if forged_owner else psycopg.errors.UniqueViolation), db.get_conn() as conn:
        conn.execute(f"""INSERT INTO payment_operations ({columns})
          SELECT %s,%s,agent_id,run_id,mandate_id,mandate_version,mandate_hash,'ckt_other',request_hash,
          %s,%s,%s,%s,%s FROM payment_operations WHERE run_id=%s""",
          ("pay_" + uuid4().hex, self.other_owner if forged_owner else self.owner,
           "grt_" + uuid4().hex, uuid4(), uuid4(), uuid4(), "blocked" if forged_owner else "prepared", run["id"]))

  def test_prepared_payment_status_is_owned_and_never_exposes_reserved_instrument_or_grant(self):
    _, run, body = self.payment_setup()
    self.crash_preflight(body)
    operation = self.payment_operation(run)
    path = f"/payments/{operation['id']}"
    response = self.request("GET", path)
    self.assertEqual(response.status_code, 200, response.text)
    self.assertEqual(response.json()["operation"]["state"], "prepared")
    self.assertEqual(response.json()["status"], "blocked")
    self.assertIsNone(response.json()["grant_id"])
    for key in ("grant_reference", "instrument_reference", "issuance_key", "authorization_event_id"):
      self.assertNotIn(str(operation[key]), response.text)
    self.assertEqual(self.request("GET", path, token=self.other_agent_token).status_code, 404)

  def test_historical_approved_grant_blocks_a_new_checkout_without_reissue(self):
    from psycopg.types.json import Jsonb
    active, run, body = self.payment_setup()
    old_id = "pay_" + uuid4().hex
    record = {"id": old_id, "status": "approved", "verification_id": "ver_historical",
              "grant_id": "grt_historical", "reasons": []}
    with db.get_conn() as conn:
      conn.execute("""INSERT INTO payment_attempts
        (id,user_id,agent_id,mandate_id,mandate_version,checkout_id,run_id,status,record)
        VALUES (%s,%s,%s,%s,%s,'ckt_historical',%s,'approved',%s)""",
        (old_id, self.owner, self.agent_id, active["id"], active["version"], run["id"], Jsonb(record)))
    with patch("payment_service._fetch_store_checkout") as fetch, patch("payment_service._seed_grant") as seed:
      response = self.request("POST", "/payments", body=body)
      self.assertEqual(response.status_code, 409, response.text)
      fetch.assert_not_called()
      seed.assert_not_called()
    self.assertIsNone(self.payment_operation(run))
    history = self.request("GET", f"/payments/{old_id}").json()
    self.assertEqual(history["payment_execution"], "unavailable")
    self.assertEqual(history["authorization_status"], "unverified")

  def test_restart_safe_migration_and_uuid_identity_mapping(self):
    db.init_db()
    response = self.request("GET","/identity",token=self.user_token)
    self.assertEqual(response.json(),{"user_id":self.owner,"role":"human"})
    with db.get_conn() as conn:
      self.assertEqual(conn.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"],len(list((Path(__file__).resolve().parents[2]/"db/migrations").glob("*.sql"))))
      mapping=conn.execute("SELECT id FROM leash_users WHERE auth_user_id=%s",(self.legacy_auth_id,)).fetchone()
      self.assertEqual(mapping["id"],leash_user_id(str(self.legacy_auth_id)))

  def test_payment_preflight_is_registered_owned_idempotent_and_stopped(self):
    from test_payment_service import _store_checkout
    active = self.active()
    run = self.run_body(active)
    self.assertEqual(self.request("POST", "/agent-runs", body=run).status_code, 201)
    proposal = {"mandate_id": active["id"], "checkout_id": "ckt_charger", "run_id": run["id"]}
    env = {"STORE_URL": "http://isolated-store.test", "STORE_API_TOKEN": "s" * 32}
    with (patch.dict(os.environ, env),
          patch("payment_service._fetch_store_checkout", return_value=_store_checkout()) as fetch,
          patch("payment_service._seed_grant") as seed,
          patch("payment_service._bind_store") as bind):
      missing = {key: value for key, value in proposal.items() if key != "run_id"}
      self.assertEqual(self.request("POST", "/payments", body=missing).status_code, 422)
      foreign = {**proposal, "run_id": "run_foreign"}
      self.assertEqual(self.request("POST", "/payments", body=foreign).status_code, 404)
      fetch.assert_not_called()
      first = self.request("POST", "/payments", body=proposal)
      self.assertEqual(first.status_code, 200, first.text)
      self.assertEqual(first.json()["status"], "blocked")
      self.assertEqual(first.json()["reasons"], ["checkout_source_unavailable_or_wrong_owner", "financial_authority_unavailable"])
      self.assertIsNone(first.json()["grant_id"])
      self.assertNotIn("instrument_token", first.json())
      again = self.request("POST", "/payments", body=proposal)
      self.assertEqual(again.json(), first.json())
      self.assertEqual(fetch.call_count, 1)
      path = f"/payments/{first.json()['id']}"
      self.assertEqual(self.request("GET", path).status_code, 200)
      self.assertEqual(self.request("GET", path, token=self.other_agent_token).status_code, 404)
      self.assertEqual(self.request("GET", path, token=self.user_token).status_code, 401)
      # Another agent owned by the same human cannot read this run's attempt.
      peer_token = "peer-" + uuid4().hex
      with db.get_conn() as conn:
        bind_agent(conn, user_id=self.owner, agent_id="agt_" + uuid4().hex, token=peer_token, modes=("live",))
      self.assertEqual(self.request("GET", path, token=peer_token).status_code, 404)
      stop = self.request("POST", f"/agent-runs/{run['id']}/stop", token=self.user_token)
      self.assertEqual(stop.status_code, 200, stop.text)
      self.assertEqual(self.request("POST", "/payments", body=proposal).status_code, 409)
      self.assertEqual(fetch.call_count, 1)
      seed.assert_not_called()
      bind.assert_not_called()
    with db.get_conn() as conn:
      row = conn.execute("SELECT count(*) n FROM payment_attempts WHERE run_id=%s", (run["id"],)).fetchone()
      self.assertEqual(row["n"], 1)

  def test_account_stop_blocks_payment_preflight_before_merchant_fetch(self):
    active = self.active()
    run = self.run_body(active)
    self.assertEqual(self.request("POST", "/agent-runs", body=run).status_code, 201)
    with patch("workflow_control.stop_rail", return_value={"status": "pending"}):
      self.assertEqual(self.request("POST", "/killswitch", token=self.user_token, body={"on": True}).status_code, 200)
    # Test the service with the former principal as well as revoked HTTP auth.
    from payment_service import request_payment
    from leash_shared.models import PaymentProposal
    from principals import Principal
    with patch("payment_service._fetch_store_checkout") as fetch, db.get_conn() as conn:
      with self.assertRaises(AuthorityError) as error:
        request_payment(conn, PaymentProposal(mandate_id=active["id"], checkout_id="ckt_charger", run_id=run["id"]),
                        Principal("agent", self.owner, self.agent_id))
      self.assertEqual(error.exception.status, 409)
      fetch.assert_not_called()

  def test_rail_ingest_has_separate_credential_owner_validation_and_original_decision(self):
    event_id="evt_rail_"+uuid4().hex
    payload={"event_id":event_id,"type":"authorization.decided","user_id":self.owner,
      "data":{"result":"DECLINED","reason":"checkout_binding_mismatch","rail":"local_payment_rail_simulator",
        "decision_source":"local_rail","provider":"local_rail","event_id":"provider-event-1",
        "amount_cents":2999,"currency":"USD","descriptor":"VOLT SUPPLY CO","mcc":"5732", "decided_at":utc_now().isoformat()}}
    event_token="events-"+uuid4().hex
    control_token="controls-"+uuid4().hex
    with patch.dict(os.environ,{"RAIL_EVENT_TOKEN":event_token,"WEBHOOK_INTERNAL_TOKEN":control_token}):
      self.assertEqual(self.request("POST","/internal/activity",body=payload).status_code,401)
      self.assertEqual(self.request("POST","/internal/activity",token=control_token,body=payload).status_code,401)
      self.assertEqual(self.request("POST","/internal/activity",token=event_token,body={**payload,"type":"mandate.confirmed"}).status_code,422)
      self.assertEqual(self.request("POST","/internal/activity",token=event_token,body={**payload,"user_id":"usr_missing"}).status_code,422)
      self.assertEqual(self.request("POST","/internal/activity",token=event_token,body={**payload,"auth_user_id":str(self.other_auth_id)}).status_code,422)
      self.assertEqual(self.request("POST","/internal/activity",token=event_token,body=payload).status_code,201)
      self.assertEqual(self.request("POST","/internal/activity",token=event_token,body=payload).status_code,409)
      self.assertEqual(self.request("POST","/internal/activity",token=event_token,body={**payload,"data":{**payload["data"],"result":"APPROVED"}}).status_code,422)
    with db.get_conn() as conn:
      self.assertEqual(conn.execute("SELECT count(*) n FROM audit_events WHERE event_id=%s",(event_id,)).fetchone()["n"],1)
      self.assertIsNone(conn.execute("SELECT id FROM leash_users WHERE id='usr_missing'").fetchone())

  def test_stop_persists_owned_card_closure_and_retries_unknown_without_new_authority(self):
    card_token="card_"+uuid4().hex
    foreign="card_"+uuid4().hex
    with db.get_conn() as conn:
      conn.execute("UPDATE users SET lithic_card_token=%s WHERE id=%s",(card_token,self.auth_id))
      conn.execute("UPDATE users SET lithic_card_token=%s WHERE id=%s",(foreign,self.other_auth_id))
    from unittest.mock import Mock
    def provider_call(path,**kwargs):
      self.assertEqual(path,"/internal/lithic/card-state")
      self.assertEqual(kwargs["json"],{"card_token":card_token,"state":"CLOSED"})
      with db.get_conn() as conn:
        operation=conn.execute("SELECT * FROM card_control_operations WHERE user_id=%s",(self.owner,)).fetchone()
        self.assertIsNotNone(operation) # Intent already durable before provider call.
      return Mock(is_success=True,json=lambda:{"card_token":card_token,"state":"CLOSED","provider":"lithic_sandbox"})
    with patch.dict(os.environ,{"WEBHOOK_INTERNAL_TOKEN":"control-"+"a"*32,"WEBHOOK_URL":"http://rail.test"}), patch("workflow_control.stop_rail",return_value={"status":"enforced","unused_grants_revoked":0}), patch("workflow_control.httpx.Client") as client:
      post=client.return_value.__enter__.return_value.post
      import httpx
      post.side_effect=httpx.ReadTimeout("private provider text")
      first=self.request("POST","/killswitch",token=self.user_token,body={"on":True})
      self.assertEqual(first.json()["provider_card_controls"],{"status":"pending","total":1,"confirmed":0})
      self.assertEqual(first.json()["status"],"pending_enforcement")
      self.assertNotIn("private",first.text)
      post.side_effect=provider_call
      second=self.request("POST","/killswitch",token=self.user_token,body={"on":True})
      self.assertEqual(second.json()["provider_card_controls"],{"status":"enforced","total":1,"confirmed":1})
      self.assertEqual(second.json()["status"],"financially_stopped")
      third=self.request("POST","/killswitch",token=self.user_token,body={"on":True})
      self.assertEqual(third.json()["provider_card_controls"]["confirmed"],1)
      self.assertEqual(post.call_count,2) # Confirmed control is not repeated.
    with db.get_conn() as conn:
      self.assertEqual(conn.execute("SELECT count(*) n FROM card_control_operations WHERE card_token=%s",(card_token,)).fetchone()["n"],1)
      self.assertIsNone(conn.execute("SELECT id FROM card_control_operations WHERE card_token=%s",(foreign,)).fetchone())

  def test_signup_login_identity_and_legacy_me_keep_uuid(self):
    email = uuid4().hex + "@example.com"
    # Identity creation must work without provider configuration or issuance.
    with patch("leash_shared.lithic.create_account_holder") as holder, \
        patch("leash_shared.lithic.create_virtual_card") as card:
      response = self.client.post("/auth/signup",json={"email":email,"password":"r02-password-valid",
        "first_name":"Demo", "last_name":"User", "postal_code":"64101", "spend_limit_cents":50000})
      holder.assert_not_called()
      card.assert_not_called()
    self.assertFalse(response.json()["user"]["lithic_linked"])
    self.assertEqual(response.status_code,201,response.text)
    payload = response.json()
    identity = self.request("GET","/identity",token=payload["access_token"])
    self.assertEqual(identity.json()["user_id"],leash_user_id(payload["user"]["id"]))
    self.assertEqual(self.request("GET","/auth/me",token=payload["access_token"]).json()["id"],payload["user"]["id"])
    self.assertEqual(self.client.post("/auth/login",json={"email":email,"password":"r02-password-valid"}).status_code,200)
    self.assertEqual(self.client.post("/auth/login",json={"email":email,"password":"wrong"}).status_code,401)

  def test_logout_revokes_only_presented_session_and_fresh_login_restores_human_actions(self):
    draft=self.draft()
    active=self.active()
    password="isolated-session-password"
    email=f"{self.auth_id.hex}@example.com"
    with db.get_conn() as conn:
      conn.execute("UPDATE users SET password_hash=%s WHERE id=%s",(auth.hash_password(password),self.auth_id))
    other_session=auth.create_access_token(str(self.auth_id),email)
    self.assertNotEqual(other_session,self.user_token)
    self.assertEqual(self.request("POST","/auth/logout",token=self.user_token).status_code,204)
    for path in ("/auth/me","/identity","/agent-runs","/killswitch","/activity"):
      self.assertEqual(self.request("GET",path,token=self.user_token).status_code,401)
    self.assertEqual(self.request("POST",f'/mandates/{draft["id"]}/approve',token=self.user_token,
      body={**self.binding(draft),"confirmed":True}).status_code,401)
    self.assertEqual(self.request("GET","/identity",token=self.other_user_token).status_code,200)
    self.assertEqual(self.request("GET","/identity",token=other_session).status_code,200)
    # Logout is session control; it does not silently revoke confirmed delegation.
    self.assertEqual(self.request("GET",f'/mandates/{active["id"]}').json()["status"],"active")
    login=self.client.post("/auth/login",json={"email":email,"password":password})
    self.assertEqual(login.status_code,200)
    fresh=login.json()["access_token"]
    self.assertNotEqual(fresh,self.user_token)
    self.assertEqual(self.request("POST",f'/mandates/{draft["id"]}/approve',token=fresh,
      body={**self.binding(draft),"confirmed":True}).status_code,200)
    with db.get_conn() as conn:
      rows=conn.execute("SELECT token_hash,user_id FROM revoked_sessions WHERE user_id=%s",(self.auth_id,)).fetchall()
      self.assertEqual(len(rows),1)
      self.assertNotEqual(rows[0]["token_hash"],self.user_token)

  def test_cross_origin_cookie_cannot_authorize_human_confirmation(self):
    draft=self.draft()
    response=self.client.post(f'/mandates/{draft["id"]}/approve',
      headers={"Origin":"https://attacker.invalid","Cookie":"hmw_access_token="+self.user_token},
      json={**self.binding(draft),"confirmed":True})
    self.assertEqual(response.status_code,401)
    self.assertEqual(self.request("GET",f'/mandates/{draft["id"]}').json()["status"],"proposed")

  def registered_trace(self):
    mandate = self.active()
    registration = self.run_body(mandate)
    self.assertEqual(self.request("POST","/agent-runs",body=registration).status_code,201)
    return {"type":"agent.tool.before", "event_id":"evt_"+uuid4().hex,
      "run_id":registration["id"],"agent_id":self.agent_id,"agent_mode":"live",
      "timestamp":utc_now().isoformat(),"tool_name":"browse","tool_use_id":"tool_1",
      "tool_arguments":{"authorization":"Bearer test-sensitive","pan":"4111111111111111"},
      "trust_classification":"trusted_checkout"}

  def test_provenance_persist_redact_scope_and_idempotency(self):
    trace = self.registered_trace()
    self.assertEqual(self.request("POST","/provenance",body=trace).status_code,201)
    self.assertEqual(self.request("POST","/provenance",body=trace).status_code,409)
    self.assertEqual(self.request("POST","/provenance",body={**trace,"tool_name":"request_payment"}).status_code,422)
    history = self.request("GET","/activity",token=self.user_token).json()["events"]
    event = next(e for e in history if e["event_id"] == trace["event_id"])
    self.assertEqual(event["data"]["tool_arguments"]["pan"],"[REDACTED]")
    self.assertEqual(event["data"]["trust_classification"],"agent_proposal")
    self.assertFalse(event["data"]["authoritative"])
    other = self.request("GET","/activity",token=self.other_user_token).json()["events"]
    self.assertNotIn(trace["event_id"],[e["event_id"] for e in other])
    self.assertEqual(self.request("GET","/activity").status_code,401)

  def test_provenance_rejects_foreign_run_agent_mode_and_excess_size(self):
    trace = self.registered_trace()
    for changes, expected in [({"run_id":"run_unknown"},404),({"agent_id":self.other_agent_id},422),
                              ({"agent_mode":"scripted"},422),({"type":"payment.approved"},422)]:
      response=self.request("POST","/provenance",body={**trace,**changes})
      self.assertEqual(response.status_code,expected,response.text)
    self.assertEqual(self.request("POST","/provenance",body=trace,token=self.other_agent_token).status_code,404)
    self.assertEqual(self.request("POST","/provenance",body={**trace,"tool_arguments":{"large":"x"*131072}}).status_code,413)

  def test_kill_switch_is_human_scoped_durable_and_truthful_on_outage(self):
    trace = self.registered_trace()
    self.assertEqual(self.request("POST","/killswitch",body={"on":True}).status_code,401)
    with patch("workflow_control.stop_rail",return_value={"status":"pending","reason":"test outage"}):
      stopped = self.request("POST","/killswitch",token=self.user_token,body={"on":True})
    self.assertEqual(stopped.status_code,200,stopped.text)
    self.assertEqual(stopped.json()["status"],"pending_enforcement")
    self.assertFalse(stopped.json()["previous_authorizations_reversed"])
    self.assertEqual(self.request("GET","/killswitch",token=self.user_token).json(),{"on":True,"rail_enforced":False,"provider_controls_enforced":True})
    self.assertEqual(self.request("GET","/killswitch",token=self.other_user_token).json()["on"],False)
    control=self.request("GET",f'/agent-runs/{trace["run_id"]}/control').json()
    self.assertEqual(control,{"run_id":trace["run_id"],"cancel_requested":True,"authority_current":False})
    self.assertEqual(self.request("GET",f'/agent-runs/{trace["run_id"]}/control',token=self.other_agent_token).status_code,404)
    # Late traces remain deliverable; cancellation must preserve its evidence.
    self.assertEqual(self.request("POST","/provenance",body=trace).status_code,201)
    draft=self.draft()
    self.assertEqual(self.request("POST",f'/mandates/{draft["id"]}/approve',token=self.user_token,
                                 body={**self.binding(draft),"confirmed":True}).status_code,409)
    self.assertEqual(self.request("POST","/agent-runs",body=self.run_body(draft)).status_code,409)
    with patch("workflow_control.stop_rail",return_value={"status":"enforced","unused_grants_revoked":2}):
      retried=self.request("POST","/killswitch",token=self.user_token,body={"on":True})
    self.assertEqual(retried.json()["status"],"financially_stopped")
    self.assertTrue(self.request("GET","/killswitch",token=self.user_token).json()["rail_enforced"])

  def test_run_stop_is_owned_idempotent_and_preserves_other_runs_and_mandate(self):
    mandate=self.active()
    first,second=self.run_body(mandate),self.run_body(mandate)
    for registration in (first,second):
      self.assertEqual(self.request("POST","/agent-runs",body=registration).status_code,201)
    route=f'/agent-runs/{first["id"]}/stop'
    self.assertEqual(self.request("POST",route).status_code,401)
    self.assertEqual(self.request("POST",route,token=self.other_user_token).status_code,404)
    self.assertFalse(self.request("GET",f'/agent-runs/{first["id"]}/control').json()["cancel_requested"])
    with patch("workflow_control.stop_rail") as rail, patch("workflow_control.close_owned_cards") as cards:
      responses=[self.request("POST",route,token=self.user_token) for _ in range(2)]
      rail.assert_not_called()
      cards.assert_not_called()
    self.assertEqual(responses[0].json(),responses[1].json())
    self.assertEqual(responses[0].json()["financial_revocation"],"pending_run_binding")
    self.assertEqual(responses[0].json()["graph_cancellation"],"not_acknowledged")
    self.assertFalse(responses[0].json()["previous_authorizations_reversed"])
    self.assertEqual(self.request("GET",route,token=self.user_token).json(),responses[0].json())
    self.assertEqual(self.request("GET",f'/agent-runs/{first["id"]}/control').json()["authority_current"],False)
    self.assertEqual(self.request("GET",f'/agent-runs/{second["id"]}/control').json()["authority_current"],True)
    self.assertEqual(self.request("POST","/agent-runs",body=first).status_code,409)
    self.assertEqual(self.request("POST","/agent-runs",body=second).status_code,201)
    self.assertEqual(self.request("GET",f'/mandates/{mandate["id"]}').json()["status"],"active")
    self.assertFalse(self.request("GET","/killswitch",token=self.user_token).json()["on"])
    self.assertEqual(len(self.request("GET","/agent-runs",token=self.user_token).json()["runs"]),2)
    self.assertEqual(self.request("GET","/agent-runs",token=self.other_user_token).json()["runs"],[])
    self.assertEqual(self.request("GET","/agent-runs").status_code,401)
    events=self.request("GET","/activity",token=self.user_token).json()["events"]
    self.assertEqual(len([e for e in events if e["type"]=="run.stop.requested"]),1)

  def test_run_stop_concurrent_requests_keep_one_durable_intent(self):
    mandate=self.active()
    registration=self.run_body(mandate)
    self.assertEqual(self.request("POST","/agent-runs",body=registration).status_code,201)
    barrier=Barrier(2)
    def stop():
      barrier.wait(timeout=5)
      return self.request("POST",f'/agent-runs/{registration["id"]}/stop',token=self.user_token)
    with ThreadPoolExecutor(max_workers=2) as workers:
      results=list(workers.map(lambda _:stop(),range(2)))
    self.assertEqual([r.status_code for r in results],[200,200])
    self.assertEqual(results[0].json(),results[1].json())
    with db.get_conn() as conn:
      self.assertEqual(conn.execute("SELECT count(*) n FROM run_cancellations WHERE run_id=%s",(registration["id"],)).fetchone()["n"],1)

  def test_paused_provider_card_is_not_confirmed_closed_and_legacy_intent_survives(self):
    from unittest.mock import Mock
    token="card_"+uuid4().hex
    with db.get_conn() as conn:
      conn.execute("UPDATE users SET lithic_card_token=%s WHERE id=%s",(token,self.auth_id))
      conn.execute("INSERT INTO card_control_operations (id,user_id,card_token,requested_state,outcome,observed_state,requested_at) VALUES (%s,%s,%s,'PAUSED','confirmed','PAUSED',%s)",("ctl_"+uuid4().hex,self.owner,token,utc_now()))
    with patch.dict(os.environ,{"WEBHOOK_INTERNAL_TOKEN":"control-"+"a"*32,"WEBHOOK_URL":"http://rail.test"}), patch("workflow_control.stop_rail",return_value={"status":"enforced","unused_grants_revoked":0}), patch("workflow_control.httpx.Client") as client:
      client.return_value.__enter__.return_value.post.return_value=Mock(is_success=True,json=lambda:{"provider":"lithic_sandbox","card_token":token,"state":"PAUSED"})
      result=self.request("POST","/killswitch",token=self.user_token,body={"on":True})
      self.assertEqual(result.json()["status"],"pending_enforcement")
      self.assertEqual(result.json()["provider_card_controls"],{"status":"pending","total":1,"confirmed":0})
    with db.get_conn() as conn:
      operations=conn.execute("SELECT requested_state,outcome FROM card_control_operations WHERE user_id=%s ORDER BY requested_state",(self.owner,)).fetchall()
      self.assertEqual(operations,[{"requested_state":"CLOSED","outcome":"unknown"},{"requested_state":"PAUSED","outcome":"confirmed"}])

  def test_actual_http_sse_reconnect_replays_without_starting_runs(self):
    import threading
    import time
    import httpx
    import uvicorn
    trace = self.registered_trace()
    self.assertEqual(self.request("POST","/provenance",body=trace).status_code,201)
    history=self.request("GET","/activity",token=self.user_token).json()["events"]
    before=len(history)
    cursor=history[-2]["sequence"]
    server=uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=0,log_level="error",timeout_graceful_shutdown=1))
    thread=threading.Thread(target=server.run,daemon=True)
    thread.start()
    try:
      deadline=time.monotonic()+5
      while not server.started and time.monotonic()<deadline:
        time.sleep(0.02)
      self.assertTrue(server.started)
      port=server.servers[0].sockets[0].getsockname()[1]
      with httpx.Client(base_url=f"http://127.0.0.1:{port}",timeout=3) as client:
        headers={"Authorization":"Bearer "+self.user_token,"Last-Event-ID":str(cursor)}
        with client.stream("GET","/activity/stream",headers=headers) as response:
          self.assertEqual(response.status_code,200)
          frames=[]
          for line in response.iter_lines():
            frames.append(line)
            if line.startswith("data:") and trace["event_id"] in line:
              break
        self.assertIn("id: "+str(history[-1]["sequence"]),frames)
        self.assertEqual(client.get("/activity/stream",headers={**headers,"Last-Event-ID":"bad"}).status_code,422)
        self.assertEqual(client.get("/activity/stream").status_code,401)
      self.assertEqual(len(self.request("GET","/activity",token=self.user_token).json()["events"]),before)
    finally:
      server.should_exit=True
      thread.join(3)
      self.assertFalse(thread.is_alive())

  def test_agent_cannot_use_any_human_mutation_or_history_route(self):
    draft = self.draft()
    for method,path,body in [
      ("POST",f'/mandates/{draft["id"]}/approve',{**self.binding(draft),"confirmed":True}),
      ("PATCH",f'/mandates/{draft["id"]}',{**self.binding(draft),"proposal":self.proposal}),
      ("POST",f'/mandates/{draft["id"]}/revoke',self.binding(draft)),
      ("GET",f'/mandates/{draft["id"]}/versions',None),
    ]:
      with self.subTest(path=path):
        self.assertEqual(self.request(method,path,body=body).status_code,401)
    self.assertEqual(self.request("POST","/mandates/propose",token=self.user_token,body=self.proposal).status_code,401)
    self.assertEqual(self.request("POST","/agent-runs",token=self.user_token,body=self.run_body(draft)).status_code,401)

  def test_cross_owner_and_cross_agent_access_are_denied(self):
    draft = self.draft()
    for token in (self.other_agent_token,self.other_user_token):
      self.assertEqual(self.request("GET",f'/mandates/{draft["id"]}',token=token).status_code,404)
      self.assertNotIn(draft["id"],self.request("GET","/mandates",token=token).text)
    self.assertEqual(self.request("POST",f'/mandates/{draft["id"]}/approve',token=self.other_user_token,
                      body={**self.binding(draft),"confirmed":True}).status_code,404)
    with db.get_conn() as conn:
      same_owner_agent="agt_"+uuid4().hex
      same_owner_token="same-owner-agent-"+uuid4().hex
      bind_agent(conn,user_id=self.owner,agent_id=same_owner_agent,token=same_owner_token,modes=("live",))
    self.assertEqual(self.request("GET",f'/mandates/{draft["id"]}',token=same_owner_token).status_code,404)

  def test_approval_is_hash_bound_signed_and_idempotent(self):
    draft = self.draft()
    bad = self.request("POST",f'/mandates/{draft["id"]}/approve',token=self.user_token,
                      body={"version":1,"canonical_payload_hash":"0"*64,"confirmed":True})
    self.assertEqual(bad.status_code,409)
    active = self.active(draft)
    self.assertEqual(active["canonical_payload_hash"],draft["canonical_payload_hash"])
    self.assertTrue(active["signature"])
    self.assertEqual(self.active(draft),active)
    items=self.request("GET","/mandates?status=active").json()["items"]
    self.assertIn(active,items)
    with db.get_conn() as conn:
      self.assertEqual(conn.execute("SELECT count(*) AS n FROM mandate_confirmations WHERE mandate_id=%s",(draft["id"],)).fetchone()["n"],1)
      self.assertEqual(conn.execute("SELECT count(*) AS n FROM audit_events WHERE record->'data'->>'mandate_id'=%s",(draft["id"],)).fetchone()["n"],2)

  def test_missing_signing_key_rolls_back_confirmation_and_audit(self):
    draft = self.draft()
    with patch.dict(os.environ,{"MANDATE_SIGNING_KEY":""}):
      response = self.request("POST",f'/mandates/{draft["id"]}/approve',token=self.user_token,
                              body={**self.binding(draft),"confirmed":True})
    self.assertEqual(response.status_code,503)
    with db.get_conn() as conn:
      self.assertEqual(conn.execute("SELECT count(*) AS n FROM mandate_confirmations WHERE mandate_id=%s",(draft["id"],)).fetchone()["n"],0)
    self.assertEqual(self.request("GET",f'/mandates/{draft["id"]}').json()["status"],"proposed")

  def test_replacement_preserves_signed_history_and_needs_fresh_confirmation(self):
    active=self.active()
    response=self.request("PATCH",f'/mandates/{active["id"]}',token=self.user_token,
                           body={**self.binding(active),"proposal":{**self.proposal,"max_cents":2999}})
    self.assertEqual(response.status_code,200,response.text)
    draft=response.json()
    self.assertEqual(draft["version"],2)
    self.assertEqual(draft["status"],"proposed")
    self.assertIsNone(draft["signature"])
    self.assertNotEqual(draft["canonical_payload_hash"],active["canonical_payload_hash"])
    self.assertEqual(self.request("POST",f'/mandates/{active["id"]}/approve',token=self.user_token,
                                 body={**self.binding(active),"confirmed":True}).status_code,409)
    history=self.request("GET",f'/mandates/{active["id"]}/versions',token=self.user_token).json()["items"]
    self.assertEqual([v["status"] for v in history],["superseded","proposed"])
    self.assertEqual(history[0]["signature"],active["signature"])
    self.assertEqual(self.active(draft)["version"],2)

  def test_revocation_stops_run_registration_and_cannot_be_reapproved(self):
    active=self.active()
    response=self.request("POST",f'/mandates/{active["id"]}/revoke',token=self.user_token,body=self.binding(active))
    self.assertEqual(response.status_code,200)
    self.assertEqual(response.json()["status"],"revoked")
    self.assertEqual(self.request("POST","/agent-runs",body=self.run_body(active)).status_code,409)
    self.assertEqual(self.request("POST",f'/mandates/{active["id"]}/approve',token=self.user_token,
                                 body={**self.binding(active),"confirmed":True}).status_code,409)

  def test_expiry_and_future_start_fail_closed(self):
    now=utc_now()
    future=self.active(self.draft({**self.proposal,"valid_from":(now+timedelta(hours=1)).isoformat(),
                                   "valid_until":(now+timedelta(hours=2)).isoformat()}))
    self.assertEqual(self.request("POST","/agent-runs",body=self.run_body(future)).status_code,409)
    self.assertNotIn(future["id"],self.request("GET","/mandates?status=active").text)
    draft=self.draft({**self.proposal,"valid_until":(now+timedelta(minutes=1)).isoformat()})
    with patch("mandate_routes.utc_now",return_value=now+timedelta(minutes=2)), patch("mandate_service.utc_now",return_value=now+timedelta(minutes=2)):
      self.assertEqual(self.request("GET",f'/mandates/{draft["id"]}').json()["status"],"expired")
      self.assertEqual(self.request("POST",f'/mandates/{draft["id"]}/approve',token=self.user_token,
                                   body={**self.binding(draft),"confirmed":True}).status_code,409)

  def test_confirmation_rechecks_expiry_after_lock_acquisition(self):
    now=utc_now()
    draft=self.draft({**self.proposal,"valid_until":(now+timedelta(minutes=1)).isoformat()})
    # Simulate an expiry crossed while waiting for the mandate lock.
    with patch("mandate_routes.utc_now",return_value=now), patch("mandate_service.utc_now",return_value=now+timedelta(minutes=2)):
      response=self.request("POST",f'/mandates/{draft["id"]}/approve',token=self.user_token,
                            body={**self.binding(draft),"confirmed":True})
    self.assertEqual(response.status_code,409)

  def test_demo_token_is_human_only_and_separate_from_agent_credentials(self):
    demo="isolated-demo-user-"+uuid4().hex
    with patch.dict(os.environ,{"USER_TOKEN":demo,"DEMO_USER_ID":"usr_demo_test"}):
      response=self.request("GET","/identity",token=demo)
      self.assertEqual(response.json()["user_id"],"usr_demo_test")
      self.assertEqual(self.request("POST","/mandates/propose",token=demo,body=self.proposal).status_code,401)
      self.assertEqual(self.request("GET",f'/mandates/{self.draft()["id"]}',token=demo).status_code,404)

  def test_readiness_requires_successful_migrations_and_live_database(self):
    with patch.dict(os.environ,{"DATABASE_URL":TEST_DSN}):
      with TestClient(app) as client:
        self.assertEqual(client.get("/readyz").status_code,200)
        with patch("db.get_conn",side_effect=psycopg.OperationalError("private connection details")):
          response=client.get("/readyz")
        self.assertEqual(response.status_code,503)
        self.assertNotIn("private",response.text)

  def test_registration_echoes_server_binding_and_rejects_changed_retries(self):
    with db.get_conn() as conn:
      bind_agent(conn,user_id=self.owner,agent_id=self.agent_id,token=self.agent_token,modes=("scripted",))
    active=self.active()
    body=self.run_body(active,"scripted")
    response=self.request("POST","/agent-runs",body=body)
    self.assertEqual(response.status_code,201,response.text)
    run=response.json()
    for key,value in {"user_id":self.owner,"agent_id":self.agent_id,"mandate_version":1,
                      "mandate_hash":active["canonical_payload_hash"],"agent_mode":"scripted"}.items():
      self.assertEqual(run[key],value)
    self.assertEqual(self.request("POST","/agent-runs",body=body).json(),run)
    self.assertEqual(self.request("POST","/agent-runs",body={**body,"agent_mode":"live"}).status_code,403)
    self.assertEqual(self.request("POST","/agent-runs",body={**body,"model":"different"}).status_code,409)
    self.assertEqual(self.request("POST","/agent-runs",body={**body,"user_id":self.other_owner}).status_code,422)
    self.request("POST",f'/mandates/{active["id"]}/revoke',token=self.user_token,body=self.binding(active))
    self.assertEqual(self.request("POST","/agent-runs",body=body).status_code,409)

  def test_proposed_mandate_or_unauthorized_mode_cannot_start_run(self):
    draft=self.draft()
    self.assertEqual(self.request("POST","/agent-runs",body=self.run_body(draft)).status_code,409)
    with db.get_conn() as conn:
      bind_agent(conn,user_id=self.owner,agent_id=self.agent_id,token=self.agent_token,modes=("live",))
    self.assertEqual(self.request("POST","/agent-runs",body=self.run_body(draft,"scripted")).status_code,403)

  def test_agent_binding_does_not_move_owner_and_rotation_disables_old_token(self):
    with self.assertRaises(AuthorityError), db.get_conn() as conn:
      bind_agent(conn,user_id=self.other_owner,agent_id=self.agent_id,token=self.agent_token,modes=("live",))
    new_token="rotated-credential-"+uuid4().hex
    with db.get_conn() as conn:
      bind_agent(conn,user_id=self.owner,agent_id=self.agent_id,token=new_token,modes=("live",))
    self.assertEqual(self.request("GET","/mandates").status_code,401)
    self.assertEqual(self.request("GET","/mandates",token=new_token).status_code,200)

  def test_immutable_sql_history_rejects_update_and_delete(self):
    active=self.active()
    self.request("POST","/agent-runs",body=self.run_body(active))
    for table in ("mandate_versions","mandate_confirmations","mandate_transitions","agent_runs","audit_events"):
      for verb in ("UPDATE","DELETE"):
        with self.subTest(table=table,verb=verb), self.assertRaises(psycopg.errors.CheckViolation), db.get_conn() as conn:
          statement=(f"UPDATE {table} SET " + ("record=record" if table!="mandate_transitions" else "status=status")) if verb=="UPDATE" else f"DELETE FROM {table}"
          conn.execute(statement)

  def test_transaction_rollback_leaves_no_partial_draft_or_events(self):
    with db.get_conn() as conn:
      before=conn.execute("SELECT count(*) AS n FROM mandate_heads").fetchone()["n"]
    with patch("mandate_service.audit",side_effect=AuthorityError(503,"simulated audit outage")):
      self.assertEqual(self.request("POST","/mandates/propose",body=self.proposal).status_code,503)
    with db.get_conn() as conn:
      self.assertEqual(conn.execute("SELECT count(*) AS n FROM mandate_heads").fetchone()["n"],before)

  def test_two_concurrent_confirmations_return_one_signature_and_event(self):
    draft=self.draft()
    barrier=Barrier(2)
    def confirm():
      barrier.wait(timeout=5)
      with TestClient(app) as client:
        return client.post(f'/mandates/{draft["id"]}/approve',headers={"Authorization":"Bearer "+self.user_token},
                           json={**self.binding(draft),"confirmed":True})
    with ThreadPoolExecutor(max_workers=2) as pool:
      responses=list(pool.map(lambda _:confirm(),range(2)))
    self.assertEqual([r.status_code for r in responses],[200,200])
    self.assertEqual(responses[0].json(),responses[1].json())

  def test_two_concurrent_replacements_cannot_both_use_old_version(self):
    active=self.active()
    barrier=Barrier(2)
    def replacement(amount):
      barrier.wait(timeout=5)
      # No startup hooks here; use the real app/SQL routes and separate connections.
      client=TestClient(app)
      try:
        return client.patch(f'/mandates/{active["id"]}',headers={"Authorization":"Bearer "+self.user_token},
                             json={**self.binding(active),"proposal":{**self.proposal,"max_cents":amount}})
      finally:
        client.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
      responses=list(pool.map(replacement,[2999,3500]))
    self.assertEqual(sorted(r.status_code for r in responses),[200,409])

  def test_human_draft_only_uses_existing_operator_provisioned_live_agent(self):
    response = self.request("POST", "/mandates/draft", token=self.user_token, body=self.proposal)
    self.assertEqual(response.status_code, 201, response.text)
    self.assertEqual(response.json()["agent_id"], self.agent_id)
    self.assertEqual(response.json()["status"], "proposed")
    self.assertIsNone(response.json()["signature"])
    with db.get_conn() as conn:
      conn.execute("UPDATE leash_agents SET enabled=false WHERE id=%s", (self.agent_id,))
      before = conn.execute("SELECT count(*) AS n FROM leash_agents").fetchone()["n"]
    with patch.dict(os.environ, {"AGENT_TOKEN_SHOPPER": "unclaimed-deployment-token-"+"x"*32}):
      denied = self.request("POST", "/mandates/draft", token=self.user_token, body=self.proposal)
    self.assertEqual(denied.status_code, 409)
    with db.get_conn() as conn:
      self.assertEqual(conn.execute("SELECT count(*) AS n FROM leash_agents").fetchone()["n"], before)

  def test_human_draft_rejects_scripted_only_and_ambiguous_live_bindings(self):
    with db.get_conn() as conn:
      conn.execute("UPDATE leash_agents SET allowed_modes='[\"scripted\"]' WHERE id=%s", (self.agent_id,))
    self.assertEqual(self.request("POST", "/mandates/draft", token=self.user_token, body=self.proposal).status_code, 409)
    with db.get_conn() as conn:
      conn.execute("UPDATE leash_agents SET allowed_modes='[\"live\"]' WHERE id=%s", (self.agent_id,))
      bind_agent(conn, user_id=self.owner, agent_id="agt_second_"+uuid4().hex,
                 token="second-live-token-"+uuid4().hex, modes=("live",))
    self.assertEqual(self.request("POST", "/mandates/draft", token=self.user_token, body=self.proposal).status_code, 409)

  def test_human_purchase_history_and_immutable_evidence_are_owner_scoped(self):
    from test_payment_service import _store_checkout
    active, run, body = self.payment_setup()
    with patch("payment_service._fetch_store_checkout", return_value=_store_checkout()):
      attempt = self.payment_direct(body)
    history = self.request("GET", "/purchase-attempts", token=self.user_token)
    self.assertEqual(history.status_code, 200, history.text)
    self.assertEqual(history.json()["attempts"][0]["id"], attempt.id)
    detail = self.request("GET", f"/purchase-attempts/{attempt.id}", token=self.user_token)
    self.assertEqual(detail.status_code, 200, detail.text)
    record = detail.json()
    self.assertEqual(record["mandate"]["canonical_payload_hash"], active["canonical_payload_hash"])
    self.assertEqual(record["observation"]["checkout"]["items"][0]["sku"], "CHG-65W")
    self.assertEqual(record["evidence_status"], "observed_unverified")
    self.assertFalse(record["attempt"]["financial_authority"])
    self.assertFalse(record["observation"]["assessment"]["financial_authority"])
    self.assertEqual(detail.headers["cache-control"], "no-store")
    for private in ("grant_reference", "instrument_reference", "issuance_key", "authorization_event_id", "token_sha256"):
      self.assertNotIn(private, detail.text)
    self.assertEqual(self.request("GET", f"/purchase-attempts/{attempt.id}", token=self.other_user_token).status_code, 404)
    self.assertEqual(self.request("GET", "/purchase-attempts", token=self.other_user_token).json()["attempts"], [])
    self.assertEqual(self.request("GET", "/purchase-attempts", token=self.agent_token).status_code, 401)
    self.assertEqual(self.request("GET", f"/purchase-attempts?before={attempt.id}", token=self.other_user_token).status_code, 404)

  def test_purchase_history_cursor_and_missing_observation_are_truthful(self):
    from test_payment_service import _store_checkout
    active, run, body = self.payment_setup()
    with patch("payment_service._fetch_store_checkout", return_value=_store_checkout()):
      first = self.payment_direct(body)
    second_body = {**body, "checkout_id": "ckt_second"}
    import hashlib
    from leash_shared.models import canonical_json
    source = _store_checkout()
    source["checkout_id"] = "ckt_second"
    fields = ("checkout_id", "currency", "line_items", "mcc", "merchant_descriptor", "recurring", "total_cents")
    source["facts_hash"] = hashlib.sha256(canonical_json({key: source[key] for key in fields}).encode()).hexdigest()
    with patch("payment_service._fetch_store_checkout", return_value=source):
      second = self.payment_direct(second_body)
    first_page = self.request("GET", "/purchase-attempts?limit=1", token=self.user_token).json()
    self.assertEqual(first_page["attempts"][0]["id"], second.id)
    self.assertEqual(first_page["next_cursor"], second.id)
    next_page = self.request("GET", f"/purchase-attempts?limit=1&before={second.id}", token=self.user_token).json()
    self.assertEqual(next_page["attempts"][0]["id"], first.id)
    self.assertIsNone(next_page["next_cursor"])
    self.crash_preflight({**body, "checkout_id": "ckt_prepared"})
    with db.get_conn() as conn:
      prepared = conn.execute("SELECT id FROM payment_operations WHERE run_id=%s AND state='prepared'", (run["id"],)).fetchone()
    detail = self.request("GET", f'/purchase-attempts/{prepared["id"]}', token=self.user_token).json()
    self.assertIsNone(detail["observation"])
    self.assertEqual(detail["evidence_status"], "not_observed")
    self.assertEqual(detail["attempt"]["state"], "prepared")


if __name__ == "__main__":
  unittest.main()
