"""FastAPI entry point for the PHASE 0 service health check."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.agents.checkpoint import open_checkpointer
from app.api.places import router as places_router
from app.api.plans import build_orchestrator, store as state_store, router as plans_router
from app.api.bookings import router as bookings_router
from app.core.config import checkpoint_url, database_url, hue_database_path, settings_notes, validate_settings
from app.core.health import checkpoint_status, hue_source_status, state_db_status
from app.db.migrate import upgrade_to_head

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate settings, migrate the state DB, then open the checkpointer and build the orchestrator."""
    problems = validate_settings()
    if problems:
        raise RuntimeError("Invalid configuration: " + "; ".join(problems))
    for note in settings_notes():
        logger.info(note)
    upgrade_to_head(database_url())
    target = checkpoint_url()
    async with open_checkpointer(target) as checkpointer:
        app.state.checkpointer = checkpointer
        app.state.checkpoint_url = target
        app.state.orchestrator = build_orchestrator(checkpointer)
        try:
            yield
        finally:
            app.state.checkpointer = None
            app.state.checkpoint_url = None


app = FastAPI(title="Hue Travel Multi-Agent", version="0.0.1", lifespan=lifespan)
app.include_router(places_router)
app.include_router(plans_router)
app.include_router(bookings_router)

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@app.get("/health", response_model=None)
def health(request: Request) -> dict[str, Any] | JSONResponse:
    """Report each component; any component down makes the whole service 503."""
    components = {
        "hue_source": hue_source_status(hue_database_path()),
        "state_db": state_db_status(state_store.engine),
        "checkpoint": checkpoint_status(
            getattr(request.app.state, "checkpointer", None),
            getattr(request.app.state, "checkpoint_url", None),
        ),
    }
    healthy = all(item["ok"] for item in components.values())
    body = {"status": "ok" if healthy else "unavailable", "components": components}
    if healthy:
        return body
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=body)


# Mount last: a "/" mount registered before API routes would shadow them (e.g. /health).
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
