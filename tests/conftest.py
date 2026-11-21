"""Test-wide setup: the API plan store lives in memory, so test runs never touch backend/data."""

from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite://"
