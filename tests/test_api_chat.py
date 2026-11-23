"""Chat API: POST a message, GET the history, owner checks, and the plan card over HTTP."""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api import chat as chat_module  # noqa: E402
from app.api.chat import get_understand  # noqa: E402
from app.main import app  # noqa: E402

ALICE = {"X-User-Id": "alice"}
BOB = {"X-User-Id": "bob"}
PLAN_TRIP = "Đi Huế 2 ngày từ 20/12 từ Hà Nội 2 người ngân sách 5 triệu thích ẩm thực"


def test_rag_construction_failure_disables_rag_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_retriever(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(chat_module, "rag_enabled", lambda: True)
    monkeypatch.setattr(chat_module, "qu_enabled", lambda: True)
    monkeypatch.setattr(chat_module, "EmbeddingStore", lambda path: None)
    monkeypatch.setattr(chat_module, "Retriever", broken_retriever)
    chat_module._rag.cache_clear()
    try:
        assert chat_module._rag() is None
    finally:
        chat_module._rag.cache_clear()


def test_rag_switched_off_gives_no_answerer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_module, "rag_enabled", lambda: False)
    monkeypatch.setattr(chat_module, "qu_enabled", lambda: True)
    chat_module._rag.cache_clear()
    try:
        assert chat_module._rag() is None
    finally:
        chat_module._rag.cache_clear()


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _conversation() -> str:
    return f"api-chat-{uuid.uuid4().hex}"


def test_post_answers_with_a_reply_that_carries_the_understanding_source(client: TestClient) -> None:
    conversation = _conversation()

    response = client.post(f"/api/v1/chat/{conversation}", json={"text": "Đi Huế 2 ngày"}, headers=ALICE)

    assert response.status_code == 200
    body = response.json()
    assert body["message_id"]
    assert body["understanding"]["source"] == "RULES"
    assert body["quick_replies"] == []


def test_post_a_complete_request_returns_a_plan_summary_card(client: TestClient) -> None:
    conversation = _conversation()

    client.post(f"/api/v1/chat/{conversation}", json={"text": PLAN_TRIP}, headers=ALICE)
    # Transport and stay come next; "tùy" settles them, then pace and places, which "tùy" settles too.
    # The summary waits for "ok" before the plan starts (S4).
    client.post(f"/api/v1/chat/{conversation}", json={"text": "tùy"}, headers=ALICE)
    client.post(f"/api/v1/chat/{conversation}", json={"text": "tùy"}, headers=ALICE)
    response = client.post(f"/api/v1/chat/{conversation}", json={"text": "ok"}, headers=ALICE)

    assert response.status_code == 200
    cards = response.json()["cards"]
    assert cards[0]["kind"] == "plan_summary"
    assert cards[0]["status"] == "AWAITING_APPROVAL"
    assert len(cards[0]["days"]) == 2


def test_another_user_gets_403_when_posting_to_the_conversation(client: TestClient) -> None:
    conversation = _conversation()
    client.post(f"/api/v1/chat/{conversation}", json={"text": "Đi Huế 2 ngày"}, headers=ALICE)

    response = client.post(f"/api/v1/chat/{conversation}", json={"text": "Đi Huế 3 ngày"}, headers=BOB)

    assert response.status_code == 403


def test_history_returns_the_turns_in_order_for_the_owner(client: TestClient) -> None:
    conversation = _conversation()
    client.post(f"/api/v1/chat/{conversation}", json={"text": "Đi Huế 2 ngày"}, headers=ALICE)
    client.post(f"/api/v1/chat/{conversation}", json={"text": "20/12"}, headers=ALICE)

    response = client.get(f"/api/v1/chat/{conversation}", headers=ALICE)

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[1]["payload"]["understanding"]["source"] == "RULES"


def test_history_is_403_for_another_owner_and_404_when_missing(client: TestClient) -> None:
    conversation = _conversation()
    client.post(f"/api/v1/chat/{conversation}", json={"text": "Đi Huế 2 ngày"}, headers=ALICE)

    other_owner = client.get(f"/api/v1/chat/{conversation}", headers=BOB)
    missing = client.get(f"/api/v1/chat/{_conversation()}", headers=ALICE)

    assert other_owner.status_code == 403
    assert missing.status_code == 404


def test_empty_message_is_a_validation_error(client: TestClient) -> None:
    response = client.post(f"/api/v1/chat/{_conversation()}", json={"text": ""}, headers=ALICE)

    assert response.status_code == 422


def test_the_understanding_function_is_an_injectable_dependency(client: TestClient) -> None:
    from app.understanding.models import Intent, ParsedQuery, QuSource

    def fake(text, context):
        return ParsedQuery(intent=Intent.OUT_OF_SCOPE, source=QuSource.OLLAMA)

    app.dependency_overrides[get_understand] = lambda: fake
    try:
        response = client.post(f"/api/v1/chat/{_conversation()}", json={"text": "bất kỳ"}, headers=ALICE)
    finally:
        app.dependency_overrides.clear()

    assert response.json()["understanding"]["source"] == "OLLAMA"
    assert response.json()["understanding"]["intent"] == "out_of_scope"
