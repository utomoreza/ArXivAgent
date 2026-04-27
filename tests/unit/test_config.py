from datetime import date
from typing import get_args

import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch

import src.config as config
from src.config import Settings


def _minimal_settings(**kwargs) -> Settings:
    """Create Settings with minimum required fields, bypassing env var lookup."""
    defaults = dict(
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db",
        ANTHROPIC_API_KEY="sk-ant-test",
        INCEPTION_DATE="2026-01-01",
    )
    defaults.update(kwargs)
    return Settings(**defaults)

#### INCEPTION_DATE

def test_missing_inception_date_raises_validation_error(monkeypatch: MonkeyPatch):
    monkeypatch.delenv("INCEPTION_DATE", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db",
            ANTHROPIC_API_KEY="sk-ant-test",
        )
    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "INCEPTION_DATE" in field_names


@pytest.mark.parametrize(
    "invalid_input",
    [
        "0000-13-32", "9999-00-00", "2026", "01-01-2026", "2026/01/01",
        "2026-13-32", "1.0", "", "a", 1, 1.0, 2026,
    ],
)
def test_inception_date_given_invalid_input(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _minimal_settings(INCEPTION_DATE=invalid_input)
    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "INCEPTION_DATE" in field_names, \
        f"Uncaught error when given invalid input '{invalid_input}' of type '{type(invalid_input)}'"


def test_inception_date_parsed_as_date_object():
    settings = _minimal_settings(INCEPTION_DATE="2026-01-15")
    assert settings.INCEPTION_DATE == date(2026, 1, 15)

#### ANTHROPIC_API_KEY

def test_missing_anthropic_api_key_raises_validation_error(monkeypatch: MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db",
            INCEPTION_DATE="2026-01-01",
        )
    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "ANTHROPIC_API_KEY" in field_names


@pytest.mark.parametrize("invalid_input", [1, 1.0, ""])
def test_anthropic_api_key_given_invalid_input(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _minimal_settings(ANTHROPIC_API_KEY=invalid_input)
    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "ANTHROPIC_API_KEY" in field_names, \
        f"Uncaught error when given invalid input '{invalid_input}' of type '{type(invalid_input)}'"

#### DATABASE_URL

def test_missing_database_url_raises_validation_error(monkeypatch: MonkeyPatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            INCEPTION_DATE="2026-01-01",
            ANTHROPIC_API_KEY="sk-ant-test",
        )
    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "DATABASE_URL" in field_names


# we expect both user & pass only use alphanumeric strings for ease of encoding
@pytest.mark.parametrize(
    "valid_input",
    [
        "postgresql+asyncpg://user:pass@localhost/db",
        "postgresql+asyncpg://user:pass@www.example.com/db",
        "postgresql+asyncpg://user:pass@www.example.com:1234/db",
        "postgresql+asyncpg://user:xxx123@localhost/db",
        "postgresql+asyncpg://myuser123:1234@localhost:1111/db",
    ]
)
def test_database_url_given_valid_input(valid_input):
    settings = _minimal_settings(DATABASE_URL=valid_input)
    assert settings.DATABASE_URL == valid_input


@pytest.mark.parametrize(
    "invalid_input",
    [
        "", "1", 1, 1.0,
        "postgresql://user:pass@localhost/db",
        "sqlite://user:pass@www.example.com/db",
        "postgresql+asyncpg://user:pass#$()<>@www.example.com:1234/db",
        "postgresql+asyncpg://fqef&*^.,:xxx123@localhost/db",
    ]
)
def test_database_url_given_invalid_input(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _minimal_settings(DATABASE_URL=invalid_input)
    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "DATABASE_URL" in field_names, \
        f"Uncaught error when given invalid input '{invalid_input}' of type '{type(invalid_input)}'"

#### RAG_WINDOW_DAYS

def test_rag_window_days_fallack_to_default_if_ungiven():
    settings = _minimal_settings()
    assert settings.RAG_WINDOW_DAYS == config._DEFAULT_RAG_WINDOW_DAYS


@pytest.mark.parametrize("valid_input", [0, 1, 30])
def test_rag_window_days_non_negative_valid_input(valid_input):
    settings = _minimal_settings(RAG_WINDOW_DAYS=valid_input)
    assert settings.RAG_WINDOW_DAYS == valid_input


@pytest.mark.parametrize("valid_input", ["0", "1", "30"])
def test_rag_window_days_non_negative_str_valid_input(valid_input):
    settings = _minimal_settings(RAG_WINDOW_DAYS=valid_input)
    assert settings.RAG_WINDOW_DAYS == int(valid_input)


@pytest.mark.parametrize("invalid_input", [-1, -0.1, -90])
def test_rag_window_days_negative_invalid_input(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _minimal_settings(RAG_WINDOW_DAYS=invalid_input)
    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "RAG_WINDOW_DAYS" in field_names, \
        f"Uncaught error when given invalid input '{invalid_input}' of type '{type(invalid_input)}'"


@pytest.mark.parametrize("invalid_input", ["-1", "-0.1", "-90"])
def test_rag_window_days_negative_str_invalid_input(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _minimal_settings(RAG_WINDOW_DAYS=invalid_input)
    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "RAG_WINDOW_DAYS" in field_names, \
        f"Uncaught error when given invalid input '{invalid_input}' of type '{type(invalid_input)}'"


@pytest.mark.parametrize("invalid_input", [1.0, 90.2, "", "a"])
def test_rag_window_days_given_invalid_input(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _minimal_settings(RAG_WINDOW_DAYS=invalid_input)
    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "RAG_WINDOW_DAYS" in field_names, \
        f"Uncaught error when given invalid input '{invalid_input}' of type '{type(invalid_input)}'"

#### TOPIC_LIST

def test_topic_list_fallback_to_default_if_ungiven():
    settings = _minimal_settings()
    assert isinstance(settings.TOPIC_LIST, list)
    assert sorted(settings.TOPIC_LIST) == sorted(config._DEFAULT_TOPIC_LIST.split(","))


@pytest.mark.parametrize("invalid_input", [1, 0.2, ""])
def test_topic_list_given_invalid_input(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _minimal_settings(TOPIC_LIST=invalid_input)
    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "TOPIC_LIST" in field_names, \
        f"Uncaught error when given invalid input '{invalid_input}' of type '{type(invalid_input)}'"


def test_topic_list_parses_as_list_from_comma_separated_string():
    settings = _minimal_settings(
        TOPIC_LIST="Large Language Models,Computer Vision,Robotics"
    )
    assert isinstance(settings.TOPIC_LIST, list)
    assert len(settings.TOPIC_LIST) == 3
    assert settings.TOPIC_LIST[0] == "Large Language Models"
    assert settings.TOPIC_LIST[1] == "Computer Vision"
    assert settings.TOPIC_LIST[2] == "Robotics"


def test_topic_list_given_one_topic_only():
    settings = _minimal_settings(TOPIC_LIST="Robotics")
    assert settings.TOPIC_LIST == ["Robotics"]


def test_topic_list_strips_whitespace():
    settings = _minimal_settings(
        TOPIC_LIST="Large Language Models, Computer Vision , Robotics "
    )
    assert settings.TOPIC_LIST == ["Large Language Models", "Computer Vision", "Robotics"]


def test_topic_list_each_topic_in_title_style():
    settings = _minimal_settings(
        TOPIC_LIST="large Language moDels,cOmputer Vision,ROBOTICS"
    )
    assert settings.TOPIC_LIST == ["Large Language Models", "Computer Vision", "Robotics"]

#### ARXIV_CATEGORIES

def test_arxiv_categories_fallback_to_default_if_ungiven():
    settings = _minimal_settings()
    assert isinstance(settings.ARXIV_CATEGORIES, list)
    assert sorted(settings.ARXIV_CATEGORIES) == sorted(config._DEFAULT_ARXIV_CATEGORIES.split(","))


def test_arxiv_categories_can_be_overridden():
    settings = _minimal_settings(ARXIV_CATEGORIES="cs.LG,cs.CV")
    assert isinstance(settings.ARXIV_CATEGORIES, list)
    assert settings.ARXIV_CATEGORIES == ["cs.LG", "cs.CV"]


def test_arxiv_categories_given_one_category_only():
    settings = _minimal_settings(ARXIV_CATEGORIES="cs.LG")
    assert settings.ARXIV_CATEGORIES == ["cs.LG"]


def test_arxiv_categories_strips_whitespace():
    settings = _minimal_settings(ARXIV_CATEGORIES="cs.LG, cs.CV , cs.AR")
    assert settings.ARXIV_CATEGORIES == ["cs.LG", "cs.CV", "cs.AR"]


@pytest.mark.parametrize(
    "invalid_input",
    (
        "AbC.AB,AB.AB", "abc.ab,Abb.Baa", "aa.bb,aa.11", "11.aa,aa.BB",
        "11.22,33.44", "1", "1.0", "", 1, 1.0,
    ),
)
def test_arxiv_categories_given_incorrect_input(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _minimal_settings(ARXIV_CATEGORIES=invalid_input)
    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "ARXIV_CATEGORIES" in field_names, \
        f"Uncaught error when given invalid input '{invalid_input}' of type '{type(invalid_input)}'"

#### DAILY_SCHEDULER_TIME

def test_daily_scheduler_time_default():
    settings = _minimal_settings()
    # TODO: this default values below should be parameterized via .env
    assert settings.DAILY_SCHEDULER_TIME == config._DEFAULT_DAILY_SCHEDULER_TIME


@pytest.mark.parametrize("invalid_input", (1, 0.2, ""))
def test_daily_scheduler_time_given_invalid_input(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _minimal_settings(DAILY_SCHEDULER_TIME=invalid_input)
    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "DAILY_SCHEDULER_TIME" in field_names, \
        f"Uncaught error when given invalid input '{invalid_input}' of type '{type(invalid_input)}'"


@pytest.mark.parametrize(
    "invalid_input",
    ("30 20 * * 0 *", "30 20 * *", "61 25 32 13 7"),
)
def test_daily_scheduler_time_given_incorrect_format(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _minimal_settings(DAILY_SCHEDULER_TIME=invalid_input)
    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "DAILY_SCHEDULER_TIME" in field_names, \
        f"Uncaught error when given invalid input '{invalid_input}' of type '{type(invalid_input)}'"

#### WEEKLY_SCHEDULER_TIME

def test_weekly_scheduler_time_default():
    settings = _minimal_settings()
    assert settings.WEEKLY_SCHEDULER_TIME == config._DEFAULT_WEEKLY_SCHEDULER_TIME


@pytest.mark.parametrize("invalid_input", (1, 0.2, ""))
def test_weekly_scheduler_time_given_invalid_input(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _minimal_settings(WEEKLY_SCHEDULER_TIME=invalid_input)
    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "WEEKLY_SCHEDULER_TIME" in field_names, \
        f"Uncaught error when given invalid input '{invalid_input}' of type '{type(invalid_input)}'"


@pytest.mark.parametrize(
    "invalid_input",
    ("30 20 * * 0 *", "30 20 * *", "61 25 32 13 7"),
)
def test_weekly_scheduler_time_given_incorrect_format(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _minimal_settings(WEEKLY_SCHEDULER_TIME=invalid_input)
    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "WEEKLY_SCHEDULER_TIME" in field_names, \
        f"Uncaught error when given invalid input '{invalid_input}' of type '{type(invalid_input)}'"

#### LOG_LEVEL

def test_log_level_defaults_to_info():
    settings = _minimal_settings()
    assert settings.LOG_LEVEL == config._DEFAULT_LOG_LEVEL


def test_log_level_given_not_in_literal():
    valid_options = get_args(config._DEFAULT_LOG_LEVEL)
    for option in valid_options:
        settings = _minimal_settings(LOG_LEVEL=option)
        assert settings.LOG_LEVEL == option


@pytest.mark.parametrize("invalid_input", ["a", "1", "", 1, 1.0])
def test_log_level_invalid_input(invalid_input):
    with pytest.raises(ValidationError) as exc_info:
        _minimal_settings(LOG_LEVEL=invalid_input)
    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "LOG_LEVEL" in field_names, \
        f"Uncaught error when given invalid input '{invalid_input}' of type '{type(invalid_input)}'"
