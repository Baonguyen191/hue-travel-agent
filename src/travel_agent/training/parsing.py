"""Parse output thô của model thành Itinerary. Nghiêm ngặt: không sửa hộ output."""

from __future__ import annotations

from pydantic import ValidationError

from travel_agent.domain.models import Itinerary


def parse_itinerary(raw: str) -> Itinerary | None:
    """Trả None khi output không phải JSON hợp lệ theo schema Itinerary.

    Không cắt code fence, không vá JSON: output hỏng phải được tính là lỗi của model.
    """
    try:
        return Itinerary.model_validate_json(raw.strip())
    except ValidationError:
        return None
