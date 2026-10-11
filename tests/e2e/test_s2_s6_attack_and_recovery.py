"""S2/S6 share one actual Graph, unchanged mandate and one authorization."""


def test_s2_same_merchant_same_amount_subscription_blocked(attack_session):
  blocked = [row for row in attack_session["attempts"] if row["state"] == "blocked"]
  assert blocked, attack_session
  assert all(row["authorization_status"] != "authorized" for row in blocked)
  assert any("subscription" in (row["reason"] or "").lower()
             or "verification" in (row["reason"] or "").lower() for row in blocked)


def test_s6_same_graph_recovers_under_unchanged_mandate(attack_session):
  rows = attack_session["attempts"]
  approved = [row for row in rows if row["authorization_status"] == "authorized"]
  assert len(approved) == 1, attack_session
  assert any(row["state"] == "blocked" for row in rows)
  assert len({row["mandate_id"] for row in rows}) == 1
  assert {row["mandate_version"] for row in rows} == {attack_session["mandate"]["version"]}
  assert approved[0]["rail"] == "local_payment_rail_simulator"
