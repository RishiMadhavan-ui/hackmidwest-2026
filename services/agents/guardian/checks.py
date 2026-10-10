"""Deterministic guardian findings. No model, no I/O.

These run before any model call (AGENTS.md: deterministic checks first). They
are findings for the investigation, not the payment decision: the api's
checkout verifier and the rail decide whether money moves.

Every check fails closed. A missing or malformed field is a finding, never a
pass. Each finding carries a severity: "block" means the attempt breaks a
confirmed constraint; "review" means the evidence is incomplete or suspicious.
"""

from datetime import UTC, datetime
from typing import Any

# TODO: switch to leash_shared.models (PurchaseMandate, CheckoutSnapshot,
# AgentTraceEvent) once R01 is frozen. Field names follow the draft in
# tests/decision_cases.yaml.

Check = dict[str, Any]

REQUIRED_ITEM_FIELDS = (
  "sku",
  "product_category",
  "unit_cents",
  "quantity",
  "recurring",
  "subscription",
)


def _check(
  name: str, passed: bool, severity: str, detail: str, evidence: list[str] | None = None
) -> Check:
  return {
    "name": name,
    "passed": passed,
    "severity": severity,
    "detail": detail,
    "evidence": evidence or [],
  }


def _parse_time(value: Any) -> datetime | None:
  if not isinstance(value, str):
    return None
  try:
    parsed = datetime.fromisoformat(value)
  except ValueError:
    return None
  return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _is_cents(value: Any) -> bool:
  # bool is a subclass of int, and True is not an amount.
  return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _dollars(cents: int) -> str:
  return f"${cents / 100:.2f}"


def check_mandate_active(mandate: dict[str, Any], now: datetime) -> Check:
  name = "mandate_active"
  if mandate.get("status") != "active":
    return _check(name, False, "block", f"Mandate status is {mandate.get('status')!r}.")
  for field in ("valid_from", "valid_until"):
    if mandate.get(field) is not None and _parse_time(mandate.get(field)) is None:
      return _check(name, False, "block", f"Mandate {field} is not a valid timestamp.")
  valid_from = _parse_time(mandate.get("valid_from"))
  valid_until = _parse_time(mandate.get("valid_until"))
  if valid_from and now < valid_from:
    return _check(name, False, "block", f"Mandate is not valid until {valid_from.isoformat()}.")
  if valid_until and now > valid_until:
    return _check(name, False, "block", f"Mandate expired at {valid_until.isoformat()}.")
  return _check(name, True, "block", "Mandate is confirmed and in its validity window.")


def check_checkout_complete(checkout: dict[str, Any] | None) -> Check:
  name = "trusted_checkout_complete"
  if not checkout:
    return _check(name, False, "review", "No trusted checkout from the merchant; nothing verified.")
  items = checkout.get("items")
  if not isinstance(items, list) or not items:
    return _check(name, False, "review", "Trusted checkout has no items.")
  for item in items:
    missing = [f for f in REQUIRED_ITEM_FIELDS if item.get(f) is None]
    if missing:
      return _check(
        name,
        False,
        "review",
        f"Checkout item {item.get('sku')!r} is missing {', '.join(missing)}.",
        [f"checkout:{checkout.get('checkout_id')}"],
      )
  for field in ("currency", "total_cents", "merchant_id"):
    if checkout.get(field) is None:
      return _check(name, False, "review", f"Trusted checkout is missing {field}.")
  return _check(
    name,
    True,
    "review",
    "Trusted checkout has every required field.",
    [f"checkout:{checkout.get('checkout_id')}"],
  )


def _items(checkout: dict[str, Any] | None) -> list[dict[str, Any]]:
  items = (checkout or {}).get("items")
  return items if isinstance(items, list) else []


def check_checkout_fresh(checkout: dict[str, Any] | None, now: datetime) -> Check:
  name = "checkout_not_expired"
  if checkout is None:
    return _check(name, False, "review", "No trusted checkout, so no expiry to check.")
  expires = _parse_time(checkout.get("expires_at"))
  if expires is None:
    return _check(name, False, "review", "Trusted checkout has no valid expiry.")
  if now > expires:
    return _check(name, False, "block", f"Checkout expired at {expires.isoformat()}.")
  return _check(name, True, "block", f"Checkout is valid until {expires.isoformat()}.")


def check_totals_consistent(checkout: dict[str, Any] | None) -> Check:
  name = "checkout_totals_consistent"
  if checkout is None:
    return _check(name, False, "review", "No trusted checkout totals.")
  parts = [checkout.get(k, 0) for k in ("subtotal_cents", "tax_cents", "shipping_cents")]
  total = checkout.get("total_cents")
  if not all(_is_cents(v) for v in [*parts, total]):
    return _check(name, False, "block", "Checkout amounts are not non-negative integer cents.")
  lines = sum(
    i.get("unit_cents", 0) * i.get("quantity", 0)
    for i in _items(checkout)
    if _is_cents(i.get("unit_cents")) and _is_cents(i.get("quantity"))
  )
  if sum(parts) != total or lines != checkout.get("subtotal_cents", lines):
    return _check(
      name,
      False,
      "review",
      f"Checkout amounts don't add up: items {lines}, parts {parts}, total {total}.",
    )
  return _check(name, True, "review", "Line items, subtotal, tax, shipping, and total agree.")


def check_category(mandate: dict[str, Any], checkout: dict[str, Any] | None) -> Check:
  name = "category_matches"
  wanted = mandate.get("category")
  ref = [f"checkout:{(checkout or {}).get('checkout_id')}"]
  wrong = [i for i in _items(checkout) if i.get("product_category") != wanted]
  if not wanted:
    return _check(name, False, "block", "Mandate has no category, so nothing can match.")
  if not _items(checkout):
    return _check(name, False, "review", "No trusted items to compare against the category.")
  if wrong:
    found = ", ".join(f"{i.get('sku')} is {i.get('product_category')!r}" for i in wrong)
    return _check(name, False, "block", f"User asked for {wanted!r}; checkout has {found}.", ref)
  return _check(name, True, "block", f"Every item is {wanted!r}.", ref)


def check_no_subscription(mandate: dict[str, Any], checkout: dict[str, Any] | None) -> Check:
  name = "no_subscription"
  # Absent permission means not allowed.
  if mandate.get("allow_subscription") is True:
    return _check(name, True, "block", "Mandate allows subscriptions.")
  subs = [i for i in _items(checkout) if i.get("subscription") is not False]
  if subs:
    skus = ", ".join(str(i.get("sku")) for i in subs)
    return _check(
      name,
      False,
      "block",
      f"User said no subscriptions; checkout item {skus} is a subscription or unknown.",
      [f"checkout:{(checkout or {}).get('checkout_id')}"],
    )
  return _check(name, True, "block", "No subscription items.")


def check_no_recurring(mandate: dict[str, Any], checkout: dict[str, Any] | None) -> Check:
  name = "no_recurring_charge"
  if mandate.get("allow_recurring") is True:
    return _check(name, True, "block", "Mandate allows recurring charges.")
  recurring = [i for i in _items(checkout) if i.get("recurring") is not False]
  if recurring:
    skus = ", ".join(str(i.get("sku")) for i in recurring)
    return _check(
      name,
      False,
      "block",
      f"Checkout item {skus} bills on a recurring schedule (or doesn't say).",
      [f"checkout:{(checkout or {}).get('checkout_id')}"],
    )
  return _check(name, True, "block", "No recurring charges.")


def check_quantity(mandate: dict[str, Any], checkout: dict[str, Any] | None) -> Check:
  name = "quantity_within_scope"
  limit = mandate.get("max_quantity", 1)
  total_qty = 0
  for item in _items(checkout):
    qty = item.get("quantity")
    if not _is_cents(qty) or qty < 1:
      return _check(name, False, "block", f"Item {item.get('sku')!r} has an invalid quantity.")
    total_qty += qty
  if total_qty > limit:
    return _check(name, False, "block", f"Checkout has {total_qty} units; mandate allows {limit}.")
  return _check(name, True, "block", f"{total_qty} unit(s), within the limit of {limit}.")


def check_total(mandate: dict[str, Any], checkout: dict[str, Any] | None) -> Check:
  name = "total_within_limit"
  limit = mandate.get("max_cents")
  total = (checkout or {}).get("total_cents")
  if not _is_cents(limit):
    return _check(name, False, "block", "Mandate max_cents is not a non-negative integer.")
  if checkout is None:
    return _check(name, False, "review", "No trusted total to compare against the limit.")
  if not _is_cents(total):
    return _check(name, False, "block", "Checkout total_cents is not a non-negative integer.")
  if total > limit:
    return _check(
      name, False, "block", f"Total {_dollars(total)} is over the {_dollars(limit)} limit."
    )
  return _check(name, True, "block", f"Total {_dollars(total)} is within {_dollars(limit)}.")


def check_currency(mandate: dict[str, Any], checkout: dict[str, Any] | None) -> Check:
  name = "currency_matches"
  expected = mandate.get("currency")
  if expected != "USD":
    return _check(name, False, "block", f"Mandate currency {expected!r} is not supported.")
  if checkout is None:
    return _check(name, False, "review", "No trusted checkout currency.")
  if checkout.get("currency") != expected:
    return _check(name, False, "block", f"Checkout is in {checkout.get('currency')!r}, not USD.")
  return _check(name, True, "block", "Currency is USD.")


def check_merchant(mandate: dict[str, Any], checkout: dict[str, Any] | None) -> Check:
  name = "merchant_allowed"
  allowlist = mandate.get("merchant_allowlist")
  if not allowlist:
    return _check(name, True, "block", "Mandate has no merchant allowlist.")
  if checkout is None:
    return _check(name, False, "review", "No trusted checkout, so the merchant is unknown.")
  merchant = checkout.get("merchant_id")
  if merchant in allowlist:
    return _check(name, True, "block", f"Merchant {merchant} is allowed.")
  return _check(name, False, "block", f"Merchant {merchant!r} is not on the allowlist.")


def _constraint_met(operator: str, wanted: Any, actual: Any) -> bool | None:
  """True/False if we can tell, None if the value's type makes it unknowable."""
  if operator == "equals":
    if isinstance(wanted, str) and isinstance(actual, str):
      return actual.strip().casefold() == wanted.strip().casefold()
    return type(actual) is type(wanted) and actual == wanted
  if operator == "contains":
    if not isinstance(actual, str):
      return None
    return str(wanted).casefold() in actual.casefold()
  if operator in ("minimum", "maximum"):
    if not _is_cents(actual) or not _is_cents(wanted):
      return None
    return actual >= wanted if operator == "minimum" else actual <= wanted
  return None


def check_product_constraints(mandate: dict[str, Any], checkout: dict[str, Any] | None) -> Check:
  name = "product_constraints_met"
  constraints = mandate.get("product_constraints") or []
  if not constraints:
    return _check(name, True, "block", "Mandate has no product constraints.")
  items = _items(checkout)
  if not items:
    return _check(name, False, "review", "No trusted items to check the product constraints.")
  ref = [f"checkout:{(checkout or {}).get('checkout_id')}"]
  unknown = []
  for item in items:
    attributes = {
      str(a.get("name", "")).casefold(): a.get("value") for a in item.get("attributes") or []
    }
    for constraint in constraints:
      attr = str(constraint.get("name", "")).casefold()
      operator = constraint.get("operator", "equals")
      wanted = constraint.get("value")
      if attr not in attributes:
        unknown.append(f"{item.get('sku')} doesn't state its {constraint.get('name')}")
        continue
      met = _constraint_met(operator, wanted, attributes[attr])
      if met is False:
        return _check(
          name,
          False,
          "block",
          f"User required {constraint.get('name')} {operator} {wanted!r}; "
          f"{item.get('sku')} has {attributes[attr]!r}.",
          ref,
        )
      if met is None:
        unknown.append(f"{item.get('sku')} {constraint.get('name')} can't be compared")
  if unknown:
    return _check(name, False, "review", "; ".join(unknown) + ".", ref)
  return _check(name, True, "block", "Every item meets the user's product constraints.", ref)


def check_claim_matches_checkout(
  proposal: dict[str, Any] | None, checkout: dict[str, Any] | None
) -> Check:
  """Did the agent describe what it's actually buying? A mismatch is evidence."""
  name = "agent_claim_matches_checkout"
  claimed = {i.get("sku") for i in (proposal or {}).get("items", []) if i.get("sku")}
  actual = {i.get("sku") for i in _items(checkout)}
  if not claimed or not actual:
    return _check(name, True, "review", "No SKU-level claim to compare.")
  if claimed != actual:
    return _check(
      name,
      False,
      "review",
      f"Agent said it was buying {sorted(claimed)}; the checkout contains {sorted(actual)}.",
      [f"checkout:{(checkout or {}).get('checkout_id')}"],
    )
  return _check(name, True, "review", "Agent's description matches the checkout.")


def suspicious_sources(provenance: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """Pages the agent read that hid instruction-like text."""
  out = []
  for record in provenance:
    phrases = record.get("hidden_suspicious_phrases") or []
    if record.get("hidden_text_detected") and phrases:
      out.append(
        {
          "url": record.get("url"),
          "sha256": record.get("sha256"),
          "excerpt": record.get("excerpt", ""),
          "phrases": phrases,
          "event_id": record.get("event_id"),
        }
      )
  return out


def check_injection_signals(provenance: list[dict[str, Any]]) -> Check:
  name = "no_injection_signals"
  sources = suspicious_sources(provenance)
  if sources:
    urls = ", ".join(str(s["url"]) for s in sources)
    return _check(
      name,
      False,
      "review",
      f"The agent read hidden instruction-like text on {urls}.",
      [f"source:{s['sha256']}" for s in sources],
    )
  return _check(name, True, "review", "No hidden instruction-like text on pages the agent read.")


def check_attempt_planted(
  provenance: list[dict[str, Any]], checkout: dict[str, Any] | None
) -> Check:
  """Was the SKU being bought named in hidden text the agent read?"""
  name = "attempt_not_planted_by_page"
  skus = [str(i.get("sku")) for i in _items(checkout) if i.get("sku")]
  for source in suspicious_sources(provenance):
    planted = [sku for sku in skus if sku in (source["excerpt"] or "")]
    if planted:
      return _check(
        name,
        False,
        "review",
        f"{', '.join(planted)} was named in hidden text on {source['url']} before the agent "
        "tried to buy it.",
        [f"source:{source['sha256']}", f"checkout:{(checkout or {}).get('checkout_id')}"],
      )
  return _check(name, True, "review", "Nothing being bought was named in hidden page text.")


def run_checks(
  mandate: dict[str, Any],
  checkout: dict[str, Any] | None,
  proposal: dict[str, Any] | None,
  provenance: list[dict[str, Any]],
  now: datetime,
) -> list[Check]:
  return [
    check_mandate_active(mandate, now),
    check_checkout_complete(checkout),
    check_checkout_fresh(checkout, now),
    check_totals_consistent(checkout),
    check_category(mandate, checkout),
    check_product_constraints(mandate, checkout),
    check_no_subscription(mandate, checkout),
    check_no_recurring(mandate, checkout),
    check_quantity(mandate, checkout),
    check_total(mandate, checkout),
    check_currency(mandate, checkout),
    check_merchant(mandate, checkout),
    check_claim_matches_checkout(proposal, checkout),
    check_injection_signals(provenance),
    check_attempt_planted(provenance, checkout),
  ]
