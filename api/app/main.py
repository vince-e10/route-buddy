import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.logging_setup import configure_logging
from app.routers import confirm, webhooks, ws


app = FastAPI()
log = logging.getLogger(__name__)

app.include_router(confirm.router)
app.include_router(webhooks.router)
app.include_router(ws.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.on_event("startup")
async def startup() -> None:
    configure_logging(settings)
    try:
        import app.deps
    except ImportError:
        log.warning("agent dependencies are not wired")


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
