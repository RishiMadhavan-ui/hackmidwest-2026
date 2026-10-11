import logging
import os

import runtime  # noqa: F401
import psycopg
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from auth import router as auth_router
from authority_errors import AuthorityError, DatabaseUnavailable
from cards import router as cards_router
from db import init_db
from mandate_routes import router as mandate_router

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="Hack Midwest API")
app.state.schema_ready = False

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
app.include_router(cards_router)
app.include_router(mandate_router)


@app.exception_handler(AuthorityError)
def authority_error(_, exc: AuthorityError):
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail})


@app.exception_handler(DatabaseUnavailable)
@app.exception_handler(psycopg.Error)
def database_error(_, exc):
    # SQL/connection error strings may contain credentials or submitted data.
    logger.warning("Database operation failed (%s)", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Database temporarily unavailable"})


@app.exception_handler(RequestValidationError)
def invalid_request(_, exc):
    return JSONResponse(status_code=422, content={"detail": "Invalid request fields or values"})


@app.on_event("startup")
def on_startup() -> None:
    app.state.schema_ready = False
    if not os.getenv("DATABASE_URL", "").strip():
        logger.warning("DATABASE_URL unset — auth routes will fail until Postgres is configured")
        return
    if not os.getenv("JWT_SECRET", "").strip():
        logger.warning("JWT_SECRET unset — auth token minting will fail until configured")
    try:
        init_db()
        app.state.schema_ready = True
        logger.info("Database migrations ready")
    except Exception:
        logger.error("Database migration failed; readiness remains unavailable")
        raise DatabaseUnavailable("Database migration failed") from None


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "hackmidwest-api",
    }


@app.get("/healthz")
def healthz():
    return health()


@app.get("/readyz")
def readyz():
    if not app.state.schema_ready:
        return JSONResponse(status_code=503, content={"detail": "Database migrations are not ready"})
    try:
        from db import get_conn
        with get_conn() as conn:
            conn.execute("SELECT 1")
    except (DatabaseUnavailable, psycopg.Error):
        return JSONResponse(status_code=503, content={"detail": "Database temporarily unavailable"})
    return {"status": "ok", "service": "hackmidwest-api"}
