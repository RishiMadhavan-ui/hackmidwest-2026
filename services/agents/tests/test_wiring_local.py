"""Local wiring: agents service -> real MCP server (subprocess) -> stub api.

STUB API AND STORE. These stand in for Rishi's api and Cameron's store so the
pieces in this lane can be tested over real HTTP: Strands' MCP client against
our MCP server, bearer passthrough, run_id correlation, trace intake, and the
scripted shopper. Their decisions are canned and prove nothing about Leash's
enforcement; that's what tests/e2e is for.
"""

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

from shopper.runs import RunManager, StartRun, run_shopper

AGENTS_DIR = Path(__file__).parents[1]
MCP_DIR = AGENTS_DIR.parent / "mcp"
POISONED = (Path(__file__).parent / "fixtures/listings/charger_poisoned.html").read_text()
TOKEN = "agent-wiring-token"
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

  @app.post("/provenance")
  async def provenance(request: Request):
    log["trace_auth"].add(request.headers.get("authorization"))
    log["trace"].append(await request.json())
    return JSONResponse({"ok": True}, 202)

  return app


def make_stub_store() -> FastAPI:
  app = FastAPI()

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
  log = {"payments": [], "payment_auth": [], "trace": [], "trace_auth": set()}
  api_url, api_server = serve(make_stub_api(log))
  store_url, store_server = serve(make_stub_store())
  mcp_port = free_port()
  mcp = subprocess.Popen(
    ["uv", "run", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(mcp_port)],
    cwd=MCP_DIR,
    env={**os.environ, "API_URL": api_url},
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    start_new_session=os.name != "nt",
  )
  mcp_url = f"http://127.0.0.1:{mcp_port}"
  for _ in range(120):
    try:
      if httpx.get(f"{mcp_url}/healthz", timeout=1).status_code == 200:
        break
    except httpx.HTTPError:
      time.sleep(0.25)
  else:
    kill_tree(mcp)
    pytest.fail("MCP server did not start")
  yield {"api": api_url, "store": store_url, "mcp": f"{mcp_url}/mcp", "log": log}
  kill_tree(mcp)
  api_server.should_exit = True
  store_server.should_exit = True


@pytest.fixture
def env(stack, monkeypatch):
  monkeypatch.setenv("API_URL", stack["api"])
  monkeypatch.setenv("STORE_URL", stack["store"])
  monkeypatch.setenv("MCP_URL", stack["mcp"])
  monkeypatch.setenv("AGENT_TOKEN_SHOPPER", TOKEN)
  for key in ("payments", "payment_auth", "trace"):
    stack["log"][key].clear()
  return stack


def run(req: StartRun) -> dict:
  manager = RunManager(runner=run_shopper)
  run_id = manager.start(req)["id"]
  for _ in range(300):
    record = manager.get(run_id)
    if record["status"] in ("completed", "failed"):
      return record
    time.sleep(0.1)
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
  decisions = [
    e["policy_decision"]
    for e in log["trace"]
    if e["type"] == "agent.tool.after" and e["tool_name"] == "request_payment"
  ]
  assert decisions == ["blocked"]


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
