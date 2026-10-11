"""ASA adapter unit tests (no Lithic network)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import base64
import hashlib
import hmac
import time
import unittest
from copy import deepcopy

from asa import (
  AsaAuthError,
  AsaConfigurationError,
  AsaParseError,
  decision_to_asa_result,
  normalize_asa_request,
  verify_asa_signature,
)
from decide import Decision


def _sign(secret: bytes, webhook_id: str, ts: str, body: bytes) -> str:
  signed = f"{webhook_id}.{ts}.".encode("utf-8") + body
  digest = base64.b64encode(hmac.new(secret, signed, hashlib.sha256).digest()).decode()
  return f"v1,{digest}"


class AsaAdapterTests(unittest.TestCase):
  def test_missing_invalid_secret_and_unknown_signature_version_fail_closed(self):
    arguments = dict(
      body=b"{}",
      webhook_id="msg_1",
      webhook_timestamp=str(int(time.time())),
      webhook_signature="v1,x",
    )
    for secret in ("", "whsec_!bad", "whsec_"):
      with self.assertRaises(AsaConfigurationError):
        verify_asa_signature(**arguments, secret=secret)
    key = b"test-secret"
    arguments["webhook_signature"] = _sign(
      key, arguments["webhook_id"], arguments["webhook_timestamp"], b"{}"
    ).replace("v1,", "v2,")
    with self.assertRaises(AsaAuthError):
      verify_asa_signature(**arguments, secret=base64.b64encode(key).decode())

  def test_amount_currency_and_merchant_identity_are_not_inferred(self):
    body = {
      "token": "txn-1",
      "status": "AUTHORIZATION",
      "card": {"token": "ins_1"},
      "merchant": {"descriptor": "VOLT SUPPLY CO", "mcc": "5732"},
      "amounts": {"merchant": {"amount": 2999, "currency": "USD"}},
    }
    variations = [
      {"amounts": {"merchant": {"amount": True, "currency": "USD"}}},
      {"amounts": {"merchant": {"amount": 2999.0, "currency": "USD"}}},
      {"amounts": {"merchant": {"amount": "2999", "currency": "USD"}}},
      {"amounts": {"merchant": {"amount": 2999}}},
      {
        "amounts": {
          "merchant": {"amount": 2999, "currency": "USD"},
          "hold": {"amount": 3000, "currency": "USD"},
        }
      },
      {"merchant": {"acceptor_id": "VOLT SUPPLY CO", "mcc": "5732"}},
      {"card": []},
      {"status": None},
      {"amounts": []},
    ]
    for change in variations:
      with self.subTest(change=change), self.assertRaises(AsaParseError):
        normalize_asa_request({**deepcopy(body), **change})

  def test_normalize_amounts_merchant_block(self) -> None:
    attempt = normalize_asa_request(
      {
        "token": "txn-1",
        "status": "AUTHORIZATION",
        "amounts": {"merchant": {"amount": 2999, "currency": "USD"}},
        "merchant": {"descriptor": "VOLT SUPPLY CO", "mcc": "5732"},
        "card": {"token": "ins_charger_01"},
      }
    )
    self.assertEqual(attempt.event_id, "txn-1")
    self.assertEqual(attempt.amount_cents, 2999)
    self.assertEqual(attempt.instrument_token, "ins_charger_01")
    self.assertEqual(attempt.request_type, "AUTHORIZATION")

  def test_hmac_accepts_valid_signature(self) -> None:
    body = b'{"token":"t"}'
    secret = b"test-secret"
    wid = "msg_1"
    ts = str(int(time.time()))
    sig = _sign(secret, wid, ts, body)
    verify_asa_signature(
      body=body,
      webhook_id=wid,
      webhook_timestamp=ts,
      webhook_signature=sig,
      secret="whsec_" + base64.b64encode(secret).decode(),
    )

  def test_hmac_rejects_bad_signature(self) -> None:
    with self.assertRaises(AsaAuthError):
      verify_asa_signature(
        body=b"{}",
        webhook_id="msg_1",
        webhook_timestamp=str(int(time.time())),
        webhook_signature="v1,deadbeef",
        secret="whsec_" + base64.b64encode(b"test-secret").decode(),
      )

  def test_decision_mapping(self) -> None:
    self.assertEqual(
      decision_to_asa_result(Decision(result="APPROVED", reason="approved")),
      "APPROVED",
    )
    self.assertEqual(
      decision_to_asa_result(Decision(result="DECLINED", reason="no_grant")),
      "UNAUTHORIZED_MERCHANT",
    )
    self.assertEqual(
      decision_to_asa_result(Decision(result="DECLINED", reason="killswitch_on")),
      "CARD_PAUSED",
    )


if __name__ == "__main__":
  unittest.main()
