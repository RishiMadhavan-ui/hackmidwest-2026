"""Direct HTTP callers cannot mint payment instruments or choose another owner."""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime  # noqa: E402,F401
import auth  # noqa: E402
import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402
from leash_shared import lithic  # noqa: E402


class CardAuthorityTests(unittest.TestCase):
  def setUp(self):
    self.env = patch.dict(os.environ, {
      "AGENT_TOKEN_SHOPPER":"fixture-live-credential",
      "AGENT_TOKEN_SHOPPER_SCRIPTED":"fixture-scripted-credential",
      "AGENTS_SERVICE_TOKEN":"fixture-service-credential",
    }, clear=True)
    self.env.start()
    self.addCleanup(self.env.stop)
    self.secret = patch.object(auth, "JWT_SECRET", "fixture-human-jwt-key-" + "x"*32)
    self.secret.start()
    self.addCleanup(self.secret.stop)
    self.owner = str(uuid4())
    self.other = str(uuid4())
    self.token = auth.create_access_token(self.owner, "fixture@example.com")
    self.user = patch("auth.get_user_by_id", return_value={
      "id":self.owner, "email":"fixture@example.com"})
    self.user_mock = self.user.start()
    self.addCleanup(self.user.stop)
    self.database = patch("cards.get_conn")
    self.db_mock = self.database.start()
    self.addCleanup(self.database.stop)
    self.conn = self.db_mock.return_value.__enter__.return_value
    self.issuer = patch("leash_shared.lithic.create_virtual_card",
      side_effect=AssertionError("HTTP card management reached issuance"))
    self.issuer_mock = self.issuer.start()
    self.addCleanup(self.issuer.stop)
    self.client = TestClient(app)
    self.addCleanup(self.client.close)

  def call(self, method, path, token=None, body=None):
    headers = {"Authorization":"Bearer " + token} if token else {}
    return self.client.request(method, path, headers=headers, json=body)

  def assert_no_issuance(self):
    self.issuer_mock.assert_not_called()
    self.db_mock.assert_not_called()

  def test_missing_and_unknown_credentials_cannot_access_cards(self):
    for token in (None, "fixture-unregistered-agent"):
      for method, path, body in (("POST","/cards",{"spend_limit_cents":2999}),
                                ("GET","/cards",None),("GET","/cards/fixture-card",None)):
        with self.subTest(token=token, method=method, path=path):
          self.assertEqual(self.call(method,path,token,body).status_code,401)
    self.assert_no_issuance()

  def test_live_scripted_and_service_tokens_cannot_issue_or_read_any_users_cards(self):
    for name in ("AGENT_TOKEN_SHOPPER","AGENT_TOKEN_SHOPPER_SCRIPTED","AGENTS_SERVICE_TOKEN"):
      for method, path, body in (
        ("POST","/cards",{"user_id":self.other,"spend_limit_cents":2999}),
        ("GET",f"/cards?user_id={self.other}",None),
        ("GET",f"/cards/fixture-card?user_id={self.other}",None)):
        with self.subTest(credential=name,method=method,path=path):
          response = self.call(method,path,os.environ[name],body)
          self.assertEqual(response.status_code,403)
          self.assertIsInstance(response.json()["detail"],str)
    self.user_mock.assert_not_called()
    self.assert_no_issuance()

  def test_human_login_and_correlation_cannot_replace_verified_payment_authority(self):
    for single_use in (True, False):
      for duration in ("TRANSACTION","FOREVER"):
        response = self.call("POST","/cards",self.token,{
          "user_id":self.owner,"spend_limit_cents":2999,
          "single_use":single_use,"spend_limit_duration":duration,
          "correlation_id":"caller-claimed-grant"})
        self.assertEqual(response.status_code,409)
        self.assertIn("verified payment flow",response.json()["detail"])
        self.assertNotIn("pan",response.json())
        self.assertNotIn("cvv",response.json())
    self.assert_no_issuance()

  def test_human_cannot_choose_another_owner_for_any_card_route(self):
    for method,path,body in (
      ("POST","/cards",{"user_id":self.other,"spend_limit_cents":2999}),
      ("GET",f"/cards?user_id={self.other}",None),
      ("GET",f"/cards/fixture-card?user_id={self.other}",None)):
      self.assertEqual(self.call(method,path,self.token,body).status_code,403)
    self.assert_no_issuance()

  def test_caller_cannot_supply_a_grant_to_enable_direct_issuance(self):
    response = self.call("POST","/cards",self.token,{
      "spend_limit_cents":2999,"grant":{"status":"approved"}})
    self.assertEqual(response.status_code,422)
    self.assert_no_issuance()

  def test_deleted_account_and_invalid_signed_subject_cannot_manage_cards(self):
    self.user_mock.return_value = None
    self.assertEqual(self.call("GET","/cards",self.token).status_code,401)
    self.user_mock.reset_mock()
    bad_token = auth.create_access_token("not-a-uuid","fixture@example.com")
    self.assertEqual(self.call("GET","/cards",bad_token).status_code,401)
    self.user_mock.assert_not_called()
    self.assert_no_issuance()

  def metadata(self):
    return {"card_token":"fixture-card","last_four":"1234","spend_limit_cents":2999,
      "spend_limit_duration":"TRANSACTION","card_type":"SINGLE_USE","state":"OPEN",
      "correlation_id":"fixture-correlation","created_at":None}

  def test_human_metadata_list_uses_authenticated_owner_and_excludes_payment_details(self):
    self.conn.execute.return_value.fetchall.return_value = [self.metadata()]
    response = self.call("GET",f"/cards?user_id={self.owner}",self.token)
    self.assertEqual(response.status_code,200)
    self.assertEqual(self.conn.execute.call_args.args[1],(self.owner,))
    self.assertEqual(response.json()[0]["last_four"],"1234")
    self.assertNotIn("pan",response.json()[0])
    self.assertNotIn("cvv",response.json()[0])
    self.issuer_mock.assert_not_called()

  def test_card_lookup_scopes_the_query_to_both_card_and_owner(self):
    self.conn.execute.return_value.fetchone.return_value = self.metadata()
    response = self.call("GET","/cards/fixture-card",self.token)
    self.assertEqual(response.status_code,200)
    self.assertEqual(self.conn.execute.call_args.args[1],("fixture-card",self.owner))
    self.conn.execute.return_value.fetchone.return_value = None
    self.assertEqual(self.call("GET","/cards/another-users-card",self.token).status_code,404)
    self.issuer_mock.assert_not_called()


class InternalLithicIntegrationTests(unittest.TestCase):
  def test_non_sandbox_endpoints_rejected_before_http_or_credentials(self):
    for endpoint in ("production", "https://api.lithic.com", "http://attacker.invalid", "sandbbox", ""):
      with patch.dict(os.environ,{"LITHIC_ENVIRONMENT":endpoint},clear=True), \
          patch("leash_shared.lithic.httpx.Client") as client:
        with self.assertRaises(lithic.LithicError):
          lithic.create_account_holder("test@example.com","Demo","User","64101")
        client.assert_not_called()

  def test_provider_wrapper_remains_available_for_future_verified_backend_issuance(self):
    # Provider transport is mocked; this is adapter compatibility, not grant enforcement.
    with patch.dict(os.environ,{"LITHIC_API_KEY":"fixture-provider-key"},clear=True), \
        patch("leash_shared.lithic.httpx.Client") as client:
      transport = MagicMock()
      client.return_value.__enter__.return_value = transport
      transport.post.return_value = httpx.Response(201,json={
        "token":"fixture-card","last_four":"1234","pan":"fixture-pan","cvv":"fixture-cvv"})
      card = lithic.create_virtual_card("fixture-account",spend_limit_cents=2999,
        spend_limit_duration="TRANSACTION",card_type="SINGLE_USE",
        tags={"leash_correlation":"fixture-verified-payment"},include_payment_details=True)
      self.assertEqual(card["card_token"],"fixture-card")
      payload = transport.post.call_args.kwargs["json"]
      self.assertEqual(payload["type"],"SINGLE_USE")
      self.assertEqual(payload["spend_limit"],2999)
      self.assertEqual(payload["tags"]["leash_correlation"],"fixture-verified-payment")


if __name__ == "__main__":
  unittest.main()
