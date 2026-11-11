from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class Severity(StrEnum):
    ERROR = "error"  # plan không được trả cho user
    WARNING = "warning"  # plan dùng được nhưng phải hiển thị cảnh báo


class IssueCode(StrEnum):
    UNKNOWN_PLACE = "unknown_place"
    DUPLICATE_PLACE = "duplicate_place"
    DAY_COUNT_MISMATCH = "day_count_mismatch"
    DATE_MISMATCH = "date_mismatch"
    STOP_TIME_ORDER = "stop_time_order"
    OUTSIDE_DAY_WINDOW = "outside_day_window"
    STOP_OVERLAP = "stop_overlap"
    TRAVEL_TIME_INSUFFICIENT = "travel_time_insufficient"
    CLOSED_DURING_VISIT = "closed_during_visit"
    OPENING_HOURS_UNKNOWN = "opening_hours_unknown"
    OVERLOADED_DAY = "overloaded_day"
    MISSING_MEAL = "missing_meal"


class Issue(BaseModel):
    code: IssueCode
    severity: Severity
    message: str
    day_index: int | None = None
    stop_index: int | None = None
    place_id: str | None = None


class ValidationReport(BaseModel):
    issues: list[Issue]
    estimated_legs: int = 0

    @property
    def is_valid(self) -> bool:
        return not self.errors()

    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity is Severity.ERROR]
