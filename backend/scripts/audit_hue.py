"""Read-only audit for the supplied Hue SQLite places dataset."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

DEFAULT_DATABASE = Path(__file__).resolve().parents[1] / "data" / "hue.sqlite"


def open_read_only(database_path: Path) -> sqlite3.Connection:
    """Open an existing SQLite database without allowing any mutation."""
    if not database_path.is_file():
        raise FileNotFoundError(f"Database file not found: {database_path}")
    connection = sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def generate_audit_report(database_path: Path) -> dict[str, Any]:
    """Collect source facts without modifying the database or creating tables."""
    connection = open_read_only(database_path)
    try:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(places)")]
        if not columns:
            raise ValueError("Expected table 'places' was not found.")

        row_count = connection.execute("SELECT COUNT(*) FROM places").fetchone()[0]
        null_counts = {
            column: connection.execute(
                f'SELECT COUNT(*) FROM places WHERE "{column}" IS NULL'
            ).fetchone()[0]
            for column in columns
        }
        key_counts: Counter[str] = Counter()
        invalid_json_rows = 0
        for row in connection.execute("SELECT attributes_json FROM places"):
            try:
                attributes = json.loads(row["attributes_json"])
            except (TypeError, json.JSONDecodeError):
                invalid_json_rows += 1
                continue
            if isinstance(attributes, dict):
                key_counts.update(attributes.keys())
            else:
                invalid_json_rows += 1

        categories = [
            {"category": row["category"], "count": row["count"]}
            for row in connection.execute(
                "SELECT category, COUNT(*) AS count FROM places "
                "GROUP BY category ORDER BY category"
            )
        ]
        coordinate_range = connection.execute(
            "SELECT MIN(lat) AS min_lat, MAX(lat) AS max_lat, "
            "MIN(lon) AS min_lon, MAX(lon) AS max_lon FROM places"
        ).fetchone()

        def distributions(column: str) -> list[dict[str, Any]]:
            return [
                {"value": row["value"], "count": row["count"]}
                for row in connection.execute(
                    f'SELECT "{column}" AS value, COUNT(*) AS count FROM places '
                    f'GROUP BY "{column}" ORDER BY count DESC, value'
                )
            ]

        return {
            "database": str(database_path),
            "integrity": connection.execute("PRAGMA quick_check").fetchone()[0],
            "row_count": row_count,
            "category_count": len(categories),
            "categories": categories,
            "columns": columns,
            "null_counts": null_counts,
            "null_rates": {
                column: (count / row_count if row_count else 0.0)
                for column, count in null_counts.items()
            },
            "attribute_keys": dict(sorted(key_counts.items())),
            "invalid_attributes_json_rows": invalid_json_rows,
            "coordinates": dict(coordinate_range),
            "sources": distributions("source"),
            "licenses": distributions("license"),
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    try:
        report = generate_audit_report(args.database)
    except (FileNotFoundError, ValueError, sqlite3.Error) as error:
        parser.error(str(error))

    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Integrity: {report['integrity']}")
        print(f"Rows: {report['row_count']}")
        print(f"Categories ({report['category_count']}): {report['categories']}")
        print(f"NULL counts: {report['null_counts']}")
        print(f"Attribute keys: {report['attribute_keys']}")
        print(f"Coordinates: {report['coordinates']}")
        print(f"Sources: {report['sources']}")
        print(f"Licenses: {report['licenses']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
