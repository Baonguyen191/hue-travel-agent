"""Test-wide setup: the API plan store and checkpointer live in memory, so test runs never touch backend/data."""

from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["CHECKPOINT_URL"] = "memory://"
