"""R03 deterministic policy. Trusted callers supply authentication and scope facts.

This module never fetches an agent URL, calls a model, issues a grant or charges.
The merchant retrieval/payment integration remains a separate completion gate.
"""

from datetime import datetime
from uuid import uuid4

from leash_shared.models import (
  Check,
  CheckoutSnapshot,
  CheckoutVerification,
  ConstraintOperator,
  MandateStatus,
  PurchaseMandate,
  VerificationDecision,
)

SUPPORTED_CATEGORIES = frozenset({"laptop_charger"})


def attribute_matches(actual, constraint) -> bool:
  expected = constraint.value
  if constraint.operator == ConstraintOperator.EQUALS:
    if type(actual) is not type(expected):
      return False
    return (
      actual.strip().casefold() == expected.strip().casefold()
      if isinstance(actual, str)
      else actual == expected
    )
  if constraint.operator == ConstraintOperator.CONTAINS:
    return (
      isinstance(actual, str)
      and expected.strip().casefold() in actual.strip().casefold()
    )
  if type(actual) is not int:
    return False
  return (
    actual >= expected
    if constraint.operator == ConstraintOperator.MINIMUM
    else actual <= expected
  )


def verify_checkout(
  mandate: PurchaseMandate,
  checkout: CheckoutSnapshot,
  *,
  now: datetime,
  confirmation_valid: bool,
  checkout_authenticated: bool,
  successful_purchases: int,
) -> CheckoutVerification:
  # Fail closed even for incorrectly typed internal callers; no truthy strings
  # or inferred counts can supply the authentication/scope predicates.
  if (
    type(confirmation_valid) is not bool
    or type(checkout_authenticated) is not bool
    or type(successful_purchases) is not int
    or successful_purchases < 0
    or now.tzinfo is None
  ):
    raise ValueError(
      "Verified authentication, purchase count and aware server clock are required"
    )
  checks = []

  def add(name, passed, reason):
    checks.append(
      Check(name=name, passed=bool(passed), detail="passed" if passed else reason)
    )

  add(
    "mandate_confirmed",
    confirmation_valid
    and mandate.status == MandateStatus.ACTIVE
    and mandate.approved_at is not None
    and mandate.signature is not None,
    "mandate_unconfirmed",
  )
  add(
    "mandate_valid",
    mandate.valid_from <= now < mandate.valid_until,
    "mandate_expired_or_not_started",
  )
  add(
    "checkout_authenticated",
    checkout_authenticated and checkout.user_id == mandate.user_id,
    "checkout_source_unavailable_or_wrong_owner",
  )
  # Revalidate at the enforcement boundary; nested attributes may hold mutable data.
  CheckoutSnapshot.model_validate(checkout.model_dump(mode="python"))
  PurchaseMandate.model_validate(mandate.model_dump(mode="python"))
  recurrence_consistent = all(
    not item.billing_interval or item.subscription or item.recurring
    for item in checkout.items
  )
  add("checkout_integrity", recurrence_consistent, "checkout_recurrence_inconsistent")
  add(
    "checkout_valid",
    checkout.source.retrieved_at <= now < checkout.expires_at,
    "checkout_expired_or_future_evidence",
  )
  known_category = mandate.category in SUPPORTED_CATEGORIES
  add(
    "category",
    known_category
    and all(item.product_category == mandate.category for item in checkout.items),
    "unknown_category" if not known_category else "category_mismatch",
  )
  constraint_ok = True
  unknown = False
  for item in checkout.items:
    attributes = {}
    duplicates = set()
    for attribute in item.attributes:
      key = attribute.name.strip().casefold()
      if key in attributes:
        duplicates.add(key)
      attributes[key] = attribute.value
    for constraint in mandate.product_constraints:
      key = constraint.name.strip().casefold()
      if key not in attributes or key in duplicates:
        unknown = True
        constraint_ok = False
      elif not attribute_matches(attributes[key], constraint):
        constraint_ok = False
  add(
    "product_constraints",
    constraint_ok,
    "product_attribute_unknown" if unknown else "product_constraint_unmet",
  )
  add(
    "quantity",
    sum(item.quantity for item in checkout.items) <= mandate.max_quantity,
    "quantity_exceeded",
  )
  add(
    "purchase_scope",
    successful_purchases < mandate.maximum_purchases,
    "purchase_scope_exhausted",
  )
  add(
    "merchant",
    mandate.merchant_allowlist is None
    or checkout.merchant_id in mandate.merchant_allowlist,
    "merchant_not_allowed",
  )
  add("amount", checkout.total_cents <= mandate.max_cents, "amount_over_limit")
  add("currency", checkout.currency == mandate.currency, "currency_mismatch")
  add(
    "subscription",
    mandate.allow_subscription or all(not item.subscription for item in checkout.items),
    "subscription_prohibited",
  )
  add(
    "recurring",
    mandate.allow_recurring or all(not item.recurring for item in checkout.items),
    "recurring_prohibited",
  )
  shipping = mandate.shipping_constraints
  shipping_ok = (
    mandate.location is None
  )  # Free-text location needs a confirmed structured interpretation.
  if shipping:
    shipping_ok = shipping_ok and (
      (shipping.country is None or checkout.shipping_country == shipping.country)
      and (
        shipping.postal_code is None
        or (
          checkout.shipping_postal_code is not None
          and checkout.shipping_postal_code.strip().casefold()
          == shipping.postal_code.strip().casefold()
        )
      )
      and (
        shipping.deliver_by is None
        or (
          checkout.delivery_at is not None
          and checkout.delivery_at <= shipping.deliver_by
        )
      )
      and (
        shipping.max_shipping_cents is None
        or checkout.shipping_cents <= shipping.max_shipping_cents
      )
    )
  add("shipping", shipping_ok, "shipping_constraint_unverified")
  reasons = tuple(check.detail for check in checks if not check.passed)
  return CheckoutVerification(
    id="ver_" + uuid4().hex,
    user_id=mandate.user_id,
    purchase_attempt_id=checkout.purchase_attempt_id,
    mandate_id=mandate.id,
    mandate_version=mandate.version,
    mandate_hash=mandate.canonical_payload_hash,
    checkout_id=checkout.checkout_id,
    checkout_hash=checkout.checkout_hash,
    decision=VerificationDecision.BLOCKED if reasons else VerificationDecision.VERIFIED,
    checks=tuple(checks),
    reasons=reasons,
    verified_at=now,
  )
