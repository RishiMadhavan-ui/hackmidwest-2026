"""Opt-in real SDK Graph + HTTP MCP/store/API + PostgreSQL + Redis acceptance.

Only the model is scripted. Every boundary and financial transition is real;
this does not claim live inference, Lithic, or deployed Kubernetes behavior.
"""

import base64
from contextlib import ExitStack
import os
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_r02_postgres as fixture
import httpx
from nacl.signing import SigningKey
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import uvicorn

ROOT=Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.getenv("LEASH_TEST_STACK")=="1", "Enable isolated local Graph acceptance explicitly")
class GraphStackTests(unittest.TestCase):
  def test_signature_attack_recovers_and_authorizes_through_real_mcp_and_rail(self):
    dsn=fixture.TEST_DSN
    redis=os.getenv("LEASH_TEST_VALKEY_URL","")
    params=conninfo_to_dict(dsn)
    if params.get("host") != "127.0.0.1" or not params.get("dbname","").startswith("leash_test") or redis != "redis://127.0.0.1:56379/15":
      raise RuntimeError("Refusing acceptance outside dedicated localhost test databases")
    schema="graph_test_"+uuid4().hex
    with fixture.psycopg.connect(dsn) as conn:
      conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    secret=lambda: uuid4().hex+uuid4().hex
    service,merchant,store_api,store_charge,store_mcp,rail_control,rail_charge,event_token=[secret() for _ in range(8)]
    base={k:v for k,v in os.environ.items() if k.upper() in {"PATH","SYSTEMROOT","WINDIR","TEMP","TMP","APPDATA","LOCALAPPDATA","PATHEXT"}}
    api="http://127.0.0.1:58200"
    env={"DATABASE_URL":make_conninfo(dsn,options=f"-c search_path={schema}"),
      "LEASH_EXECUTION_ENABLED":"1", "AGENTS_URL":"http://127.0.0.1:58201", "AGENTS_SERVICE_TOKEN":service,
      "STORE_URL":"http://127.0.0.1:58204", "STORE_API_TOKEN":store_api,"STORE_CHARGE_TOKEN":store_charge,
      "MERCHANT_BACKEND_TOKEN":merchant,"WEBHOOK_URL":"http://127.0.0.1:58205","WEBHOOK_INTERNAL_TOKEN":rail_control,
      "RAIL_EVENT_TOKEN":event_token,"ATTACK_LAB_ENABLED":"1","USER_TOKEN":"",
      "MANDATE_SIGNING_KEY":base64.b64encode(bytes(SigningKey.generate())).decode()}
    children=[]; logs=[]; server=None; thread=None
    def ready(url):
      end=time.monotonic()+30
      while time.monotonic()<end:
        try:
          if httpx.get(url,timeout=1).status_code==200: return
        except httpx.HTTPError: pass
        for proc, log in zip(children,logs):
          if proc.poll() is not None:
            log.seek(0); message=log.read().decode(errors="replace")[-2500:]
            for value in (service,merchant,store_api,store_charge,store_mcp,rail_control,rail_charge,event_token):
              message=message.replace(value,"[REDACTED]")
            self.fail("Local service startup failed: "+message)
        time.sleep(.15)
      self.fail("Local service did not become ready: "+url)
    def child(path,port,settings):
      log=tempfile.TemporaryFile(); logs.append(log)
      proc=subprocess.Popen([str(ROOT/path/".venv/Scripts/python.exe"),"-m","uvicorn","main:app","--host","127.0.0.1","--port",str(port),"--log-level","warning"],
        cwd=ROOT/path,env={**base,"PYTHONUTF8":"1","PYTHONPATH":str(ROOT/"shared"),**settings},stdout=log,stderr=log)
      children.append(proc); ready(f"http://127.0.0.1:{port}/health")
    try:
      with ExitStack() as stack, tempfile.TemporaryDirectory(prefix="leash-test-trace-") as spool:
        stack.enter_context(patch.object(fixture.db,"DATABASE_URL",make_conninfo(dsn,options=f"-c search_path={schema}")))
        stack.enter_context(patch.object(fixture.auth,"JWT_SECRET",secret()))
        stack.enter_context(patch.dict(os.environ,env))
        fixture.db.init_db()
        server=uvicorn.Server(uvicorn.Config(fixture.app,host="127.0.0.1",port=58200,log_level="error",timeout_graceful_shutdown=1))
        thread=threading.Thread(target=server.run,daemon=True); thread.start(); ready(api+"/readyz")
        child(Path("services/webhook"),58205,{"VALKEY_URL":redis,"WEBHOOK_INTERNAL_TOKEN":rail_control,
          "WEBHOOK_CHARGE_TOKEN":rail_charge,"RAIL_EVENT_TOKEN":event_token,"API_URL":api})
        child(Path("services/store"),58204,{"LEASH_EXECUTION_ENABLED":"1","API_URL":api,
          "STORE_API_TOKEN":store_api,"STORE_CHARGE_TOKEN":store_charge,"MERCHANT_BACKEND_TOKEN":merchant,
          "WEBHOOK_URL":env["WEBHOOK_URL"],"WEBHOOK_CHARGE_TOKEN":rail_charge})
        child(Path("services/mcp-leash"),58202,{"API_URL":api})
        child(Path("services/mcp-store"),58203,{"API_URL":api,"STORE_URL":env["STORE_URL"],"STORE_API_TOKEN":store_api,
          "STORE_CHARGE_TOKEN":store_charge,"STORE_MCP_TOKEN":store_mcp})
        child(Path("services/agents"),58201,{"API_URL":api,"AGENTS_SERVICE_TOKEN":service,
          "MCP_LEASH_URL":"http://127.0.0.1:58202/mcp","MCP_STORE_URL":"http://127.0.0.1:58203/mcp",
          "STORE_URL":env["STORE_URL"],"STORE_MCP_TOKEN":store_mcp,"TRACE_SPOOL_DIR":spool})
        operator_id=uuid4(); user_id="usr_"+operator_id.hex
        with fixture.db.get_conn() as conn:
          conn.execute("INSERT INTO users(id,email,password_hash) VALUES (%s,%s,%s)",(operator_id,"local-graph-test@example.com","test-only"))
        token=fixture.auth.create_access_token(str(operator_id),"local-graph-test@example.com")
        stack.enter_context(patch.dict(os.environ,{"ATTACK_LAB_OPERATOR_USER_IDS":user_id,"ATTACK_LAB_OPERATOR_IDS":""}))
        headers={"Authorization":"Bearer "+token}
        with httpx.Client(base_url=api,headers=headers,timeout=15) as client:
          interpreted=client.post("/mandates/interpret",json={"instruction":"Buy me a computer charger under $40. No subscriptions."})
          self.assertEqual(interpreted.status_code,200,interpreted.text)
          proposal=interpreted.json()["proposal"]
          self.assertEqual(proposal["max_cents"],3999)
          human_draft=client.post("/mandates/draft",json=proposal)
          self.assertEqual(human_draft.status_code,201,human_draft.text)
          self.assertEqual(human_draft.json()["user_id"],user_id)
          response=client.post("/attack-lab/namespaces",json={})
          self.assertEqual(response.status_code,200,response.text)
          namespace=response.json()["namespace"]
          self.assertNotEqual(namespace["demo_user_id"],user_id)
          ns="/attack-lab/namespaces/"+namespace["id"]
          response=client.post(ns+"/control",json={"enabled":True,"expected_revision":namespace["revision"]})
          self.assertEqual(response.status_code,200,response.text)
          self.assertTrue(response.json()["execution_available"])
          response=client.post(ns+"/draft",json={"scenario":"signature_attack","mode":"scripted"})
          self.assertEqual(response.status_code,201,response.text)
          mandate=response.json()["mandate"]
          response=client.post(ns+"/execute",json={"mandate_id":mandate["id"],"version":mandate["version"],
            "canonical_payload_hash":mandate["canonical_payload_hash"],"confirmed":True})
          self.assertEqual(response.status_code,202,response.text)
          run_id=response.json()["run_id"]
          self.assertNotIn("credential",response.text)
          self.assertNotIn("launch_id",response.text)
          end=time.monotonic()+105
          while time.monotonic()<end:
            history=client.get(ns+"/history").json()
            if history["runs"] and history["runs"][0]["state"]=="terminal": break
            time.sleep(.2)
          history=client.get(ns+"/history").json()
          with httpx.Client() as internal:
            worker=internal.get(f'http://127.0.0.1:58201/runs/{run_id}',headers={"Authorization":"Bearer "+service}).json()
          self.assertEqual(worker["status"],"authorized", {"status":worker["status"],"error":worker.get("error"),"progress":history["runs"]})
          self.assertEqual(history["runs"][0]["progress"]["attempt"],2)
          self.assertEqual(sorted(item["state"] for item in history["attempts"]),["authorized","blocked"])
          with fixture.db.get_conn() as conn:
            record=conn.execute("SELECT record FROM mandate_confirmations WHERE mandate_id=%s",(mandate["id"],)).fetchone()["record"]
            self.assertEqual(record["canonical_payload_hash"],mandate["canonical_payload_hash"])
            outcomes=conn.execute("SELECT count(*) AS n FROM payment_outcomes p JOIN payment_operations o ON o.id=p.payment_id WHERE o.run_id=%s AND p.record->>'result'='APPROVED'",(run_id,)).fetchone()
            self.assertEqual(outcomes["n"],1)
            rows=conn.execute("SELECT record FROM audit_events WHERE user_id=%s AND record->'data'->>'lab_namespace_id'=%s ORDER BY sequence",(user_id,namespace["id"])).fetchall()
            phases=[row["record"]["data"].get("phase") for row in rows]
            for phase in ("graph.started","candidate.quarantined","recovery.started","payment.authorized"):
              self.assertIn(phase,phases)
            self.assertTrue(any(row["record"]["type"]=="agent.tool.before" for row in rows))
          persisted = client.get("/activity?limit=200").json()["events"]
          self.assertEqual(client.get("/activity?limit=200").json()["events"],persisted)
          # Real SSE replays the same persisted record, with a usable reconnect
          # cursor. Reading a stream never launches another agent or payment.
          def first_stream(headers=None):
            with client.stream("GET","/activity/stream",headers=headers) as stream:
              self.assertEqual(stream.status_code,200)
              for line in stream.iter_lines():
                if line.startswith("data: "):
                  item=json.loads(line[6:])
                  if "event_id" in item: return item
            self.fail("No persisted SSE event")
          first=first_stream()
          self.assertEqual(first,persisted[0])
          replay=first_stream({"Last-Event-ID":str(first["sequence"])})
          self.assertEqual(replay,persisted[1])
          # The real account's draft remains proposed and no real-account payment
          # was created by the isolated scenario.
          self.assertEqual(client.get(f'/mandates/{human_draft.json()["id"]}').json()["status"],"proposed")
          self.assertEqual(client.get("/purchase-attempts").json()["attempts"],[])
          self.assertEqual(client.get(f'/agent-runs/{run_id}/execution').status_code,404)
          with fixture.db.get_conn() as conn:
            conn.execute("UPDATE attack_lab_rate_windows SET started_at=now()-interval '61 seconds' WHERE operator_user_id=%s",(user_id,))
          response=client.post(ns+"/reset",json={})
          self.assertEqual(response.status_code,200,response.text)
          self.assertTrue(response.json()["history_retained"])
          self.assertFalse(response.json()["previous_authorizations_reversed"])
          # Stop a second real Graph before any payment. Reset cannot erase
          # previous authorizations or contaminate the ordinary account.
          with fixture.db.get_conn() as conn:
            conn.execute("UPDATE attack_lab_rate_windows SET started_at=now()-interval '61 seconds' WHERE operator_user_id=%s",(user_id,))
          current = client.get("/attack-lab/access").json()["namespace"]
          self.assertEqual(client.post(ns+"/control",json={"enabled":True,"expected_revision":current["revision"]}).status_code,200)
          drafted = client.post(ns+"/draft",json={"scenario":"legitimate_charger","mode":"scripted"}).json()["mandate"]
          dispatched = client.post(ns+"/execute",json={"mandate_id":drafted["id"],"version":drafted["version"],
            "canonical_payload_hash":drafted["canonical_payload_hash"],"confirmed":True})
          self.assertEqual(dispatched.status_code,202,dispatched.text)
          stopped_id = dispatched.json()["run_id"]
          stop = client.post(ns+"/runs/"+stopped_id+"/stop",json={})
          self.assertEqual(stop.status_code,200,stop.text)
          self.assertEqual(stop.json()["financial_revocation"],"enforced")
          end=time.monotonic()+15
          while time.monotonic()<end:
            with fixture.db.get_conn() as conn:
              stopped = conn.execute("SELECT graph_ack_at FROM run_executions WHERE run_id=%s",(stopped_id,)).fetchone()
            if stopped["graph_ack_at"]: break
            time.sleep(.2)
          # A queued worker that could not claim after Stop need not fabricate
          # a Graph acknowledgement. It must have no financial authorization.
          with fixture.db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT count(*) n FROM payment_outcomes p JOIN payment_operations o ON o.id=p.payment_id WHERE o.run_id=%s",(stopped_id,)).fetchone()["n"],0)
            self.assertEqual(conn.execute("SELECT count(*) n FROM payment_outcomes p JOIN payment_operations o ON o.id=p.payment_id WHERE o.run_id=%s AND p.record->>'result'='APPROVED'",(run_id,)).fetchone()["n"],1)
    finally:
      for proc in reversed(children):
        proc.terminate()
        try: proc.wait(timeout=8)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
      for log in logs: log.close()
      if server: server.should_exit=True
      if thread: thread.join(timeout=8)
      with fixture.psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
