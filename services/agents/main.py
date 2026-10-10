from fastapi import FastAPI

from guardian.routes import router as guardian_router
from shopper.runs import router as runs_router

app = FastAPI(title="Leash agents")
app.include_router(guardian_router)
app.include_router(runs_router)


@app.get("/healthz")
def healthz():
  return {"status": "ok", "service": "agents"}
