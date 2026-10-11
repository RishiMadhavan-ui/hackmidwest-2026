"""Canonical Volt Supply Co. catalog — source of truth for checkouts.

Charger and VoltCare share merchant descriptor and MCC 5732 so ASA/merchant
controls alone cannot distinguish them (see tests/decision_cases.yaml). Additional
tech SKUs expand demo mandates beyond the USB-C charger; two are recurring.
"""

from __future__ import annotations

from typing import Any

# Simulated merchant (Lithic sandbox / local rail) — never real customer funds.
MERCHANT_NAME = "Volt Supply Co."
MERCHANT_DESCRIPTOR = "VOLT SUPPLY CO"
MERCHANT_MCC = "5732"


def _sku(
  *,
  product_id: str,
  sku: str,
  name: str,
  price_cents: int,
  category: str,
  subscription: bool,
  recurring: bool,
  billing_interval: str | None,
  attributes: list[dict[str, Any]],
) -> dict[str, Any]:
  return {
    "id": product_id,
    "sku": sku,
    "name": name,
    "price_cents": price_cents,
    "recurring": recurring,
    "category": category,
    "subscription": subscription,
    "billing_interval": billing_interval,
    "attributes": attributes,
    "merchant_descriptor": MERCHANT_DESCRIPTOR,
    "mcc": MERCHANT_MCC,
  }


PRODUCTS: dict[str, dict[str, Any]] = {
  "chg-65w": _sku(
    product_id="chg-65w",
    sku="CHG-65W",
    name="65W USB-C GaN Laptop Charger",
    price_cents=2999,
    category="laptop_charger",
    subscription=False,
    recurring=False,
    billing_interval=None,
    attributes=[
      {"name": "connector", "value": "USB-C"},
      {"name": "wattage", "value": 65},
    ],
  ),
  "voltcare": _sku(
    product_id="voltcare",
    sku="SUB-CARE-MO",
    name="VoltCare Protection Plan",
    price_cents=2999,
    category="protection_plan",
    subscription=True,
    recurring=True,
    billing_interval="monthly",
    attributes=[],
  ),
  # One-time tech expansions
  "hub-7p": _sku(
    product_id="hub-7p",
    sku="HUB-7P",
    name="7-Port USB-C Multiport Hub",
    price_cents=3499,
    category="usb_hub",
    subscription=False,
    recurring=False,
    billing_interval=None,
    attributes=[
      {"name": "connector", "value": "USB-C"},
      {"name": "ports", "value": 7},
    ],
  ),
  "buds-anc": _sku(
    product_id="buds-anc",
    sku="EAR-ANC",
    name="VoltBuds ANC Wireless Earbuds",
    price_cents=7999,
    category="headphones",
    subscription=False,
    recurring=False,
    billing_interval=None,
    attributes=[
      {"name": "connectivity", "value": "bluetooth"},
      {"name": "anc", "value": True},
    ],
  ),
  "ssd-1tb": _sku(
    product_id="ssd-1tb",
    sku="SSD-1TB",
    name="1TB USB-C Portable SSD",
    price_cents=8999,
    category="storage",
    subscription=False,
    recurring=False,
    billing_interval=None,
    attributes=[
      {"name": "connector", "value": "USB-C"},
      {"name": "capacity_gb", "value": 1000},
    ],
  ),
  # Subscription / recurring expansions
  "voltcloud": _sku(
    product_id="voltcloud",
    sku="SUB-CLOUD-MO",
    name="VoltCloud Device Backup",
    price_cents=999,
    category="cloud_backup",
    subscription=True,
    recurring=True,
    billing_interval="monthly",
    attributes=[{"name": "storage_gb", "value": 200}],
  ),
  "voltshield": _sku(
    product_id="voltshield",
    sku="SUB-SHIELD-MO",
    name="VoltShield Security Suite",
    price_cents=1499,
    category="security_software",
    subscription=True,
    recurring=True,
    billing_interval="monthly",
    attributes=[{"name": "seats", "value": 1}],
  ),
}

# Agent / fixture aliases → canonical product id (case-insensitive lookup).
_ALIASES: dict[str, str] = {
  "chg-65w": "chg-65w",
  "chg_65w": "chg-65w",
  "chg65w": "chg-65w",
  "voltcare": "voltcare",
  "volt-care": "voltcare",
  "volt_care": "voltcare",
  "hub-7p": "hub-7p",
  "hub_7p": "hub-7p",
  "buds-anc": "buds-anc",
  "buds_anc": "buds-anc",
  "ssd-1tb": "ssd-1tb",
  "ssd_1tb": "ssd-1tb",
  "voltcloud": "voltcloud",
  "volt-cloud": "voltcloud",
  "volt_cloud": "voltcloud",
  "voltshield": "voltshield",
  "volt-shield": "voltshield",
  "volt_shield": "voltshield",
  # SKU aliases
  "CHG-65W": "chg-65w",
  "SUB-CARE-MO": "voltcare",
  "sub-care-mo": "voltcare",
  "HUB-7P": "hub-7p",
  "EAR-ANC": "buds-anc",
  "SSD-1TB": "ssd-1tb",
  "SUB-CLOUD-MO": "voltcloud",
  "sub-cloud-mo": "voltcloud",
  "SUB-SHIELD-MO": "voltshield",
  "sub-shield-mo": "voltshield",
}


def list_products() -> list[dict[str, Any]]:
  """Stable catalog order for discovery pages."""
  from copy import deepcopy
  return [deepcopy(PRODUCTS[pid]) for pid in PRODUCTS]


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
