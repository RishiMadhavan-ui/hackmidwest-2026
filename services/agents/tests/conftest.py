import pytest

# Unit tests never talk to a real api, MCP server, store, or bucket, even if
# the developer's shell has those configured.
_NETWORK_ENV = [
  "API_URL",
  "AGENT_TOKEN_SHOPPER",
  "MCP_URL",
  "OBJ_ENDPOINT",
  "OBJ_BUCKET",
  "OBJ_ACCESS_KEY",
  "OBJ_SECRET_KEY",
]


@pytest.fixture(autouse=True)
def _isolate_network_env(monkeypatch):
  for name in _NETWORK_ENV:
    monkeypatch.delenv(name, raising=False)
