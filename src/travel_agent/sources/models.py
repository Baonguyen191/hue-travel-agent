"""Link nguồn dữ liệu do người dùng thêm vào để xử lý sau.

Chỉ lưu link và ghi chú. Server không tự tải nội dung từ link; việc đọc từng nguồn
(kiểm tra điều khoản, giấy phép, trích dữ liệu) làm riêng ở bước xử lý.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

MAX_URL_LENGTH = 2000
MAX_URLS_PER_BATCH = 200


class LinkTopic(StrEnum):
    SIGHTS = "sights"  # điểm tham quan
    FOOD = "food"  # ẩm thực
    STAY = "stay"  # lưu trú
    ITINERARY = "itinerary"  # lịch trình mẫu, kinh nghiệm
    OTHER = "other"


class LinkStatus(StrEnum):
    NEW = "new"  # chưa xử lý
    PROCESSED = "processed"  # đã trích dữ liệu
    FAILED = "failed"  # không dùng được (lỗi, cấm crawl, giấy phép không cho phép...)


def _is_http_url(url: str) -> bool:
    if len(url) > MAX_URL_LENGTH or any(char.isspace() for char in url):
        return False
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


class LinkInput(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=MAX_URLS_PER_BATCH)
    topic: LinkTopic = LinkTopic.OTHER
    note: str | None = None

    @field_validator("urls", mode="before")
    @classmethod
    def _clean_urls(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        cleaned: list[str] = []
        invalid: list[str] = []
        for raw in value:
            url = str(raw).strip()
            if not url:
                continue
            if not _is_http_url(url):
                invalid.append(url)
            elif url not in cleaned:
                cleaned.append(url)
        if invalid:
            raise ValueError(
                "Link không hợp lệ (cần bắt đầu bằng http:// hoặc https://): "
                + ", ".join(invalid[:5])
            )
        return cleaned

    @field_validator("note", mode="before")
    @classmethod
    def _blank_note(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value


class SourceLink(BaseModel):
    id: int
    url: str
    topic: LinkTopic
    note: str | None
    status: LinkStatus
    added_at: dt.datetime


class AddResult(BaseModel):
    added: list[SourceLink]
    duplicates: list[str]
