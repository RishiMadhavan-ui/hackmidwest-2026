import pytest

# Unit tests never talk to a real api, MCP server, store, bucket, or model,
# even if the developer's shell has those configured.
_NETWORK_ENV = [
  "API_URL",
  "AGENT_TOKEN_SHOPPER",
  "AGENTS_SERVICE_TOKEN",
  "MCP_URL",
  "MCP_LEASH_URL",
  "MCP_STORE_URL",
  "STORE_MCP_TOKEN",
  "STORE_URL",
  "STORE_API_TOKEN",
  "OBJ_ENDPOINT",
  "OBJ_BUCKET",
  "OBJ_ACCESS_KEY",
  "OBJ_SECRET_KEY",
  "TRACE_SPOOL_DIR",
]
# Only tests marked live_inference may reach the model endpoint.
_INFERENCE_ENV = ["INFERENCE_BASE_URL", "INFERENCE_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_KEY"]


@pytest.fixture(autouse=True)
def _isolate_network_env(request, monkeypatch, tmp_path):
  for name in _NETWORK_ENV:
    monkeypatch.delenv(name, raising=False)
  if request.node.get_closest_marker("live_inference") is None:
    for name in _INFERENCE_ENV:
      monkeypatch.delenv(name, raising=False)
  # Trace spooling writes files; keep them in a per-test temp dir.
  monkeypatch.setenv("TRACE_SPOOL_DIR", str(tmp_path / "trace-spool"))
