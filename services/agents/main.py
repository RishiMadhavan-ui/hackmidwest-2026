from fastapi import FastAPI

from guardian.routes import router as guardian_router

app = FastAPI(title="Leash agents")
app.include_router(guardian_router)


@app.get("/healthz")
def healthz():
  return {"status": "ok", "service": "agents"}
