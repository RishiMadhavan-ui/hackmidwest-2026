"""Live and scripted runs use separate, mode-bound Leash credentials."""

import pytest

from shopper.credentials import CredentialError, credential_for

LIVE = "live-token-0123456789abcdef0123456789"
SCRIPTED = "scripted-token-0123456789abcdef012345"


@pytest.fixture
def both(monkeypatch):
  monkeypatch.setenv("AGENT_TOKEN_SHOPPER", LIVE)
  monkeypatch.setenv("AGENT_TOKEN_SHOPPER_SCRIPTED", SCRIPTED)


def test_each_mode_gets_its_own_token_and_agent_id(both):
  live, scripted = credential_for("live"), credential_for("scripted")
  assert (live.token, live.agent_id) == (LIVE, "agt_shopper")
  assert (scripted.token, scripted.agent_id) == (SCRIPTED, "agt_shopper_scripted")
  assert scripted.bearer() == {"Authorization": f"Bearer {SCRIPTED}"}


def test_scripted_never_falls_back_to_the_live_credential(monkeypatch):
  monkeypatch.setenv("AGENT_TOKEN_SHOPPER", LIVE)
  with pytest.raises(CredentialError, match="AGENT_TOKEN_SHOPPER_SCRIPTED is not set") as err:
    credential_for("scripted")
  assert LIVE not in str(err.value)


def test_live_never_falls_back_to_the_scripted_credential(monkeypatch):
  monkeypatch.setenv("AGENT_TOKEN_SHOPPER_SCRIPTED", SCRIPTED)
  with pytest.raises(CredentialError, match="AGENT_TOKEN_SHOPPER is not set"):
    credential_for("live")


def test_one_token_for_both_modes_is_refused(monkeypatch):
  monkeypatch.setenv("AGENT_TOKEN_SHOPPER", LIVE)
  monkeypatch.setenv("AGENT_TOKEN_SHOPPER_SCRIPTED", LIVE)
  for mode in ("live", "scripted"):
    with pytest.raises(CredentialError, match="separate credential") as err:
      credential_for(mode)
    assert LIVE not in str(err.value)


def test_one_agent_id_for_both_modes_is_refused(both, monkeypatch):
  monkeypatch.setenv("SHOPPER_SCRIPTED_AGENT_ID", "agt_shopper")
  with pytest.raises(CredentialError, match="different agent ids"):
    credential_for("scripted")


def test_agent_ids_are_configurable(both, monkeypatch):
  monkeypatch.setenv("SHOPPER_SCRIPTED_AGENT_ID", "agt_fixture")
  assert credential_for("scripted").agent_id == "agt_fixture"
