from contextlib import asynccontextmanager

from fastapi import FastAPI

from guardian.routes import router as guardian_router
from provenance.sink import api_configured, default_sinks
from shopper.credentials import CredentialError, credential_for
from shopper.runs import router as runs_router


@asynccontextmanager
async def lifespan(_: FastAPI):
  # Start each credential's trace outbox right away so events spooled before a
  # restart are delivered even if no new run starts.
  if api_configured():
    import os
    token = os.environ.get("AGENTS_SERVICE_TOKEN", "")
    if len(token) >= 32:
      for sink in default_sinks(token, "delegated"):
        sink.start()
    for mode in ("live", "scripted"):
      try:
        credential = credential_for(mode)
      except CredentialError:
        continue  # that mode isn't provisioned here
      for sink in default_sinks(credential.token, mode):
        start = getattr(sink, "start", None)
        if start:
          start()
  yield


app = FastAPI(title="Leash agents", lifespan=lifespan)
app.include_router(guardian_router)
app.include_router(runs_router)


# /health matches the api and the LKE probes; /healthz is the AGENTS.md name.
@app.get("/health")
@app.get("/healthz")
def healthz():
  return {"status": "ok", "service": "agents"}
