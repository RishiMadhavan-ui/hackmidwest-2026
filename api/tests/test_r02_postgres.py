"""Actual SQL/HTTP tests against an explicitly selected disposable local database."""

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
from pathlib import Path
import sys
from threading import Barrier
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

  def test_restart_safe_migration_and_uuid_identity_mapping(self):
    db.init_db()
    response = self.request("GET","/identity",token=self.user_token)
    self.assertEqual(response.json(),{"user_id":self.owner,"role":"human"})
    with db.get_conn() as conn:
      self.assertEqual(conn.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"],3)
      mapping=conn.execute("SELECT id FROM leash_users WHERE auth_user_id=%s",(self.legacy_auth_id,)).fetchone()
      self.assertEqual(mapping["id"],leash_user_id(str(self.legacy_auth_id)))

  def test_signup_login_identity_and_legacy_me_keep_uuid(self):
    email = uuid4().hex + "@example.com"
    # Exercise current signup/SQL identity mapping without reaching Lithic.
    with patch("auth.create_account_holder", return_value={
      "account_token":"fixture-account", "account_holder_token":"fixture-holder"}), \
        patch("auth.create_virtual_card", return_value={
          "card_token":"fixture-card", "last_four":"1234", "spend_limit_cents":50000}):
      response = self.client.post("/auth/signup",json={"email":email,"password":"r02-password-valid",
        "first_name":"Demo", "last_name":"User", "postal_code":"64101", "spend_limit_cents":50000})
    self.assertEqual(response.status_code,201,response.text)
    payload = response.json()
    identity = self.request("GET","/identity",token=payload["access_token"])
    self.assertEqual(identity.json()["user_id"],leash_user_id(payload["user"]["id"]))
    self.assertEqual(self.request("GET","/auth/me",token=payload["access_token"]).json()["id"],payload["user"]["id"])
    self.assertEqual(self.client.post("/auth/login",json={"email":email,"password":"r02-password-valid"}).status_code,200)
    self.assertEqual(self.client.post("/auth/login",json={"email":email,"password":"wrong"}).status_code,401)

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


if __name__ == "__main__":
  unittest.main()
