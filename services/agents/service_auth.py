"""Bearer authentication for the agents service's own routes.

POST /runs, GET /runs/{id}, and POST /guardian/evaluate are for the Leash api
(and the e2e runner), never for browsers or agents. Callers present
AGENTS_SERVICE_TOKEN. With no token configured the routes refuse every call:
keeping the service off the public ingress is necessary but isn't
authentication.

Run ownership (which user, which mandate) is bound by the api when the run
registers; see shopper/registration.py.
"""

import hmac
import os

from fastapi import Header, HTTPException


def require_service_token(authorization: str | None = Header(default=None)) -> None:
  expected = os.environ.get("AGENTS_SERVICE_TOKEN")
  if not expected:
    raise HTTPException(status_code=503, detail="agents service token is not configured")
  scheme, _, token = (authorization or "").partition(" ")
  if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip(), expected):
    raise HTTPException(
      status_code=401,
      detail="missing or invalid service token",
      headers={"WWW-Authenticate": "Bearer"},
    )
