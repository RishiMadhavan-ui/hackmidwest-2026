"""Server-held demo Ed25519 signing; this is not a device passkey."""

import base64
import os

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

from authority_errors import AuthorityError
from leash_shared.models import PurchaseMandate, canonical_json, mandate_payload


def signing_key() -> SigningKey:
  try:
    seed = base64.b64decode(os.environ.get("MANDATE_SIGNING_KEY", ""), validate=True)
    if len(seed) != 32:
      raise ValueError("invalid seed length")
    return SigningKey(seed)
  except (ValueError, TypeError) as exc:
    raise AuthorityError(503, "Mandate signing is not configured") from exc


def confirmation_bytes(mandate: PurchaseMandate) -> bytes:
  # Also bind when the authenticated owner confirmed this exact version.
  return canonical_json({
    "purpose": "leash.mandate-confirmation.v1",
    "mandate": mandate_payload(mandate),
    "canonical_payload_hash": mandate.canonical_payload_hash,
    "approved_at": mandate.approved_at,
  }).encode("utf-8")


def sign_confirmation(mandate: PurchaseMandate, key: SigningKey) -> str:
  return base64.b64encode(key.sign(confirmation_bytes(mandate)).signature).decode("ascii")


def verify_confirmation(mandate: PurchaseMandate, verify_key: str) -> bool:
  if mandate.signature is None or mandate.approved_at is None:
    return False
  try:
    public = VerifyKey(base64.b64decode(verify_key, validate=True))
    public.verify(confirmation_bytes(mandate), base64.b64decode(mandate.signature, validate=True))
  except (BadSignatureError, ValueError, TypeError):
    return False
  return True
