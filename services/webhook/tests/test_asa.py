"""ASA adapter unit tests (no Lithic network)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import unittest

from asa import (
  AsaAuthError,
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
