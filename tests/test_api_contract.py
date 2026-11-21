from __future__ import annotations
import sys
from pathlib import Path
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"backend"))
from app.main import app
def test_phase_10_public_api_contract_exposes_safe_workflow_routes():
    paths=TestClient(app).get("/openapi.json").json()["paths"]
    assert "/api/v1/plans/{thread_id}" in paths
    assert "/api/v1/plans/{thread_id}/approve" in paths
    assert "/api/v1/plans/{thread_id}/book" in paths
