from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "backend" / "scripts" / "audit_hue.py"
DATABASE_PATH = ROOT / "backend" / "data" / "hue.sqlite"

spec = importlib.util.spec_from_file_location("audit_hue", AUDIT_PATH)
assert spec and spec.loader
audit_hue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_hue)


def test_audit_reports_expected_source_facts() -> None:
    report = audit_hue.generate_audit_report(DATABASE_PATH)

    assert report["integrity"] == "ok"
    assert report["row_count"] == 1587
    assert report["category_count"] == 8
    assert sum(category["count"] for category in report["categories"]) == 1587
    assert report["invalid_attributes_json_rows"] == 0
    assert report["coordinates"]["min_lat"] < report["coordinates"]["max_lat"]
    assert report["coordinates"]["min_lon"] < report["coordinates"]["max_lon"]
    assert report["sources"] == [{"value": "huetripo.hue.gov.vn", "count": 1587}]
