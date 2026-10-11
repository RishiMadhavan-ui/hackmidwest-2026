"""Volt Supply Co. — simulated merchant (Lithic sandbox / local rail).

Canonical catalog + checkout truth for LEASH. Listing HTML may be poisoned in
evil mode; POST /api/checkouts always reflects the real SKU from PRODUCTS.
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from catalog import MERCHANT_DESCRIPTOR, MERCHANT_MCC, get_product, resolve_product_id
from pages import render_product_page

logger = logging.getLogger("leash.store")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

app = FastAPI(
  title="LEASH Volt Supply Co. (simulated merchant)",
  description="Mock storefront for Hack Midwest. Lithic sandbox only — no real funds.",
  version="0.1.0",
)

# In-memory checkouts for the demo process (not durable across replicas).
_CHECKOUTS: dict[str, dict[str, Any]] = {}

Quantity = Annotated[StrictInt, Field(ge=1, le=99)]


class CheckoutCreate(BaseModel):
  model_config = ConfigDict(extra="ignore")
  # mcp-store sends "sku"; this prompt uses "product_id" — accept either.
  product_id: str | None = None
  sku: str | None = None
  quantity: Quantity = 1


class CardBody(BaseModel):
  model_config = ConfigDict(extra="ignore")
  # PAN/CVV may arrive from mcp-store; never log or persist them.
  number: str | None = None
  exp_month: int | None = None
  exp_year: int | None = None
  cvv: str | None = None
  token: str | None = None


class CompleteBody(BaseModel):
  model_config = ConfigDict(extra="ignore")
  payment_id: str = Field(min_length=1, max_length=128)
  card_token: str | None = None
  instrument_token: str | None = None
  card: CardBody | None = None


def _evil_enabled(evil_query: bool | None = None) -> bool:
  if evil_query is True:
    return True
  if evil_query is False:
    return False
  return os.getenv("STORE_EVIL_MODE", "").strip() in {"1", "true", "TRUE", "yes", "YES"}


def _store_api_token() -> str:
  return os.getenv("STORE_API_TOKEN", "").strip()


def _require_store_auth(authorization: str | None) -> None:
  expected = _store_api_token()
  if not expected:
    # Unconfigured: open for local smoke; LKE should set STORE_API_TOKEN.
    return
  if not authorization or not authorization.startswith("Bearer "):
    raise HTTPException(status_code=401, detail="missing store bearer token")
  got = authorization.removeprefix("Bearer ").strip()
  if not secrets.compare_digest(got, expected):
    raise HTTPException(status_code=401, detail="invalid store bearer token")


def _line_item(product: dict[str, Any], quantity: int) -> dict[str, Any]:
  return {
    "product_id": product["id"],
    "name": product["name"],
    "price_cents": int(product["price_cents"]),
    "quantity": quantity,
    "recurring": bool(product["recurring"]),
    "category": product["category"],
  }


def _checkout_public(record: dict[str, Any]) -> dict[str, Any]:
  return {
    "checkout_id": record["checkout_id"],
    "line_items": record["line_items"],
    "total_cents": record["total_cents"],
    "recurring": record["recurring"],
    "currency": "USD",
    "merchant_descriptor": record["merchant_descriptor"],
    "mcc": record["mcc"],
    "status": record["status"],
    # Explicit label: simulated merchant, not a live card network merchant.
    "provider": "simulated_merchant",
    "rail": "lithic_sandbox",
  }


@app.get("/healthz")
@app.get("/health")
def healthz() -> dict[str, Any]:
  return {
    "status": "ok",
    "service": "leash-store",
    "merchant": "volt_supply_co_simulated",
    "evil_mode_env": _evil_enabled(),
  }


@app.get("/products/{product_id}", response_class=HTMLResponse)
def product_page(
  product_id: str,
  evil: bool | None = Query(default=None, description="Force evil listing when true"),
) -> HTMLResponse:
  pid = resolve_product_id(product_id)
  if not pid:
    raise HTTPException(status_code=404, detail="Unknown product")
  html = render_product_page(pid, evil=_evil_enabled(evil))
  return HTMLResponse(content=html, status_code=200)


@app.post("/api/checkouts")
def create_checkout(
  body: CheckoutCreate,
  authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
  """Create a checkout from the canonical catalog — never from agent claims."""
  _require_store_auth(authorization)
  raw = body.product_id or body.sku
  if not raw:
    raise HTTPException(status_code=422, detail="product_id or sku is required")
  product = get_product(raw)
  if not product:
    raise HTTPException(status_code=404, detail="Unknown SKU")

  quantity = int(body.quantity)
  unit = int(product["price_cents"])
  total = unit * quantity
  checkout_id = f"ckt_{secrets.token_hex(8)}"
  line = _line_item(product, quantity)
  record = {
    "checkout_id": checkout_id,
    "product_id": product["id"],
    "line_items": [line],
    "total_cents": total,
    "recurring": bool(product["recurring"]),
    "merchant_descriptor": product["merchant_descriptor"],
    "mcc": product["mcc"],
    "status": "open",
    "payment_id": None,
    "lithic": None,
  }
  _CHECKOUTS[checkout_id] = record
  logger.info(
    "checkout_created id=%s product_id=%s total_cents=%s recurring=%s",
    checkout_id,
    product["id"],
    total,
    product["recurring"],
  )
  return _checkout_public(record)


@app.get("/api/checkouts/{checkout_id}")
def get_checkout(
  checkout_id: str,
  authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
  """Trusted read for the API verifier (R03) — same record create stored."""
  _require_store_auth(authorization)
  record = _CHECKOUTS.get(checkout_id)
  if not record:
    raise HTTPException(status_code=404, detail="Unknown checkout")
  return _checkout_public(record)


@app.post("/api/checkouts/{checkout_id}/complete")
def complete_checkout(
  checkout_id: str,
  body: CompleteBody,
  authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
  """Charge the exact stored checkout via Lithic sandbox simulate authorize.

  Card PAN/CVV are never logged or persisted. Lithic ASA simulate requires a
  card_token (instrument); PAN-only bodies cannot trigger sandbox auth.
  """
  _require_store_auth(authorization)
  record = _CHECKOUTS.get(checkout_id)
  if not record:
    raise HTTPException(status_code=404, detail="Unknown checkout")
  if record["status"] == "completed":
    # Idempotent replay of the original outcome (no second simulate).
    return {
      **_checkout_public(record),
      "payment_id": record.get("payment_id"),
      "authorization": record.get("lithic"),
    }

  card_token = (
    (body.card_token or "").strip()
    or (body.instrument_token or "").strip()
    or ((body.card.token if body.card else None) or "").strip()
  )
  # Touch card fields only to accept the wire shape; never assign to locals we log.
  if body.card and (body.card.number or body.card.cvv):
    # PAN/CVV present from mcp-store — discarded for Lithic simulate (needs token).
    pass

  if not card_token:
    raise HTTPException(
      status_code=422,
      detail=(
        "card_token is required for Lithic sandbox authorization "
        "(PAN/CVV alone cannot call /v1/simulate/authorize)"
      ),
    )

  try:
    from leash_shared.lithic import LithicError, simulate_authorization
  except ImportError as exc:
    raise HTTPException(status_code=503, detail="Lithic client unavailable") from exc

  try:
    lithic_result = simulate_authorization(
      card_token=card_token,
      amount_cents=int(record["total_cents"]),
      descriptor=str(record["merchant_descriptor"] or MERCHANT_DESCRIPTOR),
      mcc=str(record["mcc"] or MERCHANT_MCC),
    )
  except LithicError as exc:
    logger.info(
      "checkout_lithic_failed id=%s product_id=%s reason=%s",
      checkout_id,
      record["product_id"],
      str(exc),
    )
    raise HTTPException(status_code=502, detail=str(exc)) from exc

  # Persist only non-sensitive authorization metadata.
  safe_auth = {
    "token": lithic_result.get("token") or lithic_result.get("authorization_token"),
    "debugging_assertion": lithic_result.get("debugging_assertion"),
    "result": _infer_result(lithic_result),
  }
  record["status"] = "completed"
  record["payment_id"] = body.payment_id
  record["lithic"] = safe_auth
  # Never store card_token long-term beyond this process; keep last-4 only if provided.
  logger.info(
    "checkout_completed id=%s product_id=%s total_cents=%s payment_id=%s lithic_result=%s",
    checkout_id,
    record["product_id"],
    record["total_cents"],
    body.payment_id,
    safe_auth.get("result"),
  )
  return {
    **_checkout_public(record),
    "payment_id": body.payment_id,
    "authorization": safe_auth,
  }


def _infer_result(lithic_result: dict[str, Any]) -> str:
  for key in ("result", "status", "authorization_result"):
    val = lithic_result.get(key)
    if isinstance(val, str) and val.strip():
      return val.strip().upper()
  # Sandbox simulate often returns a token when ASA approved/declined upstream.
  if lithic_result.get("token") or lithic_result.get("debugging_assertion"):
    return "SUBMITTED"
  return "UNKNOWN"


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
  return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# Test helper: clear memory between unit tests.
def reset_checkouts() -> None:
  _CHECKOUTS.clear()
