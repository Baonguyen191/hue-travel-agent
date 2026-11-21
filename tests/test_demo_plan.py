"""`plan` demo subcommand: the DoD sentence end to end, missing fields, and flag consistency."""

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

DOD_SENTENCE = (
    "Tôi đi Huế 3 ngày 2 đêm, xuất phát Hà Nội, 2 người, "
    "ngân sách 6 triệu, thích di tích và đặc sản"
)


def test_dod_plan_waits_restarts_approves_and_books_mock_items(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["plan", DOD_SENTENCE, "--start", "2026-12-05", "--approve", "BUDGET", "--book"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "AWAITING_APPROVAL" in output
    assert "APPROVED" in output
    assert "MÔ PHỎNG" in output
    assert "từ checkpoint" in output
    assert "TỰ LIÊN HỆ" in output
    assert "… và " in output
    assert "search → itinerary → budget → validate → approval" in output


def test_plan_without_start_exits_2_and_names_the_missing_start_date(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["plan", DOD_SENTENCE])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "start_date" in captured.out + captured.err


def test_book_without_approve_is_refused_with_exit_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["plan", DOD_SENTENCE, "--start", "2026-12-05", "--book"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "--approve" in captured.err


def test_fail_hotel_reports_partially_booked(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        ["plan", DOD_SENTENCE, "--start", "2026-12-05", "--approve", "BUDGET", "--book", "--fail", "hotel"]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "PARTIALLY_BOOKED" in output


def test_json_output_is_the_final_plan_and_booking(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        ["plan", DOD_SENTENCE, "--start", "2026-12-05", "--approve", "BUDGET", "--book", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["plan"]["status"] == "APPROVED"
    assert payload["booking"]["status"] == "BOOKED"
