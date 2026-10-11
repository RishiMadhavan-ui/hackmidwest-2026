"""Role and signature regressions without a database; PostgreSQL coverage follows."""

import base64
import os
from pathlib import Path
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime  # noqa: E402,F401
from fastapi.testclient import TestClient  # noqa: E402
from nacl.signing import SigningKey  # noqa: E402

from authority_errors import AuthorityError, DatabaseUnavailable  # noqa: E402
from leash_shared.models import MandateProposal, PurchaseMandate  # noqa: E402
from main import app, on_startup  # noqa: E402
from mandate_routes import MandateConfirmation  # noqa: E402
from mandate_service import approve, make_draft, propose_human, replace, revoke  # noqa: E402
from principals import Principal, leash_user_id, require_agent, require_human, require_reader  # noqa: E402
from signing import sign_confirmation, signing_key, verify_confirmation  # noqa: E402


class SigningTests(unittest.TestCase):
  def setUp(self):
    self.now = datetime.now(timezone.utc)
    self.draft = make_draft(MandateProposal(description="Buy a USB-C charger. No subscriptions.", category="laptop_charger", max_cents=3999),
                            mandate_id="mnd_test", version=1, user_id="usr_test", agent_id="agt_shopper", now=self.now)
    self.key = SigningKey.generate()
    unsigned = self.draft.model_copy(update={"approved_at": self.now})
    self.active = PurchaseMandate.model_validate({**self.draft.model_dump(), "status": "active",
                     "approved_at": self.now, "signature": sign_confirmation(unsigned, self.key)})
    self.public = base64.b64encode(bytes(self.key.verify_key)).decode("ascii")

  def test_real_ed25519_and_every_authority_change_invalidates_signature(self):
    self.assertTrue(verify_confirmation(self.active, self.public))
    for field, value in {"max_cents":4000, "allow_subscription":True, "user_id":"usr_other",
                         "version":2, "description":"Buy a subscription", "approved_at":self.now+timedelta(seconds=1)}.items():
      with self.subTest(field=field):
        self.assertFalse(verify_confirmation(self.active.model_copy(update={field:value}), self.public))
    other_key = base64.b64encode(bytes(SigningKey.generate().verify_key)).decode("ascii")
    self.assertFalse(verify_confirmation(self.active, other_key))
    self.assertFalse(verify_confirmation(self.draft, self.public))

  def test_missing_or_malformed_signing_configuration_fails_closed(self):
    for value in ("", "not base64", base64.b64encode(b"short").decode()):
      with self.subTest(value=value), patch.dict(os.environ, {"MANDATE_SIGNING_KEY":value}):
        with self.assertRaises(AuthorityError) as error:
          signing_key()
        self.assertEqual(error.exception.status, 503)

  def test_default_expiry_is_bounded_and_past_expiry_is_rejected(self):
    self.assertEqual(self.draft.valid_until-self.now, timedelta(minutes=30))
    with self.assertRaises(AuthorityError):
      make_draft(MandateProposal(description="charger", category="laptop_charger", max_cents=3999,
                                valid_until=self.now-timedelta(seconds=1)),
                 mandate_id="mnd_past", version=1, user_id="usr_test", agent_id="agt_shopper", now=self.now)

  def test_confirmation_needs_exact_binding_and_strict_true(self):
    binding = {"version":1, "canonical_payload_hash":self.draft.canonical_payload_hash}
    for confirmed in (False, 1, "true", None):
      with self.subTest(confirmed=confirmed), self.assertRaises(ValueError):
        MandateConfirmation(**binding, confirmed=confirmed)
    self.assertTrue(MandateConfirmation(**binding, confirmed=True).confirmed)

  def test_uuid_mapping_is_stable_and_validates_input(self):
    self.assertEqual(leash_user_id("12345678-1234-1234-1234-123456789abc"), "usr_12345678123412341234123456789abc")
    with self.assertRaises(ValueError):
      leash_user_id("usr_attacker")

  def test_direct_service_invocation_cannot_promote_an_agent(self):
    for operation in (approve, replace, revoke):
      with self.subTest(operation=operation.__name__), self.assertRaises(AuthorityError) as error:
        options = {"proposal":MandateProposal(description="charger",category="laptop_charger",max_cents=3999)} if operation is replace else {}
        operation(None,"mnd_test",Principal("agent","usr_test","agt_shopper",("live",)),
                  version=1,content_hash=self.draft.canonical_payload_hash,now=self.now,**options)
      self.assertEqual(error.exception.status,403)

  def test_human_draft_rejects_agent_principal(self):
    proposal = MandateProposal(
      description="Buy a USB-C charger. No subscriptions.",
      category="laptop_charger",
      max_cents=3999,
    )
    with self.assertRaises(AuthorityError) as error:
      propose_human(
        None,
        proposal,
        Principal("agent", "usr_test", "agt_shopper", ("live",)),
        now=self.now,
      )
    self.assertEqual(error.exception.status, 403)


class RouteBoundaryTests(unittest.TestCase):
  def setUp(self):
    self.client = TestClient(app)
    def denied():
      raise AuthorityError(401, "Not authenticated")
    app.dependency_overrides[require_human] = denied
    app.dependency_overrides[require_agent] = denied
    app.dependency_overrides[require_reader] = denied

  def tearDown(self):
    app.dependency_overrides.clear()
    self.client.close()

  def test_all_authority_routes_require_authentication(self):
    for method, path in [("POST","/mandates/propose"),("GET","/mandates"),("GET","/mandates/mnd_test"),
                         ("POST","/mandates/mnd_test/approve"),("PATCH","/mandates/mnd_test"),
                         ("POST","/mandates/mnd_test/revoke"),("GET","/mandates/mnd_test/versions"),
                         ("POST","/agent-runs"),("GET","/identity")]:
      with self.subTest(path=path):
        response = self.client.request(method,path,json={})
        self.assertEqual(response.status_code,401)
        self.assertIsInstance(response.json()["detail"],str)

  def test_invalid_proposals_and_agent_owned_authority_fields_return_plain_422(self):
    app.dependency_overrides[require_agent] = lambda: Principal("agent","usr_test","agt_shopper",("live",))
    for body in ({"description":"x", "category":"x", "max_cents":True},
                 {"description":"x", "category":"x", "max_cents":100, "user_id":"usr_other"}):
      response = self.client.post("/mandates/propose",json=body)
      self.assertEqual(response.status_code,422)
      self.assertIsInstance(response.json()["detail"],str)

  def test_database_outage_is_503_not_permanent_intake_error(self):
    app.dependency_overrides[require_reader] = lambda: Principal("human","usr_test")
    with patch("mandate_routes.get_conn",side_effect=DatabaseUnavailable("private connection detail")):
      response = self.client.get("/mandates")
    self.assertEqual(response.status_code,503)
    self.assertNotIn("private",response.text)

  def test_configured_database_migration_failure_stops_startup(self):
    with patch.dict(os.environ,{"DATABASE_URL":"local-test-configured"}), patch("main.init_db",side_effect=DatabaseUnavailable("private")):
      with self.assertRaises(DatabaseUnavailable) as error:
        on_startup()
    self.assertNotIn("private",str(error.exception))
    self.assertFalse(app.state.schema_ready)


if __name__ == "__main__":
  unittest.main()
