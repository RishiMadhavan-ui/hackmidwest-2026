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
      self.assertEqual(first.json()["reasons"], ["financial_authority_unavailable"])
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


if __name__ == "__main__":
  unittest.main()
