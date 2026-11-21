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


def test_book_dod_scenario_shows_steps_mock_items_and_contact_lines(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["book", "--scenario", "dod"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Đặt khi chưa duyệt → bị chặn (409)" in output
    assert "Duyệt phương án Tiết kiệm (version 1" in output
    assert "MÔ PHỎNG" in output
    assert "TỰ LIÊN HỆ" in output
    assert "BOOKED" in output
    assert "không đặt trùng" in output
    assert "Giải thích" in output


def test_book_fail_hotel_reports_partially_booked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["book", "--scenario", "dod", "--fail", "hotel"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "PARTIALLY_BOOKED" in output


def test_book_timeout_hotel_is_reconciled_on_the_second_press(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["book", "--scenario", "dod", "--timeout", "hotel"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "UNKNOWN" in output
    assert "đối soát" in output
    assert "UNKNOWN → BOOKED" in output


def test_book_price_change_reconfirms_and_books_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["book", "--scenario", "dod", "--price-change"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "RECONFIRM_REQUIRED" in output
    assert "MOCK-" not in output
    assert "book calls: 0" in output


def test_book_other_user_is_refused_with_403(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["book", "--scenario", "dod", "--other-user"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "403" in output


def test_book_json_prints_only_the_final_booking_result(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["book", "--scenario", "dod", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "BOOKED"
    assert any(item["kind"] == "POI" for item in payload["items"])


def test_book_unknown_option_exits_2_with_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["book", "--scenario", "dod", "--option", "COMFORT"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "COMFORT" in captured.err
