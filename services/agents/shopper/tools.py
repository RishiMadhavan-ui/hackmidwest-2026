"""Tools the shopper can call directly (the Leash tools come from MCP).

browse() is naive on purpose: it hands the model every bit of text on the page,
hidden or not. That's how the demo injection reaches the shopper. Defenses
belong in the api, the store, and the rail, never here (AGENTS.md).

The store tools only talk to the configured STORE_URL. Their routes are a
proposal pending Cameron's canonical merchant interface (H04/H05).
"""

import json
import os
from datetime import UTC, datetime
from typing import Any

import httpx
from strands import ToolContext, tool

from provenance.hooks import FETCHES_KEY
from provenance.html_text import extract

MAX_PAGE_CHARS = 12_000
HTTP_TIMEOUT = 10.0

# TODO: confirm with Cameron (H04/H05). Proposed store routes:
#   POST {STORE_URL}/api/checkouts               {"sku", "quantity"} -> checkout
#   POST {STORE_URL}/api/checkouts/{id}/complete {"payment_id", "card"?} -> result
CHECKOUTS_PATH = "/api/checkouts"


def _store_url() -> str:
  return os.environ.get("STORE_URL", "http://localhost:8004").rstrip("/")


def _error(reason: str, **extra: Any) -> str:
  return json.dumps({"status": "error", "reason": reason, **extra})


def _store_headers() -> dict[str, str]:
  # TODO(C02/H05): replace with the scoped caller/session credential agreed
  # with Cameron. Only the configured store's checkout API ever gets it;
  # browse() can be pointed anywhere by a page, so it never sends credentials.
  token = os.environ.get("STORE_API_TOKEN")
  return {"Authorization": f"Bearer {token}"} if token else {}


def _store_post(path: str, body: dict[str, Any]) -> str:
  try:
    res = httpx.post(_store_url() + path, json=body, headers=_store_headers(), timeout=HTTP_TIMEOUT)
  except httpx.HTTPError as exc:
    return _error(f"store unreachable ({type(exc).__name__})")
  try:
    payload = res.json()
  except ValueError:
    payload = {"body": res.text[:500]}
  if res.is_error:
    detail = payload.get("detail") if isinstance(payload, dict) else None
    return _error(detail or f"store returned HTTP {res.status_code}", http_status=res.status_code)
  return json.dumps(payload)


@tool(context=True)
def browse(url: str, tool_context: ToolContext) -> str:
  """Open a web page and return all of its text.

  Args:
    url: The full http(s) URL of the page to read.
  """
  try:
    res = httpx.get(url, timeout=HTTP_TIMEOUT, follow_redirects=True)
  except httpx.HTTPError as exc:
    return f"Could not load {url}: {type(exc).__name__}"

  # Leave the exact bytes for the provenance hook, which hashes and snapshots
  # them. The model only gets the extracted text below.
  fetches = tool_context.invocation_state.setdefault(FETCHES_KEY, {})
  fetches[tool_context.tool_use["toolUseId"]] = {
    "url": str(res.url),
    "html": res.text,
    "status_code": res.status_code,
    "fetched_at": datetime.now(UTC).isoformat(),
  }
  text = extract(res.text).all_text()
  return f"URL: {res.url}\nHTTP {res.status_code}\n\n{text[:MAX_PAGE_CHARS]}"


@tool
def create_checkout(sku: str, quantity: int = 1) -> str:
  """Start a checkout at the store for one product.

  Returns the store's checkout, including a checkout_id. Pass that checkout_id
  to request_payment so Leash can verify the order with the store.

  Args:
    sku: The product SKU exactly as the store lists it, e.g. "CHG-65W".
    quantity: How many units. Usually 1.
  """
  return _store_post(CHECKOUTS_PATH, {"sku": sku, "quantity": quantity})


@tool
def complete_checkout(
  checkout_id: str,
  payment_id: str,
  card_number: str | None = None,
  exp_month: int | None = None,
  exp_year: int | None = None,
  cvv: str | None = None,
) -> str:
  """Pay for a checkout after Leash approved the payment.

  Use the payment_id from request_payment. If Leash returned single-use card
  details, pass them too. The store charges only the exact checkout Leash
  approved.

  Args:
    checkout_id: The checkout_id from create_checkout.
    payment_id: The payment id from request_payment.
    card_number: Single-use card number from Leash, if one was returned.
    exp_month: Card expiry month, if a card was returned.
    exp_year: Card expiry year, if a card was returned.
    cvv: Card security code, if a card was returned.
  """
  body: dict[str, Any] = {"payment_id": payment_id}
  if card_number:
    body["card"] = {
      "number": card_number,
      "exp_month": exp_month,
      "exp_year": exp_year,
      "cvv": cvv,
    }
  return _store_post(f"{CHECKOUTS_PATH}/{checkout_id}/complete", body)
