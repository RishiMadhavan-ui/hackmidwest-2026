from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from guardian import evaluate
from main import app

NOW = datetime(2026, 10, 10, 20, 0, tzinfo=UTC)

HOTEL = {
  "name": "Crossroads Hotel",
  "descriptor": "CROSSROADS HOTEL KC",
  "mcc": "7011",
  "url": "http://store.test/hotels/crossroads",
}
GIFT_CARDS = {
  "name": "GiftCard Express",
  "descriptor": "GIFTCARD EXPRESS",
  "mcc": "5947",
  "url": "http://store.test/giftcards",
}


def make_mandate(**overrides):
  mandate = {
    "id": "mnd_1",
    "user_id": "usr_demo",
    "agent_id": "agt_shopper",
    "status": "active",
    "description": "hotel in Kansas City on Saturday, max $180",
    "category": "lodging",
    "max_cents": 18000,
    "currency": "USD",
    "location": "Kansas City, MO",
    "valid_from": "2026-10-10T18:00:00Z",
    "valid_until": "2026-10-11T23:59:00Z",
    "merchant_allowlist": None,
    "version": 1,
  }
  return {**mandate, **overrides}


def make_cart(merchant=HOTEL, total_cents=16500, **overrides):
  cart = {
    "id": "crt_1",
    "mandate_id": "mnd_1",
    "merchant": merchant,
    "items": [{"name": "King room, Sat Oct 10", "quantity": 1, "unit_cents": total_cents}],
    "total_cents": total_cents,
  }
  cart.update(overrides)
  return cart


def failed(verdict):
  return {c["name"] for c in verdict["checks"] if not c["passed"]}


def test_clean_cart_has_no_findings():
  verdict = evaluate(make_mandate(), make_cart(), [], now=NOW)
  assert verdict["recommendation"] == "no_findings"
  assert failed(verdict) == set()
  assert len(verdict["checks"]) == 6


def test_gift_card_denied_on_mcc_alone():
  # The demo's first block. Under the limit and otherwise valid, so the MCC
  # check is the only thing that catches it, with no model involved.
  verdict = evaluate(make_mandate(), make_cart(merchant=GIFT_CARDS, total_cents=15000), [], now=NOW)
  assert verdict["recommendation"] == "block"
  assert failed(verdict) == {"mcc_matches_category"}
  assert verdict["model"] is None


def test_hotel_chain_mcc_range_allowed():
  verdict = evaluate(make_mandate(), make_cart(merchant={**HOTEL, "mcc": "3501"}), [], now=NOW)
  assert verdict["recommendation"] == "no_findings"


def test_amount_exactly_at_limit_has_no_findings():
  verdict = evaluate(make_mandate(), make_cart(total_cents=18000), [], now=NOW)
  assert verdict["recommendation"] == "no_findings"


@pytest.mark.parametrize(
  ("mandate", "cart", "check"),
  [
    (make_mandate(status="proposed"), make_cart(), "mandate_active"),
    (make_mandate(status="revoked"), make_cart(), "mandate_active"),
    (make_mandate(valid_until="2026-10-10T19:59:00Z"), make_cart(), "mandate_active"),
    (make_mandate(valid_from="2026-10-10T21:00:00Z"), make_cart(), "mandate_active"),
    (make_mandate(valid_until="not a date"), make_cart(), "mandate_active"),
    (make_mandate(), make_cart(mandate_id="mnd_other"), "cart_for_mandate"),
    (make_mandate(), make_cart(total_cents=18001), "within_limit"),
    (make_mandate(), make_cart(total_cents=165.0), "within_limit"),
    (make_mandate(max_cents="18000"), make_cart(), "within_limit"),
    (make_mandate(currency="EUR"), make_cart(), "currency_matches"),
    (make_mandate(), make_cart(currency="EUR"), "currency_matches"),
    (make_mandate(merchant_allowlist=["OTHER HOTEL"]), make_cart(), "merchant_allowlisted"),
    (make_mandate(category="flights"), make_cart(), "mcc_matches_category"),
    (make_mandate(), make_cart(merchant={**HOTEL, "mcc": "abc"}), "mcc_matches_category"),
  ],
)
def test_each_hard_failure_denies(mandate, cart, check):
  verdict = evaluate(mandate, cart, [], now=NOW)
  assert verdict["recommendation"] == "block"
  assert failed(verdict) == {check}
  assert verdict["reasons"]


def test_allowlist_matches_name_or_descriptor_case_insensitively():
  for entry in ("crossroads hotel", "CROSSROADS HOTEL KC"):
    verdict = evaluate(make_mandate(merchant_allowlist=[entry]), make_cart(), [], now=NOW)
    assert verdict["recommendation"] == "no_findings"


def test_missing_fields_fail_closed():
  verdict = evaluate({}, {}, [], now=NOW)
  assert verdict["recommendation"] == "block"
  assert failed(verdict) >= {"mandate_active", "within_limit", "mcc_matches_category"}


def test_evaluate_route():
  body = {
    "mandate": make_mandate(valid_until="2099-01-01T00:00:00Z"),
    "cart": make_cart(merchant=GIFT_CARDS),
    "provenance": [],
  }
  res = TestClient(app).post("/guardian/evaluate", json=body)
  assert res.status_code == 200
  verdict = res.json()
  assert verdict["recommendation"] == "block"
  assert set(verdict) == {"recommendation", "reasons", "checks", "suspicious_sources", "model"}
