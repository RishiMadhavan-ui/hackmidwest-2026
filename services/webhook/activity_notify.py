"""Best-effort activity fan-out AFTER the authorize response (not on the critical path)."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from decide import Decision

logger = logging.getLogger("leash.webhook.activity")


def notify_authorization_decided(
  *,
  decision: Decision,
  event_id: str,
  instrument_token: str,
  amount_cents: int,
  currency: str,
  descriptor: str,
  mcc: str,
  user_id: str | None,
  decision_source: str,
  latency_ms: float,
) -> None:
  """POST authorization.decided into the API audit feed when configured."""
  api = os.getenv("API_URL", "").strip().rstrip("/")
  token = os.getenv("WEBHOOK_INTERNAL_TOKEN", "").strip()
  if not api or not token:
    return
  body: dict[str, Any] = {
    "type": "authorization.decided",
    "instrument_token": instrument_token,
    "data": {
      "result": decision.result,
      "reason": decision.reason,
      "rail": decision.rail,
      "decision_source": decision_source,
      "latency_ms": latency_ms,
      "event_id": event_id,
      "amount_cents": amount_cents,
      "currency": currency,
      "descriptor": descriptor,
      "mcc": mcc,
      "provider": decision_source,
    },
  }
  if user_id:
    body["user_id"] = user_id
  try:
    with httpx.Client(timeout=2.0) as client:
      res = client.post(
        f"{api}/internal/activity",
        headers={
          "Authorization": f"Bearer {token}",
          "Content-Type": "application/json",
        },
        json=body,
      )
    if res.status_code >= 400:
      logger.warning("activity notify failed status=%s", res.status_code)
  except httpx.HTTPError:
    logger.warning("activity notify unreachable", exc_info=False)
