from fastapi import FastAPI

app = FastAPI(title="Leash agents")


@app.get("/healthz")
def healthz():
  return {"status": "ok", "service": "agents"}
