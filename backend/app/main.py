import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.logging_config import configure_logging
from app.api import auth, agents, wallet, payments, deposit, admin, platform, distribution
from app.models import webhook_event  # noqa: F401 — registers table with SQLAlchemy metadata
from app.models import platform_setting  # noqa: F401 — registers table with SQLAlchemy metadata
from app.models import pack_purchase  # noqa: F401 — registers table with SQLAlchemy metadata
from app.workers.celery_app import celery_app  # noqa: F401

# Configure logging before anything else so all startup logs are formatted.
configure_logging(settings.LOG_LEVEL)
logger = logging.getLogger("app.request")

app = FastAPI(
    title="Agent Revenue Sharing Platform",
    description="Multi-tier AI agent revenue sharing with ProActive, Proportion, and Speculation systems",
    version="1.0.0",
)
#uvicorn app.main:app --reload
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,  # set CORS_ORIGINS in .env for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Log every request with method, path, status and how long it took.
    4xx/5xx responses are logged at WARNING so problems stand out.
    Unhandled exceptions are logged with a full traceback before re-raising.
    """
    start = time.perf_counter()
    client = request.client.host if request.client else "?"
    logger.debug("→ %s %s (from %s)", request.method, request.url.path, client)

    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.exception(
            "✗ %s %s — unhandled error after %.1fms", request.method, request.url.path, elapsed_ms
        )
        raise

    elapsed_ms = (time.perf_counter() - start) * 1000
    level = logging.WARNING if response.status_code >= 400 else logging.INFO
    logger.log(
        level,
        "%s %s → %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all so unexpected errors are always logged with a traceback."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

app.include_router(auth.router)
app.include_router(agents.router)
app.include_router(wallet.router)
app.include_router(payments.router)
app.include_router(deposit.router)
app.include_router(admin.router)
app.include_router(platform.router)
app.include_router(distribution.router)
