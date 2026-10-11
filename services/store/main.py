"""Volt Supply Co. — simulated merchant, with no enabled payment rail.

Canonical catalog + checkout truth for LEASH. Listing HTML may be poisoned in
evil mode; POST /api/checkouts always reflects the real SKU from PRODUCTS.
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictInt

from catalog import get_product, resolve_product_id
from pages import render_product_page

logger = logging.getLogger("leash.store")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

app = FastAPI(
  title="LEASH Volt Supply Co. (simulated merchant)",
  description="Simulated storefront; payment completion awaits protected checkout binding.",
  version="0.1.0",
)

# In-memory checkouts for the demo process (not durable across replicas).
_CHECKOUTS: dict[str, dict[str, Any]] = {}

Quantity = Annotated[StrictInt, Field(ge=1, le=99)]


class CheckoutCreate(BaseModel):
  model_config = ConfigDict(extra="forbid")
  # mcp-store sends "sku"; this prompt uses "product_id" — accept either.
  product_id: str | None = Field(default=None, min_length=1, max_length=128)
  sku: str | None = Field(default=None, min_length=1, max_length=128)
  quantity: Quantity = 1


class CardBody(BaseModel):
  model_config = ConfigDict(extra="ignore")
  # PAN/CVV may arrive from mcp-store; never log or persist them.
  number: SecretStr | None = None
  exp_month: Annotated[StrictInt, Field(ge=1, le=12)] | None = None
  exp_year: Annotated[StrictInt, Field(ge=2000, le=9999)] | None = None
  cvv: SecretStr | None = None
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
  if len(expected) < 32:
    raise HTTPException(status_code=503, detail="Store authentication is not configured")
  if not authorization or not authorization.startswith("Bearer "):
    raise HTTPException(status_code=401, detail="missing store bearer token")
  got = authorization.removeprefix("Bearer ").strip()
  if not secrets.compare_digest(got, expected):
    raise HTTPException(status_code=401, detail="invalid store bearer token")


def _line_item(product: dict[str, Any], quantity: int) -> dict[str, Any]:
  return {
    "product_id": product["id"],
    "sku": product["sku"],
    "name": product["name"],
    "price_cents": int(product["price_cents"]),
    "quantity": quantity,
    "recurring": bool(product["recurring"]),
    "category": product["category"],
    "subscription": product["subscription"],
    "billing_interval": product["billing_interval"],
    "attributes": product["attributes"],
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
    "rail": None,
  }


@app.get("/healthz")
@app.get("/health")
def healthz() -> dict[str, Any]:
  return {
    "status": "ok",
    "service": "leash-store",
    "merchant": "volt_supply_co_simulated",
    "evil_mode_env": _evil_enabled(),
    "payment_completion": "unavailable",
    "checkout_persistence": "process_memory",
  }


@app.get("/readyz")
def readyz() -> dict[str, Any]:
  if len(_store_api_token()) < 32:
    raise HTTPException(status_code=503, detail="Store authentication is not configured")
  return {**healthz(), "checkout_auth_configured": True}


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
  if body.product_id and body.sku and resolve_product_id(body.product_id) != resolve_product_id(body.sku):
    raise HTTPException(status_code=422, detail="product_id and sku must identify the same product")
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
  """No charge until the backend verifies and durably binds this exact checkout."""
  _require_store_auth(authorization)
  if checkout_id not in _CHECKOUTS:
    raise HTTPException(status_code=404, detail="Unknown checkout")
  # A caller's payment/card identifier is a claim, not spending authority.
  # No provider call, completed projection, or alternate purchase on failure.
  raise HTTPException(
    status_code=503,
    detail="Payment completion is unavailable until verified checkout binding and durable payment operations are implemented",
  )


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
  # FastAPI's default validation body can echo submitted PAN/CVV/token fields.
  return JSONResponse(status_code=422, content={"detail": "Invalid store request"})


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
  return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# Test helper: clear memory between unit tests.
def reset_checkouts() -> None:
  _CHECKOUTS.clear()
