import re
from datetime import date
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    SettingsConfigDict,
)
from pydantic_settings.exceptions import SettingsError

_DEFAULT_TOPIC_LIST = (
    "Large Language Models,Computer Vision,Reinforcement Learning,"
    "Multimodal AI,Robotics,ML Theory & Optimization"
)
_DEFAULT_ARXIV_CATEGORIES = "cs.LG,cs.CV,cs.CL,cs.AI,cs.RO,stat.ML"
_DEFAULT_RAG_WINDOW_DAYS = 90
_DEFAULT_DAILY_SCHEDULER_TIME = "30 20 * * 0,1,2,3,4"
_DEFAULT_WEEKLY_SCHEDULER_TIME = "0 1 * * 5"
_DEFAULT_LOG_LEVEL = "INFO"

_ARXIV_CAT_RE = re.compile(r"^[a-z]{2,6}\.[A-Z]{2,3}$")
# postgresql+asyncpg://alphanumeric:alphanumeric@host[:port]/dbname
_DATABASE_URL_RE = re.compile(
    r"^postgresql\+asyncpg://[a-zA-Z0-9]+:[a-zA-Z0-9]+@[a-zA-Z0-9.\-]+(:\d+)?/[a-zA-Z0-9_]+$"
)

LogLevel = Literal["DEBUG", "INFO", "ERROR"]


def _parse_inception_date(v: object) -> object:
    if not isinstance(v, str):
        raise ValueError("INCEPTION_DATE must be a string in YYYY-MM-DD format")
    return v


def _parse_database_url(v: object) -> str:
    if not isinstance(v, str):
        raise ValueError("DATABASE_URL must be a string")
    if not v.strip():
        raise ValueError("DATABASE_URL must not be empty")
    if not _DATABASE_URL_RE.match(v):
        raise ValueError(
            "DATABASE_URL must be in the form "
            "postgresql+asyncpg://user:pass@host[:port]/dbname "
            "where user and password are alphanumeric only"
        )
    return v


def _parse_anthropic_api_key(v: object) -> str:
    if not isinstance(v, str):
        raise ValueError("ANTHROPIC_API_KEY must be a string")
    if not v.strip():
        raise ValueError("ANTHROPIC_API_KEY must not be empty")
    return v


def _parse_rag_window_days(v: object) -> int:
    if isinstance(v, float):
        raise ValueError("RAG_WINDOW_DAYS must be an integer, not a float")
    if isinstance(v, str):
        stripped = v.strip()
        if not stripped:
            raise ValueError("RAG_WINDOW_DAYS must not be empty")
        try:
            return int(stripped)
        except ValueError:
            raise ValueError(
                f"RAG_WINDOW_DAYS must be a valid integer string, got {v!r}"
            )
    return v


def _title_word(word: str) -> str:
    """Capitalize a single word, preserving short all-caps acronyms (AI, ML, CV...)."""
    if word.isalpha() and len(word) <= 3 and word.isupper():
        return word
    return word.capitalize()


def _smart_title(topic: str) -> str:
    return " ".join(_title_word(w) for w in topic.split(" "))


def _parse_topic_list(v: object) -> list[str]:
    if not isinstance(v, str):
        raise ValueError("TOPIC_LIST must be a comma-separated string")
    if not v.strip():
        raise ValueError("TOPIC_LIST must not be empty")
    topics = [_smart_title(s.strip()) for s in v.split(",") if s.strip()]
    if not topics:
        raise ValueError("TOPIC_LIST must contain at least one topic")
    return topics


def _parse_arxiv_categories(v: object) -> list[str]:
    if not isinstance(v, str):
        raise ValueError("ARXIV_CATEGORIES must be a comma-separated string")
    if not v.strip():
        raise ValueError("ARXIV_CATEGORIES must not be empty")
    cats = [s.strip() for s in v.split(",") if s.strip()]
    if not cats:
        raise ValueError("ARXIV_CATEGORIES must contain at least one category")
    for cat in cats:
        if not _ARXIV_CAT_RE.match(cat):
            raise ValueError(
                f"Invalid arXiv category {cat!r}. "
                "Expected: <2-6 lowercase>.<2-3 UPPERCASE>, "
                "e.g. cs.LG, stat.ML"
            )
    return cats


def _parse_cron_string(field_name: str):
    def validator(v: object) -> str:
        if not isinstance(v, str):
            raise ValueError(f"{field_name} must be a string")
        if not v.strip():
            raise ValueError(f"{field_name} must not be empty")
        parts = v.split()
        if len(parts) != 5:
            raise ValueError(
                f"{field_name} must have exactly 5 cron fields "
                f"(minute hour day month weekday), got {len(parts)}"
            )
        ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
        names = ["minute", "hour", "day_of_month", "month", "day_of_week"]
        for part, (lo, hi), name in zip(parts, ranges, names):
            if part == "*":
                continue
            for token in part.split(","):
                try:
                    n = int(token)
                except ValueError:
                    raise ValueError(
                        f"Invalid cron {name} token {token!r} in {field_name}"
                    )
                if not (lo <= n <= hi):
                    raise ValueError(
                        f"Cron {name} value {n} out of range [{lo},{hi}]"
                        f" in {field_name}"
                    )
        return v

    return validator


def _parse_log_level(v: object) -> str:
    if not isinstance(v, str):
        raise ValueError("LOG_LEVEL must be a string")
    if not v.strip():
        raise ValueError("LOG_LEVEL must not be empty")
    return v


class _CommaSeparatedEnvSource(EnvSettingsSource):
    """Env source that returns the raw string when JSON decoding fails for list
    fields, allowing BeforeValidator to handle comma-separated values instead."""

    def prepare_field_value(self, field_name, field, value, value_is_complex):
        try:
            return super().prepare_field_value(
                field_name, field, value, value_is_complex
            )
        except (SettingsError, ValueError):
            return value


class _CommaSeparatedDotEnvSource(DotEnvSettingsSource):
    """Dotenv source with the same CSV fallback as _CommaSeparatedEnvSource."""

    def prepare_field_value(self, field_name, field, value, value_is_complex):
        try:
            return super().prepare_field_value(
                field_name, field, value, value_is_complex
            )
        except (SettingsError, ValueError):
            return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    INCEPTION_DATE: Annotated[date, BeforeValidator(_parse_inception_date)]
    DATABASE_URL: Annotated[str, BeforeValidator(_parse_database_url)]
    ANTHROPIC_API_KEY: Annotated[str, BeforeValidator(_parse_anthropic_api_key)]

    RAG_WINDOW_DAYS: Annotated[
        int, BeforeValidator(_parse_rag_window_days), Field(ge=0)
    ] = _DEFAULT_RAG_WINDOW_DAYS
    ARXIV_CATEGORIES: Annotated[
        list[str], BeforeValidator(_parse_arxiv_categories)
    ] = _DEFAULT_ARXIV_CATEGORIES  # type: ignore[assignment]
    TOPIC_LIST: Annotated[
        list[str], BeforeValidator(_parse_topic_list)
    ] = _DEFAULT_TOPIC_LIST  # type: ignore[assignment]
    DAILY_SCHEDULER_TIME: Annotated[
        str, BeforeValidator(_parse_cron_string("DAILY_SCHEDULER_TIME"))
    ] = _DEFAULT_DAILY_SCHEDULER_TIME
    WEEKLY_SCHEDULER_TIME: Annotated[
        str, BeforeValidator(_parse_cron_string("WEEKLY_SCHEDULER_TIME"))
    ] = _DEFAULT_WEEKLY_SCHEDULER_TIME
    LOG_LEVEL: Annotated[
        LogLevel, BeforeValidator(_parse_log_level)
    ] = _DEFAULT_LOG_LEVEL

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """Replace env/dotenv sources with CSV-fallback variants.

        Mirrors env_file and encoding from dotenv_settings so that _env_file=None
        passed to Settings() in tests is correctly propagated.
        """
        return (
            init_settings,
            _CommaSeparatedEnvSource(settings_cls),
            _CommaSeparatedDotEnvSource(
                settings_cls,
                env_file=dotenv_settings.env_file,
                env_file_encoding=dotenv_settings.env_file_encoding,
            ),
            file_secret_settings,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
