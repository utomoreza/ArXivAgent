# Quickstart: ArXiv Intelligence Agent

**Date**: 2026-04-23 | **Plan**: [plan.md](plan.md)

---

## Prerequisites

- Python 3.12
- PostgreSQL 16 with pgvector extension (`CREATE EXTENSION vector;`)
- `uv` installed (`pip install uv` or via [uv docs](https://docs.astral.sh/uv/))
- An Anthropic API key

---

## 1. Clone and Install

```bash
git clone <repo-url>
cd ArXivAgent

# Install all dependencies (creates .venv automatically)
uv sync
```

---

## 2. Configure Environment

Copy the example env file and fill in required values:

```bash
cp .env.example .env
```

Required variables:

```bash
# Required
INCEPTION_DATE=2026-01-01          # Earliest date to backfill from on first run
ANTHROPIC_API_KEY=sk-ant-...       # Anthropic API key

# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/arxivagent

# Optional (defaults shown)
RAG_WINDOW_DAYS=90
ARXIV_CATEGORIES=cs.LG,cs.CV,cs.CL,cs.AI,cs.RO,stat.ML
DAILY_SCHEDULER_TIME="30 20 * * 0,1,2,3,4"
WEEKLY_SCHEDULER_TIME="0 1 * * 5"
LOG_LEVEL=INFO
```

---

## 3. Set Up the Database

```bash
# Create the database
createdb arxivagent

# Enable pgvector extension
psql arxivagent -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Run migrations
uv run alembic upgrade head
```

---

## 4. Run the Service

```bash
uv run python -m src.main
```

On first run, the service detects an empty `DateRecord` table and automatically
runs the inception backfill: it fetches and processes every arXiv announcement
day from `INCEPTION_DATE` to yesterday before the regular scheduler takes over.

Backfill progress is logged to stdout at INFO level:

```
INFO  [backfill] Starting inception backfill from 2026-01-01 to 2026-04-22
INFO  [backfill] Processing 2026-01-05 (Sun) — fetching arXiv papers...
INFO  [backfill] 2026-01-05: 312 papers fetched, processed, digest generated
...
INFO  [backfill] Inception backfill complete. Handing off to regular schedulers.
```

---

## 5. Run Tests

Coverage is enabled by default via `pyproject.toml` (`addopts`). Every `pytest`
run produces a terminal report and an HTML report at `htmlcov/index.html`.

```bash
# All tests (coverage on by default)
uv run pytest

# Unit tests only
uv run pytest tests/unit/

# Integration tests (requires a running test PostgreSQL instance)
uv run pytest tests/integration/

# Disable coverage for a quick run
uv run pytest --no-cov

# Open HTML coverage report (macOS)
open htmlcov/index.html
```

Integration tests use a separate test database. Set `TEST_DATABASE_URL` in your
environment or `.env.test` file.

Coverage configuration lives in `pyproject.toml` under `[tool.coverage.run]` and
`[tool.coverage.report]`. Branch coverage is enabled; `src/migrations/` and
`src/main.py` are excluded from measurement.

---

## 6. Query the API

Once the service is running (or after at least one daily digest is generated):

### Get a daily digest

```bash
curl http://localhost:8000/digests/daily/2026-04-21
```

### Get a weekly digest

```bash
# week_start_date must be a Sunday
curl http://localhost:8000/digests/weekly/2026-04-19
```

### Ask a question

```bash
curl -X POST http://localhost:8000/qa \
  -H "Content-Type: application/json" \
  -d '{"question": "Which papers improved MMLU this week?"}'
```

---

## 7. Key Files

| File | Purpose |
|------|---------|
| `src/main.py` | Service entrypoint — starts FastAPI + APScheduler |
| `src/config.py` | All environment variable settings (Pydantic) |
| `src/pipeline/fetcher.py` | arXiv paper fetching with retry logic |
| `src/pipeline/processor.py` | Paper extraction (metadata + full text + topic) |
| `src/pipeline/detector.py` | Groundbreaking paper detection |
| `src/pipeline/daily_generator.py` | Daily digest generation |
| `src/pipeline/weekly_generator.py` | Weekly digest generation |
| `src/pipeline/rag_indexer.py` | Embedding + pgvector indexing |
| `src/scheduler/jobs.py` | APScheduler job definitions + backfill logic |
| `src/api/routers/digests.py` | GET /digests/daily and /digests/weekly |
| `src/api/routers/qa.py` | POST /qa |
| `src/db/models.py` | SQLAlchemy ORM models |
| `migrations/` | Alembic migration scripts |

---

## 8. Linting and Formatting

```bash
# Check
uv run ruff check src/ tests/

# Format
uv run ruff format src/ tests/
```

Ruff is configured to enforce all Code Quality principles from the constitution
(no unused imports, no dead code, line length, etc.).
