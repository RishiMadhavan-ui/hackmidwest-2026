"""Configured merchant -> API durable facts and exact local rail completion."""

import hmac
import os
import ssl
from urllib.parse import quote

import httpx
from fastapi import HTTPException

SCOPE_HEADERS = {"x-leash-run-id", "x-leash-worker-id", "x-leash-generation", "x-leash-execution-token"}
TLS_CONTEXT = ssl.create_default_context()


def enabled():
  return os.getenv("LEASH_EXECUTION_ENABLED") == "1"


def scope_context(headers):
  base = os.getenv("API_URL", "").rstrip("/")
  if not base or not enabled():
    raise HTTPException(503, "Execution backend is not configured")
  scoped = {k: v for k,v in headers.items() if k.lower() in SCOPE_HEADERS}
  try:
    with httpx.Client(timeout=3, follow_redirects=False, verify=TLS_CONTEXT) as client:
      result = client.post(base+"/execution/authorize", headers=scoped,
        json={"audience":"mcp-store", "action":"browse"})
    if not result.is_success:
      raise HTTPException(403, "Listing execution scope is not current")
    return result.json()
  except (httpx.HTTPError, ValueError):
    raise HTTPException(503, "Listing scope verification unavailable") from None


def backend_auth(authorization):
  token = os.getenv("MERCHANT_BACKEND_TOKEN", "")
  if len(token) < 32 or token == os.getenv("STORE_API_TOKEN"):
    raise HTTPException(503, "Distinct merchant backend credential is not configured")
  if not authorization or not hmac.compare_digest(authorization, "Bearer " + token):
    raise HTTPException(403, "Backend checkout retrieval credential required")


def call(method, path, body=None, headers=None):
  base = os.getenv("API_URL", "").rstrip("/")
  token = os.getenv("MERCHANT_BACKEND_TOKEN", "")
  if not base or len(token) < 32 or token == os.getenv("STORE_API_TOKEN"):
    raise HTTPException(503, "Durable merchant backend is not configured")
  scoped = {k: v for k, v in (headers or {}).items() if k.lower() in SCOPE_HEADERS}
  try:
    with httpx.Client(base_url=base, timeout=5, follow_redirects=False, verify=TLS_CONTEXT) as client:
      res = client.request(method, "/internal/merchant" + path, json=body,
        headers={"Authorization": "Bearer " + token, **scoped})
    if not res.is_success:
      raise HTTPException(res.status_code, "Merchant operation rejected by execution backend")
    result = res.json()
    if not isinstance(result, dict):
      raise ValueError()
    return result
  except (httpx.HTTPError, ValueError):
    raise HTTPException(503, "Merchant backend unavailable; reconcile the same operation") from None


def complete(checkout_id, payment_id, headers):
  path = "/checkouts/" + quote(checkout_id, safe="")
  body = {"payment_id": payment_id}
  payload = call("POST", path + "/begin", body, headers)
  url, token = os.getenv("WEBHOOK_URL", "").rstrip("/"), os.getenv("WEBHOOK_CHARGE_TOKEN", "")
  if not url or len(token) < 32:
    raise HTTPException(503, "Local rail is not configured; operation remains pending")
  try:
    # No automatic HTTP retries or fresh authorization IDs. The API owns the
    # persisted event ID and independently reads the rail's cached result.
    with httpx.Client(timeout=3, follow_redirects=False, verify=TLS_CONTEXT) as client:
      client.post(url + "/local/authorize", json=payload, headers={"Authorization": "Bearer " + token})
  except httpx.HTTPError:
    pass
  return call("POST", path + "/reconcile", body, headers)
