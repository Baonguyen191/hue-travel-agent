"""PHASE 4 CLI demo tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.demo.__main__ import main  # noqa: E402


def test_search_dod_scenario_prints_category_tables_and_mock_offers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["search", "--scenario", "dod"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "historic" in output
    assert "restaurant" in output
    assert "[MOCK]" in output


def test_search_json_output_is_a_parseable_search_result(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["search", "--scenario", "dod", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] in {"READY", "PARTIAL"}
    assert payload["poi_candidates"]
    assert all(offer["source"] == "MOCK" for offer in payload["hotel_offers"])
