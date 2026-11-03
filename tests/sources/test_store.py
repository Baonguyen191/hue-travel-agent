import datetime as dt
from pathlib import Path

import pytest
from pydantic import ValidationError

from travel_agent.sources.models import LinkInput, LinkStatus, LinkTopic
from travel_agent.sources.store import LinkStore

NOW = dt.datetime(2026, 11, 3, 10, 0, tzinfo=dt.UTC)


def make_store(tmp_path: Path) -> LinkStore:
    return LinkStore(tmp_path / "hue.sqlite")


def test_add_many_links_with_shared_topic_and_note(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    result = store.add(
        LinkInput(
            urls=["https://example.com/a", "https://example.com/b"],
            topic=LinkTopic.FOOD,
            note="quán ăn Huế",
        ),
        NOW,
    )
    assert [link.url for link in result.added] == ["https://example.com/a", "https://example.com/b"]
    assert result.duplicates == []
    assert all(link.topic is LinkTopic.FOOD for link in result.added)
    assert all(link.status is LinkStatus.NEW for link in result.added)
    assert result.added[0].note == "quán ăn Huế"
    store.close()


def test_duplicates_are_reported_not_added_twice(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add(LinkInput(urls=["https://example.com/a"]), NOW)
    result = store.add(LinkInput(urls=["https://example.com/a", "https://example.com/c"]), NOW)
    assert [link.url for link in result.added] == ["https://example.com/c"]
    assert result.duplicates == ["https://example.com/a"]
    assert len(store.list()) == 2
    store.close()


def test_list_newest_first_and_filter_by_status(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add(LinkInput(urls=["https://example.com/old"]), NOW)
    store.add(LinkInput(urls=["https://example.com/new"]), NOW + dt.timedelta(minutes=1))
    assert [link.url for link in store.list()] == [
        "https://example.com/new",
        "https://example.com/old",
    ]
    old = store.list()[1]
    store.set_status(old.id, LinkStatus.PROCESSED)
    assert [link.url for link in store.list(LinkStatus.NEW)] == ["https://example.com/new"]
    assert store.counts() == {"new": 1, "processed": 1, "failed": 0, "total": 2}
    store.close()


def test_delete(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    [link] = store.add(LinkInput(urls=["https://example.com/a"]), NOW).added
    assert store.delete(link.id) is True
    assert store.delete(link.id) is False
    assert store.list() == []
    store.close()


def test_blank_lines_dropped_and_batch_deduplicated() -> None:
    links = LinkInput(urls=["  https://example.com/a ", "", "https://example.com/a"])
    assert links.urls == ["https://example.com/a"]


@pytest.mark.parametrize(
    "bad",
    ["example.com/no-scheme", "ftp://example.com/file", "javascript:alert(1)", "https://"],
)
def test_rejects_non_http_urls(bad: str) -> None:
    with pytest.raises(ValidationError, match="Link không hợp lệ"):
        LinkInput(urls=[bad])


def test_requires_at_least_one_url() -> None:
    with pytest.raises(ValidationError):
        LinkInput(urls=["", "   "])
