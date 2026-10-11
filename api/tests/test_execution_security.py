"""Real PostgreSQL/HTTP boundaries; rail transport doubles, no live funds."""

from datetime import timedelta
import hashlib
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_r02_postgres as fixture
from execution import worker_credential
from leash_shared.models import canonical_json
from principals import Principal, token_digest

db = fixture.db


@unittest.skipUnless(fixture.TEST_DSN, "Requires disposable localhost PostgreSQL")
class ExecutionSecurityTests(unittest.TestCase):
  setUpClass = classmethod(fixture.PostgresAuthorityTests.setUpClass.__func__)
  tearDownClass = classmethod(fixture.PostgresAuthorityTests.tearDownClass.__func__)
  tearDown = fixture.PostgresAuthorityTests.tearDown
  request = fixture.PostgresAuthorityTests.request
  active = fixture.PostgresAuthorityTests.active
  draft = fixture.PostgresAuthorityTests.draft
  binding = fixture.PostgresAuthorityTests.binding

  def setUp(self):
    fixture.PostgresAuthorityTests.setUp(self)
    env = patch.dict(os.environ, {"LEASH_EXECUTION_ENABLED":"1", "STORE_URL":"http://store.test",
      "STORE_API_TOKEN":"store-"+"s"*40, "MERCHANT_BACKEND_TOKEN":"merchant-"+"m"*40,
      "WEBHOOK_URL":"http://rail.test", "WEBHOOK_INTERNAL_TOKEN":"rail-"+"r"*40,
      "AGENTS_SERVICE_TOKEN":"service-"+"x"*40})
    env.start(); self.addCleanup(env.stop)
    self.epoch = uuid4().hex
    self.rail_calls = []
    def rail(method, path, body=None):
      self.rail_calls.append((method,path,body))
      if path.endswith("/epoch"):
        return {"epoch": self.epoch}
      if path.endswith("/lease"):
        return {"epoch": self.epoch, "run_id":body["run_id"]}
      if path.endswith("/grants"):
        return {"epoch":self.epoch,"grant_id":body["grant"]["grant_id"]}
      return {"epoch":self.epoch,"found":False}
    for target in ("execution.rail", "purchase_execution.rail"):
      mock = patch(target, side_effect=rail); mock.start(); self.addCleanup(mock.stop)

  def launched(self):
    mandate = self.active()
    result = self.request("POST","/agent-runs/launch",token=self.user_token,
      body={"mandate_id":mandate["id"], **self.binding(mandate),"confirmed":True})
    self.assertEqual(result.status_code,201,result.text)
    run = result.json()
    private = worker_credential(run["run_id"], Principal("human",self.owner))
    self.worker_token = private["agent_credential"]
    worker = "worker_"+uuid4().hex
    response = self.request("POST",f'/agent-runs/{run["run_id"]}/execution/claim', token=self.worker_token,
      body={"protocol":"execution-v1", "worker_id":worker,"launch_id":run["launch_id"]})
    self.assertEqual(response.status_code,200,response.text)
    lease = response.json()
    self.scopes = {aud: {"x-leash-run-id":run["run_id"], "x-leash-worker-id":worker,
      "x-leash-generation":"1", "x-leash-execution-token":token} for aud,token in lease["scope_tokens"].items()}
    return mandate, run, worker

  def facts(self, sku="CHG-65W", category="laptop_charger", subscription=False):
    cid="ckt_"+uuid4().hex
    facts={"checkout_id":cid,"currency":"USD","merchant_descriptor":"VOLT SUPPLY CO","mcc":"5732",
      "line_items":[{"product_id":"voltcare" if subscription else "chg-65w", "sku":sku,
        "name":"VoltCare" if subscription else "USB-C charger", "price_cents":2999,"quantity":1,
        "category":category,"subscription":subscription,"recurring":subscription,
        "billing_interval":"monthly" if subscription else None,
        "attributes": [] if subscription else [{"name":"connector","value":"USB-C"}]}],
      "total_cents":2999,"recurring":subscription,"status":"open"}
    fields=("checkout_id","currency","line_items","mcc","merchant_descriptor","recurring","total_cents")
    facts["facts_hash"]=hashlib.sha256(canonical_json({key:facts[key] for key in fields}).encode()).hexdigest()
    return facts

  def pay(self, mandate, run, facts):
    headers={"Authorization":"Bearer "+os.environ["MERCHANT_BACKEND_TOKEN"],**self.scopes["mcp-store"]}
    res=self.client.post("/internal/merchant/checkouts",headers=headers,json={"facts":facts})
    self.assertEqual(res.status_code,201,res.text)
    frozen=res.json()
    with patch("purchase_execution._merchant_facts",return_value=frozen):
      res=self.client.post("/payments", headers={"Authorization":"Bearer "+self.worker_token,
        **self.scopes["mcp-leash"]}, json={"mandate_id":mandate["id"],"run_id":run["run_id"],"checkout_id":facts["checkout_id"]})
    self.assertEqual(res.status_code,200,res.text)
    return res.json()

  def test_new_humans_draft_without_rebinding_the_cluster_token(self):
    with db.get_conn() as conn:
      conn.execute("UPDATE leash_agents SET enabled=false WHERE id=%s",(self.agent_id,))
    with patch.dict(os.environ,{"AGENT_TOKEN_SHOPPER":self.other_agent_token}):
      draft=self.request("POST","/mandates/draft",token=self.user_token,body=self.proposal)
    self.assertEqual(draft.status_code,201,draft.text)
    self.assertNotEqual(draft.json()["agent_id"],self.other_agent_id)
    with db.get_conn() as conn:
      other=conn.execute("SELECT user_id,token_sha256 FROM leash_agents WHERE id=%s",(self.other_agent_id,)).fetchone()
      self.assertEqual(other["user_id"],self.other_owner)
      self.assertEqual(other["token_sha256"],token_digest(self.other_agent_token))

  def test_expiring_worker_is_run_bound_and_cannot_confirm_or_register_authority(self):
    mandate, run, worker=self.launched()
    claim={"protocol":"execution-v1","worker_id":worker,"launch_id":run["launch_id"]}
    self.assertEqual(self.request("POST",f'/agent-runs/{run["run_id"]}/execution/claim',token=self.worker_token,body=claim).status_code,409)
    self.assertEqual(self.request("POST",f'/mandates/{mandate["id"]}/approve',token=self.worker_token,
      body={**self.binding(mandate),"confirmed":True}).status_code,401)
    self.assertEqual(self.request("POST","/agent-runs",token=self.worker_token,
      body={"id":"run_other","mandate_id":mandate["id"],"agent_mode":"live"}).status_code,403)
    self.assertEqual(self.request("POST","/agent-runs/run_other/execution/heartbeat",token=self.worker_token,
      body={"worker_id":worker,"generation":1}).status_code,403)
    with db.get_conn() as conn:
      conn.execute("UPDATE run_credentials SET expires_at=now()-interval '1 second' WHERE run_id=%s",(run["run_id"],))
    self.assertEqual(self.request("POST",f'/agent-runs/{run["run_id"]}/execution/heartbeat',token=self.worker_token,
      body={"worker_id":worker,"generation":1}).status_code,401)

  def test_audiences_cross_owner_and_missing_scope_never_create_financial_authority(self):
    mandate,run,_=self.launched()
    body={"mandate_id":mandate["id"],"run_id":run["run_id"],"checkout_id":"ckt_missing"}
    result=self.client.post("/payments",headers={"Authorization":"Bearer "+self.other_agent_token,
      **self.scopes["mcp-leash"]},json=body)
    self.assertEqual(result.status_code,404)
    result=self.client.post("/payments",headers={"Authorization":"Bearer "+self.worker_token,
      **self.scopes["mcp-store"]},json=body)
    self.assertEqual(result.status_code,403)
    with patch("payment_service._fetch_store_checkout",return_value=self.facts()), patch("payment_service._seed_grant") as seed:
      result=self.request("POST","/payments",token=self.worker_token,body=body)
    self.assertNotEqual(result.json().get("status"),"approved")
    seed.assert_not_called()
    self.assertFalse(any(path.endswith('/grants') for _,path,_ in self.rail_calls))

  def test_same_merchant_amount_subscription_blocks_then_clean_checkout_gets_scoped_grant(self):
    mandate,run,_=self.launched()
    attack=self.pay(mandate,run,self.facts("SUB-CARE-MO","protection_plan",True))
    self.assertEqual(attack["status"],"blocked")
    self.assertIsNone(attack["grant_id"])
    before=len(self.rail_calls)
    valid=self.pay(mandate,run,self.facts("CHG-65W-SAFE"))
    self.assertEqual(valid["status"],"approved")
    self.assertTrue(any(path.endswith('/grants') for _,path,_ in self.rail_calls[before:]))
    self.assertEqual(self.request("GET",f'/mandates/{mandate["id"]}',token=self.user_token).json()["canonical_payload_hash"],mandate["canonical_payload_hash"])
    detail=self.request("GET",f'/purchase-attempts/{valid["id"]}',token=self.user_token)
    self.assertEqual(detail.status_code,200,detail.text)
    self.assertEqual(detail.json()["attempt"]["state"],"ready")
    self.assertEqual(detail.json()["evidence_status"],"merchant_owned_frozen")
    self.assertEqual(detail.json()["attempt"]["authorization_status"],"unverified")

  def test_stop_ack_persists_and_other_users_cannot_stop_or_read_execution(self):
    _,run,worker=self.launched()
    path=f'/agent-runs/{run["run_id"]}'
    self.assertEqual(self.request("GET",path+"/execution",token=self.other_user_token).status_code,404)
    self.assertEqual(self.request("POST",path+"/stop",token=self.other_user_token).status_code,404)
    with patch("workflow_control.stop_rail_run",return_value={"status":"enforced","unused_grants_revoked":0}):
      stopped=self.request("POST",path+"/stop",token=self.user_token)
    self.assertEqual(stopped.status_code,200,stopped.text)
    self.assertEqual(self.request("GET",path+"/stop",token=self.user_token).json()["financial_revocation"],"enforced")
    self.assertEqual(self.request("POST",path+"/execution/heartbeat",token=self.worker_token,
      body={"worker_id":worker,"generation":1}).status_code,409)

  def test_authenticated_natural_interpretation_preserves_existing_identity(self):
    result = self.request("POST","/mandates/interpret",token=self.user_token,
      body={"instruction":"Buy me a computer charger under $40. No subscriptions."})
    self.assertEqual(result.status_code,200,result.text)
    self.assertEqual(result.json()["proposal"]["max_cents"],3999)
    with db.get_conn() as conn:
      self.assertEqual(str(conn.execute("SELECT auth_user_id FROM leash_users WHERE id=%s",(self.owner,)).fetchone()["auth_user_id"]),str(self.auth_id))

  def test_owner_reconciles_original_event_and_never_submits_a_charge(self):
    from purchase_execution import authorization_payload, move
    mandate,run,_ = self.launched()
    payment = self.pay(mandate,run,self.facts())
    with db.get_conn() as conn:
      op = conn.execute("SELECT * FROM payment_operations WHERE id=%s",(payment["id"],)).fetchone()
      activation = conn.execute("SELECT * FROM payment_activations WHERE payment_id=%s",(payment["id"],)).fetchone()
      op = move(conn,op,"authorizing","test_original_outcome_lost")
    payload = {**authorization_payload(op,activation),"event_scope":"local"}
    cached = {"epoch":self.epoch,"found":True,"fingerprint":hashlib.sha256(canonical_json(payload).encode()).hexdigest(),
      "decision":{"result":"APPROVED","reason":"approved","rail":"local_payment_rail_simulator"}}
    self.assertEqual(self.request("POST",f'/purchase-attempts/{payment["id"]}/reconcile',token=self.other_user_token).status_code,404)
    with patch("purchase_execution.rail",return_value=cached) as readback:
      result = self.request("POST",f'/purchase-attempts/{payment["id"]}/reconcile',token=self.user_token)
      self.assertEqual(result.status_code,200,result.text)
      self.assertEqual(result.json()["authorization_status"],"authorized")
      again = self.request("POST",f'/purchase-attempts/{payment["id"]}/reconcile',token=self.user_token)
      self.assertEqual(again.json()["state"],"authorized")
      self.assertEqual(readback.call_count,1)
      self.assertEqual(readback.call_args.args[0],"GET")

  def test_background_expiry_revokes_before_absent_event_is_cancelled(self):
    from reconciliation import reconcile_run
    mandate,run,_ = self.launched()
    payment = self.pay(mandate,run,self.facts())
    with db.get_conn() as conn:
      conn.execute("UPDATE run_executions SET lease_until=now()-interval '1 second' WHERE run_id=%s",(run["run_id"],))
    def rail(method,path,body=None):
      if method == "POST":
        return {**body,"financial_revocation":"enforced"}
      return {"epoch":self.epoch,"found":False}
    with patch("reconciliation.rail",side_effect=rail),patch("purchase_execution.rail",side_effect=rail):
      reconcile_run(run["run_id"])
    with db.get_conn() as conn:
      self.assertEqual(conn.execute("SELECT state FROM payment_operations WHERE id=%s",(payment["id"],)).fetchone()["state"],"cancelled")
      self.assertIsNotNone(conn.execute("SELECT rail_stopped_at FROM run_executions WHERE run_id=%s",(run["run_id"],)).fetchone()["rail_stopped_at"])

  def test_expired_unclaimed_launch_becomes_terminal_without_graph_ack(self):
    from reconciliation import reconcile_run
    mandate = self.active()
    launched = self.request("POST", "/agent-runs/launch", token=self.user_token,
      body={"mandate_id":mandate["id"],**self.binding(mandate),"confirmed":True})
    self.assertEqual(launched.status_code,201,launched.text)
    run_id = launched.json()["run_id"]
    with db.get_conn() as conn:
      conn.execute("UPDATE run_executions SET deadline=now()-interval '1 second' WHERE run_id=%s",(run_id,))
    with patch("reconciliation.rail",return_value={"run_id":run_id,"user_id":self.owner,"financial_revocation":"enforced"}):
      reconcile_run(run_id)
    status = self.request("GET",f'/agent-runs/{run_id}/execution',token=self.user_token).json()
    self.assertEqual(status["state"],"terminal")
    self.assertFalse(status["graph_acknowledged"])
    self.assertTrue(status["rail_stopped"])
