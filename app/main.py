from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings, STATIC_DIR, TEMPLATES_DIR, DATA_DIR
from app.core.logging import setup_logging
from app.db.session import Base, engine, SessionLocal
from app.models import User  # ensure models are imported
from app.core.templates import templates
from app.services.scheduler import start_scheduler, shutdown_scheduler

# Routers
from app.routers import auth as auth_router
from app.routers import dashboard as dashboard_router
from app.routers import profile as profile_router
from app.routers import admin as admin_router
from app.routers import picks as picks_router
from app.routers import history as history_router


settings = get_settings()
setup_logging()
logger = logging.getLogger("app")

app = FastAPI(title=settings.APP_NAME)

# Static
app.mount("/static", StaticFiles(directory=(Path(__file__).parent / "static").as_posix()), name="static")
avatars_root = (DATA_DIR / "avatars")
avatars_root.mkdir(parents=True, exist_ok=True)
app.mount("/avatars", StaticFiles(directory=avatars_root.as_posix()), name="avatars")


class FirstRunRedirectMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        # Allow static and setup-admin and health
        path = request.url.path
        if path.startswith("/static") or path.startswith("/setup-admin") or path.startswith("/healthz"):
            return await call_next(request)

        # Check if any user exists; if not, redirect to setup-admin
        try:
            with SessionLocal() as db:
                has_user = db.query(User.id).first() is not None
            if not has_user:
                return RedirectResponse(url="/setup-admin", status_code=302)
        except Exception as e:
            logger.exception("Startup DB issue: %s", e)
        return await call_next(request)


# Middleware
app.add_middleware(FirstRunRedirectMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    # Create tables if not present
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ensured.")

    # Lightweight migrations for existing installs (no Alembic yet)
    try:
        with engine.begin() as conn:
            insp = inspect(conn)
            # Add season_type to weeks if missing (ESPN semantics: 1=Pre, 2=Reg, 3=Post)
            week_cols = [c.get("name") for c in insp.get_columns("weeks")]
            if "season_type" not in week_cols:
                logger.info("Applying migration: add weeks.season_type ...")
                conn.execute(text("ALTER TABLE weeks ADD COLUMN season_type INTEGER DEFAULT 2"))
                # Backfill NULLs to default regular season
                conn.execute(text("UPDATE weeks SET season_type = 2 WHERE season_type IS NULL"))
                # Best-effort index (supported by SQLite and Postgres)
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_weeks_season_type ON weeks(season_type)"))
                logger.info("Migration applied: weeks.season_type added and backfilled.")
    except Exception:
        logger.exception("Startup migration failed; proceeding without blocking.")
    # Start background scheduler (weekly backups, etc.)
    try:
        start_scheduler()
    except Exception:
        logger.exception("Failed to start background scheduler")


@app.on_event("shutdown")
def on_shutdown() -> None:
    try:
        shutdown_scheduler()
    except Exception:
        logger.exception("Failed to shutdown background scheduler")


@app.get("/healthz", response_class=HTMLResponse)
def healthz(request: Request):
    return HTMLResponse("ok")

@app.get("/favicon.ico")
def favicon_redirect():
    return RedirectResponse(url="/static/favicon.svg", status_code=308)


# Include routers
app.include_router(auth_router.router)
app.include_router(dashboard_router.router)
app.include_router(profile_router.router)
app.include_router(admin_router.router)
app.include_router(picks_router.router)
app.include_router(history_router.router)
