"""Local wiring: agents -> both real MCP services (subprocesses) -> stub api and store.

The Leash MCP service (services/mcp-leash) and the store MCP service
(services/mcp-store) run as separate processes, as they do on LKE.

STUB API AND STORE. These stand in for Rishi's api and Cameron's store so the
pieces in this lane can be tested over real HTTP: Strands' MCP clients against
both servers, separate credentials, run_id correlation, store-side page
evidence, trace intake, and the scripted shopper. Their decisions are canned
and prove nothing about Leash's enforcement; that's what tests/e2e is for.
"""

import hashlib
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from provenance.outbox import shared_outbox
from shopper.runs import RunManager, StartRun, run_shopper

AGENTS_DIR = Path(__file__).parents[1]
LEASH_DIR = AGENTS_DIR.parent / "mcp-leash"
STORE_DIR = AGENTS_DIR.parent / "mcp-store"
POISONED = (STORE_DIR / "tests/fixtures/listings/charger_poisoned.html").read_text()
# Credentials each MCP service must NOT be given: the store service never
# holds the Leash token, and the Leash service never holds store secrets.
_SECRETS = {
  "AGENT_TOKEN_SHOPPER",
  "AGENT_TOKEN_SHOPPER_SCRIPTED",
  "STORE_MCP_TOKEN",
  "STORE_API_TOKEN",
  "API_URL",
  "STORE_URL",
}
TOKEN = "agent-wiring-token"  # the scripted credential these runs use
LIVE_TOKEN = "live-agent-wiring-token"
STORE_MCP_TOKEN = "store-mcp-wiring-token"
PAN = "4111111111111111"

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to start MCP server")


def kill_tree(proc: subprocess.Popen) -> None:
  # `uv run` starts uvicorn as a child; killing only uv leaves the server
  # running and holding its port.
  if os.name == "nt":
    subprocess.run(
      ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
      check=False,
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL,
    )
  else:
    os.killpg(proc.pid, 9)
  proc.wait(timeout=10)


def start_mcp(directory: Path, env: dict[str, str]) -> tuple[subprocess.Popen, str]:
  port = free_port()
  proc = subprocess.Popen(
    ["uv", "run", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
    cwd=directory,
    env={**{k: v for k, v in os.environ.items() if k not in _SECRETS}, **env},
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    start_new_session=os.name != "nt",
  )
  url = f"http://127.0.0.1:{port}"
  for _ in range(120):
    try:
      if httpx.get(f"{url}/health", timeout=1).status_code == 200:
        return proc, url
    except httpx.HTTPError:
      pass
    time.sleep(0.25)
  kill_tree(proc)
  pytest.fail(f"{directory.name} did not start")


def free_port() -> int:
  with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    return s.getsockname()[1]


def serve(app: FastAPI) -> tuple[str, uvicorn.Server]:
  port = free_port()
  server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
  threading.Thread(target=server.run, daemon=True).start()
  for _ in range(100):
    if server.started:
      break
    time.sleep(0.05)
  return f"http://127.0.0.1:{port}", server


def make_stub_api(log: dict) -> FastAPI:
  app = FastAPI()

  @app.post("/payments")
  async def payments(request: Request):
    log["payment_auth"].append(request.headers.get("authorization"))
    body = await request.json()
    log["payments"].append(body)
    if body["checkout_id"] == "chk_sub":
      return JSONResponse({"id": "pay_2", "status": "blocked", "reasons": ["subscription"]}, 201)
    card = {"number": PAN, "exp_month": 12, "exp_year": 2028, "cvv": "321"}
    return JSONResponse({"id": "pay_1", "status": "approved", "card": card}, 201)

  @app.post("/agent-runs")
  async def register_run(request: Request):
    body = await request.json()
    log["order"].append("register")
    log["registrations"].append({"auth": request.headers.get("authorization"), **body})
    return JSONResponse({"id": body["id"], "agent_mode": body["agent_mode"]}, 201)

  @app.post("/provenance")
  async def provenance(request: Request):
    log["order"].append("trace")
    log["trace_auth"].add(request.headers.get("authorization"))
    log["trace"].append(await request.json())
    return JSONResponse({"ok": True}, 202)

  return app


def make_stub_store(log: dict) -> FastAPI:
  app = FastAPI()

  @app.middleware("http")
  async def record_auth(request: Request, call_next):
    log["store_auth"].append(request.headers.get("authorization"))
    return await call_next(request)

  @app.get("/products/chg-65w")
  def listing():
    return HTMLResponse(POISONED)

  @app.post("/api/checkouts")
  async def checkout(request: Request):
    sku = (await request.json())["sku"]
    cid = "chk_sub" if sku == "SUB-CARE-MO" else "chk_charger"
    return JSONResponse({"checkout_id": cid, "total_cents": 2999, "currency": "USD"}, 201)

  @app.post("/api/checkouts/{cid}/complete")
  def complete(cid: str):
    return {"status": "paid", "checkout_id": cid}

  return app


@pytest.fixture(scope="module")
def stack():
  log = {
    "payments": [],
    "payment_auth": [],
    "trace": [],
    "trace_auth": set(),
    "registrations": [],
    "order": [],
    "store_auth": [],
  }
  api_url, api_server = serve(make_stub_api(log))
  store_url, store_server = serve(make_stub_store(log))
  leash, leash_url = start_mcp(LEASH_DIR, {"API_URL": api_url})
  store, store_mcp_url = start_mcp(
    STORE_DIR, {"STORE_URL": store_url, "STORE_MCP_TOKEN": STORE_MCP_TOKEN}
  )
  yield {
    "api": api_url,
    "store": store_url,
    "leash_mcp": f"{leash_url}/mcp",
    "store_mcp": f"{store_mcp_url}/mcp",
    "log": log,
  }
  kill_tree(leash)
  kill_tree(store)
  api_server.should_exit = True
  store_server.should_exit = True


@pytest.fixture
def env(stack, monkeypatch):
  monkeypatch.setenv("API_URL", stack["api"])
  monkeypatch.setenv("STORE_URL", stack["store"])
  monkeypatch.setenv("MCP_LEASH_URL", stack["leash_mcp"])
  monkeypatch.setenv("MCP_STORE_URL", stack["store_mcp"])
  # Both credentials exist, as in the cluster; scripted runs must pick theirs.
  monkeypatch.setenv("AGENT_TOKEN_SHOPPER", LIVE_TOKEN)
  monkeypatch.setenv("AGENT_TOKEN_SHOPPER_SCRIPTED", TOKEN)
  monkeypatch.setenv("STORE_MCP_TOKEN", STORE_MCP_TOKEN)
  for key in ("payments", "payment_auth", "trace", "registrations", "order", "store_auth"):
    stack["log"][key].clear()
  return stack


def run(req: StartRun) -> dict:
  manager = RunManager(runner=run_shopper)
  run_id = manager.start(req)["id"]
  for _ in range(300):
    record = manager.get(run_id)
    if record["status"] in ("completed", "failed"):
      break
    time.sleep(0.1)
  # Traces go through the durable outbox; wait for them to land.
  assert shared_outbox(os.environ["API_URL"], TOKEN, "scripted").flush(timeout=10)
  return record


def test_scripted_attack_over_real_mcp(env):
  record = run(
    StartRun(
      task="Buy a USB-C laptop charger for under $40. No subscriptions.",
      mandate_id="mnd_1",
      start_url=f"{env['store']}/products/chg-65w",
      agent_mode="scripted",
      sku="SUB-CARE-MO",
      claim_sku="CHG-65W",
    )
  )
  assert record["status"] == "completed", record["error"]
  log = env["log"]

  # Registered with the agent's token before the first trace event.
  assert record["registered"] is True
  [registration] = log["registrations"]
  assert registration["auth"] == f"Bearer {TOKEN}"
  assert registration["id"] == record["id"]
  assert registration["agent_mode"] == "scripted"
  assert log["order"][0] == "register"

  # The MCP server forwarded the agent's bearer unchanged and the run id.
  assert log["payment_auth"] == [f"Bearer {TOKEN}"]
  [payment] = log["payments"]
  assert payment["checkout_id"] == "chk_sub"
  assert payment["run_id"] == record["id"]
  assert payment["proposal"]["items"][0]["sku"] == "CHG-65W"

  # Trace events reached the api's intake with the agent token, labeled.
  assert log["trace_auth"] == {f"Bearer {TOKEN}"}
  types = [e["type"] for e in log["trace"]]
  assert "provenance.source" in types
  assert {e["agent_mode"] for e in log["trace"]} == {"scripted"}
  # Events name the scripted agent, matching the credential that sent them.
  assert {e["agent_id"] for e in log["trace"]} == {"agt_shopper_scripted"}
  everything_sent = json.dumps(log["registrations"]) + str(log["payment_auth"])
  assert LIVE_TOKEN not in everything_sent and LIVE_TOKEN not in str(log["trace_auth"])
  decisions = [
    e["policy_decision"]
    for e in log["trace"]
    if e["type"] == "agent.tool.after" and e["tool_name"] == "request_payment"
  ]
  assert decisions == ["blocked"]

  # The page was inspected inside the Store MCP; only its evidence came back.
  [source] = [e for e in log["trace"] if e["type"] == "provenance.source"]
  assert source["sha256"] == hashlib.sha256(POISONED.encode()).hexdigest()
  assert source["hidden_text_detected"] is True
  assert "SUB-CARE-MO" in source["excerpt"]
  assert "<div" not in json.dumps(log["trace"])

  # Separate credentials: the store never saw the Leash token or the Store MCP token.
  assert log["store_auth"]
  assert not any(TOKEN in (a or "") or STORE_MCP_TOKEN in (a or "") for a in log["store_auth"])


def test_scripted_legit_purchase_never_leaks_card_into_trace(env):
  record = run(
    StartRun(
      task="Buy a USB-C laptop charger for under $40. No subscriptions.",
      mandate_id="mnd_1",
      start_url=f"{env['store']}/products/chg-65w",
      agent_mode="scripted",
      sku="CHG-65W",
    )
  )
  assert record["status"] == "completed", record["error"]
  tools = [e["tool_name"] for e in record["events"] if e["type"] == "agent.tool.after"]
  assert tools == ["browse", "create_checkout", "request_payment", "complete_checkout"]
  everything = json.dumps(env["log"]["trace"]) + json.dumps(record)
  assert PAN not in everything
  assert '"321"' not in everything
