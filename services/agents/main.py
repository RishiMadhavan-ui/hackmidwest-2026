from contextlib import asynccontextmanager

from fastapi import FastAPI

from guardian.routes import router as guardian_router
from provenance.sink import default_sinks
from shopper.runs import router as runs_router


@asynccontextmanager
async def lifespan(_: FastAPI):
  # Start the trace outbox right away so events spooled before a restart are
  # delivered even if no new run starts.
  for sink in default_sinks():
    start = getattr(sink, "start", None)
    if start:
      start()
  yield


app = FastAPI(title="Leash agents", lifespan=lifespan)
app.include_router(guardian_router)
app.include_router(runs_router)


@app.get("/healthz")
def healthz():
  return {"status": "ok", "service": "agents"}
