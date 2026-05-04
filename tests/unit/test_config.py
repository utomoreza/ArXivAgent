from datetime import date
from typing import get_args

import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch

import src.config as config
from src.config import Settings, get_settings

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_REQUIRED = {
    "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/db",
    "ANTHROPIC_API_KEY": "sk-ant-test",
    "INCEPTION_DATE": "2026-01-01",
}


def _env_settings(monkeypatch: MonkeyPatch, **env_vars: str) -> Settings:
    """Create Settings from environment variables, exercising the full source pipeline.

    All values are strings (as they are in a real environment). Skips dotenv
    loading so the developer's .env file does not interfere.
    """
    for k, v in {**_REQUIRED, **env_vars}.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)


def _init_settings(**kwargs) -> Settings:
    """Create Settings via constructor injection.

    Use only for non-string type validation (int, float, etc.) that cannot be
    represented as environment variables.
    """
    return Settings(**{**_REQUIRED, **kwargs})


#### INCEPTION_DATE

def test_missing_inception_date_raises_validation_error(monkeypatch: MonkeyPatch):
    monkeypatch.delenv("INCEPTION_DATE", raising=False)
    for k, v in {k: v for k, v in _REQUIRED.items() if k != "INCEPTION_DATE"}.items():
        monkeypatch.setenv(k, v)
    with pytest.raises((ValidationError, Exception)):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "invalid_input",
    ["0000-13-32", "9999-00-00", "2026", "01-01-2026", "2026/01/01", "2026-13-32", "a"],
)
def test_inception_date_given_invalid_string(monkeypatch: MonkeyPatch, invalid_input: str):
    with pytest.raises(ValidationError) as exc_info:
        _env_settings(monkeypatch, INCEPTION_DATE=invalid_input)
    assert "INCEPTION_DATE" in [e["loc"][0] for e in exc_info.value.errors()], \
        f"Expected INCEPTION_DATE error for input {invalid_input!r}"


@pytest.mark.parametrize("invalid_input", [1, 1.0, 2026])
def test_inception_date_given_non_string(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _init_settings(INCEPTION_DATE=invalid_input)
    assert "INCEPTION_DATE" in [e["loc"][0] for e in exc_info.value.errors()], \
        f"Expected INCEPTION_DATE error for input {invalid_input!r}"


def test_inception_date_parsed_as_date_object(monkeypatch: MonkeyPatch):
    settings = _env_settings(monkeypatch, INCEPTION_DATE="2026-01-15")
    assert settings.INCEPTION_DATE == date(2026, 1, 15)


#### ANTHROPIC_API_KEY

def test_missing_anthropic_api_key_raises_validation_error(monkeypatch: MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for k, v in {k: v for k, v in _REQUIRED.items() if k != "ANTHROPIC_API_KEY"}.items():
        monkeypatch.setenv(k, v)
    with pytest.raises((ValidationError, Exception)):
        Settings(_env_file=None)


def test_anthropic_api_key_empty_string_rejected(monkeypatch: MonkeyPatch):
    with pytest.raises(ValidationError) as exc_info:
        _env_settings(monkeypatch, ANTHROPIC_API_KEY="")
    assert "ANTHROPIC_API_KEY" in [e["loc"][0] for e in exc_info.value.errors()]


@pytest.mark.parametrize("invalid_input", [1, 1.0])
def test_anthropic_api_key_given_non_string(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _init_settings(ANTHROPIC_API_KEY=invalid_input)
    assert "ANTHROPIC_API_KEY" in [e["loc"][0] for e in exc_info.value.errors()], \
        f"Expected ANTHROPIC_API_KEY error for input {invalid_input!r}"


#### DATABASE_URL

def test_missing_database_url_raises_validation_error(monkeypatch: MonkeyPatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for k, v in {k: v for k, v in _REQUIRED.items() if k != "DATABASE_URL"}.items():
        monkeypatch.setenv(k, v)
    with pytest.raises((ValidationError, Exception)):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "valid_input",
    [
        "postgresql+asyncpg://user:pass@localhost/db",
        "postgresql+asyncpg://user:pass@www.example.com/db",
        "postgresql+asyncpg://user:pass@www.example.com:1234/db",
        "postgresql+asyncpg://user:xxx123@localhost/db",
        "postgresql+asyncpg://myuser123:1234@localhost:1111/db",
    ],
)
def test_database_url_given_valid_input(monkeypatch: MonkeyPatch, valid_input: str):
    settings = _env_settings(monkeypatch, DATABASE_URL=valid_input)
    assert settings.DATABASE_URL == valid_input


@pytest.mark.parametrize(
    "invalid_input",
    [
        "",
        "postgresql://user:pass@localhost/db",
        "sqlite://user:pass@www.example.com/db",
        "postgresql+asyncpg://user:pass#$()<>@www.example.com:1234/db",
        "postgresql+asyncpg://fqef&*^.,:xxx123@localhost/db",
    ],
)
def test_database_url_given_invalid_string(monkeypatch: MonkeyPatch, invalid_input: str):
    with pytest.raises(ValidationError) as exc_info:
        _env_settings(monkeypatch, DATABASE_URL=invalid_input)
    assert "DATABASE_URL" in [e["loc"][0] for e in exc_info.value.errors()], \
        f"Expected DATABASE_URL error for input {invalid_input!r}"


@pytest.mark.parametrize("invalid_input", [1, 1.0])
def test_database_url_given_non_string(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _init_settings(DATABASE_URL=invalid_input)
    assert "DATABASE_URL" in [e["loc"][0] for e in exc_info.value.errors()], \
        f"Expected DATABASE_URL error for input {invalid_input!r}"


#### RAG_WINDOW_DAYS

def test_rag_window_days_fallback_to_default_if_ungiven(monkeypatch: MonkeyPatch):
    settings = _env_settings(monkeypatch)
    assert settings.RAG_WINDOW_DAYS == config._DEFAULT_RAG_WINDOW_DAYS


@pytest.mark.parametrize("valid_input", [0, 1, 30])
def test_rag_window_days_non_negative_int(valid_input):
    settings = _init_settings(RAG_WINDOW_DAYS=valid_input)
    assert settings.RAG_WINDOW_DAYS == valid_input

@pytest.mark.parametrize("valid_input", ["0", "1", "30"])
def test_rag_window_days_valid_string(monkeypatch: MonkeyPatch, valid_input: str):
    settings = _env_settings(monkeypatch, RAG_WINDOW_DAYS=valid_input)
    assert settings.RAG_WINDOW_DAYS == int(valid_input)


@pytest.mark.parametrize("invalid_input", ["-1", "-90", "a", ""])
def test_rag_window_days_invalid_string(monkeypatch: MonkeyPatch, invalid_input: str):
    with pytest.raises(ValidationError) as exc_info:
        _env_settings(monkeypatch, RAG_WINDOW_DAYS=invalid_input)
    assert "RAG_WINDOW_DAYS" in [e["loc"][0] for e in exc_info.value.errors()], \
        f"Expected RAG_WINDOW_DAYS error for input {invalid_input!r}"



@pytest.mark.parametrize("invalid_input", [-1, 1.0, 90.2])
def test_rag_window_days_invalid_non_string(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _init_settings(RAG_WINDOW_DAYS=invalid_input)
    assert "RAG_WINDOW_DAYS" in [e["loc"][0] for e in exc_info.value.errors()], \
        f"Expected RAG_WINDOW_DAYS error for input {invalid_input!r}"


#### TOPIC_LIST

def test_topic_list_fallback_to_default_if_ungiven(monkeypatch: MonkeyPatch):
    settings = _env_settings(monkeypatch)
    assert isinstance(settings.TOPIC_LIST, list)
    assert sorted(settings.TOPIC_LIST) == sorted(config._DEFAULT_TOPIC_LIST.split(","))


def test_topic_list_parses_as_list_from_comma_separated_string(monkeypatch: MonkeyPatch):
    settings = _env_settings(
        monkeypatch, TOPIC_LIST="Large Language Models,Computer Vision,Robotics"
    )
    assert isinstance(settings.TOPIC_LIST, list)
    assert settings.TOPIC_LIST == ["Large Language Models", "Computer Vision", "Robotics"]


def test_topic_list_given_one_topic_only(monkeypatch: MonkeyPatch):
    settings = _env_settings(monkeypatch, TOPIC_LIST="Robotics")
    assert settings.TOPIC_LIST == ["Robotics"]


def test_topic_list_strips_whitespace(monkeypatch: MonkeyPatch):
    settings = _env_settings(
        monkeypatch, TOPIC_LIST="Large Language Models, Computer Vision , Robotics "
    )
    assert settings.TOPIC_LIST == ["Large Language Models", "Computer Vision", "Robotics"]


def test_topic_list_each_topic_in_title_style(monkeypatch: MonkeyPatch):
    settings = _env_settings(
        monkeypatch, TOPIC_LIST=(
            "large Language moDels,cOmputer Vision,ROBOTICS,AI engineering,ML system"
        )
    )
    assert settings.TOPIC_LIST == [
        "Large Language Models", "Computer Vision", "Robotics",
        "AI Engineering", "ML System",
    ]


def test_topic_list_empty_string_rejected(monkeypatch: MonkeyPatch):
    with pytest.raises(ValidationError) as exc_info:
        _env_settings(monkeypatch, TOPIC_LIST="")
    assert "TOPIC_LIST" in [e["loc"][0] for e in exc_info.value.errors()]


def test_topic_list_all_commas_rejected(monkeypatch: MonkeyPatch):
    # Non-empty string that yields no topics after splitting — hits the `not topics` branch.
    with pytest.raises(ValidationError) as exc_info:
        _env_settings(monkeypatch, TOPIC_LIST=",,")
    assert "TOPIC_LIST" in [e["loc"][0] for e in exc_info.value.errors()]


@pytest.mark.parametrize("invalid_input", [1, 0.2])
def test_topic_list_given_non_string(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _init_settings(TOPIC_LIST=invalid_input)
    assert "TOPIC_LIST" in [e["loc"][0] for e in exc_info.value.errors()], \
        f"Expected TOPIC_LIST error for input {invalid_input!r}"


#### ARXIV_CATEGORIES

def test_arxiv_categories_fallback_to_default_if_ungiven(monkeypatch: MonkeyPatch):
    settings = _env_settings(monkeypatch)
    assert isinstance(settings.ARXIV_CATEGORIES, list)
    assert sorted(settings.ARXIV_CATEGORIES) == sorted(config._DEFAULT_ARXIV_CATEGORIES.split(","))


def test_arxiv_categories_can_be_overridden(monkeypatch: MonkeyPatch):
    settings = _env_settings(monkeypatch, ARXIV_CATEGORIES="cs.LG,cs.CV")
    assert isinstance(settings.ARXIV_CATEGORIES, list)
    assert settings.ARXIV_CATEGORIES == ["cs.LG", "cs.CV"]


def test_arxiv_categories_given_one_category_only(monkeypatch: MonkeyPatch):
    settings = _env_settings(monkeypatch, ARXIV_CATEGORIES="cs.LG")
    assert settings.ARXIV_CATEGORIES == ["cs.LG"]


def test_arxiv_categories_strips_whitespace(monkeypatch: MonkeyPatch):
    settings = _env_settings(monkeypatch, ARXIV_CATEGORIES="cs.LG, cs.CV , cs.AR")
    assert settings.ARXIV_CATEGORIES == ["cs.LG", "cs.CV", "cs.AR"]


@pytest.mark.parametrize(
    "invalid_input",
    [
        "AbC.AB,AB.AB", "abc.ab,Abb.Baa", "aa.bb,aa.11", "11.aa,aa.BB",
        "11.22,33.44", "1", "",
    ],
)
def test_arxiv_categories_given_invalid_string(monkeypatch: MonkeyPatch, invalid_input: str):
    with pytest.raises(ValidationError) as exc_info:
        _env_settings(monkeypatch, ARXIV_CATEGORIES=invalid_input)
    assert "ARXIV_CATEGORIES" in [e["loc"][0] for e in exc_info.value.errors()], \
        f"Expected ARXIV_CATEGORIES error for input {invalid_input!r}"


@pytest.mark.parametrize("invalid_input", [1, 1.0])
def test_arxiv_categories_given_non_string(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _init_settings(ARXIV_CATEGORIES=invalid_input)
    assert "ARXIV_CATEGORIES" in [e["loc"][0] for e in exc_info.value.errors()], \
        f"Expected ARXIV_CATEGORIES error for input {invalid_input!r}"


def test_arxiv_categories_all_commas_rejected(monkeypatch: MonkeyPatch):
    # Non-empty string that yields no categories after splitting — hits the `not cats` branch.
    with pytest.raises(ValidationError) as exc_info:
        _env_settings(monkeypatch, ARXIV_CATEGORIES=",,")
    assert "ARXIV_CATEGORIES" in [e["loc"][0] for e in exc_info.value.errors()]


#### DAILY_SCHEDULER_TIME

def test_daily_scheduler_time_default(monkeypatch: MonkeyPatch):
    settings = _env_settings(monkeypatch)
    assert settings.DAILY_SCHEDULER_TIME == config._DEFAULT_DAILY_SCHEDULER_TIME


@pytest.mark.parametrize("invalid_input", [""])
def test_daily_scheduler_time_empty_string_rejected(monkeypatch: MonkeyPatch, invalid_input: str):
    with pytest.raises(ValidationError) as exc_info:
        _env_settings(monkeypatch, DAILY_SCHEDULER_TIME=invalid_input)
    assert "DAILY_SCHEDULER_TIME" in [e["loc"][0] for e in exc_info.value.errors()]


@pytest.mark.parametrize("invalid_input", [1, 0.2])
def test_daily_scheduler_time_given_non_string(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _init_settings(DAILY_SCHEDULER_TIME=invalid_input)
    assert "DAILY_SCHEDULER_TIME" in [e["loc"][0] for e in exc_info.value.errors()], \
        f"Expected DAILY_SCHEDULER_TIME error for input {invalid_input!r}"


@pytest.mark.parametrize(
    "invalid_input",
    ["30 20 * * 0 *", "30 20 * *", "61 25 32 13 7"],
)
def test_daily_scheduler_time_given_incorrect_format(monkeypatch: MonkeyPatch, invalid_input: str):
    with pytest.raises(ValidationError) as exc_info:
        _env_settings(monkeypatch, DAILY_SCHEDULER_TIME=invalid_input)
    assert "DAILY_SCHEDULER_TIME" in [e["loc"][0] for e in exc_info.value.errors()], \
        f"Expected DAILY_SCHEDULER_TIME error for input {invalid_input!r}"


def test_daily_scheduler_time_given_non_numeric_token(monkeypatch: MonkeyPatch):
    # Hits the `except ValueError` branch inside _parse_cron_string for non-integer tokens.
    with pytest.raises(ValidationError) as exc_info:
        _env_settings(monkeypatch, DAILY_SCHEDULER_TIME="abc 20 * * 0")
    assert "DAILY_SCHEDULER_TIME" in [e["loc"][0] for e in exc_info.value.errors()]


#### WEEKLY_SCHEDULER_TIME

def test_weekly_scheduler_time_default(monkeypatch: MonkeyPatch):
    settings = _env_settings(monkeypatch)
    assert settings.WEEKLY_SCHEDULER_TIME == config._DEFAULT_WEEKLY_SCHEDULER_TIME


@pytest.mark.parametrize("invalid_input", [""])
def test_weekly_scheduler_time_empty_string_rejected(monkeypatch: MonkeyPatch, invalid_input: str):
    with pytest.raises(ValidationError) as exc_info:
        _env_settings(monkeypatch, WEEKLY_SCHEDULER_TIME=invalid_input)
    assert "WEEKLY_SCHEDULER_TIME" in [e["loc"][0] for e in exc_info.value.errors()]


@pytest.mark.parametrize("invalid_input", [1, 0.2])
def test_weekly_scheduler_time_given_non_string(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _init_settings(WEEKLY_SCHEDULER_TIME=invalid_input)
    assert "WEEKLY_SCHEDULER_TIME" in [e["loc"][0] for e in exc_info.value.errors()], \
        f"Expected WEEKLY_SCHEDULER_TIME error for input {invalid_input!r}"


@pytest.mark.parametrize(
    "invalid_input",
    ["30 20 * * 0 *", "30 20 * *", "61 25 32 13 7"],
)
def test_weekly_scheduler_time_given_incorrect_format(monkeypatch: MonkeyPatch, invalid_input: str):
    with pytest.raises(ValidationError) as exc_info:
        _env_settings(monkeypatch, WEEKLY_SCHEDULER_TIME=invalid_input)
    assert "WEEKLY_SCHEDULER_TIME" in [e["loc"][0] for e in exc_info.value.errors()], \
        f"Expected WEEKLY_SCHEDULER_TIME error for input {invalid_input!r}"


#### LOG_LEVEL

def test_log_level_defaults_to_info(monkeypatch: MonkeyPatch):
    settings = _env_settings(monkeypatch)
    assert settings.LOG_LEVEL == config._DEFAULT_LOG_LEVEL


def test_log_level_all_valid_literal_options_accepted(monkeypatch: MonkeyPatch):
    for option in get_args(config.LogLevel):
        settings = _env_settings(monkeypatch, LOG_LEVEL=option)
        assert settings.LOG_LEVEL == option


@pytest.mark.parametrize("invalid_input", ["a", "1", ""])
def test_log_level_invalid_string_rejected(monkeypatch: MonkeyPatch, invalid_input: str):
    with pytest.raises(ValidationError) as exc_info:
        _env_settings(monkeypatch, LOG_LEVEL=invalid_input)
    assert "LOG_LEVEL" in [e["loc"][0] for e in exc_info.value.errors()], \
        f"Expected LOG_LEVEL error for input {invalid_input!r}"


@pytest.mark.parametrize("invalid_input", [1, 1.0])
def test_log_level_given_non_string(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _init_settings(LOG_LEVEL=invalid_input)
    assert "LOG_LEVEL" in [e["loc"][0] for e in exc_info.value.errors()], \
        f"Expected LOG_LEVEL error for input {invalid_input!r}"


#### LARGE_CLAUDE_LLM / SMALL_CLAUDE_LLM

def test_large_claude_llm_defaults_to_sonnet(monkeypatch: MonkeyPatch):
    settings = _env_settings(monkeypatch)
    assert settings.LARGE_CLAUDE_LLM == config._DEFAULT_LARGE_CLAUDE_LLM


def test_small_claude_llm_defaults_to_haiku(monkeypatch: MonkeyPatch):
    settings = _env_settings(monkeypatch)
    assert settings.SMALL_CLAUDE_LLM == config._DEFAULT_SMALL_CLAUDE_LLM


def test_large_claude_llm_can_be_overridden(monkeypatch: MonkeyPatch):
    settings = _env_settings(monkeypatch, LARGE_CLAUDE_LLM="claude-opus-4-7")
    assert settings.LARGE_CLAUDE_LLM == "claude-opus-4-7"


def test_small_claude_llm_can_be_overridden(monkeypatch: MonkeyPatch):
    settings = _env_settings(monkeypatch, SMALL_CLAUDE_LLM="claude-haiku-4-5-20251001")
    assert settings.SMALL_CLAUDE_LLM == "claude-haiku-4-5-20251001"


#### get_settings()

def test_get_settings_returns_settings_instance(monkeypatch: MonkeyPatch):
    for k, v in _REQUIRED.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert isinstance(settings, Settings)
    finally:
        get_settings.cache_clear()
