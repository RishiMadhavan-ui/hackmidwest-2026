"""Shared setup for end-to-end scenarios against a running Leash stack.

These run only when LEASH_E2E=1, against real services. They never mock
anything: a pass here means the actual api, store, rail, and agent did it.

  LEASH_E2E=1 uv run --project services/agents pytest tests/e2e -v
"""

import os
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest

REQUIRED_ENV = ["API_URL", "AGENTS_URL", "USER_TOKEN", "AGENT_TOKEN_SHOPPER", "E2E_CHARGER_URL"]

INSTRUCTION = "Buy a USB-C laptop charger for under $40. No subscriptions."


def pytest_collection_modifyitems(config, items):
  if os.environ.get("LEASH_E2E") != "1":
    skip = pytest.mark.skip(reason="set LEASH_E2E=1 to run against a live stack")
    for item in items:
      item.add_marker(skip)
    return
  missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
  if missing:
    skip = pytest.mark.skip(reason=f"missing env: {', '.join(missing)}")
    for item in items:
      item.add_marker(skip)


@pytest.fixture(scope="session")
def api_as_agent() -> httpx.Client:
  token = os.environ["AGENT_TOKEN_SHOPPER"]
  return httpx.Client(
    base_url=os.environ["API_URL"], headers={"Authorization": f"Bearer {token}"}, timeout=30
  )


@pytest.fixture(scope="session")
def api_as_user() -> httpx.Client:
  token = os.environ["USER_TOKEN"]
  return httpx.Client(
    base_url=os.environ["API_URL"], headers={"Authorization": f"Bearer {token}"}, timeout=30
  )


@pytest.fixture(scope="session")
def agents() -> httpx.Client:
  return httpx.Client(base_url=os.environ["AGENTS_URL"], timeout=30)


def wait_for(fetch: Callable[[], dict[str, Any]], done: Callable[[dict], bool], timeout: float):
  deadline = time.monotonic() + timeout
  while True:
    value = fetch()
    if done(value) or time.monotonic() > deadline:
      return value
    time.sleep(2)
