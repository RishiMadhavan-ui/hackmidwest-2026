import json

from provenance.redact import REDACTED, redact, redact_text

PAN = "4111111111111111"


def test_card_dict_keeps_only_last_four():
  card = {"card_number": PAN, "exp_month": 12, "exp_year": 2028, "cvv": "123"}
  out = redact(card)
  assert out == {
    "card_number": "[CARD ****1111]",
    "exp_month": 12,
    "exp_year": 2028,
    "cvv": REDACTED,
  }


def test_nested_and_listed_values():
  payload = {"status": "approved", "card": {"number": PAN, "cvc": 987}, "items": [{"pan": PAN}]}
  dumped = json.dumps(redact(payload))
  assert PAN not in dumped
  assert "987" not in dumped
  assert "****1111" in dumped


def test_pan_inside_free_text():
  for text in (PAN, "4111 1111 1111 1111", "4111-1111-1111-1111", f"card={PAN}."):
    out = redact_text(f"use {text} now")
    assert "41111111" not in out.replace(" ", "").replace("-", "")
    assert "****1111" in out


def test_cvv_inside_free_text_and_json_strings():
  for text in ('"cvv": "123"', "cvv=123", "CVV: 123", "cvc 4567", "security code 123"):
    out = redact_text(text)
    assert "123" not in out and "4567" not in out, out


def test_card_details_inside_serialized_tool_result():
  # MCP tool results arrive as JSON text, so key-based redaction can't see them.
  text = json.dumps({"card": {"number": PAN, "exp_month": 12, "cvv": "321"}})
  out = redact_text(text)
  assert PAN not in out
  assert "321" not in out


def test_credentials_masked():
  out = redact({"Authorization": "Bearer sk-live-abc", "note": "sent Bearer abc.def-ghi"})
  assert out["Authorization"] == REDACTED
  assert "abc.def-ghi" not in out["note"]


def test_ordinary_values_untouched():
  value = {"total_cents": 2999, "sku": "CHG-USB-C-65W", "id": "pay_01ABC", "qty": 1}
  assert redact(value) == value
