"""Opt-in local PostgreSQL + real Redis + store + webhook + Next streaming smoke.

No model, Lithic, deployment or shared database is used. The store is simulated. Grants are
explicit backend fixtures; this is transport/control evidence, not a purchase demo.
"""

import base64
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime  # noqa: F401,E402
import auth  # noqa: E402
import db  # noqa: E402
import httpx  # noqa: E402
import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402
from nacl.signing import SigningKey  # noqa: E402
import uvicorn  # noqa: E402
from main import app  # noqa: E402
from principals import bind_agent  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DSN = os.getenv("LEASH_TEST_DATABASE_URL", "")
RAIL_URL = os.getenv("LEASH_TEST_VALKEY_URL", "")


@unittest.skipUnless(
  os.getenv("LEASH_TEST_STACK") == "1",
  "Set LEASH_TEST_STACK=1 after building web and starting isolated test databases",
)
class AlignmentStackTests(unittest.TestCase):
  def test_persisted_sse_through_next_and_human_stop_ack_from_real_rail(self):
    params = conninfo_to_dict(DSN)
    rail = urlparse(RAIL_URL)
    if (
      params.get("host") not in {"localhost", "127.0.0.1"}
      or not params.get("dbname", "").startswith("leash_test")
      or rail.hostname not in {"localhost", "127.0.0.1"}
      or rail.port != 56379
      or rail.path != "/15"
    ):
      raise RuntimeError(
        "Refusing stack tests outside explicitly isolated localhost test databases"
      )
    standalone = ROOT / "web/.next/standalone"
    self.assertTrue((standalone / "server.js").is_file(), "Build web first")
    schema = "alignment_test_" + uuid4().hex
    with psycopg.connect(DSN) as conn:
      conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    internal = "control-" + uuid4().hex
    merchant = "merchant-" + uuid4().hex
    secret = "jwt-" + uuid4().hex
    agent = "agent-" + uuid4().hex
    event_token = "events-" + uuid4().hex
    child_base = {
      k: v
      for k, v in os.environ.items()
      if k.upper()
      in {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "APPDATA",
        "LOCALAPPDATA",
        "PATHEXT",
      }
    }
    children = []
    thread = None
    server = None

    def wait_ready(url):
      deadline = time.monotonic() + 25
      while time.monotonic() < deadline:
        try:
          if httpx.get(url, timeout=1).status_code < 500:
            return
        except httpx.HTTPError:
          pass
        time.sleep(0.1)
      for child in children:
        if child.poll() is not None and child.stderr is not None:
          self.fail(
            "Local child exited: " + child.stderr.read(3000).decode(errors="replace")
          )
      self.fail("Local service did not become ready: " + url)

    try:
      with (
        patch.object(
          db,
          "DATABASE_URL",
          make_conninfo(DSN, options=f"-c search_path={schema}"),
        ),
        patch.object(auth, "JWT_SECRET", secret),
        patch.dict(
          os.environ,
          {
            "DATABASE_URL": DSN,
            "JWT_SECRET": secret,
            "USER_TOKEN": "",
            "MANDATE_SIGNING_KEY": base64.b64encode(
              bytes(SigningKey.generate())
            ).decode(),
            "WEBHOOK_URL": "http://127.0.0.1:58105",
            "WEBHOOK_INTERNAL_TOKEN": internal,
            "RAIL_EVENT_TOKEN": event_token,
          },
        ),
      ):
        db.init_db()
        server = uvicorn.Server(
          uvicorn.Config(
            app,
            host="127.0.0.1",
            port=58100,
            log_level="error",
            timeout_graceful_shutdown=1,
          )
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        wait_ready("http://127.0.0.1:58100/readyz")
        webhook_env = {
          **child_base,
          "VALKEY_URL": RAIL_URL,
          "WEBHOOK_INTERNAL_TOKEN": internal,
          "WEBHOOK_CHARGE_TOKEN": merchant,
          "RAIL_EVENT_TOKEN": event_token,
          "API_URL": "http://127.0.0.1:58100",
        }
        children.append(
          subprocess.Popen(
            [
              str(ROOT / "services/webhook/.venv/Scripts/python.exe"),
              "-m",
              "uvicorn",
              "main:app",
              "--host",
              "127.0.0.1",
              "--port",
              "58105",
              "--log-level",
              "error",
            ],
            cwd=ROOT / "services/webhook",
            env=webhook_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
          )
        )
        wait_ready("http://127.0.0.1:58105/readyz")
        store_token = "store-" + uuid4().hex
        children.append(
          subprocess.Popen(
            [
              str(ROOT / "services/store/.venv/Scripts/python.exe"),
              "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
              "--port", "58104", "--log-level", "error",
            ],
            cwd=ROOT / "services/store",
            env={**child_base, "STORE_API_TOKEN": store_token, "STORE_EVIL_MODE": "0"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
          )
        )
        wait_ready("http://127.0.0.1:58104/readyz")
        children.append(
          subprocess.Popen(
            [shutil.which("node"), "server.js"],
            cwd=standalone,
            env={
              **child_base,
              "PORT": "58130",
              "HOSTNAME": "127.0.0.1",
              "API_ORIGIN": "http://127.0.0.1:58100",
              "STORE_ORIGIN": "http://127.0.0.1:58104",
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
          )
        )
        wait_ready(
          "http://127.0.0.1:58130/backend/activity/stream"
        )  # unauthenticated 401
        self.assertEqual(
          httpx.post(
            "http://127.0.0.1:58130/backend/internal/activity", timeout=5
          ).status_code,
          404,
        )
        self.assertEqual(
          httpx.get("http://127.0.0.1:58130/store/products/chg-65w", timeout=5).status_code,
          200,
        )
        self.assertEqual(
          httpx.post("http://127.0.0.1:58130/store/api/checkouts", json={"sku": "CHG-65W"}, timeout=5).status_code,
          404,
        )
        with httpx.Client(base_url="http://127.0.0.1:58104", timeout=5) as store_client:
          self.assertEqual(store_client.post("/api/checkouts", json={"sku": "CHG-65W"}).status_code, 401)
          store_client.headers["Authorization"] = "Bearer " + store_token
          checkout = store_client.post("/api/checkouts", json={"sku": "CHG-65W"}).json()
          self.assertEqual(checkout["total_cents"], 2999)
          self.assertEqual(
            store_client.post(
              f"/api/checkouts/{checkout['checkout_id']}/complete",
              json={"payment_id": "unverified-claim", "card_token": "unverified-card"},
            ).status_code,
            403,
          )
        with httpx.Client(base_url="http://127.0.0.1:58100", timeout=5) as client:
          signup = client.post(
            "/auth/signup",
            json={
              "email": uuid4().hex + "@example.com",
              "password": "test-password-valid",
              "first_name": "Fixture",
              "last_name": "User",
              "postal_code": "64101",
            },
          )
          self.assertEqual(signup.status_code, 201, signup.text)
          human = {"Authorization": "Bearer " + signup.json()["access_token"]}
          owner = client.get("/identity", headers=human).json()["user_id"]
          agent_id = "agt_" + uuid4().hex
          with db.get_conn() as conn:
            bind_agent(
              conn,
              user_id=owner,
              agent_id=agent_id,
              token=agent,
              modes=("scripted",),
            )
          ah = {"Authorization": "Bearer " + agent}
          draft = client.post(
            "/mandates/propose",
            headers=ah,
            json={
              "description": "Buy a USB-C charger under $40. No subscriptions.",
              "category": "laptop_charger",
              "max_cents": 3999,
            },
          ).json()
          approved = client.post(
            f"/mandates/{draft['id']}/approve",
            headers=human,
            json={
              "version": draft["version"],
              "canonical_payload_hash": draft["canonical_payload_hash"],
              "confirmed": True,
            },
          )
          self.assertEqual(approved.status_code, 200, approved.text)
          cursor = client.get("/activity", headers=human).json()["next_cursor"]
          now = datetime.now(timezone.utc)
          grant = {
            "grant_id": "grt_" + uuid4().hex,
            "payment_id": "pay_fixture",
            "mandate_id": draft["id"],
            "mandate_version": 1,
            "mandate_hash": draft["canonical_payload_hash"],
            "user_id": owner,
            "verification_id": "ver_fixture",
            "verified_checkout_id": "chk_fixture",
            "verified_checkout_hash": "a" * 64,
            "payment_instrument_id": "ins_" + uuid4().hex,
            "merchant_id": "volt_supply_co",
            "merchant_descriptor": "VOLT SUPPLY CO",
            "mcc": "5732",
            "authorized_amount_cents": 2999,
            "currency": "USD",
            "merchant_binding_id": "bind_fixture",
            "bound_at": now.isoformat(),
            "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=1)).isoformat(),
            "mandate_expires_at": draft["valid_until"],
            "checkout_expires_at": (now + timedelta(minutes=2)).isoformat(),
          }
          with httpx.Client(
            base_url="http://127.0.0.1:58105", timeout=3
          ) as rail_client:
            seeded = rail_client.put(
              "/internal/grants",
              headers={"Authorization": "Bearer " + internal},
              json=grant,
            )
            self.assertEqual(seeded.status_code, 200, seeded.text)
            stopped = client.post("/killswitch", headers=human, json={"on": True})
            self.assertEqual(stopped.status_code, 200, stopped.text)
            self.assertEqual(stopped.json()["status"], "financially_stopped")
            self.assertEqual(stopped.json()["rail"]["unused_grants_revoked"], 1)
            denied = rail_client.post(
              "/local/authorize",
              headers={"Authorization": "Bearer " + merchant},
              json={
                "event_id": "evt_" + uuid4().hex,
                "instrument_token": grant["payment_instrument_id"],
                "descriptor": grant["merchant_descriptor"],
                "mcc": "5732",
                "amount_cents": 2999,
                "currency": "USD",
                "checkout_id": "chk_fixture",
                "checkout_hash": "a" * 64,
                "merchant_binding_id": "bind_fixture",
              },
            )
            self.assertEqual(denied.json()["reason"], "killswitch_on")
          deadline = time.monotonic() + 5
          while time.monotonic() < deadline:
            records = client.get("/activity", headers=human).json()["events"]
            decisions = [e for e in records if e["type"] == "authorization.decided"]
            if decisions:
              break
            time.sleep(0.1)
          self.assertEqual(len(decisions), 1, "Durable rail relay did not reach API")
          self.assertEqual(decisions[0]["data"]["reason"], "killswitch_on")
          with httpx.stream(
            "GET",
            f"http://127.0.0.1:58130/backend/activity/stream?after={cursor}",
            headers=human,
            timeout=5,
          ) as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/event-stream", response.headers["content-type"])
            for line in response.iter_lines():
              if line.startswith("data:") and '"rail_outcome"' in line:
                self.assertIn('"enforced"', line)
                break
            else:
              self.fail("Next proxy did not stream the persisted rail acknowledgement")
    finally:
      for child in children:
        child.terminate()
        try:
          child.wait(5)
        except subprocess.TimeoutExpired:
          child.kill()
          child.wait(3)
        if child.stderr:
          child.stderr.close()
      if server:
        server.should_exit = True
        if thread:
          thread.join(3)
      with psycopg.connect(DSN) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
