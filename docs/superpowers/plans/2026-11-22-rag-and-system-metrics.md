# Place RAG + System Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a hybrid-retrieval RAG answerer for open place questions in the chat, then one evaluation harness that measures 13 metrics (RAG, Multi-Agent, Travel Planning, Performance).

**Architecture:** `backend/app/rag/` holds the index (bge-m3 vectors in a separate SQLite file), the retriever (BM25 + dense + RRF + filters), a fact checker and the answerer (qwen3.5:4b, JSON output, fallback to the existing template). `ChatService._place_info` calls the answerer when one is injected. `backend/app/evaluation/` holds gold loaders, pure metric functions, a 9b judge, tool spies, a chat harness and the `run` CLI that writes `reports/system/*.json`.

**Tech Stack:** Python 3, FastAPI, pydantic v2, httpx (`MockTransport` in tests), sqlite3, numpy (new), LangGraph (existing orchestrator), Ollama HTTP API, pytest.

**Spec:** `docs/superpowers/specs/2026-11-22-rag-and-system-metrics-design.md`

## Global Constraints

- Run every command from `backend/` with the project venv: `../.venv/Scripts/python` (Windows). Tests: `../.venv/Scripts/python -m pytest ../tests -q`.
- Tests never call a real Ollama: use `httpx.MockTransport`. `tests/conftest.py` sets `QU_ENABLED=false` and (after Task 5) `RAG_ENABLED=false`.
- Test files start with the same `sys.path` header as `tests/test_understanding_extract.py`:
  ```python
  import sys as _sys
  from pathlib import Path as _Path
  _BACKEND = _Path(__file__).resolve().parents[1] / "backend"
  if str(_BACKEND) not in _sys.path:
      _sys.path.insert(0, str(_BACKEND))
  ```
  and import app modules with `# noqa: E402`.
- POI ids look like `huetripo:531787`. Dai Noi is `huetripo:531787`, opening hours `07:30-17:30` (used by existing tests).
- The POI DB `backend/data/hue.sqlite` is read-only. The RAG index lives in `backend/data/rag_index.sqlite` (already git-ignored by `backend/data/*.sqlite`).
- Ollama models: generator `qwen3.5:4b`, judge `qwen3.5:9b`, embeddings `bge-m3`.
- Eval reference date: `EVAL_REF = date(2026, 11, 18)` from `app.understanding.evaluate`.
- Code style: module docstring, `from __future__ import annotations`, type hints, short docstrings, no new dependency except `numpy`.
- The full suite (587 tests before this plan) must pass at the end of every task.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/core/usage.py` (new) | `Usage`, `record_usage()`, `add_usage()` — per-turn token counts via a ContextVar |
| `backend/app/core/config.py` (modify) | `rag_enabled`, `rag_embed_model`, `rag_gen_model`, `rag_index_path` |
| `backend/app/understanding/extract.py` (modify) | call `add_usage("extractor", payload)` |
| `backend/app/rag/__init__.py` (new) | package marker |
| `backend/app/rag/index.py` (new) | `document_text`, `EmbedClient`, `EmbeddingStore`, `build_index`, CLI |
| `backend/app/rag/retrieve.py` (new) | `tokenize`, `BM25`, `rrf`, `Hit`, `RetrievalResult`, `Retriever` |
| `backend/app/rag/facts.py` (new) | `CITE_RE`, `FactMismatch`, `check_facts` |
| `backend/app/rag/answer.py` (new) | `RagAnswer`, `RagAnswerer`, `build_context`, `strip_citations` |
| `backend/app/chat/service.py` (modify) | optional `rag`, `handler_log`, `last_rag`; async `_place_info` |
| `backend/app/api/chat.py` (modify) | build the answerer once; inject into `ChatService` |
| `backend/app/evaluation/__init__.py` (new) | package marker |
| `backend/app/evaluation/gold.py` (new) | pydantic gold models + JSONL loaders |
| `backend/app/evaluation/stats.py` (new) | `mean`, `percentile`, `rate` |
| `backend/app/evaluation/rag_metrics.py` (new) | context precision/recall, faithfulness, claim F1 |
| `backend/app/evaluation/agent_metrics.py` (new) | handler hits, tool exact, tool counts |
| `backend/app/evaluation/planning_metrics.py` (new) | budget, schedule feasibility, constraint checks |
| `backend/app/evaluation/judge.py` (new) | `Judge` (claims, support, compare) over Ollama |
| `backend/app/evaluation/spies.py` (new) | `CallLog`, `spy_method`, `spy_poi_search` |
| `backend/app/evaluation/harness.py` (new) | `EvalHarness`, `build_harness`, `final_state` |
| `backend/app/evaluation/run.py` (new) | suites, summaries, CLI |
| `data/eval/rag_eval_v1.jsonl`, `data/eval/scenarios_v1.jsonl` (new) | gold sets (written by Opus, Task 6) |
| `reports/system/README.md` (new) | metric table and failure analysis (Task 8) |

---

### Task 1: Token usage recorder

**Files:**
- Create: `backend/app/core/usage.py`
- Modify: `backend/app/understanding/extract.py` (method `OllamaExtractor._chat`, near line 370)
- Test: `tests/test_usage.py`

**Interfaces:**
- Produces: `Usage(prompt_tokens: int = 0, completion_tokens: int = 0, calls: int = 0)` with `.total_tokens`, `.add(prompt, completion)`, `.to_dict() -> dict[str, int]`; `record_usage() -> ContextManager[dict[str, Usage]]`; `add_usage(component: str, payload: Mapping[str, Any]) -> None`. Component names used later: `"extractor"`, `"rag_generator"`, `"embedding"`, `"judge"`.

- [ ] **Step 1: Write the failing tests** — `tests/test_usage.py`

```python
"""Token usage recorder: sums Ollama counts per component, ignores missing counts, crosses threads."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))

import asyncio  # noqa: E402
import datetime as dt  # noqa: E402
import json  # noqa: E402

import httpx  # noqa: E402

from app.core.usage import Usage, add_usage, record_usage  # noqa: E402
from app.understanding.extract import OllamaExtractor  # noqa: E402


def test_add_usage_sums_counts_per_component() -> None:
    with record_usage() as usage:
        add_usage("extractor", {"prompt_eval_count": 100, "eval_count": 20})
        add_usage("extractor", {"prompt_eval_count": 50, "eval_count": 5})
        add_usage("rag_generator", {"prompt_eval_count": 7, "eval_count": 3})
    assert usage["extractor"] == Usage(prompt_tokens=150, completion_tokens=25, calls=2)
    assert usage["extractor"].total_tokens == 175
    assert usage["rag_generator"].to_dict() == {
        "prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10, "calls": 1,
    }


def test_missing_or_invalid_counts_add_zero_but_count_the_call() -> None:
    with record_usage() as usage:
        add_usage("extractor", {})
        add_usage("extractor", {"prompt_eval_count": "x", "eval_count": -4})
    assert usage["extractor"] == Usage(prompt_tokens=0, completion_tokens=0, calls=2)


def test_add_usage_without_recorder_does_nothing() -> None:
    add_usage("extractor", {"prompt_eval_count": 1, "eval_count": 1})


def test_counts_from_a_worker_thread_reach_the_recorder() -> None:
    async def scenario() -> None:
        await asyncio.to_thread(add_usage, "extractor", {"prompt_eval_count": 3, "eval_count": 2})

    with record_usage() as usage:
        asyncio.run(scenario())
    assert usage["extractor"].total_tokens == 5


def test_extractor_records_ollama_counts() -> None:
    content = json.dumps({"intent": "out_of_scope"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"message": {"content": content}, "prompt_eval_count": 900, "eval_count": 40}
        )

    extractor = OllamaExtractor("http://ollama.test", "qwen3.5:4b", transport=httpx.MockTransport(handler))
    with record_usage() as usage:
        try:
            extractor.extract("Thời tiết Huế thế nào?", dt.date(2026, 11, 18))
        except Exception:  # the minimal JSON may fail schema validation; the counts still count
            pass
    assert usage["extractor"].prompt_tokens >= 900
    assert usage["extractor"].completion_tokens >= 40
```

- [ ] **Step 2: Run and confirm failure**

Run: `../.venv/Scripts/python -m pytest ../tests/test_usage.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.core.usage'`.

- [ ] **Step 3: Implement** — `backend/app/core/usage.py`

```python
"""Token counts from Ollama responses, collected per chat turn without passing a recorder around.

`record_usage()` installs a dict in a ContextVar. `asyncio.to_thread` copies the context, so a
worker thread sees the same dict object and its additions are visible to the caller.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


@dataclass
class Usage:
    """Tokens used by one component during one recording."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.calls += 1

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "calls": self.calls,
        }


_CURRENT: ContextVar[dict[str, Usage] | None] = ContextVar("travel_usage", default=None)


@contextmanager
def record_usage() -> Iterator[dict[str, Usage]]:
    """Collect usage by component until the block ends."""
    usage: dict[str, Usage] = {}
    token = _CURRENT.set(usage)
    try:
        yield usage
    finally:
        _CURRENT.reset(token)


def add_usage(component: str, payload: Mapping[str, Any]) -> None:
    """Add one Ollama response's counts; does nothing when no recording is active."""
    usage = _CURRENT.get()
    if usage is None:
        return
    usage.setdefault(component, Usage()).add(
        _count(payload.get("prompt_eval_count")), _count(payload.get("eval_count"))
    )


def _count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value
```

In `backend/app/understanding/extract.py`: add `from app.core.usage import add_usage` to the imports, and in `OllamaExtractor._chat`, directly after the `try/except` block that sets `payload`, add:

```python
        if isinstance(payload, dict):
            add_usage("extractor", payload)
```

- [ ] **Step 4: Run tests**

Run: `../.venv/Scripts/python -m pytest ../tests/test_usage.py ../tests/test_understanding_extract.py -q`
Expected: all PASS.

- [ ] **Step 5: Full suite and commit**

Run: `../.venv/Scripts/python -m pytest ../tests -q` — expected all pass.

```bash
git add backend/app/core/usage.py backend/app/understanding/extract.py tests/test_usage.py
git commit -m "feat(core): per-turn token usage recorder for Ollama calls"
```

---

### Task 2: RAG config, document text, embedding client, index store

**Files:**
- Modify: `backend/app/core/config.py` (append functions), `backend/requirements.txt` (add numpy)
- Create: `backend/app/rag/__init__.py`, `backend/app/rag/index.py`
- Test: `tests/test_rag_index.py`

**Interfaces:**
- Consumes: `Place` (`app.schemas.place`), `HuePlacesRepository`, `add_usage` (Task 1).
- Produces:
  - `config.rag_enabled() -> bool`, `rag_embed_model() -> str` (default `"bge-m3"`), `rag_gen_model() -> str` (default `qu_model()`), `rag_index_path() -> Path` (env `RAG_INDEX_PATH`, default `DATA_DIR / "rag_index.sqlite"`).
  - `index.PHONE_KEY = "Điện thoại"`, `index.CATEGORY_LABELS: dict[str, str]`, `index.price_text(place) -> str | None`, `index.document_text(place) -> str`, `index.text_hash(text) -> str`.
  - `index.EmbedError(RuntimeError)`; `index.EmbedClient(base_url, model, timeout=120.0, transport=None)` with `.model` and `.embed(texts: Sequence[str]) -> list[list[float]]`.
  - `index.EmbeddingStore(path: Path)` with `.hashes(model) -> dict[str, str]`, `.upsert(model, rows: Sequence[tuple[str, str, Sequence[float]]])`, `.delete(poi_ids: Iterable[str])`, `.all_ids() -> set[str]`, `.load(model) -> tuple[list[str], numpy.ndarray]` (rows L2-normalised float32; shape `(0, 0)` when empty).
  - `index.IndexStats(embedded: int, unchanged: int, deleted: int)`; `index.build_index(places, store, client, batch=32) -> IndexStats`; `index.main(argv=None) -> int`.

- [ ] **Step 1: Add numpy**

Append `numpy>=1.26,<3` to `backend/requirements.txt`, then run `../.venv/Scripts/python -m pip install "numpy>=1.26,<3"`.
Expected: `Successfully installed numpy-...`.

- [ ] **Step 2: Write the failing tests** — `tests/test_rag_index.py`

```python
"""RAG index: document text, hashing, embedding client, incremental store."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))

import json  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

import httpx  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

from app.core import config  # noqa: E402
from app.rag.index import (  # noqa: E402
    EmbedClient,
    EmbedError,
    EmbeddingStore,
    build_index,
    document_text,
    text_hash,
)
from app.schemas.place import Place  # noqa: E402


def make_place(poi_id: str = "huetripo:1", **overrides: object) -> Place:
    data: dict[str, object] = {
        "id": poi_id,
        "name": "Bún bò Mệ Kéo",
        "category": "restaurant",
        "lat": 16.47,
        "lon": 107.58,
        "address": "20 Bạch Đằng",
        "opening_hours_raw": "06:00-21:00",
        "opening_hours_confidence": "UNVERIFIED",
        "price_min_vnd": 30000,
        "price_max_vnd": 50000,
        "price_status": "REFERENCE_RANGE",
        "rating_value": 4.5,
        "rating_count": 120,
        "summary": "Quán bún bò lâu đời.",
        "source": "huetripo",
        "source_place_id": poi_id.split(":")[1],
        "collected_at": datetime(2026, 11, 1, tzinfo=timezone.utc),
        "raw_attributes": {"Loại hình (theo nguồn)": "Quán ăn", "Điện thoại": "0234 3826 123"},
    }
    data.update(overrides)
    return Place.model_validate(data)


def test_document_text_orders_fields_and_skips_missing_ones() -> None:
    text = document_text(make_place())
    assert text == (
        "Bún bò Mệ Kéo. quán ăn. Loại hình: Quán ăn. Địa chỉ: 20 Bạch Đằng. "
        "Giờ mở cửa: 06:00-21:00. Giá: 30.000đ – 50.000đ. Điện thoại: 0234 3826 123. "
        "Đánh giá: 4.5/5 (120 lượt). Quán bún bò lâu đời."
    )
    bare = document_text(make_place(address=None, opening_hours_raw=None, price_min_vnd=None,
                                    price_max_vnd=None, price_status="UNKNOWN", rating_value=None,
                                    rating_count=None, summary=None, raw_attributes={}))
    assert bare == "Bún bò Mệ Kéo. quán ăn"


def test_text_hash_is_stable_and_changes_with_text() -> None:
    assert text_hash("a") == text_hash("a")
    assert text_hash("a") != text_hash("b")


def _embed_handler(calls: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        vectors = [[float(len(text)), 1.0, 0.0] for text in body["input"]]
        return httpx.Response(200, json={"embeddings": vectors, "prompt_eval_count": 5})
    return handler


def test_embed_client_posts_model_and_inputs() -> None:
    calls: list[dict] = []
    client = EmbedClient("http://ollama.test", "bge-m3", transport=httpx.MockTransport(_embed_handler(calls)))
    assert client.embed(["ab", "abc"]) == [[2.0, 1.0, 0.0], [3.0, 1.0, 0.0]]
    assert calls == [{"model": "bge-m3", "input": ["ab", "abc"]}]


def test_embed_client_raises_on_wrong_count() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[1.0]]})
    client = EmbedClient("http://ollama.test", "bge-m3", transport=httpx.MockTransport(handler))
    with pytest.raises(EmbedError):
        client.embed(["a", "b"])


def test_build_index_embeds_only_changed_rows_and_deletes_removed(tmp_path) -> None:
    calls: list[dict] = []
    client = EmbedClient("http://ollama.test", "bge-m3", transport=httpx.MockTransport(_embed_handler(calls)))
    store = EmbeddingStore(tmp_path / "rag.sqlite")
    first = [make_place("huetripo:1"), make_place("huetripo:2", name="Chè Hẻm")]
    assert build_index(first, store, client, batch=1).embedded == 2
    assert len(calls) == 2

    calls.clear()
    second = [make_place("huetripo:1"), make_place("huetripo:3", name="Cơm hến")]
    stats = build_index(second, store, client)
    assert (stats.embedded, stats.unchanged, stats.deleted) == (1, 1, 1)
    assert calls[0]["input"] == [document_text(second[1])]
    assert store.all_ids() == {"huetripo:1", "huetripo:3"}


def test_store_load_returns_normalised_float32_matrix(tmp_path) -> None:
    store = EmbeddingStore(tmp_path / "rag.sqlite")
    store.upsert("bge-m3", [("huetripo:2", "h2", [0.0, 3.0]), ("huetripo:1", "h1", [4.0, 0.0])])
    ids, matrix = store.load("bge-m3")
    assert ids == ["huetripo:1", "huetripo:2"]
    assert matrix.dtype == np.float32
    np.testing.assert_allclose(matrix, [[1.0, 0.0], [0.0, 1.0]])
    assert store.load("other-model")[1].shape == (0, 0)


def test_config_defaults(monkeypatch) -> None:
    for name in ("RAG_ENABLED", "RAG_EMBED_MODEL", "RAG_GEN_MODEL", "RAG_INDEX_PATH", "QU_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert config.rag_enabled() is True
    assert config.rag_embed_model() == "bge-m3"
    assert config.rag_gen_model() == "qwen3.5:4b"
    assert config.rag_index_path() == config.DATA_DIR / "rag_index.sqlite"
    monkeypatch.setenv("RAG_ENABLED", "off")
    assert config.rag_enabled() is False
```

`Place` literals (from `app/schemas/place.py`): `OpeningHoursConfidence = "UNVERIFIED" | "PARTIAL" | "UNKNOWN"`, `PriceStatus = "REFERENCE_RANGE" | "FREE_CLAIM" | "UNKNOWN"`. A free place uses `is_free_claim=True`.

- [ ] **Step 3: Run and confirm failure**

Run: `../.venv/Scripts/python -m pytest ../tests/test_rag_index.py -q`
Expected: FAIL, `No module named 'app.rag'`.

- [ ] **Step 4: Implement config** — append to `backend/app/core/config.py`:

```python
def _flag(name: str) -> bool:
    """An on/off environment flag that is on unless set to 0, false, no or off."""
    value = os.environ.get(name)
    if value is None or not value.strip():
        return True
    return value.strip().lower() not in {"0", "false", "no", "off"}


def rag_enabled() -> bool:
    """False keeps place answers on the template path (tests and offline use)."""
    return _flag("RAG_ENABLED")


def rag_embed_model() -> str:
    """Ollama embedding model for the place index."""
    return os.environ.get("RAG_EMBED_MODEL") or "bge-m3"


def rag_gen_model() -> str:
    """Ollama model that writes place answers; defaults to the understanding model."""
    return os.environ.get("RAG_GEN_MODEL") or qu_model()


def rag_index_path() -> Path:
    """SQLite file with the place embeddings; separate from the read-only POI source."""
    configured = os.environ.get("RAG_INDEX_PATH")
    return Path(configured).expanduser() if configured else DATA_DIR / "rag_index.sqlite"
```

Also change the body of `qu_enabled()` to `return _flag("QU_ENABLED")` (same behaviour).

- [ ] **Step 5: Implement the index** — `backend/app/rag/__init__.py` containing only `"""Retrieval-augmented answers for place questions."""`, and `backend/app/rag/index.py`:

```python
"""Embedding index for place RAG: one document per POI, vectors in a separate SQLite file.

Run from `backend/`:  python -m app.rag.index [--model bge-m3]
Only POIs whose document text or model changed are embedded again.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np

from app.core.config import hue_database_path, ollama_url, rag_embed_model, rag_index_path
from app.core.usage import add_usage
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.place import Place

DEFAULT_TIMEOUT = 120.0
EMBED_BATCH = 32
PHONE_KEY = "Điện thoại"
TYPE_KEY = "Loại hình (theo nguồn)"
CATEGORY_LABELS = {
    "restaurant": "quán ăn",
    "cafe": "quán cà phê",
    "historic": "di tích",
    "attraction": "điểm tham quan",
    "market": "chợ",
    "religious": "tôn giáo",
    "park": "công viên",
    "museum": "bảo tàng",
}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS place_embeddings (
    poi_id TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL
)
"""


def _vnd(value: int) -> str:
    return f"{value:,}".replace(",", ".") + "đ"


def price_text(place: Place) -> str | None:
    """Reference price as written in answers, e.g. '30.000đ – 50.000đ'; None when unknown."""
    low, high = place.price_min_vnd, place.price_max_vnd
    if low is not None and high is not None and high != low:
        return f"{_vnd(low)} – {_vnd(high)}"
    if low is not None:
        return _vnd(low)
    if place.is_free_claim:
        return "miễn phí"
    return None


def document_text(place: Place) -> str:
    """The text that is embedded, searched and shown to the generator for one POI."""
    parts = [place.name, CATEGORY_LABELS.get(place.category, place.category)]
    source_type = place.raw_attributes.get(TYPE_KEY)
    if source_type:
        parts.append(f"Loại hình: {source_type}")
    if place.address:
        parts.append(f"Địa chỉ: {place.address}")
    if place.opening_hours_raw:
        parts.append(f"Giờ mở cửa: {place.opening_hours_raw}")
    price = price_text(place)
    if price:
        parts.append(f"Giá: {price}")
    phone = place.raw_attributes.get(PHONE_KEY)
    if phone:
        parts.append(f"Điện thoại: {phone}")
    if place.rating_value is not None:
        parts.append(f"Đánh giá: {place.rating_value}/5 ({place.rating_count or 0} lượt)")
    if place.summary:
        parts.append(place.summary.strip().rstrip("."))
    return ". ".join(parts) + ("." if place.summary else "")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbedError(RuntimeError):
    """Ollama did not return one embedding per input."""


class EmbedClient:
    """Calls Ollama `POST /api/embed`."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            response = self._client.post("/api/embed", json={"model": self.model, "input": list(texts)})
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise EmbedError(f"Ollama embed failed: {error}") from error
        vectors = payload.get("embeddings") if isinstance(payload, dict) else None
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbedError("Ollama returned the wrong number of embeddings")
        add_usage("embedding", payload)
        return [[float(x) for x in vector] for vector in vectors]


class EmbeddingStore:
    """Vectors by poi_id in their own SQLite file (float32, little endian)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(_SCHEMA)
            yield connection
            connection.commit()
        finally:
            connection.close()

    def hashes(self, model: str) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT poi_id, text_hash FROM place_embeddings WHERE model = ?", (model,)
            ).fetchall()
        return dict(rows)

    def all_ids(self) -> set[str]:
        with self._connect() as connection:
            return {row[0] for row in connection.execute("SELECT poi_id FROM place_embeddings")}

    def upsert(self, model: str, rows: Sequence[tuple[str, str, Sequence[float]]]) -> None:
        with self._connect() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO place_embeddings (poi_id, model, text_hash, dim, vector) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (poi_id, model, digest, len(vector), np.asarray(vector, dtype="<f4").tobytes())
                    for poi_id, digest, vector in rows
                ],
            )

    def delete(self, poi_ids: Iterable[str]) -> None:
        with self._connect() as connection:
            connection.executemany("DELETE FROM place_embeddings WHERE poi_id = ?", [(i,) for i in poi_ids])

    def load(self, model: str) -> tuple[list[str], np.ndarray]:
        """Ids in sorted order and their L2-normalised vectors; shape (0, 0) when empty."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT poi_id, vector FROM place_embeddings WHERE model = ? ORDER BY poi_id", (model,)
            ).fetchall()
        if not rows:
            return [], np.zeros((0, 0), dtype=np.float32)
        matrix = np.stack([np.frombuffer(blob, dtype="<f4") for _, blob in rows]).astype(np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return [poi_id for poi_id, _ in rows], matrix / norms


@dataclass(frozen=True)
class IndexStats:
    embedded: int
    unchanged: int
    deleted: int


def build_index(
    places: Sequence[Place], store: EmbeddingStore, client: EmbedClient, batch: int = EMBED_BATCH
) -> IndexStats:
    """Embed new or changed documents, keep the rest, delete rows for POIs that are gone."""
    known = store.hashes(client.model)
    todo: list[tuple[str, str, str]] = []
    unchanged = 0
    for place in places:
        text = document_text(place)
        digest = text_hash(text)
        if known.get(place.id) == digest:
            unchanged += 1
        else:
            todo.append((place.id, digest, text))
    for start in range(0, len(todo), batch):
        chunk = todo[start : start + batch]
        vectors = client.embed([text for _, _, text in chunk])
        store.upsert(client.model, [(poi_id, digest, vector) for (poi_id, digest, _), vector in zip(chunk, vectors)])
    gone = store.all_ids() - {place.id for place in places}
    store.delete(gone)
    return IndexStats(embedded=len(todo), unchanged=unchanged, deleted=len(gone))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the place embedding index.")
    parser.add_argument("--model", default=rag_embed_model())
    args = parser.parse_args(argv)
    places = HuePlacesRepository(hue_database_path()).list_all()
    client = EmbedClient(ollama_url(), args.model)
    try:
        stats = build_index(places, EmbeddingStore(rag_index_path()), client)
    except EmbedError as error:
        print(f"Index build failed: {error}", file=sys.stderr)
        return 1
    print(f"embedded={stats.embedded} unchanged={stats.unchanged} deleted={stats.deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

The test strings are the contract for `document_text`: parts joined by `". "`, and a final `"."` only when the summary closes the text. If the test fails only on punctuation, fix `document_text`, not the test.

- [ ] **Step 6: Run tests**

Run: `../.venv/Scripts/python -m pytest ../tests/test_rag_index.py ../tests/test_config.py -q`
Expected: all PASS.

- [ ] **Step 7: Build the real index (needs Ollama)**

Run: `ollama pull bge-m3` then `../.venv/Scripts/python -m app.rag.index`
Expected: `embedded=1587 unchanged=0 deleted=0`. A second run prints `embedded=0 unchanged=1587 deleted=0`.

- [ ] **Step 8: Full suite and commit**

```bash
git add backend/requirements.txt backend/app/core/config.py backend/app/rag tests/test_rag_index.py
git commit -m "feat(rag): place documents and incremental bge-m3 embedding index"
```

---

### Task 3: Hybrid retriever

**Files:**
- Create: `backend/app/rag/retrieve.py`
- Test: `tests/test_rag_retrieve.py`

**Interfaces:**
- Consumes: `document_text`, `EmbedClient`, `EmbedError`, `EmbeddingStore` (Task 2); `normalize_vietnamese`, `haversine_km` (`app.services.poi_search`); `map_preferences` (`app.services.preferences`); `ParsedQuery`, `PlaceMention` (`app.understanding.models`).
- Produces: `tokenize(text) -> list[str]`; `BM25(docs, k1=1.5, b=0.75).scores(query_tokens) -> list[float]`; `rrf(rankings: Sequence[Sequence[str]], k=60) -> dict[str, float]`; `Hit(poi_id, score, bm25_rank: int | None, dense_rank: int | None, distance_km: float | None)`; `RetrievalResult(hits: list[Hit], mode: Literal["hybrid", "bm25"])`; `Retriever(places, store=None, client=None)` with `.by_id: dict[str, Place]` and `.retrieve(question, parsed=None, k=5) -> RetrievalResult`. Constants `RRF_K = 60`, `CANDIDATES = 50`, `ANCHOR_RADIUS_KM = 2.0`.

- [ ] **Step 1: Write the failing tests** — `tests/test_rag_retrieve.py`

```python
"""Retriever: BM25 without diacritics, RRF, filters, anchor radius, BM25-only fallback."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))
_TESTS = _Path(__file__).resolve().parent
if str(_TESTS) not in _sys.path:
    _sys.path.insert(0, str(_TESTS))

import httpx  # noqa: E402

from app.rag.index import EmbedClient, EmbeddingStore  # noqa: E402
from app.rag.retrieve import BM25, Retriever, rrf, tokenize  # noqa: E402
from app.understanding.models import Intent, ParsedQuery, PlaceMention, QuSource  # noqa: E402
from test_rag_index import make_place  # noqa: E402

PLACES = [
    make_place("huetripo:1", name="Đại Nội", category="historic", lat=16.4698, lon=107.5786,
               summary="Hoàng thành triều Nguyễn."),
    make_place("huetripo:2", name="Bún bò Mệ Kéo", category="restaurant", lat=16.4710, lon=107.5800),
    make_place("huetripo:3", name="Chùa Thiên Mụ", category="religious", lat=16.4530, lon=107.5450,
               summary="Ngôi chùa cổ yên tĩnh bên sông Hương."),
    make_place("huetripo:4", name="Bún bò xa", category="restaurant", lat=16.30, lon=107.70),
]


def _parsed(poi_id: str | None = None, text: str = "Đại Nội") -> ParsedQuery:
    mention = PlaceMention(text=text, poi_id=poi_id, name=text, score=1.0) if poi_id else None
    return ParsedQuery(intent=Intent.PLACE_INFO, source=QuSource.RULES, place_query=mention)


def test_tokenize_folds_diacritics() -> None:
    assert tokenize("Bún bò Mệ Kéo!") == ["bun", "bo", "me", "keo"]


def test_bm25_ranks_matching_document_first() -> None:
    bm25 = BM25([["bun", "bo"], ["chua", "thien", "mu"], ["bun", "rieu"]])
    scores = bm25.scores(["bun", "bo"])
    assert scores[0] > scores[2] > scores[1] == 0.0


def test_rrf_sums_reciprocal_ranks() -> None:
    fused = rrf([["a", "b"], ["b", "c"]], k=60)
    assert fused["b"] == 1 / 61 + 1 / 62
    assert max(fused, key=fused.get) == "b"


def test_bm25_only_mode_without_store_and_diacritic_free_query() -> None:
    result = Retriever(PLACES).retrieve("chua thien mu", None, k=2)
    assert result.mode == "bm25"
    assert result.hits[0].poi_id == "huetripo:3"
    assert result.hits[0].bm25_rank == 1 and result.hits[0].dense_rank is None


def test_no_lexical_match_and_no_dense_gives_no_hits() -> None:
    assert Retriever(PLACES).retrieve("wifi khách sạn", None).hits == []


def test_category_filter_keeps_only_restaurants() -> None:
    result = Retriever(PLACES).retrieve("quán ăn bún bò ngon", None, k=5)
    assert {hit.poi_id for hit in result.hits} <= {"huetripo:2", "huetripo:4"}


def test_anchor_keeps_places_within_radius_and_removes_the_anchor() -> None:
    result = Retriever(PLACES).retrieve("quán bún bò gần Đại Nội", _parsed("huetripo:1"), k=5)
    ids = [hit.poi_id for hit in result.hits]
    assert ids[0] == "huetripo:2"
    assert "huetripo:1" not in ids and "huetripo:4" not in ids
    assert result.hits[0].distance_km is not None and result.hits[0].distance_km < 1


def test_linked_place_is_boosted_for_single_place_questions() -> None:
    result = Retriever(PLACES).retrieve("Đại Nội mấy giờ mở cửa", _parsed("huetripo:1"), k=3)
    assert result.hits[0].poi_id == "huetripo:1"


def test_hybrid_mode_uses_dense_ranking(tmp_path) -> None:
    store = EmbeddingStore(tmp_path / "rag.sqlite")
    store.upsert("bge-m3", [
        ("huetripo:1", "h", [0.0, 1.0]), ("huetripo:2", "h", [0.0, 1.0]),
        ("huetripo:3", "h", [1.0, 0.0]), ("huetripo:4", "h", [0.0, 1.0]),
    ])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[1.0, 0.0]]})

    client = EmbedClient("http://ollama.test", "bge-m3", transport=httpx.MockTransport(handler))
    result = Retriever(PLACES, store, client).retrieve("nơi yên bình để tĩnh tâm", None, k=2)
    assert result.mode == "hybrid"
    assert result.hits[0].poi_id == "huetripo:3"
    assert result.hits[0].dense_rank == 1


def test_embed_failure_falls_back_to_bm25(tmp_path) -> None:
    store = EmbeddingStore(tmp_path / "rag.sqlite")
    store.upsert("bge-m3", [("huetripo:3", "h", [1.0, 0.0])])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = EmbedClient("http://ollama.test", "bge-m3", transport=httpx.MockTransport(handler))
    result = Retriever(PLACES, store, client).retrieve("chùa Thiên Mụ", None)
    assert result.mode == "bm25"
    assert result.hits[0].poi_id == "huetripo:3"
```

Before Step 2, check two assumptions with one command each and adjust only the test inputs if needed (keep the assertions):
- `../.venv/Scripts/python -c "from app.services.preferences import map_preferences; print(map_preferences(['quán ăn bún bò ngon']), map_preferences(['nơi yên bình để tĩnh tâm']))"` — the first must contain `restaurant`; the second must be empty (else the dense test's category filter changes the candidates; pick another question with no category word).
- `ParsedQuery(intent=..., source=...)` must build with only those fields; if more are required, pass them.

- [ ] **Step 2: Run and confirm failure**

Run: `../.venv/Scripts/python -m pytest ../tests/test_rag_retrieve.py -q`
Expected: FAIL, `No module named 'app.rag.retrieve'`.

- [ ] **Step 3: Implement** — `backend/app/rag/retrieve.py`

```python
"""Hybrid place retrieval: BM25 on folded text + bge-m3 cosine, fused by reciprocal rank.

Filters come from the question and its ParsedQuery: categories named in the question, and an
anchor place after "gần" (POIs within ANCHOR_RADIUS_KM, nearest first, anchor removed). A linked
place without "gần" gets one extra ranking list so it comes first for single-place questions.
Without vectors or when the embed call fails, the retriever uses BM25 alone (mode "bm25").
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from app.rag.index import EmbedClient, EmbedError, EmbeddingStore, document_text
from app.schemas.place import Place
from app.services.poi_search import haversine_km, normalize_vietnamese
from app.services.preferences import map_preferences
from app.understanding.models import ParsedQuery

logger = logging.getLogger(__name__)
RRF_K = 60
CANDIDATES = 50
ANCHOR_RADIUS_KM = 2.0
_TOKEN = re.compile(r"[a-z0-9]+")
_warned = False


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(normalize_vietnamese(text))


class BM25:
    """Okapi BM25 over pre-tokenised documents."""

    def __init__(self, docs: Sequence[Sequence[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.tf = [Counter(doc) for doc in docs]
        self.lengths = [len(doc) for doc in docs]
        self.avg_length = (sum(self.lengths) / len(docs)) if docs else 1.0
        df = Counter(token for doc in docs for token in set(doc))
        n = len(docs)
        self.idf = {token: math.log(1 + (n - count + 0.5) / (count + 0.5)) for token, count in df.items()}

    def scores(self, query: Sequence[str]) -> list[float]:
        terms = [token for token in set(query) if token in self.idf]
        out: list[float] = []
        for tf, length in zip(self.tf, self.lengths):
            score = 0.0
            norm = self.k1 * (1 - self.b + self.b * length / (self.avg_length or 1.0))
            for token in terms:
                f = tf.get(token, 0)
                if f:
                    score += self.idf[token] * f * (self.k1 + 1) / (f + norm)
            out.append(score)
        return out


def rrf(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> dict[str, float]:
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, poi_id in enumerate(ranking, start=1):
            fused[poi_id] = fused.get(poi_id, 0.0) + 1.0 / (k + rank)
    return fused


@dataclass(frozen=True)
class Hit:
    poi_id: str
    score: float
    bm25_rank: int | None = None
    dense_rank: int | None = None
    distance_km: float | None = None


@dataclass(frozen=True)
class RetrievalResult:
    hits: list[Hit]
    mode: Literal["hybrid", "bm25"]


class Retriever:
    """Loads every document once; `retrieve` only reads, so threads can share it."""

    def __init__(
        self,
        places: Sequence[Place],
        store: EmbeddingStore | None = None,
        client: EmbedClient | None = None,
    ) -> None:
        self.places = list(places)
        self.by_id = {place.id: place for place in self.places}
        self.bm25 = BM25([tokenize(document_text(place)) for place in self.places])
        self.client = client
        self.matrix: np.ndarray | None = None
        if store is not None and client is not None:
            ids, vectors = store.load(client.model)
            if ids:
                row_of = {poi_id: row for row, poi_id in enumerate(ids)}
                matrix = np.zeros((len(self.places), vectors.shape[1]), dtype=np.float32)
                for index, place in enumerate(self.places):
                    if place.id in row_of:
                        matrix[index] = vectors[row_of[place.id]]
                self.matrix = matrix

    def retrieve(self, question: str, parsed: ParsedQuery | None = None, k: int = 5) -> RetrievalResult:
        anchor = self._anchor(question, parsed)
        allowed = self._allowed(question, parsed, anchor)
        rankings: list[list[str]] = []

        bm25_scores = self.bm25.scores(tokenize(question))
        bm25_order = sorted(
            (i for i in allowed if bm25_scores[i] > 0), key=lambda i: (-bm25_scores[i], self.places[i].id)
        )
        bm25_ids = [self.places[i].id for i in bm25_order[:CANDIDATES]]
        rankings.append(bm25_ids)

        dense_ids, mode = self._dense(question, allowed)
        rankings.append(dense_ids)

        distances: dict[str, float] = {}
        if anchor is not None:
            for i in allowed:
                place = self.places[i]
                distances[place.id] = haversine_km(anchor.lat, anchor.lon, place.lat, place.lon)
            rankings.append(sorted(distances, key=lambda poi_id: (distances[poi_id], poi_id))[:CANDIDATES])
        elif parsed is not None and parsed.place_query is not None and parsed.place_query.poi_id in self.by_id:
            rankings.append([parsed.place_query.poi_id])

        fused = rrf(rankings)
        ordered = sorted(fused, key=lambda poi_id: (-fused[poi_id], poi_id))[:k]
        bm25_rank = {poi_id: rank for rank, poi_id in enumerate(bm25_ids, start=1)}
        dense_rank = {poi_id: rank for rank, poi_id in enumerate(dense_ids, start=1)}
        hits = [
            Hit(
                poi_id=poi_id,
                score=round(fused[poi_id], 6),
                bm25_rank=bm25_rank.get(poi_id),
                dense_rank=dense_rank.get(poi_id),
                distance_km=round(distances[poi_id], 3) if poi_id in distances else None,
            )
            for poi_id in ordered
        ]
        return RetrievalResult(hits=hits, mode=mode)

    def _anchor(self, question: str, parsed: ParsedQuery | None) -> Place | None:
        if parsed is None or parsed.place_query is None or not parsed.place_query.poi_id:
            return None
        if " gan " not in f" {normalize_vietnamese(question)} ":
            return None
        return self.by_id.get(parsed.place_query.poi_id)

    def _allowed(self, question: str, parsed: ParsedQuery | None, anchor: Place | None) -> list[int]:
        allowed = list(range(len(self.places)))
        if anchor is not None:
            allowed = [
                i
                for i in allowed
                if self.places[i].id != anchor.id
                and haversine_km(anchor.lat, anchor.lon, self.places[i].lat, self.places[i].lon) <= ANCHOR_RADIUS_KM
            ]
        text = question
        if parsed is not None and parsed.place_query is not None and parsed.place_query.text:
            text = re.sub(re.escape(parsed.place_query.text), " ", text, flags=re.IGNORECASE)
        categories, _ = map_preferences([text])
        if categories:
            narrowed = [i for i in allowed if self.places[i].category in categories]
            if narrowed:
                allowed = narrowed
        return allowed

    def _dense(self, question: str, allowed: list[int]) -> tuple[list[str], Literal["hybrid", "bm25"]]:
        global _warned
        if self.matrix is None or self.client is None:
            return [], "bm25"
        if not allowed:
            return [], "hybrid"
        try:
            vector = np.asarray(self.client.embed([question])[0], dtype=np.float32)
        except EmbedError as error:
            if not _warned:
                logger.warning("Dense retrieval off, using BM25 only: %s", error)
                _warned = True
            return [], "bm25"
        norm = float(np.linalg.norm(vector)) or 1.0
        rows = np.asarray(allowed)
        scores = self.matrix[rows] @ (vector / norm)
        order = np.argsort(-scores, kind="stable")[:CANDIDATES]
        return [self.places[int(rows[i])].id for i in order], "hybrid"
```

- [ ] **Step 4: Run tests**

Run: `../.venv/Scripts/python -m pytest ../tests/test_rag_retrieve.py -q`
Expected: all PASS.

- [ ] **Step 5: Full suite and commit**

```bash
git add backend/app/rag/retrieve.py tests/test_rag_retrieve.py
git commit -m "feat(rag): hybrid BM25 + dense retriever with RRF, category and anchor filters"
```

---

### Task 4: Fact checker and answerer

**Files:**
- Create: `backend/app/rag/facts.py`, `backend/app/rag/answer.py`
- Test: `tests/test_rag_facts.py`, `tests/test_rag_answer.py`

**Interfaces:**
- Consumes: `Retriever`, `RetrievalResult`, `Hit` (Task 3); `document_text`, `PHONE_KEY` (Task 2); `add_usage` (Task 1).
- Produces:
  - `facts.CITE_RE` (matches `[huetripo:123]`, group 1 = id); `facts.FactMismatch(poi_id: str, kind: Literal["time","price","phone","address"], value: str)`; `facts.check_facts(answer: str, places: Sequence[Place]) -> list[FactMismatch]`.
  - `answer.REFUSAL_TEXT: str`; `answer.build_context(hits, by_id) -> str`; `answer.strip_citations(text) -> str`; `answer.RagError(RuntimeError)`; `answer.RagAnswer(text, raw_text, cited_poi_ids, answerable, source: Literal["llm","fallback","refusal"], retrieval, mismatches=[], error=None)`; `answer.RagAnswerer(retriever, fallback_text: Callable[[Place], str], base_url, model, timeout=90.0, transport=None, k=5)` with `.answer(question, parsed=None) -> RagAnswer` and `.retriever`.

- [ ] **Step 1: Write failing fact tests** — `tests/test_rag_facts.py`

```python
"""Fact checker: times, prices, phones and addresses in an answer must match the cited POIs."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))
_TESTS = _Path(__file__).resolve().parent
if str(_TESTS) not in _sys.path:
    _sys.path.insert(0, str(_TESTS))

from app.rag.facts import CITE_RE, check_facts  # noqa: E402
from test_rag_index import make_place  # noqa: E402

PLACE = make_place("huetripo:1")  # 06:00-21:00, 30.000-50.000đ, 0234 3826 123, 20 Bạch Đằng
OTHER = make_place("huetripo:2", opening_hours_raw="07:30-17:30", price_min_vnd=200000, price_max_vnd=200000)


def test_cite_re_finds_ids() -> None:
    assert CITE_RE.findall("A [huetripo:1]. B [huetripo:22].") == ["huetripo:1", "huetripo:22"]


def test_correct_facts_pass() -> None:
    answer = ("Quán mở cửa 06:00-21:00, giá 30.000đ đến 50k [huetripo:1]. "
              "Số điện thoại 0234 3826 123, địa chỉ: 20 Bạch Đằng [huetripo:1].")
    assert check_facts(answer, [PLACE]) == []


def test_wrong_time_price_phone_and_address_are_reported() -> None:
    answer = ("Quán mở cửa lúc 05:30 [huetripo:1]. Giá 90.000đ [huetripo:1]. "
              "Gọi 0905 111 222 [huetripo:1]. Địa chỉ: 99 Lê Lợi [huetripo:1].")
    kinds = sorted(m.kind for m in check_facts(answer, [PLACE]))
    assert kinds == ["address", "phone", "price", "time"]


def test_facts_are_checked_against_the_place_cited_in_the_same_sentence() -> None:
    answer = "Quán A mở 06:00 [huetripo:1]. Điểm B mở 07:30, vé 200.000đ [huetripo:2]."
    assert check_facts(answer, [PLACE, OTHER]) == []
    wrong = "Điểm B mở 06:00 [huetripo:2]."
    assert [m.kind for m in check_facts(wrong, [PLACE, OTHER])] == ["time"]


def test_durations_and_distances_are_not_facts() -> None:
    assert check_facts("Tham quan khoảng 2 giờ, cách 1.5 km [huetripo:1].", [PLACE]) == []


def test_hours_stated_for_a_place_without_hours_is_a_mismatch() -> None:
    place = make_place("huetripo:9", opening_hours_raw=None)
    assert [m.kind for m in check_facts("Mở cửa 08:00 [huetripo:9].", [place])] == ["time"]
```

- [ ] **Step 2: Write failing answer tests** — `tests/test_rag_answer.py`

```python
"""RAG answerer: JSON parsing, citation filtering, refusals, retry, fallback, fact checks."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))
_TESTS = _Path(__file__).resolve().parent
if str(_TESTS) not in _sys.path:
    _sys.path.insert(0, str(_TESTS))

import json  # noqa: E402

import httpx  # noqa: E402

from app.core.usage import record_usage  # noqa: E402
from app.rag.answer import REFUSAL_TEXT, RagAnswerer, strip_citations  # noqa: E402
from app.rag.retrieve import Retriever  # noqa: E402
from test_rag_retrieve import PLACES  # noqa: E402


def _answerer(replies: list[object]) -> tuple[RagAnswerer, list[dict]]:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        reply = replies[min(len(bodies) - 1, len(replies) - 1)]
        if isinstance(reply, int):
            return httpx.Response(reply)
        content = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return httpx.Response(200, json={"message": {"content": content}, "prompt_eval_count": 300, "eval_count": 30})

    answerer = RagAnswerer(
        Retriever(PLACES), lambda place: f"TEMPLATE {place.name}", "http://ollama.test", "qwen3.5:4b",
        transport=httpx.MockTransport(handler),
    )
    return answerer, bodies


def test_llm_answer_with_valid_citation() -> None:
    answerer, bodies = _answerer([{
        "answer": "Chùa Thiên Mụ là ngôi chùa cổ yên tĩnh [huetripo:3].",
        "cited_poi_ids": ["huetripo:3"], "answerable": True,
    }])
    with record_usage() as usage:
        result = answerer.answer("chùa Thiên Mụ có gì")
    assert result.source == "llm"
    assert result.cited_poi_ids == ["huetripo:3"]
    assert result.text == "Chùa Thiên Mụ là ngôi chùa cổ yên tĩnh."
    assert "[huetripo:3]" in result.raw_text
    assert "[huetripo:3]" in bodies[0]["messages"][-1]["content"]
    assert bodies[0]["format"]["required"] == ["answer", "cited_poi_ids", "answerable"]
    assert usage["rag_generator"].total_tokens == 330


def test_ids_outside_the_context_are_dropped_and_no_valid_id_means_refusal() -> None:
    answerer, _ = _answerer([{"answer": "Có [huetripo:999].", "cited_poi_ids": ["huetripo:999"], "answerable": True}])
    result = answerer.answer("chùa Thiên Mụ")
    assert result.source == "refusal"
    assert result.cited_poi_ids == [] and result.answerable is False
    assert result.text == REFUSAL_TEXT


def test_model_refusal_keeps_its_sentence() -> None:
    answerer, _ = _answerer([{"answer": "Dữ liệu không có thông tin wifi.", "cited_poi_ids": [], "answerable": False}])
    result = answerer.answer("chùa Thiên Mụ có wifi không")
    assert (result.source, result.text) == ("refusal", "Dữ liệu không có thông tin wifi.")


def test_empty_retrieval_refuses_without_calling_the_llm() -> None:
    answerer, bodies = _answerer([500])
    result = answerer.answer("wifi khách sạn")
    assert result.source == "refusal" and bodies == []


def test_invalid_json_is_retried_once_then_falls_back_to_the_template() -> None:
    answerer, bodies = _answerer(["not json", "still not json"])
    result = answerer.answer("chùa Thiên Mụ")
    assert len(bodies) == 2
    assert result.source == "fallback"
    assert result.text == "TEMPLATE Chùa Thiên Mụ"
    assert result.cited_poi_ids == ["huetripo:3"]
    assert result.error


def test_second_attempt_can_succeed() -> None:
    good = {"answer": "Chùa cổ [huetripo:3].", "cited_poi_ids": ["huetripo:3"], "answerable": True}
    answerer, bodies = _answerer([500, good])
    assert answerer.answer("chùa Thiên Mụ").source == "llm"
    assert len(bodies) == 2


def test_fact_mismatch_falls_back_to_the_template() -> None:
    answerer, _ = _answerer([{
        "answer": "Chùa Thiên Mụ mở cửa 03:00 [huetripo:3].", "cited_poi_ids": ["huetripo:3"], "answerable": True,
    }])
    result = answerer.answer("chùa Thiên Mụ mấy giờ mở cửa")
    assert result.source == "fallback"
    assert [m.kind for m in result.mismatches] == ["time"]


def test_strip_citations() -> None:
    assert strip_citations("A [huetripo:1]. B [huetripo:2] và C.") == "A. B và C."
```

- [ ] **Step 3: Run and confirm failure**

Run: `../.venv/Scripts/python -m pytest ../tests/test_rag_facts.py ../tests/test_rag_answer.py -q`
Expected: FAIL, missing modules.

- [ ] **Step 4: Implement** — `backend/app/rag/facts.py`

```python
"""Checks the facts an LLM place answer states against the cited POIs.

Checked: clock times (HH:MM, HHhMM), prices with a unit (đ, đồng, vnd, k, nghìn, ngàn), phone
numbers and the text after "địa chỉ". Durations ("2 giờ") and distances are not facts here. A fact
in a sentence is checked against the POIs cited in that sentence, or against every cited POI when
the sentence cites none. A fact passes when it matches at least one of those POIs.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.rag.index import PHONE_KEY
from app.schemas.place import Place
from app.services.poi_search import normalize_vietnamese

CITE_RE = re.compile(r"\[([^\[\]\s]+:[^\[\]\s]+)\]")
_TIME = re.compile(r"(?<![\d.,])([01]?\d|2[0-3])\s*[:h]\s*([0-5]\d)(?!\d)")
_PRICE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[.,]\d{3})+|\d+)\s*(nghìn|ngàn|đồng|vnđ|vnd|đ|k)(?![a-zA-Zà-ỹÀ-Ỹ])",
    re.IGNORECASE,
)
_PHONE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.-]?\d){8,10}(?!\d)")
_ADDRESS = re.compile(r"địa chỉ\s*(?:là|:)?\s*([^\[\n;]+?)(?=\s*\[|[.;\n]|$)", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[a-z0-9]+")
ADDRESS_OVERLAP = 0.6


@dataclass(frozen=True)
class FactMismatch:
    poi_id: str
    kind: Literal["time", "price", "phone", "address"]
    value: str


def _times(text: str | None) -> set[tuple[int, int]]:
    return {(int(h), int(m)) for h, m in _TIME.findall(text or "")}


def _phones(text: str | None) -> set[str]:
    found = set()
    for match in _PHONE.findall(text or ""):
        digits = re.sub(r"\D", "", match)
        found.add("0" + digits[2:] if digits.startswith("84") else digits)
    return found


def _price_value(number: str, unit: str) -> int:
    value = int(re.sub(r"[.,]", "", number))
    return value * 1000 if unit.lower() in {"k", "nghìn", "ngàn"} else value


def _price_ok(value: int, place: Place) -> bool:
    low, high = place.price_min_vnd, place.price_max_vnd
    if low is None:
        return value == 0 and place.is_free_claim
    return low <= value <= (high if high is not None else low)


def _address_ok(found: str, place: Place) -> bool:
    words = set(_WORD.findall(normalize_vietnamese(found)))
    if not words:
        return True
    known = set(_WORD.findall(normalize_vietnamese(place.address or "")))
    return len(words & known) / len(words) >= ADDRESS_OVERLAP


def check_facts(answer: str, places: Sequence[Place]) -> list[FactMismatch]:
    by_id = {place.id: place for place in places}
    mismatches: list[FactMismatch] = []
    for sentence in _SENTENCE.split(answer):
        cited = [by_id[i] for i in CITE_RE.findall(sentence) if i in by_id]
        targets = cited or list(places)
        if not targets:
            continue
        label = targets[0].id if len(targets) == 1 else ""
        body = CITE_RE.sub(" ", sentence)
        for hour, minute in sorted(_times(body)):
            if not any((hour, minute) in _times(p.opening_hours_raw) for p in targets):
                mismatches.append(FactMismatch(label, "time", f"{hour:02d}:{minute:02d}"))
        for number, unit in _PRICE.findall(body):
            if not any(_price_ok(_price_value(number, unit), p) for p in targets):
                mismatches.append(FactMismatch(label, "price", f"{number}{unit}"))
        for phone in sorted(_phones(body)):
            if not any(phone in _phones(str(p.raw_attributes.get(PHONE_KEY) or "")) for p in targets):
                mismatches.append(FactMismatch(label, "phone", phone))
        for found in _ADDRESS.findall(body):
            if not any(_address_ok(found, p) for p in targets):
                mismatches.append(FactMismatch(label, "address", found.strip()))
    return mismatches
```

`backend/app/rag/answer.py`:

```python
"""Writes a place answer from retrieved POIs with a local Ollama model.

The model returns JSON {answer, cited_poi_ids, answerable}. Ids outside the context are dropped;
an answer without a valid citation is a refusal. Every fact is checked against the cited POIs; on
a mismatch, an invalid reply after a retry, or a transport error, the template answer for the top
hit is used instead (source "fallback").
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from app.core.usage import add_usage
from app.rag.facts import CITE_RE, FactMismatch, check_facts
from app.rag.index import document_text
from app.rag.retrieve import Hit, RetrievalResult, Retriever
from app.schemas.place import Place
from app.understanding.models import ParsedQuery

MAX_ATTEMPTS = 2
DEFAULT_TIMEOUT = 90.0
REFUSAL_TEXT = "Mình chưa có thông tin để trả lời câu này trong dữ liệu Huế."
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "cited_poi_ids": {"type": "array", "items": {"type": "string"}},
        "answerable": {"type": "boolean"},
    },
    "required": ["answer", "cited_poi_ids", "answerable"],
}
SYSTEM_PROMPT = """Bạn là trợ lý du lịch Huế. Chỉ dùng thông tin trong phần NGỮ CẢNH.
Quy tắc:
- Mỗi câu nói về một địa điểm phải kết thúc bằng mã của địa điểm trong ngoặc vuông, ví dụ [huetripo:531787].
- Giờ mở cửa, giá, số điện thoại, địa chỉ phải chép đúng như trong ngữ cảnh. Không đoán, không làm tròn.
- Nếu ngữ cảnh không trả lời được câu hỏi: answerable = false, answer là một câu nói rằng dữ liệu chưa có thông tin, cited_poi_ids rỗng.
- Trả lời ngắn bằng tiếng Việt, tối đa 5 câu, gợi ý tối đa 3 địa điểm.
- cited_poi_ids liệt kê mọi mã đã dùng, theo thứ tự xuất hiện."""


class RagError(RuntimeError):
    """The generator gave no usable answer."""


class _Output(BaseModel):
    answer: str
    cited_poi_ids: list[str]
    answerable: bool


@dataclass
class RagAnswer:
    text: str
    raw_text: str
    cited_poi_ids: list[str]
    answerable: bool
    source: Literal["llm", "fallback", "refusal"]
    retrieval: RetrievalResult
    mismatches: list[FactMismatch] = field(default_factory=list)
    error: str | None = None


def build_context(hits: Sequence[Hit], by_id: Mapping[str, Place]) -> str:
    return "\n".join(f"[{hit.poi_id}] {document_text(by_id[hit.poi_id])}" for hit in hits if hit.poi_id in by_id)


def strip_citations(text: str) -> str:
    cleaned = CITE_RE.sub("", text)
    cleaned = re.sub(r"\s+([.,;!?])", r"\1", cleaned)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


class RagAnswerer:
    """Retrieve, generate, check, fall back. `answer` never raises for model problems."""

    def __init__(
        self,
        retriever: Retriever,
        fallback_text: Callable[[Place], str],
        base_url: str,
        model: str,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
        k: int = 5,
    ) -> None:
        self.retriever = retriever
        self.fallback_text = fallback_text
        self.model = model
        self.k = k
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def answer(self, question: str, parsed: ParsedQuery | None = None) -> RagAnswer:
        retrieval = self.retriever.retrieve(question, parsed, self.k)
        if not retrieval.hits:
            return RagAnswer(REFUSAL_TEXT, REFUSAL_TEXT, [], False, "refusal", retrieval)
        by_id = self.retriever.by_id
        context_ids = [hit.poi_id for hit in retrieval.hits]
        try:
            output = self._generate(question, build_context(retrieval.hits, by_id))
        except RagError as error:
            return self._fallback(retrieval, str(error))
        listed = CITE_RE.findall(output.answer) + output.cited_poi_ids
        cited = [poi_id for poi_id in dict.fromkeys(listed) if poi_id in context_ids]
        if not output.answerable or not cited:
            own = strip_citations(output.answer) if not output.answerable else ""
            text = own or REFUSAL_TEXT
            return RagAnswer(text, output.answer, [], False, "refusal", retrieval)
        mismatches = check_facts(output.answer, [by_id[poi_id] for poi_id in cited])
        if mismatches:
            result = self._fallback(retrieval, "fact mismatch")
            result.mismatches = mismatches
            return result
        return RagAnswer(strip_citations(output.answer), output.answer, cited, True, "llm", retrieval)

    def _fallback(self, retrieval: RetrievalResult, error: str) -> RagAnswer:
        place = self.retriever.by_id[retrieval.hits[0].poi_id]
        text = self.fallback_text(place)
        return RagAnswer(text, text, [place.id], True, "fallback", retrieval, error=error)

    def _generate(self, question: str, context: str) -> _Output:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"NGỮ CẢNH:\n{context}\n\nCÂU HỎI: {question}"},
        ]
        last_error = "no attempt"
        for _ in range(MAX_ATTEMPTS):
            try:
                return _Output.model_validate_json(self._chat(messages))
            except (RagError, ValidationError) as error:
                last_error = str(error)
        raise RagError(f"Generator failed after {MAX_ATTEMPTS} attempts: {last_error}")

    def _chat(self, messages: list[dict[str, str]]) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "format": ANSWER_SCHEMA,
            "stream": False,
            "think": False,
            "options": {"temperature": 0},
        }
        try:
            response = self._client.post("/api/chat", json=body)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise RagError(f"Ollama không trả lời: {error}") from error
        if isinstance(payload, dict):
            add_usage("rag_generator", payload)
        content = payload.get("message", {}).get("content") if isinstance(payload, dict) else None
        if not isinstance(content, str):
            raise RagError("Ollama trả về thiếu message.content")
        return content
```

- [ ] **Step 5: Run tests**

Run: `../.venv/Scripts/python -m pytest ../tests/test_rag_facts.py ../tests/test_rag_answer.py -q`
Expected: all PASS. If a regex test fails, fix the regex in `facts.py`; do not weaken the test.

- [ ] **Step 6: Full suite and commit**

```bash
git add backend/app/rag/facts.py backend/app/rag/answer.py tests/test_rag_facts.py tests/test_rag_answer.py
git commit -m "feat(rag): grounded place answerer with fact checks and template fallback"
```

---

### Task 5: Chat wiring

**Files:**
- Modify: `backend/app/chat/service.py`, `backend/app/api/chat.py`, `tests/conftest.py`
- Test: `tests/test_chat_service.py` (append), `tests/test_api_chat.py` (unchanged, must pass)

**Interfaces:**
- Consumes: `RagAnswerer`, `RagAnswer` (Task 4); `Retriever` (Task 3); `EmbedClient`, `EmbeddingStore` (Task 2); config functions (Task 2).
- Produces: `ChatService(..., chats, rag: RagAnswerer | None = None)`; attributes `rag`, `handler_log: list[str] | None` (default `None`; when a list, each handled turn appends exactly one name) and `last_rag: RagAnswer | None` (reset at the start of `handle`). Handler names: `plan_new`, `modify`, `place_info`, `ask_approve`, `ask_book`, `out_of_scope`, `confirm_defaults`, `run_approve`, `run_book`, `cancel`. `MAX_PLACE_CARDS = 3`. `api.chat.get_rag() -> RagAnswerer | None`.

- [ ] **Step 1: Write failing tests** — append to `tests/test_chat_service.py`:

```python
# ---------------------------------------------------------------------------
# place_info through RAG, handler log
# ---------------------------------------------------------------------------


class FakeRag:
    """Returns a fixed RagAnswer, or raises, and records the questions it got."""

    def __init__(self, answer: Any = None, error: Exception | None = None) -> None:
        self.answer_value, self.error, self.questions = answer, error, []

    def answer(self, question: str, parsed: Any = None) -> Any:
        self.questions.append(question)
        if self.error is not None:
            raise self.error
        return self.answer_value


def _rag_answer(cited: list[str], text: str = "Đại Nội mở 07:30-17:30.") -> Any:
    from app.rag.answer import RagAnswer
    from app.rag.retrieve import Hit, RetrievalResult

    retrieval = RetrievalResult(hits=[Hit(poi_id=i, score=1.0) for i in cited], mode="bm25")
    return RagAnswer(text, text, cited, bool(cited), "llm" if cited else "refusal", retrieval)


def test_place_info_uses_rag_and_shows_cards_for_cited_places() -> None:
    async def scenario():
        h = Harness()
        h.service.rag = FakeRag(_rag_answer([DAI_NOI]))
        h.fake.script("Đại Nội mấy giờ mở cửa?", _scripted(Intent.PLACE_INFO))
        reply = await h.say("c-rag", "Đại Nội mấy giờ mở cửa?")
        assert reply.text == "Đại Nội mở 07:30-17:30."
        assert [card.poi_id for card in reply.cards if isinstance(card, PlaceCard)] == [DAI_NOI]
        assert h.service.last_rag is not None and h.service.last_rag.source == "llm"
        assert h.service.rag.questions == ["Đại Nội mấy giờ mở cửa?"]

    _run(scenario)


def test_place_info_falls_back_to_the_template_when_rag_raises() -> None:
    async def scenario():
        h = Harness()
        h.service.rag = FakeRag(error=RuntimeError("boom"))
        mention = PlaceMention(text="Đại Nội", poi_id=DAI_NOI, name="Đại Nội", score=1.0)
        h.fake.script("Đại Nội ở đâu?", _scripted(Intent.PLACE_INFO, place_query=mention))
        reply = await h.say("c-rag-fail", "Đại Nội ở đâu?")
        assert DAI_NOI_HOURS in reply.text
        assert h.service.last_rag is None

    _run(scenario)


def test_handler_log_records_one_name_per_turn() -> None:
    async def scenario():
        h = Harness()
        h.service.handler_log = []
        h.fake.script("Thời tiết thế nào?", _scripted(Intent.OUT_OF_SCOPE))
        await h.say("c-log", "Thời tiết thế nào?")
        await h.say("c-log", PLAN_TRIP)
        assert h.service.handler_log == ["out_of_scope", "plan_new"]

    _run(scenario)
```

In `tests/conftest.py`, add after the `QU_ENABLED` line: `os.environ["RAG_ENABLED"] = "false"`.

- [ ] **Step 2: Run and confirm failure**

Run: `../.venv/Scripts/python -m pytest ../tests/test_chat_service.py -q -k "rag or handler_log"`
Expected: FAIL (`last_rag` / `handler_log` do not exist, or the template text is returned).

- [ ] **Step 3: Implement in `backend/app/chat/service.py`**

1. Imports: add `import logging`; change `from typing import Any` to `from typing import TYPE_CHECKING, Any`; add
   ```python
   if TYPE_CHECKING:
       from app.rag.answer import RagAnswer, RagAnswerer
   ```
   after the other imports. Add `logger = logging.getLogger(__name__)` and `MAX_PLACE_CARDS = 3` after `_CHANGE_FORMS`.
2. Constructor: add the parameter `rag: RagAnswerer | None = None` after `chats`; set `self.rag = rag`, `self.handler_log: list[str] | None = None`, `self.last_rag: RagAnswer | None = None`.
3. Add the method:

```python
    def _note(self, handler: str) -> None:
        """Record which handler answered the turn (read by the evaluator)."""
        if self.handler_log is not None:
            self.handler_log.append(handler)
```

4. In `handle`, first line of the body: `self.last_rag = None`.
5. In `_answer_pending`: just before `return self._reply(parsed, texts.CANCELLED)` add `self._note("cancel")`.
6. In `_execute`: just before each of its three `return` statements add, in order, `self._note("confirm_defaults")`, `self._note("run_approve")`, `self._note("run_book")`.
7. Replace `_dispatch` with:

```python
    async def _dispatch(self, user_id: str, text: str, parsed: ParsedQuery, context: ChatContext) -> ChatReply:
        intent = parsed.intent
        if intent is Intent.PLAN_NEW:
            self._note("plan_new")
            return await self._plan_new(user_id, parsed, context)
        if intent is Intent.MODIFY_PLAN:
            self._note("modify")
            return await self._modify(user_id, parsed, context)
        if intent is Intent.PLACE_INFO:
            self._note("place_info")
            return await self._place_info(text, parsed)
        if intent is Intent.APPROVE:
            self._note("ask_approve")
            return self._ask_approve(text, parsed, context)
        if intent is Intent.BOOK:
            self._note("ask_book")
            return self._ask_book(parsed, context)
        self._note("out_of_scope")
        return self._reply(parsed, texts.OUT_OF_SCOPE, replies=["Lên kế hoạch đi Huế"])
```

8. Rename the current `_place_info` to `_template_place_info` (body unchanged) and add above it:

```python
    async def _place_info(self, text: str, parsed: ParsedQuery) -> ChatReply:
        """RAG answer when configured; the template answer otherwise or when RAG fails."""
        if self.rag is not None:
            try:
                answer = await asyncio.to_thread(self.rag.answer, text, parsed)
            except Exception:  # RAG must never break the chat; the template path answers instead
                logger.exception("RAG answer failed; using the template answer")
            else:
                self.last_rag = answer
                found = (self.places.get_by_id(poi_id) for poi_id in answer.cited_poi_ids[:MAX_PLACE_CARDS])
                return self._reply(parsed, answer.text, cards=[place_card(p) for p in found if p is not None])
        return self._template_place_info(text, parsed)
```

9. Update the module docstring's last bullet to: `- Facts about places, prices and plans come from the data. A RAG place answer is LLM text, shown only when every checked fact matches the cited POIs.`

- [ ] **Step 4: Implement in `backend/app/api/chat.py`**

Replace the `app.core.config` import line and add imports:

```python
from app.chat import texts
from app.chat.cards import phone_of
from app.core.config import (
    ollama_url,
    qu_enabled,
    qu_model,
    rag_embed_model,
    rag_enabled,
    rag_gen_model,
    rag_index_path,
)
from app.rag.answer import RagAnswerer
from app.rag.index import EmbedClient, EmbeddingStore
from app.rag.retrieve import Retriever
```

Add after `_extractor`:

```python
@functools.cache
def _rag() -> RagAnswerer | None:
    """One answerer per process; None when RAG or the LLM is switched off."""
    if not (rag_enabled() and qu_enabled()):
        return None
    client = EmbedClient(ollama_url(), rag_embed_model())
    retriever = Retriever(hue_places.list_all(), EmbeddingStore(rag_index_path()), client)
    return RagAnswerer(retriever, lambda place: texts.place_text(place, phone_of(place)), ollama_url(), rag_gen_model())


def get_rag() -> RagAnswerer | None:
    """The place answerer; tests replace it with `app.dependency_overrides`."""
    return _rag()
```

Change `get_chat_service` to:

```python
def get_chat_service(
    request: Request,
    understand_fn: Understand = Depends(get_understand),
    rag: RagAnswerer | None = Depends(get_rag),
) -> ChatService:
    """Wire the chat service over the lifespan's store and orchestrator."""
    store: PlanStore = request.app.state.store
    return ChatService(
        understand=understand_fn,
        orchestrator=request.app.state.orchestrator,
        plans=store,
        booking=build_booking_agent(store),
        places=hue_places,
        chats=ChatStore(store.engine),
        rag=rag,
    )
```

- [ ] **Step 5: Run tests**

Run: `../.venv/Scripts/python -m pytest ../tests/test_chat_service.py ../tests/test_api_chat.py -q`
Expected: all PASS, including the three existing place_info tests.

- [ ] **Step 6: Manual check (needs Ollama and the index)**

Run from `backend/`:
```bash
../.venv/Scripts/python -c "from app.api.chat import _rag; a=_rag(); r=a.answer('Quán bún bò nào gần Đại Nội?'); print(r.source, r.retrieval.mode, r.cited_poi_ids); print(r.text)"
```
Expected: `llm hybrid [...]` (or `fallback` / `refusal` with a reason) and Vietnamese text. Paste the output into the task report.

- [ ] **Step 7: Full suite and commit**

```bash
git add backend/app/chat/service.py backend/app/api/chat.py tests/conftest.py tests/test_chat_service.py
git commit -m "feat(chat): answer place questions through RAG with template fallback"
```

---

### Task 6: Gold sets (done by Opus, not a coding subagent)

**Files:**
- Create: `backend/app/evaluation/__init__.py` (docstring only), `backend/app/evaluation/gold.py`, `data/eval/rag_eval_v1.jsonl`, `data/eval/scenarios_v1.jsonl`
- Test: `tests/test_eval_gold.py`

**Interfaces:**
- Produces (`gold.py`): `RAG_EVAL_FILE`, `SCENARIO_FILE` (paths under `PROJECT_ROOT / "data" / "eval"`); `Split = Literal["dev","test"]`; `Tool = Literal["transport","hotel","booking","poi_search","rag"]`; `Handler = Literal[<the ten names from Task 5>]`; `FinalState = Literal["awaiting_approval","approved","booked","answered","clarifying","confirming","refused","failed"]`; models `RagItem(id, split, group: Literal["single_place","near_place","by_category","unanswerable"], question, relevant_poi_ids: list[str], reference_answer: str)`, `BudgetExpect(budget_vnd: int, feasible: bool)`, `ConstraintExpect(must_include=[], exclude=[], exclude_categories=[], categories=[], num_days: int | None = None, start_date: date | None = None)`, `ScenarioExpect(handlers: list[Handler], final_state: FinalState, trace: list[str] | None = None, tools_called: list[Tool] = [], tools_not_called: list[Tool] = [], budget: BudgetExpect | None = None, constraints: ConstraintExpect | None = None)`, `Scenario(id, split, group: str, turns: list[str], expect: ScenarioExpect)` with a validator `len(expect.handlers) == len(turns)`; `load_jsonl(path, model, split: str) -> list` (split `"all"` keeps everything; an unknown split raises `ValueError`).

- [ ] **Step 1:** Write `gold.py` and `tests/test_eval_gold.py`: loader round trip on a tmp file, split selection, the handler-count validator error, and a check on the real files: both load, ids are unique, every `relevant_poi_ids`, `must_include` and `exclude` id exists in `backend/data/hue.sqlite`, split sizes are 40/20 (RAG) and 25/15 (scenarios).
- [ ] **Step 2:** Draft `rag_eval_v1.jsonl` — 60 items, 15 per group; dev = first 10 of each group, test = last 5. Gold POIs from SQL against `backend/data/hue.sqlite`, never from the retriever:
  - `single_place`: one named POI; question about hours, price, address or phone; the reference answer copies the DB value.
  - `near_place`: anchor POI + category; relevant = that category within 1 km of the anchor (haversine), nearest 5; the reference names the nearest 3.
  - `by_category`: category + attribute (free entry; rating ≥ 4.5 with ≥ 50 ratings; summary keyword); relevant = all matches, capped at 10 by rating count.
  - `unanswerable`: hotels, other cities, data the DB lacks (wifi, parking, vegetarian menu); relevant empty; the reference says the data has no information.
- [ ] **Step 3:** Draft `scenarios_v1.jsonl` — 40 scenarios (25 dev, 15 test), groups: `plan_full` 8, `plan_clarify` 5, `local_origin` 4, `budget` 6, `constraints` 6, `modify` 4, `approve_book` 4, `place_and_other` 3. Expected traces use the node names `search, itinerary, budget, validate, approval, await_approval` (plus `failed`, and repeated `itinerary, budget, validate` for each retry). Tools: a plan run calls `poi_search`, `hotel` (not for same-day trips) and `transport` (not when the trip starts in Huế); booking calls `booking`, `transport` and `hotel` (revalidation; no `transport` when starting in Huế); a place question calls `rag` (only when the run has RAG on).
- [ ] **Step 4:** Run `../.venv/Scripts/python -m pytest ../tests/test_eval_gold.py -q` — expected PASS.
- [ ] **Step 5: User review gate** — show the user 15 random items (8 RAG, 7 scenarios) in a table, apply their corrections. Do not start Task 8 before the user approves.
- [ ] **Step 6: Commit**

```bash
git add backend/app/evaluation/__init__.py backend/app/evaluation/gold.py data/eval/rag_eval_v1.jsonl data/eval/scenarios_v1.jsonl tests/test_eval_gold.py
git commit -m "feat(eval): RAG and chat scenario gold sets with loaders"
```

---

### Task 7: Metrics, judge, spies, harness, runner

**Files:**
- Create: `backend/app/evaluation/stats.py`, `rag_metrics.py`, `agent_metrics.py`, `planning_metrics.py`, `judge.py`, `spies.py`, `harness.py`, `run.py`
- Test: `tests/test_eval_rag_metrics.py`, `tests/test_eval_agent_metrics.py`, `tests/test_eval_judge.py`, `tests/test_eval_run.py`

**Interfaces:**
- Consumes: gold models (Task 6); `RagAnswerer`, `RagAnswer`, `build_context` (Task 4); `check_facts` (Task 4); `record_usage`, `Usage` (Task 1); `ChatService.handler_log`, `.last_rag`, `.rag` (Task 5); `parse_simple_opening_window` (`app.services.itinerary_optimizer`); `EVAL_REF` (`app.understanding.evaluate`); the `Harness` construction in `tests/test_chat_service.py` (lines 74–105) as the pattern for `build_harness`.
- Produces:
  - `stats.mean(values) -> float | None` (skips None, rounds to 4), `stats.percentile(values, fraction) -> float | None` (linear interpolation, rounds to 1), `stats.rate(flags) -> float | None`.
  - `rag_metrics.context_precision(retrieved: Sequence[str], relevant: Collection[str]) -> float | None`, `context_recall(...) -> float | None`, `faithfulness(supported: Sequence[bool]) -> float | None`, `claim_f1(tp, fp, fn) -> float | None`.
  - `agent_metrics.handler_hits(expected, actual) -> tuple[int, int]`, `tools_exact(called: set[str], expect) -> bool`, `tool_counts(called, expect) -> tuple[int, int, int]` (tp, fp, fn).
  - `planning_metrics.WITHIN`, `DAY_END = time(21, 0)`, `budget_compliant(budget: Mapping, expect: BudgetExpect) -> bool`, `schedule_feasible(itinerary: Mapping, places_by_id: Mapping[str, Place]) -> tuple[bool, int, list[str]]` (ok, unchecked visits, problems), `constraint_checks(itinerary: Mapping, expect: ConstraintExpect) -> dict[str, bool]`.
  - `judge.JudgeError`, `judge.Judge(base_url, model, timeout=180.0, transport=None)` with `.claims(answer) -> list[str]`, `.support(claims, context) -> list[bool]`, `.compare(claims, reference) -> tuple[int, int, int]`; usage component `"judge"`.
  - `spies.CallLog` (`.calls`, `.record(tool)`, `.called() -> set[str]`, `.clear()`), `spies.spy_method(obj, method, tool, log)`, `spies.spy_poi_search(log)` (context manager patching `app.agents.search.search_places`).
  - `harness.USER = "eval-user"`, `harness.EvalHarness` (dataclass: `service, store, chats, repo, log`), `harness.build_harness(understand_fn, rag) -> EvalHarness`, `harness.final_state(handler: str, reply: ChatReply, h: EvalHarness, conversation_id: str) -> str`.
  - `run.run_rag_suite(items, answerer, judge, understand_fn) -> dict`, `run.run_agents_suite(scenarios, make_harness, places_by_id) -> dict` (both return `{"summary": {...}, "records": [...]}`), `run.main(argv=None) -> int`. Output file: `{"config": {...}, "summary": {...}, "records": [...]}` at `reports/system/<suite>_<split>.json`.

- [ ] **Step 1: Failing tests for pure metrics** — `tests/test_eval_rag_metrics.py`:

```python
"""Pure RAG metric functions on hand-computed cases."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))

import pytest  # noqa: E402

from app.evaluation.rag_metrics import claim_f1, context_precision, context_recall, faithfulness  # noqa: E402
from app.evaluation.stats import mean, percentile, rate  # noqa: E402


def test_context_precision_rank_weighted() -> None:
    # relevant at ranks 1 and 3: (1/1 + 2/3) / 2
    assert context_precision(["a", "x", "b", "y"], {"a", "b"}) == pytest.approx((1 + 2 / 3) / 2)
    assert context_precision(["x", "y"], {"a"}) == 0.0
    assert context_precision(["a"], set()) is None


def test_context_recall() -> None:
    assert context_recall(["a", "x"], {"a", "b"}) == 0.5
    assert context_recall(["a"], set()) is None


def test_faithfulness_and_claim_f1() -> None:
    assert faithfulness([True, True, False]) == pytest.approx(2 / 3)
    assert faithfulness([]) is None
    assert claim_f1(2, 1, 1) == pytest.approx(2 / 3)
    assert claim_f1(0, 0, 0) is None


def test_stats() -> None:
    assert mean([1.0, None, 0.0]) == 0.5
    assert mean([None]) is None
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert rate([True, False, True, True]) == 0.75
```

`tests/test_eval_agent_metrics.py` — write these cases (build itinerary dicts by hand with keys `days[].date`, `days[].events[].{kind,start_at,end_at,poi_id,category,name}` and `validation.warnings`; Dai Noi `huetripo:531787` is open `07:30-17:30` in the real DB, load it with `HuePlacesRepository(BACKEND / "data" / "hue.sqlite").get_by_id`):
  - `handler_hits(["plan_new","place_info"], ["plan_new","out_of_scope"]) == (1, 2)`; `handler_hits(["plan_new","modify"], ["plan_new"]) == (1, 2)`.
  - `tools_exact({"poi_search","hotel"}, ScenarioExpect(handlers=["plan_new"], final_state="awaiting_approval", tools_called=["poi_search"], tools_not_called=["transport"])) is True`; the same with `"transport"` added to the called set is `False`.
  - `tool_counts({"poi_search","transport"}, expect(tools_called=["poi_search","hotel"], tools_not_called=["transport"])) == (1, 1, 1)`.
  - `budget_compliant({"options": [{"known_total_max_vnd": 1_900_000, "budget_status": "WITHIN_BUDGET"}], "shortfall_vnd": None}, BudgetExpect(budget_vnd=2_000_000, feasible=True))` is True; an option with status `WITHIN_BUDGET` and max 2_100_000 is False; `{"options": [{"known_total_max_vnd": 3_000_000, "budget_status": "OVER_BUDGET"}], "shortfall_vnd": 1_000_000}` with `feasible=False` is True.
  - `schedule_feasible`: a Dai Noi VISIT at 17:00–18:00 is not ok; at 08:00–09:00 is ok with 0 unchecked; a VISIT to a POI id whose `opening_hours_raw` is None (use `make_place`-style `Place` in a dict) counts 1 unchecked and stays ok; a MEAL ending 21:30 is not ok; a non-empty `validation.warnings` is not ok.
  - `constraint_checks`: `must_include=["huetripo:531787"]` absent → `{"must_include": False}`; `num_days=2, start_date=date(2026,12,20)` with two days starting `"2026-12-20"` → `{"num_days": True, "start_date": True}`; `exclude_categories=["cafe"]` with a cafe MEAL_BREAK → `{"exclude_categories": False}`.

`tests/test_eval_judge.py` with `httpx.MockTransport`: `claims` returns the list in `{"claims": [...]}`; `support(["a","b"], ctx)` maps `{"verdicts": [{"index": 0, "supported": true}, {"index": 1, "supported": false}]}` to `[True, False]`; a reply with one verdict for two claims is retried once, and a second bad reply raises `JudgeError`; `support([], ctx) == []` without a request; `compare(["a","b"], "ref")` reads `{"answer_claims": [{"index":0,"in_reference":true},{"index":1,"in_reference":false}], "reference_claims": [{"claim":"x","in_answer":false}]}` as `(1, 1, 1)`; `compare([], "ref") == (0, 0, 1)` without a request; `record_usage()` shows component `"judge"`.

`tests/test_eval_run.py`:
  - (a) `run_agents_suite` on two hand-written `Scenario`s with `make_harness=lambda: build_harness(lambda text, ctx: understand(text, EVAL_REF, ctx), None)` — scenario 1: turns `["Từ Hà Nội, 2 người, đi Huế 2 ngày từ 20/12"]`, expect `handlers=["plan_new"]`, `final_state="awaiting_approval"`, `trace=["search","itinerary","budget","validate","approval","await_approval"]`, `tools_called=["poi_search","hotel","transport"]`; scenario 2: an out-of-scope turn `["Thời tiết Đà Nẵng mai thế nào?"]` (check with the rules parser that it is out_of_scope; if not, pick a sentence that is), expect `handlers=["out_of_scope"]`, `final_state="refused"`, `tools_not_called=["transport","hotel"]`. Assert `summary["task_success_rate"] == 1.0`, `summary["routing_accuracy"] == 1.0`, `summary["tool_exact_rate"] == 1.0`, `summary["schedule_feasibility_rate"]` is not None, and `records[0]["turns"][0]["latency_ms"] > 0`.
  - (b) `run_rag_suite` on two `RagItem`s (one `single_place` with `relevant_poi_ids=["huetripo:3"]`, one `unanswerable`) with a fake answerer (attribute `retriever` = `Retriever(PLACES)` from `test_rag_retrieve`; method `answer` returns a fixed `RagAnswer` citing `huetripo:3` for the first and a refusal for the second) and a fake judge (`claims` → `["c1","c2"]`, `support` → `[True, False]`, `compare` → `(1, 1, 0)`), `understand_fn=lambda text, ctx: None`. Assert `summary["context_recall"] == 1.0`, `summary["faithfulness"] == 0.5`, the unanswerable record has `answer_correctness == 1.0`, and `summary` has every key listed in Step 4.

- [ ] **Step 2: Run and confirm failure** — `../.venv/Scripts/python -m pytest ../tests/test_eval_rag_metrics.py ../tests/test_eval_agent_metrics.py ../tests/test_eval_judge.py ../tests/test_eval_run.py -q` → FAIL, missing modules.

- [ ] **Step 3: Implement the pure modules**

`backend/app/evaluation/stats.py`:

```python
"""Small summary statistics that skip missing values."""

from __future__ import annotations

from collections.abc import Iterable, Sequence


def mean(values: Iterable[float | None]) -> float | None:
    kept = [v for v in values if v is not None]
    return round(sum(kept) / len(kept), 4) if kept else None


def rate(flags: Iterable[bool | None]) -> float | None:
    return mean(1.0 if flag else 0.0 for flag in flags if flag is not None)


def percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 1)
```

`backend/app/evaluation/rag_metrics.py`:

```python
"""RAG metrics: id-based context precision and recall, claim-based faithfulness and correctness."""

from __future__ import annotations

from collections.abc import Collection, Sequence


def context_precision(retrieved: Sequence[str], relevant: Collection[str]) -> float | None:
    """RAGAS form: mean of precision@k over the ranks that hold a relevant id; None for empty gold."""
    if not relevant:
        return None
    hits, total = 0, 0.0
    for rank, poi_id in enumerate(retrieved, start=1):
        if poi_id in relevant:
            hits += 1
            total += hits / rank
    return total / hits if hits else 0.0


def context_recall(retrieved: Sequence[str], relevant: Collection[str]) -> float | None:
    if not relevant:
        return None
    return len(set(retrieved) & set(relevant)) / len(set(relevant))


def faithfulness(supported: Sequence[bool]) -> float | None:
    return sum(supported) / len(supported) if supported else None


def claim_f1(tp: int, fp: int, fn: int) -> float | None:
    if tp + fp + fn == 0:
        return None
    return tp / (tp + 0.5 * (fp + fn))
```

`backend/app/evaluation/agent_metrics.py`:

```python
"""Multi-agent metrics: per-turn handler routing and tool-call correctness."""

from __future__ import annotations

from collections.abc import Sequence

from app.evaluation.gold import ScenarioExpect


def handler_hits(expected: Sequence[str], actual: Sequence[str]) -> tuple[int, int]:
    """(turns routed to the gold handler, gold turns); a missing actual turn is a miss."""
    hits = sum(1 for i, name in enumerate(expected) if i < len(actual) and actual[i] == name)
    return hits, len(expected)


def tools_exact(called: set[str], expect: ScenarioExpect) -> bool:
    return set(expect.tools_called) <= called and not (set(expect.tools_not_called) & called)


def tool_counts(called: set[str], expect: ScenarioExpect) -> tuple[int, int, int]:
    """(required tools called, forbidden tools called, required tools missed)."""
    required, forbidden = set(expect.tools_called), set(expect.tools_not_called)
    return len(required & called), len(forbidden & called), len(required - called)
```

`backend/app/evaluation/planning_metrics.py`:

```python
"""Travel-planning metrics on saved plan payloads (the JSON dicts PlanStore returns)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, time
from typing import Any

from app.evaluation.gold import BudgetExpect, ConstraintExpect
from app.schemas.place import Place
from app.services.itinerary_optimizer import parse_simple_opening_window

WITHIN = frozenset({"WITHIN_BUDGET", "WITHIN_BUDGET_EXCLUDING_UNKNOWN"})
DAY_END = time(21, 0)


def budget_compliant(budget: Mapping[str, Any], expect: BudgetExpect) -> bool:
    """Feasible gold: an option fits and no WITHIN_BUDGET label is false. Infeasible gold: shortfall
    is reported and no option claims to fit."""
    options = list(budget.get("options", []))
    honest = all(
        option["known_total_max_vnd"] <= expect.budget_vnd
        for option in options
        if option.get("budget_status") == "WITHIN_BUDGET"
    )
    if expect.feasible:
        fits = any(option["known_total_max_vnd"] <= expect.budget_vnd for option in options)
        return bool(options) and fits and honest
    claims_fit = any(option.get("budget_status") in WITHIN for option in options)
    return budget.get("shortfall_vnd") is not None and not claims_fit


def _events(itinerary: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [event for day in itinerary.get("days", []) for event in day.get("events", [])]


def schedule_feasible(
    itinerary: Mapping[str, Any], places_by_id: Mapping[str, Place]
) -> tuple[bool, int, list[str]]:
    """Validator clean, visits inside parsable opening windows, nothing ends after DAY_END."""
    problems = list(itinerary.get("validation", {}).get("warnings", []))
    unchecked = 0
    for event in _events(itinerary):
        start = datetime.fromisoformat(str(event["start_at"]))
        end = datetime.fromisoformat(str(event["end_at"]))
        if end.time() > DAY_END or end.date() != start.date():
            problems.append(f"{event.get('name', event.get('poi_id'))} ends after {DAY_END:%H:%M}")
        if event.get("kind") != "VISIT" or not event.get("poi_id"):
            continue
        place = places_by_id.get(event["poi_id"])
        window = parse_simple_opening_window(place.opening_hours_raw) if place else None
        if window is None:
            unchecked += 1
        elif start.time() < window[0] or end.time() > window[1]:
            problems.append(
                f"{event['poi_id']} visited {start:%H:%M}-{end:%H:%M} outside {window[0]:%H:%M}-{window[1]:%H:%M}"
            )
    return not problems, unchecked, problems


def constraint_checks(itinerary: Mapping[str, Any], expect: ConstraintExpect) -> dict[str, bool]:
    """One pass/fail per constraint type the gold states."""
    events = _events(itinerary)
    poi_ids = {event["poi_id"] for event in events if event.get("poi_id")}
    categories = {event["category"] for event in events if event.get("category")}
    days = list(itinerary.get("days", []))
    checks: dict[str, bool] = {}
    if expect.must_include:
        checks["must_include"] = set(expect.must_include) <= poi_ids
    if expect.exclude:
        checks["exclude"] = not (set(expect.exclude) & poi_ids)
    if expect.exclude_categories:
        checks["exclude_categories"] = not (set(expect.exclude_categories) & categories)
    if expect.categories:
        checks["categories"] = set(expect.categories) <= categories
    if expect.num_days is not None:
        checks["num_days"] = len(days) == expect.num_days
    if expect.start_date is not None:
        checks["start_date"] = bool(days) and str(days[0]["date"]) == expect.start_date.isoformat()
    return checks
```

`backend/app/evaluation/spies.py`:

```python
"""Tool spies: record which provider or retrieval tool a chat turn used."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import app.agents.search as search_module


class CallLog:
    """Tool names in call order."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def record(self, tool: str) -> None:
        self.calls.append(tool)

    def called(self) -> set[str]:
        return set(self.calls)

    def clear(self) -> None:
        self.calls.clear()


def spy_method(obj: Any, method: str, tool: str, log: CallLog) -> None:
    """Replace obj.method on this instance with a wrapper that records `tool` first."""
    original = getattr(obj, method)

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        log.record(tool)
        return original(*args, **kwargs)

    setattr(obj, method, wrapper)


@contextmanager
def spy_poi_search(log: CallLog) -> Iterator[None]:
    """Record "poi_search" for every POI search the Search Agent runs."""
    original = search_module.search_places

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        log.record("poi_search")
        return original(*args, **kwargs)

    search_module.search_places = wrapper
    try:
        yield
    finally:
        search_module.search_places = original
```

- [ ] **Step 4: Implement judge, harness, runner**

`backend/app/evaluation/judge.py` — same HTTP code as `RagAnswerer._chat` (POST `/api/chat`, `format` = schema, `stream` False, `think` False, `options.temperature` 0, `add_usage("judge", payload)`), `MAX_ATTEMPTS = 2`, `JudgeError` after the second failure (transport error, invalid JSON, or a shape check below). Three methods:
- `claims(answer)`: system prompt `"Split the ANSWER into short atomic factual claims in Vietnamese, one fact per claim. Ignore greetings and filler. Return JSON {\"claims\": [...]}."`; user content `f"ANSWER:\n{answer}"`; schema `{"type":"object","properties":{"claims":{"type":"array","items":{"type":"string"}}},"required":["claims"]}`; returns the non-blank stripped claims.
- `support(claims, context)`: `[]` without a request when `claims` is empty. System prompt `"For each numbered CLAIM decide whether the CONTEXT states it. supported=true only when the context says it explicitly; a claim about a place not in the context is not supported. Return JSON {\"verdicts\": [{\"index\": int, \"supported\": bool}]} with one verdict per claim."`; user content lists `CONTEXT:\n{context}\n\nCLAIMS:\n0. ...\n1. ...`; valid only when the set of indices equals `{0..n-1}`; returns booleans in index order.
- `compare(claims, reference)`: `(0, 0, 1)` without a request when `claims` is empty. System prompt `"Compare the numbered ANSWER claims with the REFERENCE answer. For each answer claim set in_reference=true when the reference states the same fact. Then split the REFERENCE into atomic claims and set in_answer=true when the answer states it. Return JSON {\"answer_claims\": [{\"index\": int, \"in_reference\": bool}], \"reference_claims\": [{\"claim\": str, \"in_answer\": bool}]}."`; valid only when answer indices equal `{0..n-1}`; returns `(tp, fp, fn)` = (answer claims in reference, answer claims not in reference, reference claims not in answer).

`backend/app/evaluation/harness.py`:

```python
"""A chat service for evaluation: in-memory stores, mock providers, tool spies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from app.agents.booking import BookingAgent
from app.agents.orchestrator import Orchestrator
from app.agents.search import SearchAgent
from app.chat import texts
from app.chat.schemas import BookingCard, ChatReply, PlanCard
from app.chat.service import ChatService
from app.chat.store import ChatStore
from app.core.config import hue_database_path
from app.db.store import PlanStore
from app.evaluation.spies import CallLog, spy_method
from app.providers.booking_mock import MockBookingProvider
from app.providers.hotel_mock import MockHotelProvider
from app.providers.transport_mock import MockTransportProvider
from app.repositories.hue_places import HuePlacesRepository
from app.services.budget_optimizer import BudgetAgent
from app.services.itinerary_optimizer import ItineraryAgent
from app.services.quote_revalidator import QuoteRevalidator

USER = "eval-user"


@dataclass
class EvalHarness:
    service: ChatService
    store: PlanStore
    chats: ChatStore
    repo: HuePlacesRepository
    log: CallLog


def build_harness(understand_fn: Callable[..., Any], rag: Any | None) -> EvalHarness:
    store = PlanStore("sqlite://")
    repo = HuePlacesRepository(hue_database_path())
    log = CallLog()
    transport, hotel, booking_provider = MockTransportProvider(), MockHotelProvider(), MockBookingProvider()
    spy_method(transport, "search", "transport", log)
    spy_method(hotel, "search", "hotel", log)
    spy_method(booking_provider, "book", "booking", log)
    if rag is not None:
        spy_method(rag, "answer", "rag", log)
    orchestrator = Orchestrator(
        SearchAgent(repo, transport, hotel),
        BudgetAgent(places=repo),
        ItineraryAgent(places=repo),
        store,
        InMemorySaver(),
    )
    booking = BookingAgent(store, booking_provider, QuoteRevalidator(transport, hotel), places=repo)
    chats = ChatStore(store.engine)
    service = ChatService(understand_fn, orchestrator, store, booking, repo, chats, rag=rag)
    service.handler_log = []
    return EvalHarness(service=service, store=store, chats=chats, repo=repo, log=log)


def final_state(handler: str, reply: ChatReply, h: EvalHarness, conversation_id: str) -> str:
    """The scenario outcome after its last turn; the first matching rule wins."""
    if any(isinstance(card, BookingCard) for card in reply.cards):
        return "booked"
    if handler == "run_approve":
        thread_id = h.chats.context(conversation_id).thread_id
        plan = h.store.latest(thread_id) if thread_id else None
        if plan is not None and h.store.active_approval(plan["plan_id"]) is not None:
            return "approved"
    if any(isinstance(card, PlanCard) for card in reply.cards):
        return "awaiting_approval"
    if handler == "place_info":
        rag = h.service.last_rag
        if (rag is not None and not rag.answerable) or reply.text == texts.PLACE_MISSING:
            return "refused"
        return "answered"
    if handler == "out_of_scope":
        return "refused"
    pending = reply.pending_confirmation or {}
    if pending.get("kind") in {"approve", "book"}:
        return "confirming"
    if handler in {"plan_new", "confirm_defaults"} and (reply.quick_replies or reply.pending_confirmation):
        return "clarifying"
    return "failed"
```

Check `ChatStore.context(conversation_id)` returns an object with `.thread_id` (it does in `chat/service.py`); if `QuoteRevalidator` takes keyword arguments, match its real signature.

`backend/app/evaluation/run.py` — implement these functions:

- `run_rag_suite(items, answerer, judge, understand_fn) -> dict`. For each item:
  1. `with record_usage() as usage:` measure `time.perf_counter()` around `parsed = understand_fn(item.question, None)` and `result = answerer.answer(item.question, parsed)` → `latency_ms`.
  2. `retrieved = [hit.poi_id for hit in result.retrieval.hits]`; context precision and recall from `rag_metrics`; `citation_hit = bool(set(result.cited_poi_ids) & set(item.relevant_poi_ids))` (None for unanswerable gold).
  3. In a separate `with record_usage() as judge_usage:` block: when `result.source == "refusal"`: `faithfulness = None`, `answer_correctness = 1.0 if item.group == "unanswerable" else 0.0`, no judge call. Otherwise: `claims = judge.claims(result.text)`; `supported = judge.support(claims, build_context(result.retrieval.hits, answerer.retriever.by_id))`; fact override: `mismatches = check_facts(result.raw_text, [answerer.retriever.by_id[i] for i in result.cited_poi_ids if i in answerer.retriever.by_id])`; for each mismatch, every claim whose text contains `mismatch.value` becomes False, and if no claim contains it, append one `False`; `faithfulness = rag_metrics.faithfulness(supported)`. Correctness: `0.0` for unanswerable gold (the bot answered), else `claim_f1(*judge.compare(claims, item.reference_answer))`. `JudgeError` → `judge_error = True`, faithfulness and correctness None.
  4. Record: `id, group, split, question, retrieved, relevant, mode, source, cited, answerable, text, claims, supported, context_precision, context_recall, faithfulness, answer_correctness, citation_hit, judge_error, latency_ms, usage` (component → `to_dict()`), `judge_usage`.
  Summary keys: `n, context_precision, context_recall, faithfulness, answer_correctness, citation_hit_rate, refusal_precision, refusal_recall, judge_errors, fallback_count, mode_counts, latency_p50_ms, latency_p95_ms, latency_mean_ms, tokens_per_turn, judge_tokens_total, per_group`. Refusal precision = gold-unanswerable refusals / all refusals; recall = gold-unanswerable refusals / gold-unanswerable items. `tokens_per_turn = {"prompt": mean, "completion": mean, "total": mean, "by_component": {component: mean total}}` over items, counting only `extractor` and `rag_generator` in `prompt/completion/total`; embedding tokens appear only in `by_component`. `per_group[group]` holds the four RAG metrics.

- `run_agents_suite(scenarios, make_harness, places_by_id) -> dict`. For each scenario: `h = make_harness()`, `conversation = f"eval-{scenario.id}"`, and inside `with spy_poi_search(h.log):` one `asyncio.run(_play(...))` coroutine that, for each turn: `before = len(h.service.handler_log)`; `with record_usage() as usage:` time `reply = await h.service.handle(conversation, USER, text)`; `handler = h.service.handler_log[before] if len(h.service.handler_log) > before else "none"`; after the turn, if the conversation has a thread, `plan = h.store.latest(thread_id)` and keep `plan["payload"]` keyed by `(plan["plan_id"], plan["version"])`. An exception records `error` on that turn and ends the scenario. After the turns: `state = await h.service.orchestrator.state(thread_id)` when a thread exists.
  Per scenario: `handlers`, `handler_hits`, `final_state` (via `harness.final_state` on the last turn; `"failed"` on error), `task_success = final == expect.final_state and no error`, `trace` (`state["trace"]` or None) and `trace_ok` (None when `expect.trace` is None), `tools_called = sorted(h.log.called())`, `tools_exact`, `tool_counts`, `budget_ok` (final plan payload `["budget"]`, None when no budget gold or no plan → False when gold exists but no plan), `feasibility` per plan version (`schedule_feasible(payload["itinerary"], places_by_id)`), `constraints` (`constraint_checks(final payload["itinerary"], expect.constraints)`, all-True required for pass; no plan with constraint gold → every stated type False), per-turn `latency_ms`, `handler`, `usage`.
  Summary keys: `n, task_success_rate, routing_accuracy` (sum hits / sum gold turns), `trace_accuracy, tool_exact_rate, tool_precision` (tp / (tp + fp)), `tool_recall` (tp / (tp + fn)), `budget_compliance_rate, budget_n, schedule_feasibility_rate, plans_n, unchecked_visits, constraint_satisfaction_rate, constraint_n, constraint_by_type, latency_p50_ms, latency_p95_ms, latency_mean_ms, latency_by_handler, tokens_per_turn, errors`.

- `main(argv=None) -> int`: arguments `--suite rag|agents|all` (default `all`), `--split dev|test|all` (default `dev`), `--judge-model` (default `qwen3.5:9b`), `--no-llm`, `--out-dir` (default `PROJECT_ROOT / "reports" / "system"`). Ollama is up when `httpx.get(f"{ollama_url()}/api/tags", timeout=5).status_code == 200`. Without Ollama or with `--no-llm`: the rag suite prints `RAG suite needs Ollama at <url>` to stderr and is skipped (return 2 if it was the only suite); the agents suite runs with `understand(text, EVAL_REF, ctx)` (rules) and `rag=None`, config `"extractor": "rules"`. With Ollama: `extractor = OllamaExtractor(ollama_url(), qu_model())`, `understand_fn = lambda text, ctx: understand(text, EVAL_REF, ctx, extractor=extractor)`; build the answerer the same way as `api.chat._rag` but directly (do not import the cached API function); `judge = Judge(ollama_url(), args.judge_model)`. Agents suite with Ollama builds a fresh answerer-sharing harness per scenario: `make_harness = lambda: build_harness(understand_fn, answerer)` — wrap the shared answerer in a thin per-harness object before spying (`types.SimpleNamespace(answer=answerer.answer, retriever=answerer.retriever)`) so spies do not stack across scenarios. `places_by_id = {p.id: p for p in HuePlacesRepository(hue_database_path()).list_all()}`. Create the out dir, write `<suite>_<split>.json` with `json.dumps({"config": ..., "summary": ..., "records": ...}, ensure_ascii=False, indent=2, default=str)`, print each summary. Config: `models` (extractor, generator, embedding, judge), `k`, `split`, `date` (today ISO), `eval_ref`, `extractor`.

- [ ] **Step 5: Run tests** — the four eval test files → PASS. Then the full suite → PASS.

- [ ] **Step 6: Smoke run without LLM**

Run: `../.venv/Scripts/python -m app.evaluation.run --suite agents --split dev --no-llm`
Expected: writes `reports/system/agents_dev.json` and prints a summary with every key; failures from the rules parser are data, not a crash.

- [ ] **Step 7: Commit** (do not commit the smoke JSON)

```bash
git add backend/app/evaluation tests/test_eval_rag_metrics.py tests/test_eval_agent_metrics.py tests/test_eval_judge.py tests/test_eval_run.py
git commit -m "feat(eval): system metrics harness for RAG, agents, planning and performance"
```

---

### Task 8: Runs and report (done by Opus)

**Files:**
- Create: `reports/system/rag_dev.json`, `agents_dev.json`, `rag_test.json`, `agents_test.json`, `reports/system/README.md`

- [ ] **Step 1: Dev runs** — `../.venv/Scripts/python -m app.evaluation.run --suite all --split dev` with nothing else using Ollama. Record the wall time.
- [ ] **Step 2: One tuning round on dev only** — read the failures. Allowed changes: RAG prompt, `ANCHOR_RADIUS_KM`, `k`, document text order, fact regexes. Every code change: haiku brief → review → full suite → its own commit. Rerun dev once.
- [ ] **Step 3: Test run, once** — `../.venv/Scripts/python -m app.evaluation.run --suite all --split test`.
- [ ] **Step 4: Write `reports/system/README.md`** — run configuration (models, k, judge, date, extractor), one table of the 13 metrics with dev and test columns, the per-group RAG table, the dev tuning changes with before/after numbers, 10 failure examples (id, question or scenario, what went wrong, cause), and caveats: the judge is a local 9b model; providers are mocks; feasibility skips visits to POIs without parsable hours (state the count).
- [ ] **Step 5: Commit**

```bash
git add reports/system
git commit -m "docs(eval): system metrics report for RAG, agents, planning and performance"
```
