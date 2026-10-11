#!/usr/bin/env bash
# Smoke the protected local-rail charge path against a live API + store.
#
# This is NOT the Mission Control mandate UI. It exercises:
#   agent run → store checkout → POST /payments (approve/block) → store complete → local rail
#
# Prerequisites:
#   1. Public API reachable (LKE NodeBalancer or local uvicorn).
#   2. Store checkout API reachable (not public on LKE — port-forward first):
#        export KUBECONFIG="$PWD/hackmidwest-kubeconfig.yaml"
#        kubectl -n hackmidwest port-forward svc/store 8004:8000
#   3. .env has STORE_API_TOKEN, STORE_CHARGE_TOKEN, AGENT_TOKEN_SHOPPER
#      (same values mounted in the cluster Secret).
#   4. That agent token is bound to the human you log in as
#      (UI draft usually binds AGENT_TOKEN_SHOPPER; otherwise manage.py bind-agent).
#
# Usage:
#   set -a && source .env && set +a
#   export API_BASE=http://173.255.199.245/backend
#   export STORE_BASE=http://127.0.0.1:8004
#   export EMAIL='you@example.com' PASSWORD='your-password'
#   bash scripts/smoke_protected_charge.sh
#
# Optional: SKIP_COMPLETE=1 to stop after approve (no merchant charge).
set -euo pipefail

API_BASE="${API_BASE:?Set API_BASE e.g. http://173.255.199.245/backend}"
STORE_BASE="${STORE_BASE:?Set STORE_BASE e.g. http://127.0.0.1:8004 (port-forward)}"
EMAIL="${EMAIL:?Set EMAIL for the human account}"
PASSWORD="${PASSWORD:?Set PASSWORD}"
AGENT_TOKEN="${AGENT_TOKEN_SHOPPER:?Set AGENT_TOKEN_SHOPPER from .env}"
STORE_API_TOKEN="${STORE_API_TOKEN:?}"
STORE_CHARGE_TOKEN="${STORE_CHARGE_TOKEN:?}"
SKIP_COMPLETE="${SKIP_COMPLETE:-0}"

json_field() {
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(d'"$1"')'
}

echo "==> health"
curl -sf "$API_BASE/health" | python3 -m json.tool >/dev/null
curl -sf "$API_BASE/readyz" | python3 -m json.tool >/dev/null
curl -sf -o /dev/null -w "store:%{http_code}\n" "$STORE_BASE/healthz" || {
  echo "Store not reachable at $STORE_BASE — start port-forward to svc/store."
  exit 1
}

echo "==> login as human"
HUMAN_TOKEN=$(curl -sf -X POST "$API_BASE/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":$(python3 -c 'import json,os; print(json.dumps(os.environ["EMAIL"]))'),\"password\":$(python3 -c 'import json,os; print(json.dumps(os.environ["PASSWORD"]))')}" \
  | json_field "['access_token']")
OWNER=$(curl -sf "$API_BASE/identity" -H "Authorization: Bearer $HUMAN_TOKEN" | json_field "['user_id']")
echo "    user_id=$OWNER"

echo "==> agent proposes mandate"
DRAFT=$(curl -sf -X POST "$API_BASE/mandates/propose" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "description": "Buy a USB-C laptop charger for under $40. No subscriptions.",
    "category": "laptop_charger",
    "max_cents": 3999,
    "product_constraints": [
      {"name": "connector", "operator": "equals", "value": "USB-C"},
      {"name": "wattage", "operator": "minimum", "value": 65}
    ]
  }')
MANDATE_ID=$(printf '%s' "$DRAFT" | json_field "['id']")
VERSION=$(printf '%s' "$DRAFT" | json_field "['version']")
HASH=$(printf '%s' "$DRAFT" | json_field "['canonical_payload_hash']")
echo "    mandate_id=$MANDATE_ID"

echo "==> human confirms mandate"
curl -sf -X POST "$API_BASE/mandates/$MANDATE_ID/approve" \
  -H "Authorization: Bearer $HUMAN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"version\":$VERSION,\"canonical_payload_hash\":\"$HASH\",\"confirmed\":true}" \
  | json_field "['status']" | grep -q active

echo "==> register agent run"
RUN_ID="run_$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
curl -sf -X POST "$API_BASE/agent-runs" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"id\":\"$RUN_ID\",\"mandate_id\":\"$MANDATE_ID\",\"agent_mode\":\"live\",\"model\":\"smoke\",\"provider\":\"smoke\"}" \
  >/dev/null
echo "    run_id=$RUN_ID"

approve_and_maybe_complete() {
  local sku="$1"
  local expect_status="$2"
  echo "==> store checkout sku=$sku"
  local checkout
  checkout=$(curl -sf -X POST "$STORE_BASE/api/checkouts" \
    -H "Authorization: Bearer $STORE_API_TOKEN" \
    -H 'Content-Type: application/json' \
    -d "{\"sku\":\"$sku\",\"quantity\":1}")
  local checkout_id
  checkout_id=$(printf '%s' "$checkout" | json_field "['checkout_id']")
  echo "    checkout_id=$checkout_id"

  echo "==> POST /payments (expect status=$expect_status)"
  local pay_code pay_body
  pay_code=$(curl -s -o /tmp/leash_pay.json -w '%{http_code}' -X POST "$API_BASE/payments" \
    -H "Authorization: Bearer $AGENT_TOKEN" \
    -H 'Content-Type: application/json' \
    -d "{\"mandate_id\":\"$MANDATE_ID\",\"checkout_id\":\"$checkout_id\",\"run_id\":\"$RUN_ID\"}")
  pay_body=$(cat /tmp/leash_pay.json)
  echo "    HTTP $pay_code"
  printf '%s\n' "$pay_body" | python3 -m json.tool
  local status
  status=$(printf '%s' "$pay_body" | json_field "['status']")
  if [[ $status != "$expect_status" ]]; then
    echo "FAIL: expected payment status $expect_status, got $status"
    exit 1
  fi

  if [[ $expect_status == approved && $SKIP_COMPLETE != 1 ]]; then
    local payment_id instrument
    payment_id=$(printf '%s' "$pay_body" | json_field "['id']")
    instrument=$(printf '%s' "$pay_body" | json_field "['instrument_token']")
    echo "==> store complete (local rail charge)"
    local complete
    complete=$(curl -sf -X POST "$STORE_BASE/api/checkouts/$checkout_id/complete" \
      -H "Authorization: Bearer $STORE_CHARGE_TOKEN" \
      -H 'Content-Type: application/json' \
      -d "{\"payment_id\":\"$payment_id\",\"instrument_token\":\"$instrument\"}")
    printf '%s\n' "$complete" | python3 -m json.tool
    printf '%s' "$complete" | json_field "['status']" | grep -q completed
    printf '%s' "$complete" | json_field "['rail_result']['result']" | grep -q APPROVED
    echo "    OK charged via local rail"
  fi
}

# Fresh run for the charger (one successful grant per mandate version).
approve_and_maybe_complete "CHG-65W" "approved"

# New mandate + run for the subscription block (historical approved grant blocks
# another checkout on the same mandate version).
echo "==> second mandate for subscription block"
DRAFT2=$(curl -sf -X POST "$API_BASE/mandates/propose" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "description": "Buy a USB-C laptop charger for under $40. No subscriptions.",
    "category": "laptop_charger",
    "max_cents": 3999,
    "product_constraints": [
      {"name": "connector", "operator": "equals", "value": "USB-C"},
      {"name": "wattage", "operator": "minimum", "value": 65}
    ]
  }')
MANDATE_ID=$(printf '%s' "$DRAFT2" | json_field "['id']")
VERSION=$(printf '%s' "$DRAFT2" | json_field "['version']")
HASH=$(printf '%s' "$DRAFT2" | json_field "['canonical_payload_hash']")
curl -sf -X POST "$API_BASE/mandates/$MANDATE_ID/approve" \
  -H "Authorization: Bearer $HUMAN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"version\":$VERSION,\"canonical_payload_hash\":\"$HASH\",\"confirmed\":true}" >/dev/null
RUN_ID="run_$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
curl -sf -X POST "$API_BASE/agent-runs" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"id\":\"$RUN_ID\",\"mandate_id\":\"$MANDATE_ID\",\"agent_mode\":\"live\",\"model\":\"smoke\",\"provider\":\"smoke\"}" \
  >/dev/null

approve_and_maybe_complete "SUB-CARE-MO" "blocked"

echo
echo "PASS: charger authorized(+completed) and subscription blocked."
echo "Optional UI check: Activity should show payment.approved / payment.denied for this user."
