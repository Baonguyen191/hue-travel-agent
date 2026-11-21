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


def test_budget_dod_scenario_prints_labelled_options_with_data_and_mock_tags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["budget", "--scenario", "dod"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Tiết kiệm" in output
    assert "[DATA]" in output
    assert "[MOCK]" in output


def test_budget_json_output_is_a_parseable_budget_result(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["budget", "--scenario", "dod", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["options"]
    assert "BUDGET" in {option["label"] for option in payload["options"]}
    assert all(option["known_total_max_vnd"] >= option["known_total_vnd"] for option in payload["options"])


def test_itinerary_dod_scenario_prints_days_named_meals_and_budget_block(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["itinerary", "--scenario", "dod"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Đại Nội Huế" in output
    assert "[Ăn trưa]" in output
    assert "[Ăn tối]" in output
    assert "Tiết kiệm" in output
    assert "(tham khảo)" in output


def test_itinerary_hides_buffer_events_and_marks_source_data(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["itinerary", "--scenario", "dod"])
    output = capsys.readouterr().out

    assert "Travel buffer" not in output
    assert "[DATA]" in output
    assert "(chưa xác minh)" in output


def test_itinerary_json_output_is_a_parseable_itinerary_result(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["itinerary", "--scenario", "dod", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert len(payload["days"]) == 3
    assert "huetripo:657208" in payload["excluded_poi_ids"]
    assert payload["validation"]["valid"] is True
