import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Hack Midwest API")

# Comma-separated origins. Same-origin /backend proxy on LKE does not need CORS;
# keep localhost for local Next.js, and allow the NodeBalancer origin when set.
_cors = os.getenv("CORS_ORIGINS", "http://localhost:3000")
allow_origins = [origin.strip() for origin in _cors.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "hackmidwest-api"
    }