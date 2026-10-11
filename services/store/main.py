"""Volt Supply Co. — simulated merchant with owned, frozen checkouts.

Canonical catalog + checkout truth for LEASH. Runtime attack listing selection
is disabled pending operator authorization; offline poisoned fixtures remain.
Create/read use STORE_API_TOKEN. Own/freeze/bind/complete require a distinct
STORE_CHARGE_TOKEN. Completion stays closed until durable payment reconciliation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictInt

from catalog import get_product, list_products, resolve_product_id
from pages import render_checkout_started, render_product_page
import execution_bridge

logger = logging.getLogger("leash.store")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

app = FastAPI(
  title="LEASH Volt Supply Co. (simulated merchant)",
  description="Simulated storefront; completion requires verified checkout binding.",
  version="0.2.0",
)

# In-memory checkouts for the demo process (not durable across replicas).
_CHECKOUTS: dict[str, dict[str, Any]] = {}

CHECKOUT_TTL = timedelta(minutes=30)
Quantity = Annotated[StrictInt, Field(ge=1, le=99)]
Sha256 = Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]
OwnerId = Annotated[str, Field(min_length=1, max_length=128)]
SessionId = Annotated[str, Field(min_length=1, max_length=128)]


class CheckoutCreate(BaseModel):
  model_config = ConfigDict(extra="forbid")
  product_id: str | None = Field(default=None, min_length=1, max_length=128)
  sku: str | None = Field(default=None, min_length=1, max_length=128)
  quantity: Quantity = 1


class OwnBody(BaseModel):
  model_config = ConfigDict(extra="forbid")
  user_id: OwnerId
  session_id: SessionId


class FreezeBody(BaseModel):
  model_config = ConfigDict(extra="forbid")
  expected_facts_hash: Sha256


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
  # Durable rail event identity reserved by the API payment operation.
  authorization_event_id: str = Field(min_length=8, max_length=128)


def _utc_now() -> datetime:
  return datetime.now(timezone.utc)


def _store_api_token() -> str:
  return os.getenv("STORE_API_TOKEN", "").strip()


def _store_charge_token() -> str:
  return os.getenv("STORE_CHARGE_TOKEN", "").strip()


def _webhook_url() -> str:
  return os.getenv("WEBHOOK_URL", "").strip().rstrip("/")


def _charge_token() -> str:
  return os.getenv("WEBHOOK_CHARGE_TOKEN", "").strip()


def _tokens_ready() -> bool:
  api = _store_api_token()
  charge = _store_charge_token()
  return len(api) >= 32 and len(charge) >= 32 and not secrets.compare_digest(api, charge)


def _require_store_auth(authorization: str | None) -> None:
  expected = _store_api_token()
  if len(expected) < 32:
    raise HTTPException(status_code=503, detail="Store authentication is not configured")
  if not authorization or not authorization.startswith("Bearer "):
    raise HTTPException(status_code=401, detail="missing store bearer token")
  got = authorization.removeprefix("Bearer ").strip()
  if not secrets.compare_digest(got, expected):
    raise HTTPException(status_code=401, detail="invalid store bearer token")


def _require_charge_auth(authorization: str | None) -> None:
  """Backend-only own/freeze/bind/complete — never the MCP browse credential."""
  expected = _store_charge_token()
  api = _store_api_token()
  if len(expected) < 32 or len(api) < 32 or secrets.compare_digest(expected, api):
    raise HTTPException(status_code=503, detail="Store charge authentication is not configured")
  if not authorization or not authorization.startswith("Bearer "):
    raise HTTPException(status_code=401, detail="missing store charge bearer token")
  got = authorization.removeprefix("Bearer ").strip()
  if not secrets.compare_digest(got, expected):
    raise HTTPException(status_code=401, detail="invalid store charge bearer token")


def _attack_lab_token() -> str:
  return os.getenv("ATTACK_LAB_TOKEN", "").strip()


def _require_attack_lab_auth(authorization: str | None) -> None:
  """Distinct operator-path credential; never STORE_API_TOKEN or public evil flags."""
  expected = _attack_lab_token()
  api = _store_api_token()
  charge = _store_charge_token()
  if (
    len(expected) < 32
    or secrets.compare_digest(expected, api)
    or (len(charge) >= 32 and secrets.compare_digest(expected, charge))
  ):
    raise HTTPException(status_code=503, detail="Attack Lab credential is not configured")
  if not authorization or not authorization.startswith("Bearer "):
    raise HTTPException(status_code=401, detail="missing Attack Lab bearer token")
  got = authorization.removeprefix("Bearer ").strip()
  if not secrets.compare_digest(got, expected):
    raise HTTPException(status_code=401, detail="invalid Attack Lab bearer token")


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


def _parse_expires(value: str) -> datetime:
  try:
    expires = datetime.fromisoformat(value.replace("Z", "+00:00"))
  except ValueError as exc:
    raise HTTPException(status_code=422, detail="Invalid expires_at") from exc
  if expires.tzinfo is None:
    raise HTTPException(status_code=422, detail="expires_at must be timezone-aware")
  return expires


def _iso(dt: datetime) -> str:
  return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_expired(record: dict[str, Any], *, now: datetime | None = None) -> bool:
  clock = now or _utc_now()
  expires = datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))
  return expires <= clock


def _checkout_public(record: dict[str, Any]) -> dict[str, Any]:
  binding = record.get("binding")
  frozen = record.get("frozen_at") is not None
  owned = record.get("user_id") is not None and record.get("session_id") is not None
  expired = _is_expired(record)
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
    "user_id": record.get("user_id"),
    "session_id": record.get("session_id"),
    "revision": int(record["revision"]),
    "frozen": frozen,
    "frozen_at": record.get("frozen_at"),
    "expires_at": record["expires_at"],
    "expired": expired,
    "ownership_authenticated": bool(owned and frozen and not expired),
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
    "evil_mode_env": False,
    "attack_lab_execution": "disabled_pending_operator_authorization",
    "payment_completion": "scoped_local_rail" if execution_bridge.enabled() else "local_rail_when_bound",
    "checkout_persistence": "api_postgresql" if execution_bridge.enabled() else "process_memory",
    "checkout_trust": "owner_session_revision_freeze_expiry",
    "charge_credential_configured": _tokens_ready(),
    "rail_configured": bool(_webhook_url() and len(_charge_token()) >= 32),
  }


@app.get("/readyz")
def readyz() -> dict[str, Any]:
  if not _tokens_ready():
    raise HTTPException(
      status_code=503,
      detail="Store API and distinct charge credentials are not configured",
    )
  return {**healthz(), "checkout_auth_configured": True, "charge_auth_configured": True}


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
  now = _utc_now()
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
    "user_id": None,
    "session_id": None,
    "revision": 1,
    "frozen_at": None,
    "created_at": _iso(now),
    "expires_at": _iso(now + CHECKOUT_TTL),
  }
  if not execution_bridge.enabled():
    _CHECKOUTS[checkout_id] = record
  logger.info(
    "checkout_created id=%s product_id=%s total_cents=%s recurring=%s",
    checkout_id,
    product["id"],
    total,
    product["recurring"],
  )
  return record


def _require_open_usable(record: dict[str, Any]) -> None:
  if record["status"] == "completed":
    raise HTTPException(status_code=409, detail="Checkout already completed")
  if _is_expired(record):
    raise HTTPException(status_code=409, detail="Checkout expired")


@app.get("/products/{product_id}", response_class=HTMLResponse)
def product_page(
  product_id: str,
  request: Request,
) -> HTMLResponse:
  # Fail closed for direct requests too, including service-token callers and
  # duplicate selectors. STORE_EVIL_MODE cannot enable public attack execution.
  selectors = request.query_params.getlist("evil")
  if any(value.lower() not in {"0", "false", "off", "no"} for value in selectors):
    raise HTTPException(status_code=403, detail="Attack Lab execution is disabled")
  pid = resolve_product_id(product_id)
  if not pid:
    raise HTTPException(status_code=404, detail="Unknown product")
  html = render_product_page(pid, evil=False)
  return HTMLResponse(content=html, status_code=200, headers={"Cache-Control": "no-store"})


@app.get("/catalog", response_class=HTMLResponse)
def clean_catalog():
  # A separate clean discovery source. It is still untrusted agent evidence;
  # the API retrieves and checks every resulting checkout independently.
  from html import escape
  products = list_products()
  rows = [f"<li>{escape(p['name'])}: SKU {escape(p['sku'])}, {p['price_cents']} cents; "
          f"category {escape(p['category'])}; subscription {bool(p['subscription'])}</li>" for p in products]
  return HTMLResponse("<h1>Volt Supply canonical catalog</h1><ul>" + "".join(rows) + "</ul>",
                      headers={"Cache-Control": "no-store"})


@app.get("/internal/attack-lab/products/{product_id}", response_class=HTMLResponse)
def attack_lab_product_page(
  product_id: str,
  request: Request,
  authorization: Annotated[str | None, Header()] = None,
) -> HTMLResponse:
  """Poisoned listing for the API operator path only — not public ?evil=1."""
  _require_attack_lab_auth(authorization)
  selectors = request.query_params.getlist("evil")
  if not selectors or any(value.lower() not in {"1", "true", "yes", "on"} for value in selectors):
    raise HTTPException(status_code=403, detail="Attack Lab product preview requires evil=1")
  pid = resolve_product_id(product_id)
  if not pid:
    raise HTTPException(status_code=404, detail="Unknown product")
  html = render_product_page(pid, evil=True)
  return HTMLResponse(
    content=html,
    status_code=200,
    headers={"Cache-Control": "no-store", "X-Leash-Attack-Lab": "1"},
  )


@app.post("/products/{product_id}/checkout", response_class=HTMLResponse)
def start_checkout_from_listing(product_id: str) -> HTMLResponse:
  """Human storefront checkout start (no bearer). Unowned until API own/freeze."""
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
  request: Request,
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
  facts = _checkout_public(_open_checkout(product, int(body.quantity)))
  if execution_bridge.enabled():
    return execution_bridge.call("POST", "/checkouts", {"facts": facts}, request.headers)
  return facts


@app.get("/api/checkouts/{checkout_id}")
def get_checkout(
  checkout_id: str,
  authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
  """Trusted read for the API verifier — same record create stored."""
  if execution_bridge.enabled():
    execution_bridge.backend_auth(authorization)
    from urllib.parse import quote
    return execution_bridge.call("GET", "/checkouts/" + quote(checkout_id, safe=""))
  _require_store_auth(authorization)
  record = _CHECKOUTS.get(checkout_id)
  if not record:
    raise HTTPException(status_code=404, detail="Unknown checkout")
  return _checkout_public(record)


@app.post("/api/checkouts/{checkout_id}/own")
def own_checkout(
  checkout_id: str,
  body: OwnBody,
  authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
  """Bind checkout to a LEASH user/session. Charge credential only; once."""
  _require_charge_auth(authorization)
  record = _CHECKOUTS.get(checkout_id)
  if not record:
    raise HTTPException(status_code=404, detail="Unknown checkout")
  _require_open_usable(record)
  if record.get("frozen_at") is not None:
    raise HTTPException(status_code=409, detail="Frozen checkout cannot change ownership")
  existing_user = record.get("user_id")
  existing_session = record.get("session_id")
  if existing_user is not None or existing_session is not None:
    if existing_user == body.user_id and existing_session == body.session_id:
      return _checkout_public(record)
    raise HTTPException(status_code=409, detail="Checkout already owned by a different user or session")
  record["user_id"] = body.user_id
  record["session_id"] = body.session_id
  record["revision"] = int(record["revision"]) + 1
  logger.info(
    "checkout_owned id=%s user_id=%s session_id=%s revision=%s",
    checkout_id,
    body.user_id,
    body.session_id,
    record["revision"],
  )
  return _checkout_public(record)


@app.post("/api/checkouts/{checkout_id}/freeze")
def freeze_checkout(
  checkout_id: str,
  body: FreezeBody,
  authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
  """Freeze catalog facts after verify. Rejects secret post-verify mutation."""
  _require_charge_auth(authorization)
  record = _CHECKOUTS.get(checkout_id)
  if not record:
    raise HTTPException(status_code=404, detail="Unknown checkout")
  _require_open_usable(record)
  if record.get("user_id") is None or record.get("session_id") is None:
    raise HTTPException(status_code=409, detail="Checkout must be owned before freeze")
  if body.expected_facts_hash != record["facts_hash"]:
    raise HTTPException(status_code=409, detail="expected_facts_hash does not match checkout")
  if record.get("frozen_at") is not None:
    # Idempotent freeze of the same facts; different hash already rejected above.
    return _checkout_public(record)
  record["frozen_at"] = _iso(_utc_now())
  record["revision"] = int(record["revision"]) + 1
  logger.info(
    "checkout_frozen id=%s revision=%s facts_hash=%s",
    checkout_id,
    record["revision"],
    record["facts_hash"][:12],
  )
  return _checkout_public(record)


@app.post("/api/checkouts/{checkout_id}/bind")
def bind_checkout(
  checkout_id: str,
  body: BindBody,
  authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
  """API-only bind after verify+grant. Requires owned frozen checkout."""
  if execution_bridge.enabled():
    raise HTTPException(409, "Verified binding is committed by the execution backend")
  _require_charge_auth(authorization)
  record = _CHECKOUTS.get(checkout_id)
  if not record:
    raise HTTPException(status_code=404, detail="Unknown checkout")
  _require_open_usable(record)
  if record.get("user_id") is None or record.get("session_id") is None:
    raise HTTPException(status_code=409, detail="Checkout must be owned before bind")
  if record.get("frozen_at") is None:
    raise HTTPException(status_code=409, detail="Checkout must be frozen before bind")
  if body.checkout_hash != record["facts_hash"]:
    raise HTTPException(
      status_code=409,
      detail="checkout_hash does not match frozen checkout facts",
    )
  if int(body.authorized_amount_cents) != int(record["total_cents"]):
    raise HTTPException(status_code=409, detail="authorized_amount_cents does not match checkout")
  expires = _parse_expires(body.expires_at)
  if expires <= _utc_now():
    raise HTTPException(status_code=422, detail="Binding already expired")
  # Binding cannot outlive the merchant checkout window.
  checkout_expires = datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))
  if expires > checkout_expires:
    raise HTTPException(status_code=422, detail="Binding expires after checkout")

  existing = record.get("binding")
  if existing and (
    existing["payment_id"] != body.payment_id
    or existing["grant_id"] != body.grant_id
    or existing["instrument_token"] != body.instrument_token
    or existing["merchant_binding_id"] != body.merchant_binding_id
    or existing["checkout_hash"] != body.checkout_hash
    or existing.get("authorization_event_id") != body.authorization_event_id
  ):
    raise HTTPException(status_code=409, detail="Checkout already bound to a different grant")

  if not existing:
    record["revision"] = int(record["revision"]) + 1
  record["binding"] = {
    "payment_id": body.payment_id,
    "grant_id": body.grant_id,
    "instrument_token": body.instrument_token,
    "merchant_binding_id": body.merchant_binding_id,
    "checkout_hash": body.checkout_hash,
    "authorized_amount_cents": int(body.authorized_amount_cents),
    "expires_at": _iso(expires),
    "authorization_event_id": body.authorization_event_id,
  }
  record["payment_id"] = body.payment_id
  logger.info(
    "checkout_bound id=%s payment_id=%s grant_id=%s revision=%s",
    checkout_id,
    body.payment_id,
    body.grant_id,
    record["revision"],
  )
  return _checkout_public(record)


@app.post("/api/checkouts/{checkout_id}/complete")
def complete_checkout(
  checkout_id: str,
  body: CompleteBody,
  request: Request,
  authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
  """Charge the local rail for a frozen bound checkout using the durable event id."""
  _require_charge_auth(authorization)
  if execution_bridge.enabled():
    return execution_bridge.complete(checkout_id, body.payment_id, request.headers)
  record = _CHECKOUTS.get(checkout_id)
  if not record:
    raise HTTPException(status_code=404, detail="Unknown checkout")

  binding = record.get("binding")
  if not binding:
    raise HTTPException(
      status_code=403,
      detail="Checkout is not bound to a verified payment grant",
    )
  if record["status"] == "completed":
    # Idempotent replay of a known local-rail outcome.
    return {
      **_checkout_public(record),
      "rail_result": record.get("rail_result"),
    }
  _require_open_usable(record)
  if record.get("frozen_at") is None:
    raise HTTPException(status_code=409, detail="Checkout must be frozen before complete")

  if body.payment_id != binding["payment_id"]:
    raise HTTPException(status_code=409, detail="payment_id does not match checkout binding")

  instrument = (
    (body.card_token or "").strip()
    or (body.instrument_token or "").strip()
    or ((body.card.token if body.card else None) or "").strip()
    or str(binding["instrument_token"])
  )
  if body.card and (body.card.number or body.card.cvv):
    pass  # accepted on wire; never logged or persisted
  if instrument != binding["instrument_token"]:
    raise HTTPException(status_code=409, detail="instrument does not match checkout binding")

  expires = datetime.fromisoformat(binding["expires_at"].replace("Z", "+00:00"))
  if expires <= _utc_now():
    raise HTTPException(status_code=409, detail="Checkout binding expired")

  event_id = binding.get("authorization_event_id")
  if not event_id:
    raise HTTPException(status_code=409, detail="Checkout binding lacks durable authorization_event_id")

  rail_url = _webhook_url()
  charge = _charge_token()
  if not rail_url or len(charge) < 32:
    raise HTTPException(status_code=503, detail="Local payment rail is not configured")

  authorize_body = {
    "event_id": event_id,
    "request_type": "AUTHORIZATION",
    "instrument_token": binding["instrument_token"],
    "descriptor": record["merchant_descriptor"],
    "mcc": record["mcc"],
    "amount_cents": int(binding["authorized_amount_cents"]),
    "currency": "USD",
    "checkout_id": checkout_id,
    "checkout_hash": binding["checkout_hash"],
    "merchant_binding_id": binding["merchant_binding_id"],
  }
  try:
    with httpx.Client(timeout=5.0, follow_redirects=False) as client:
      res = client.post(
        f"{rail_url}/local/authorize",
        headers={
          "Authorization": f"Bearer {charge}",
          "Content-Type": "application/json",
          "Accept": "application/json",
        },
        json=authorize_body,
      )
  except httpx.HTTPError:
    # Unknown outcome: do not invent a new event id or mark paid.
    raise HTTPException(
      status_code=503,
      detail="Local rail unreachable; payment outcome unknown — do not retry with a new authorization",
    ) from None

  try:
    rail_result = res.json()
  except ValueError:
    rail_result = {"result": "ERROR", "reason": "invalid_rail_response"}

  if res.status_code >= 500 or (
    isinstance(rail_result, dict) and rail_result.get("result") == "ERROR"
  ):
    raise HTTPException(
      status_code=503,
      detail="Local rail reported an unknown outcome — reconcile before any replacement purchase",
    )

  if not isinstance(rail_result, dict) or rail_result.get("result") != "APPROVED":
    raise HTTPException(
      status_code=409,
      detail=str((rail_result or {}).get("reason") or "authorization_declined"),
    )

  record["status"] = "completed"
  record["rail_result"] = {
    "result": rail_result.get("result"),
    "reason": rail_result.get("reason"),
    "rail": rail_result.get("rail") or "local_payment_rail_simulator",
    "event_id": event_id,
    "decision_source": rail_result.get("decision_source"),
    "latency_ms": rail_result.get("latency_ms"),
  }
  record["revision"] = int(record["revision"]) + 1
  logger.info(
    "checkout_completed id=%s payment_id=%s event_id=%s result=%s",
    checkout_id,
    body.payment_id,
    event_id,
    rail_result.get("result"),
  )
  return {**_checkout_public(record), "rail_result": record["rail_result"]}


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
  return JSONResponse(status_code=422, content={"detail": "Invalid store request"})


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
  return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def reset_checkouts() -> None:
  _CHECKOUTS.clear()
