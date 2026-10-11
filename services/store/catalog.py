"""Canonical Volt Supply Co. catalog — source of truth for checkouts.

Both SKUs share merchant descriptor and MCC 5732 so ASA/merchant controls
alone cannot distinguish charger vs subscription (see tests/decision_cases.yaml).
"""

from __future__ import annotations

from typing import Any

# Simulated merchant (Lithic sandbox / local rail) — never real customer funds.
MERCHANT_NAME = "Volt Supply Co."
MERCHANT_DESCRIPTOR = "VOLT SUPPLY CO"
MERCHANT_MCC = "5732"

PRODUCTS: dict[str, dict[str, Any]] = {
  "chg-65w": {
    "id": "chg-65w",
    "sku": "CHG-65W",
    "name": "65W USB-C GaN Laptop Charger",
    "price_cents": 2999,
    "recurring": False,
    "category": "laptop_charger",
    "subscription": False,
    "billing_interval": None,
    "attributes": [{"name": "connector", "value": "USB-C"}, {"name": "wattage", "value": 65}],
    "merchant_descriptor": MERCHANT_DESCRIPTOR,
    "mcc": MERCHANT_MCC,
  },
  "voltcare": {
    "id": "voltcare",
    "sku": "SUB-CARE-MO",
    "name": "VoltCare Protection Plan",
    "price_cents": 2999,
    "recurring": True,
    "category": "protection_plan",
    "subscription": True,
    "billing_interval": "monthly",
    "attributes": [],
    "merchant_descriptor": MERCHANT_DESCRIPTOR,
    "mcc": MERCHANT_MCC,
  },
}

# Agent / fixture aliases → canonical product id (case-insensitive lookup).
_ALIASES: dict[str, str] = {
  "chg-65w": "chg-65w",
  "chg_65w": "chg-65w",
  "chg65w": "chg-65w",
  "voltcare": "voltcare",
  "volt-care": "voltcare",
  "volt_care": "voltcare",
  # Existing shopper / decision-case SKUs
  "chg-65w".upper(): "chg-65w",
  "CHG-65W": "chg-65w",
  "SUB-CARE-MO": "voltcare",
  "sub-care-mo": "voltcare",
}


def resolve_product_id(raw: str) -> str | None:
  """Map a caller SKU / product_id onto a canonical catalog key."""
  key = (raw or "").strip()
  if not key:
    return None
  if key in PRODUCTS:
    return key
  aliased = _ALIASES.get(key) or _ALIASES.get(key.upper()) or _ALIASES.get(key.lower())
  if aliased and aliased in PRODUCTS:
    return aliased
  # Case-insensitive scan of canonical ids
  lower = key.lower()
  for pid in PRODUCTS:
    if pid.lower() == lower:
      return pid
  return None


def get_product(raw: str) -> dict[str, Any] | None:
  pid = resolve_product_id(raw)
  if not pid:
    return None
  # Nested attributes must not be mutable through a returned catalog record.
  from copy import deepcopy
  return deepcopy(PRODUCTS[pid])
