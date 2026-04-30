import asyncio
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routes import limiter, router
from app.config import get_settings
from app.database import wait_for_db
from app.scheduler.runner import _configure_logging, run_scheduler

# CORS_ORIGINS env var: comma-separated list of allowed origins.
# Example: CORS_ORIGINS=https://amazonscraper.viet.bui
# Defaults to localhost origins for local dev only.
_raw_origins = os.environ.get("CORS_ORIGINS", "")
_cors_origins: list[str] = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    or ["http://localhost:3000", "http://localhost:5173"]
)

# API_KEY env var: if set, all requests must include X-API-Key header with this value.
# Leave unset to disable auth (local dev / Caddy IP-allowlist is the alternative).
_API_KEY = os.environ.get("API_KEY", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging(get_settings().log_level)
    await wait_for_db()
    task = asyncio.create_task(run_scheduler())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Price Drop Monitor", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

if _API_KEY:
    @app.middleware("http")
    async def require_api_key(request: Request, call_next):
        provided = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(provided.encode(), _API_KEY.encode()):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)

app.include_router(router)
