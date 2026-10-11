"""Volt Supply Co. — simulated merchant with gated completion.

Canonical catalog + checkout truth for LEASH. Listing HTML may be poisoned in
evil mode; POST /api/checkouts always reflects the real SKU from PRODUCTS.
Binding primitives are present; completion stays closed until durable controls exist.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictInt

from catalog import get_product, resolve_product_id
from pages import render_checkout_started, render_product_page

logger = logging.getLogger("leash.store")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

app = FastAPI(
  title="LEASH Volt Supply Co. (simulated merchant)",
  description="Simulated storefront; completion requires verified checkout binding.",
  version="0.1.0",
)

# In-memory checkouts for the demo process (not durable across replicas).
_CHECKOUTS: dict[str, dict[str, Any]] = {}

Quantity = Annotated[StrictInt, Field(ge=1, le=99)]
Sha256 = Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]


class CheckoutCreate(BaseModel):
  model_config = ConfigDict(extra="forbid")
  product_id: str | None = Field(default=None, min_length=1, max_length=128)
  sku: str | None = Field(default=None, min_length=1, max_length=128)
  quantity: Quantity = 1


class CardBody(BaseModel):
  model_config = ConfigDict(extra="ignore")
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


class BindBody(BaseModel):
  model_config = ConfigDict(extra="forbid")
  payment_id: str = Field(min_length=1, max_length=128)
  grant_id: str = Field(min_length=1, max_length=128)
  instrument_token: str = Field(min_length=1, max_length=128)
  merchant_binding_id: str = Field(min_length=1, max_length=128)
  checkout_hash: Sha256
  authorized_amount_cents: Annotated[StrictInt, Field(ge=0)]
  expires_at: str = Field(min_length=8, max_length=64)


def _evil_enabled(evil_query: bool | None = None) -> bool:
  if evil_query is True:
    return True
  if evil_query is False:
    return False
  return os.getenv("STORE_EVIL_MODE", "").strip() in {"1", "true", "TRUE", "yes", "YES"}


def _store_api_token() -> str:
  return os.getenv("STORE_API_TOKEN", "").strip()


def _webhook_url() -> str:
  return os.getenv("WEBHOOK_URL", "").strip().rstrip("/")


def _charge_token() -> str:
  return os.getenv("WEBHOOK_CHARGE_TOKEN", "").strip()


def _require_store_auth(authorization: str | None) -> None:
  expected = _store_api_token()
  if len(expected) < 32:
    raise HTTPException(status_code=503, detail="Store authentication is not configured")
  if not authorization or not authorization.startswith("Bearer "):
    raise HTTPException(status_code=401, detail="missing store bearer token")
  got = authorization.removeprefix("Bearer ").strip()
  if not secrets.compare_digest(got, expected):
    raise HTTPException(status_code=401, detail="invalid store bearer token")


def _facts_hash(
  *,
  checkout_id: str,
  line_items: list[dict[str, Any]],
  total_cents: int,
  recurring: bool,
  merchant_descriptor: str,
  mcc: str,
) -> str:
  payload = {
    "checkout_id": checkout_id,
    "currency": "USD",
    "line_items": line_items,
    "mcc": mcc,
    "merchant_descriptor": merchant_descriptor,
    "recurring": recurring,
    "total_cents": total_cents,
  }
  raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
  return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
  binding = record.get("binding")
  return {
    "checkout_id": record["checkout_id"],
    "line_items": record["line_items"],
    "total_cents": record["total_cents"],
    "recurring": record["recurring"],
    "currency": "USD",
    "merchant_descriptor": record["merchant_descriptor"],
    "mcc": record["mcc"],
    "status": record["status"],
    "facts_hash": record["facts_hash"],
    # After bind, expose the verified grant checkout_hash used on the rail.
    "checkout_hash": (binding or {}).get("checkout_hash") or record["facts_hash"],
    "bound": binding is not None,
    "provider": "simulated_merchant",
    "rail": "local_payment_rail_simulator" if record["status"] == "completed" else None,
  }


@app.get("/healthz")
@app.get("/health")
def healthz() -> dict[str, Any]:
  return {
    "status": "ok",
    "service": "leash-store",
    "merchant": "volt_supply_co_simulated",
    "evil_mode_env": _evil_enabled(),
    "payment_completion": "disabled_pending_durable_controls",
    "checkout_persistence": "process_memory",
    "rail_configured": bool(_webhook_url() and len(_charge_token()) >= 32),
  }


@app.get("/readyz")
def readyz() -> dict[str, Any]:
  if len(_store_api_token()) < 32:
    raise HTTPException(status_code=503, detail="Store authentication is not configured")
  return {**healthz(), "checkout_auth_configured": True}


def _open_checkout(product: dict[str, Any], quantity: int) -> dict[str, Any]:
  """Catalog-backed open checkout — never from agent-claimed cart facts."""
  unit = int(product["price_cents"])
  total = unit * quantity
  checkout_id = f"ckt_{secrets.token_hex(8)}"
  line = _line_item(product, quantity)
  facts = _facts_hash(
    checkout_id=checkout_id,
    line_items=[line],
    total_cents=total,
    recurring=bool(product["recurring"]),
    merchant_descriptor=str(product["merchant_descriptor"]),
    mcc=str(product["mcc"]),
  )
  record = {
    "checkout_id": checkout_id,
    "product_id": product["id"],
    "line_items": [line],
    "total_cents": total,
    "recurring": bool(product["recurring"]),
    "merchant_descriptor": product["merchant_descriptor"],
    "mcc": product["mcc"],
    "status": "open",
    "facts_hash": facts,
    "binding": None,
    "payment_id": None,
    "rail_result": None,
  }
  _CHECKOUTS[checkout_id] = record
  logger.info(
    "checkout_created id=%s product_id=%s total_cents=%s recurring=%s",
    checkout_id,
    product["id"],
    total,
    product["recurring"],
  )
  return record


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


@app.post("/products/{product_id}/checkout", response_class=HTMLResponse)
def start_checkout_from_listing(product_id: str) -> HTMLResponse:
  """Human storefront checkout start (no bearer). Bind/complete stay authenticated."""
  pid = resolve_product_id(product_id)
  if not pid:
    raise HTTPException(status_code=404, detail="Unknown product")
  product = get_product(pid)
  if not product:
    raise HTTPException(status_code=404, detail="Unknown product")
  record = _open_checkout(product, 1)
  return HTMLResponse(
    content=render_checkout_started(product, record),
    status_code=200,
  )


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
  return _checkout_public(_open_checkout(product, int(body.quantity)))


@app.get("/api/checkouts/{checkout_id}")
def get_checkout(
  checkout_id: str,
  authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
  """Trusted read for the API verifier — same record create stored."""
  _require_store_auth(authorization)
  record = _CHECKOUTS.get(checkout_id)
  if not record:
    raise HTTPException(status_code=404, detail="Unknown checkout")
  return _checkout_public(record)


@app.post("/api/checkouts/{checkout_id}/bind")
def bind_checkout(
  checkout_id: str,
  body: BindBody,
  authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
  """API-only bind after verify+grant. Stores rail correlation on this checkout."""
  _require_store_auth(authorization)
  record = _CHECKOUTS.get(checkout_id)
  if not record:
    raise HTTPException(status_code=404, detail="Unknown checkout")
  if record["status"] == "completed":
    raise HTTPException(status_code=409, detail="Checkout already completed")
  if int(body.authorized_amount_cents) != int(record["total_cents"]):
    raise HTTPException(status_code=409, detail="authorized_amount_cents does not match checkout")
  try:
    expires = datetime.fromisoformat(body.expires_at.replace("Z", "+00:00"))
  except ValueError as exc:
    raise HTTPException(status_code=422, detail="Invalid expires_at") from exc
  if expires.tzinfo is None:
    raise HTTPException(status_code=422, detail="expires_at must be timezone-aware")
  if expires <= datetime.now(timezone.utc):
    raise HTTPException(status_code=422, detail="Binding already expired")

  existing = record.get("binding")
  if existing and (
    existing["payment_id"] != body.payment_id
    or existing["grant_id"] != body.grant_id
    or existing["instrument_token"] != body.instrument_token
    or existing["merchant_binding_id"] != body.merchant_binding_id
    or existing["checkout_hash"] != body.checkout_hash
  ):
    raise HTTPException(status_code=409, detail="Checkout already bound to a different grant")

  record["binding"] = {
    "payment_id": body.payment_id,
    "grant_id": body.grant_id,
    "instrument_token": body.instrument_token,
    "merchant_binding_id": body.merchant_binding_id,
    "checkout_hash": body.checkout_hash,
    "authorized_amount_cents": int(body.authorized_amount_cents),
    "expires_at": expires.isoformat().replace("+00:00", "Z"),
  }
  record["payment_id"] = body.payment_id
  logger.info(
    "checkout_bound id=%s payment_id=%s grant_id=%s",
    checkout_id,
    body.payment_id,
    body.grant_id,
  )
  return _checkout_public(record)


@app.post("/api/checkouts/{checkout_id}/complete")
def complete_checkout(
  checkout_id: str,
  body: CompleteBody,
  authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
  """Validate binding, then fail closed until durable charge controls exist."""
  _require_store_auth(authorization)
  record = _CHECKOUTS.get(checkout_id)
  if not record:
    raise HTTPException(status_code=404, detail="Unknown checkout")

  binding = record.get("binding")
  if not binding:
    raise HTTPException(
      status_code=403,
      detail="Checkout is not bound to a verified payment grant",
    )

  if body.payment_id != binding["payment_id"]:
    raise HTTPException(status_code=409, detail="payment_id does not match checkout binding")

  instrument = (
    (body.card_token or "").strip()
    or (body.instrument_token or "").strip()
    or ((body.card.token if body.card else None) or "").strip()
  )
  if body.card and (body.card.number or body.card.cvv):
    pass  # accepted on wire; never logged or persisted
  if not instrument:
    raise HTTPException(status_code=422, detail="instrument_token or card_token is required")
  if instrument != binding["instrument_token"]:
    raise HTTPException(status_code=409, detail="instrument does not match checkout binding")

  expires = datetime.fromisoformat(binding["expires_at"].replace("Z", "+00:00"))
  if expires <= datetime.now(timezone.utc):
    raise HTTPException(status_code=409, detail="Checkout binding expired")

  # Process-memory bindings and fresh event IDs cannot safely reconcile a
  # committed authorization whose response was lost. Do not charge until the
  # durable operation/event identity, caller scope and stop barriers are wired.
  raise HTTPException(
    status_code=503,
    detail="Checkout completion unavailable until durable payment reconciliation and stop controls are implemented",
  )


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
  return JSONResponse(status_code=422, content={"detail": "Invalid store request"})


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
  return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def reset_checkouts() -> None:
  _CHECKOUTS.clear()
