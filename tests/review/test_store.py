import pytest
from pydantic import ValidationError

from tests.review.conftest import NOW
from travel_agent.domain.models import Category
from travel_agent.review.models import ReviewInput, ReviewStatus
from travel_agent.review.store import ReviewStore


def test_everything_starts_pending(store: ReviewStore) -> None:
    assert store.stats() == {
        "pending": 3,
        "approved": 0,
        "rejected": 0,
        "needs_fix": 0,
        "total": 3,
    }


def test_save_moves_place_between_status_filters(store: ReviewStore) -> None:
    store.save(ReviewInput(place_id="osm:node/1", status=ReviewStatus.APPROVED), NOW)
    approved, total = store.query(status=ReviewStatus.APPROVED)
    assert total == 1
    assert approved[0].place.id == "osm:node/1"
    pending, _ = store.query(status=ReviewStatus.PENDING)
    assert "osm:node/1" not in [item.place.id for item in pending]
    assert store.stats()["approved"] == 1


def test_save_again_updates_review(store: ReviewStore) -> None:
    store.save(ReviewInput(place_id="osm:node/1", status=ReviewStatus.APPROVED), NOW)
    store.save(ReviewInput(place_id="osm:node/1", status=ReviewStatus.REJECTED, note="trùng"), NOW)
    item = store.get("osm:node/1")
    assert item is not None
    assert item.status is ReviewStatus.REJECTED
    assert item.review is not None
    assert item.review.note == "trùng"


def test_clear_returns_to_pending(store: ReviewStore) -> None:
    store.save(ReviewInput(place_id="osm:node/1", status=ReviewStatus.NEEDS_FIX), NOW)
    store.clear("osm:node/1")
    item = store.get("osm:node/1")
    assert item is not None
    assert item.status is ReviewStatus.PENDING
    assert item.review is None


def test_unknown_place_raises_key_error(store: ReviewStore) -> None:
    with pytest.raises(KeyError):
        store.save(ReviewInput(place_id="osm:node/404", status=ReviewStatus.APPROVED), NOW)


def test_overrides_apply_to_effective_place_only(store: ReviewStore) -> None:
    store.save(
        ReviewInput(
            place_id="osm:node/6",
            status=ReviewStatus.APPROVED,
            name_override="Quán Mẫu (đã sửa)",
            category_override=Category.CAFE,
            opening_hours_override="Mo-Su 06:00-22:00",
            evidence="Biển hiệu tại quán, chụp 2026-11-03",
        ),
        NOW,
    )
    item = store.get("osm:node/6")
    assert item is not None
    effective = item.effective_place()
    assert effective.name == "Quán Mẫu (đã sửa)"
    assert effective.category is Category.CAFE
    assert effective.opening_hours_raw == "Mo-Su 06:00-22:00"
    assert item.place.name == "Quán Mẫu"
    assert item.place.opening_hours_raw is None


def test_category_filter_uses_override_and_search_matches_name(store: ReviewStore) -> None:
    store.save(
        ReviewInput(
            place_id="osm:node/6", status=ReviewStatus.APPROVED, category_override=Category.CAFE
        ),
        NOW,
    )
    cafes, _ = store.query(category=Category.CAFE)
    assert sorted(item.place.id for item in cafes) == ["osm:node/6", "osm:way/2"]
    found, total = store.query(search="Bảo tàng")
    assert total == 1
    assert found[0].place.id == "osm:node/1"


def test_sources_and_source_filter(store: ReviewStore) -> None:
    assert store.sources() == {"osm": 3}
    _, total = store.query(source="osm")
    assert total == 3
    _, none = store.query(source="data.hue.gov.vn")
    assert none == 0
    assert store.stats(source="data.hue.gov.vn")["total"] == 0


def test_pagination(store: ReviewStore) -> None:
    first, total = store.query(limit=2)
    second, _ = store.query(offset=2, limit=2)
    assert total == 3
    assert len(first) == 2
    assert len(second) == 1


def test_approved_lists_all_approved(store: ReviewStore) -> None:
    store.save(ReviewInput(place_id="osm:node/1", status=ReviewStatus.APPROVED), NOW)
    store.save(ReviewInput(place_id="osm:way/2", status=ReviewStatus.REJECTED), NOW)
    assert [item.place.id for item in store.approved()] == ["osm:node/1"]


def test_blank_strings_become_none() -> None:
    review = ReviewInput(
        place_id="osm:node/1", status=ReviewStatus.APPROVED, name_override="  ", note=""
    )
    assert review.name_override is None
    assert review.note is None


def test_hours_override_must_parse() -> None:
    with pytest.raises(ValidationError, match="cú pháp"):
        ReviewInput(
            place_id="osm:node/1",
            status=ReviewStatus.APPROVED,
            opening_hours_override="sáng 7h tới chiều",
            evidence="website",
        )


def test_hours_override_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="evidence"):
        ReviewInput(
            place_id="osm:node/1",
            status=ReviewStatus.APPROVED,
            opening_hours_override="Mo-Su 07:00-17:00",
        )


def test_pending_cannot_be_saved() -> None:
    with pytest.raises(ValidationError, match="pending"):
        ReviewInput(place_id="osm:node/1", status=ReviewStatus.PENDING)
