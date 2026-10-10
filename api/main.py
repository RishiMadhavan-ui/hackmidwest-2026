import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth import router as auth_router
from db import init_db

logger = logging.getLogger("uvicorn.error")

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

app.include_router(auth_router)


@app.on_event("startup")
def on_startup() -> None:
    if not os.getenv("DATABASE_URL", "").strip():
        logger.warning("DATABASE_URL unset — auth routes will fail until Postgres is configured")
        return
    if not os.getenv("JWT_SECRET", "").strip():
        logger.warning("JWT_SECRET unset — auth token minting will fail until configured")
    try:
        init_db()
        logger.info("Database ready (users table ensured)")
    except Exception:
        logger.exception("Failed to initialize database schema")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "hackmidwest-api",
    }
