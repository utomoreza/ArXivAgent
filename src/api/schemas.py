from enum import StrEnum
from typing import Any
from datetime import date, datetime
from pydantic import BaseModel, Field, ConfigDict, model_validator

from src.db import constants


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ANNOUNCEMENT_DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu"]


class Type(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


class Status(StrEnum):
    OK = "ok"
    SKIPPED = "skipped"
    FETCH_FAILED = "fetch_failure"
    NO_ANNOUNCE = "no_announcement"
    NOT_FOUND = "not_found"
    NOT_AVAILABLE = "not_available"
    PENDING = "pending"
    REJECTED = "rejected"
    EMPTY = "empty"
    ERROR = "error"


class Error(StrEnum):
    VALIDATION = "validation_error"
    VALUE = "value_error"


class Reason:
    NO_PAPERS_SKIP = "No new papers were published on this date."
    FETCH_FAILURE_SKIP = "Data retrieval from arXiv failed after 3 attempts on this date — no digest available."
    NO_ANNOUNCEMENT = "arXiv does not publish on Fridays or Saturdays."
    FUTURE_DATE = "Date is in the future."
    BEFORE_INCEPTION_DATE = "No records available before system inception on {}."
    PENDING = "Week still ongoing — weekly digest not yet generated."
    NOT_AVAILABLE_1 = "No {} found for {} (race condition or unprocessed date)"
    NOT_AVAILABLE_2 = "{} for {} is published but DailyDigest row is missing"


"DateRecord for %s is published but DailyDigest row is missing"

MAP_STATUS_TO_REASON: dict[str, str] = {
    constants.DATE_STATUS_NO_PAPERS_SKIP: "No new papers were published on this date.",
    constants.DATE_STATUS_FETCH_FAILURE_SKIP: "Data retrieval from arXiv failed after 3 attempts on this date — no digest available.",
    constants.DATE_STATUS_NO_ANNOUNCEMENT: "arXiv does not publish on Fridays or Saturdays.",
    "future_date": "Date is in the future.",
    "before_inception_date": "No records available before system inception on {}.",
    Status.PENDING.value: "Week still ongoing — weekly digest not yet generated.",
    Status.NOT_AVAILABLE.value: "No {} found for {} (race condition or unprocessed date)",
}
MAP_ERROR_MESSAGE = {
    Type.DAILY.value: "",
    Type.WEEKLY.value: "week_start_date must be a Sunday (arXiv announcement week starts on Sunday).",
}


class BaseDigestClass(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)


# ---------------------------------------------------------------------------
# Data Schemas
# ---------------------------------------------------------------------------


class TopicSection(BaseDigestClass):
    name: str
    paper_count: int = Field(..., ge=1)
    body: str = Field(..., description="Rendered Markdown for this topic's papers")


class CoverageNote(BaseDigestClass):
    announcement_days: list[str] = Field(..., examples=["Sun", "Mon", "Tue", "Wed", "Thu"])
    days_with_content: list[date]
    no_papers_skips: list[date]
    fetch_failure_skips: list[date]


class WeeklySections(BaseDigestClass):
    benchmark_comparisons: str = Field(..., description="Rendered Markdown — side-by-side benchmark comparisons")
    trend_synthesis: str = Field(..., description="Rendered Markdown — per-topic weekly momentum")
    cross_paper_analysis: str = Field(..., description="Rendered Markdown — complementary/contradictory findings")


class DailyDigestData(BaseDigestClass):
    type: Type = Type.DAILY
    date: date
    generated_at: datetime
    paper_count: int = Field(..., ge=0)
    groundbreaking_count: int = Field(..., ge=0)
    topics: list[TopicSection]

    @model_validator(mode="before")
    @classmethod
    def map_topic_sections(cls, data: Any):
        if hasattr(data, "topic_sections"):
            data = {
                **{col.key: getattr(data, col.key) for col in data.__table__.columns},
                "topics": sorted(data.topic_sections, key=lambda t: t.paper_count, reverse=True),
                "type": Type.DAILY,
            }
        return data


class WeeklyDigestData(BaseDigestClass):
    type: Type = Type.WEEKLY
    week_start: date = Field(..., description="Sunday of the announcement week")
    week_end: date = Field(..., description="Thursday of the announcement week")
    generated_at: datetime
    paper_count: int = Field(..., ge=0)
    groundbreaking_count: int = Field(..., ge=0)
    coverage_note: CoverageNote
    sections: WeeklySections

    @model_validator(mode="before")
    @classmethod
    def from_orm_object(cls, data: Any):
        if hasattr(data, "days_with_content"):
            return {
                **{col.key: getattr(data, col.key) for col in data.__table__.columns},
                "type": Type.WEEKLY,
                "coverage_note": CoverageNote(
                    announcement_days=_ANNOUNCEMENT_DAYS,
                    days_with_content=data.days_with_content,
                    no_papers_skips=data.no_papers_skips,
                    fetch_failure_skips=data.fetch_failure_skips,
                ),
                "sections": WeeklySections(
                    benchmark_comparisons=data.benchmark_comparisons,
                    trend_synthesis=data.trend_synthesis,
                    cross_paper_analysis=data.cross_paper_analysis,
                ),
            }
        return data


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------


class DailyDigestResponse(BaseDigestClass):
    status: Status
    data: DailyDigestData | None = None
    reason: str | None = None


class WeeklyDigestResponse(BaseDigestClass):
    status: Status
    data: WeeklyDigestData | None = None
    reason: str | None = None


class ErrorResponse(BaseDigestClass):
    error: Error
    message: str
