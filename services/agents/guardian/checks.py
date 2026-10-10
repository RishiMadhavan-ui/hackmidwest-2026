"""Deterministic guardian checks. No model, no I/O.

These run before any LLM call (AGENTS.md rule 2). Every check fails closed:
missing or malformed fields count as a failure, never a pass.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

# TODO: switch to leash_shared.models (Mandate, Cart, Verdict) once models.py
# lands. Until then mandates, carts, and verdicts are plain dicts.

# Which merchant category codes count as each mandate category. A lodging
# mandate covers hotels (7011) and the airline-style hotel chain codes
# (3501-3999). Unknown categories match nothing, so they fail closed.
CATEGORY_MCCS: dict[str, set[int]] = {
  "lodging": {7011, *range(3501, 4000)},
}

Check = dict[str, Any]


def _check(name: str, passed: bool, detail: str) -> Check:
  return {"name": name, "passed": passed, "detail": detail}


def _parse_time(value: Any) -> datetime | None:
  if not isinstance(value, str):
    return None
  try:
    parsed = datetime.fromisoformat(value)
  except ValueError:
    return None
  # Contracts say timestamps are timezone-aware UTC; treat a naive one as UTC
  # instead of crashing the comparison.
  return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _is_cents(value: Any) -> bool:
  # bool is a subclass of int, and True is not an amount.
  return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _cart_hash(cart: dict[str, Any]) -> str:
  # TODO: replace with leash_shared.models.cart_hash() once it exists. Never
  # keep two hash definitions; this one only exists until Rishi's lands.
  data = {
    "mandate_id": cart.get("mandate_id"),
    "merchant": cart.get("merchant"),
    "items": cart.get("items"),
    "total_cents": cart.get("total_cents"),
  }
  canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
  return hashlib.sha256(canonical.encode()).hexdigest()


def check_mandate_active(mandate: dict[str, Any], now: datetime) -> Check:
  name = "mandate_active"
  status = mandate.get("status")
  if status != "active":
    return _check(name, False, f"Mandate status is {status!r}, not 'active'.")

  valid_from = _parse_time(mandate.get("valid_from"))
  valid_until = _parse_time(mandate.get("valid_until"))
  if mandate.get("valid_from") is not None and valid_from is None:
    return _check(name, False, "Mandate valid_from is not a valid timestamp.")
  if mandate.get("valid_until") is not None and valid_until is None:
    return _check(name, False, "Mandate valid_until is not a valid timestamp.")
  if valid_from and now < valid_from:
    return _check(name, False, f"Mandate is not valid until {valid_from.isoformat()}.")
  if valid_until and now > valid_until:
    return _check(name, False, f"Mandate expired at {valid_until.isoformat()}.")
  return _check(name, True, "Mandate is active and within its validity window.")


def check_cart_for_mandate(mandate: dict[str, Any], cart: dict[str, Any]) -> Check:
  name = "cart_for_mandate"
  if cart.get("mandate_id") != mandate.get("id"):
    return _check(
      name,
      False,
      f"Cart is for mandate {cart.get('mandate_id')!r}, not {mandate.get('id')!r}.",
    )
  return _check(name, True, "Cart references this mandate.")


def check_within_limit(mandate: dict[str, Any], cart: dict[str, Any]) -> Check:
  name = "within_limit"
  total, limit = cart.get("total_cents"), mandate.get("max_cents")
  if not _is_cents(total):
    return _check(name, False, "Cart total_cents is not a non-negative integer.")
  if not _is_cents(limit):
    return _check(name, False, "Mandate max_cents is not a non-negative integer.")
  if total > limit:
    return _check(name, False, f"Total ${total / 100:.2f} is over the ${limit / 100:.2f} limit.")
  return _check(name, True, f"Total ${total / 100:.2f} is within the ${limit / 100:.2f} limit.")


def check_currency(mandate: dict[str, Any], cart: dict[str, Any]) -> Check:
  name = "currency_matches"
  expected = mandate.get("currency")
  # The Cart contract has no currency field, and every Leash cart is USD. If a
  # cart ever does carry one, it has to match.
  actual = cart.get("currency", "USD")
  if expected != "USD":
    return _check(name, False, f"Mandate currency {expected!r} is not supported; Leash is USD.")
  if actual != expected:
    return _check(name, False, f"Cart currency {actual!r} does not match mandate {expected!r}.")
  return _check(name, True, "Currency is USD.")


def check_merchant_allowlist(mandate: dict[str, Any], cart: dict[str, Any]) -> Check:
  name = "merchant_allowlisted"
  allowlist = mandate.get("merchant_allowlist")
  if not allowlist:
    return _check(name, True, "Mandate has no merchant allowlist.")
  merchant = cart.get("merchant") or {}
  # The allowlist may hold display names or card descriptors; accept either,
  # case-insensitively, but nothing fuzzier than that.
  allowed = {str(entry).strip().casefold() for entry in allowlist}
  candidates = {str(merchant.get(k, "")).strip().casefold() for k in ("name", "descriptor")}
  if allowed & (candidates - {""}):
    return _check(name, True, f"Merchant {merchant.get('name')!r} is on the allowlist.")
  return _check(name, False, f"Merchant {merchant.get('name')!r} is not on the allowlist.")


def check_mcc_category(mandate: dict[str, Any], cart: dict[str, Any]) -> Check:
  name = "mcc_matches_category"
  category = mandate.get("category")
  merchant = cart.get("merchant") or {}
  raw_mcc = merchant.get("mcc")
  try:
    mcc = int(str(raw_mcc))
  except ValueError:
    return _check(name, False, f"Merchant MCC {raw_mcc!r} is not a number.")
  allowed = CATEGORY_MCCS.get(category)
  if allowed is None:
    return _check(name, False, f"No MCC rule for category {category!r}, so nothing matches.")
  if mcc not in allowed:
    return _check(
      name, False, f"Merchant MCC {raw_mcc} is not a {category} merchant category code."
    )
  return _check(name, True, f"Merchant MCC {raw_mcc} fits category {category!r}.")


def check_cart_hash(cart: dict[str, Any]) -> Check:
  name = "cart_hash_matches"
  sent = cart.get("cart_hash")
  if not sent:
    return _check(name, False, "Cart has no cart_hash.")
  if sent != _cart_hash(cart):
    return _check(name, False, "Cart contents do not match its cart_hash.")
  return _check(name, True, "Cart hash matches its contents.")


def run_hard_checks(mandate: dict[str, Any], cart: dict[str, Any], now: datetime) -> list[Check]:
  return [
    check_mandate_active(mandate, now),
    check_cart_for_mandate(mandate, cart),
    check_within_limit(mandate, cart),
    check_currency(mandate, cart),
    check_merchant_allowlist(mandate, cart),
    check_mcc_category(mandate, cart),
    check_cart_hash(cart),
  ]
