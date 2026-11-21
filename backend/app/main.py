"""FastAPI entry point for the PHASE 0 service health check."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.places import router as places_router
from app.api.plans import router as plans_router
from app.api.bookings import router as bookings_router
from app.core.config import hue_database_path

app = FastAPI(title="Hue Travel Multi-Agent", version="0.0.1")
app.include_router(places_router)
app.include_router(plans_router)
app.include_router(bookings_router)

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def can_open_read_only(database_path: Path) -> tuple[bool, str | None]:
    """Confirm that SQLite can read the database without creating side files."""
    if not database_path.is_file():
        return False, "Hue SQLite source file is missing."

    try:
        connection = sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            connection.execute("SELECT 1").fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return False, "Hue SQLite source file cannot be opened read-only."
    return True, None


@app.get("/health", response_model=None)
def health() -> dict[str, str] | JSONResponse:
    """Report whether the required read-only POI source is available."""
    available, detail = can_open_read_only(hue_database_path())
    if not available:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable", "database": "hue.sqlite", "detail": detail},
        )
    return {"status": "ok", "database": "hue.sqlite", "access": "read-only"}


# Mount last: a "/" mount registered before API routes would shadow them (e.g. /health).
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
