# ArXiv Intelligence Agent

An always-on background service that monitors arXiv daily, synthesizes ML research
papers into structured digests, and exposes those digests — plus a conversational
RAG Q&A interface — through HTTP endpoints.

> **Frontend**: A companion web UI is available at
> [ArXivAgentUI](https://github.com/utomoreza/ArXivAgentUI).

## Features

- **Daily digest** — papers fetched at 20:30 ET (Sun–Thu), grouped by topic, with
  key contributions, methodology notes, and benchmark results extracted via LLM
- **Groundbreaking detection** — papers that both improve a benchmark and introduce
  a novel architecture are flagged with a one-line reasoning string
- **Weekly synthesis** — cross-paper trend analysis covering the full Sun–Thu window
- **RAG Q&A** — natural-language questions answered from the rolling digest window
  with cited sources; out-of-scope questions rejected

## Prerequisites

- Python 3.12
- [`uv`](https://docs.astral.sh/uv/) (`pip install uv`)
- Docker or Podman (for the PostgreSQL + pgvector container)
- An [Anthropic API key](https://console.anthropic.com)

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/utomoreza/ArXivAgent.git
cd ArXivAgent
uv sync
```

### 2. Start the database

The project ships with a `compose.yml` that starts PostgreSQL 15 with pgvector
and automatically creates both the application database (`arxivagent`) and the
test database (`arxiv_test`).

```bash
# Docker
docker compose up -d

# Podman
podman compose up -d
```

Wait for the container to be healthy:

```bash
docker compose ps   # STATUS should show "healthy"
```

> **Native PostgreSQL**: if you prefer a local install, create the two databases
> manually and enable the vector extension in each:
> ```sql
> CREATE DATABASE arxivagent;
> CREATE DATABASE arxiv_test;
> \connect arxivagent; CREATE EXTENSION IF NOT EXISTS vector;
> \connect arxiv_test;  CREATE EXTENSION IF NOT EXISTS vector;
> ```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in the required values:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `INCEPTION_DATE` | Yes | — | Earliest date to backfill from on first run (e.g. `2026-01-01`) |
| `ANTHROPIC_API_KEY` | Yes | — | Your Anthropic API key |
| `DATABASE_URL` | Yes | — | asyncpg connection string (see `.env.example`) |
| `RAG_WINDOW_DAYS` | No | `90` | Days of digests kept searchable via `/qa` |
| `ARXIV_CATEGORIES` | No | `cs.LG,cs.CV,cs.CL,cs.AI,cs.RO,stat.ML` | arXiv categories to monitor |
| `TOPIC_LIST` | No | See `.env.example` | Topic labels used to group papers |
| `DAILY_SCHEDULER_TIME` | No | `30 20 * * 0,1,2,3,4` | Cron for daily job (America/New_York) |
| `WEEKLY_SCHEDULER_TIME` | No | `0 1 * * 5` | Cron for weekly job (America/New_York) |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, or `ERROR` |

### 4. Run database migrations

```bash
uv run alembic upgrade head
```

### 5. Start the service

```bash
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
```

On first run the service detects an empty database and runs the **inception
backfill** — fetching and processing every arXiv announcement day from
`INCEPTION_DATE` to yesterday — before handing off to the regular scheduler.
This runs in the background; the API is available immediately.

> **arXiv schedule**: announcements happen at 20:00 ET, Sunday–Thursday only.
> Friday and Saturday are never announcement days.

## API

Once the service is running, the interactive docs are at
`http://localhost:8000/docs`.

```bash
# Daily digest for a specific date
curl http://localhost:8000/digests/daily/2026-05-06

# Weekly digest (week_start must be a Sunday)
curl http://localhost:8000/digests/weekly/2026-05-04

# Q&A
curl -X POST http://localhost:8000/qa \
  -H "Content-Type: application/json" \
  -d '{"question": "Which papers improved MMLU this week?"}'
```

### Response statuses

Daily and weekly digest endpoints return a `status` field rather than a 404:

| Status | Meaning |
|--------|---------|
| `published` | Digest available; data in `digest` field |
| `pending` | Announcement day not yet processed |
| `skipped` | Announcement day with zero papers |
| `no_announcement` | Friday or Saturday — arXiv never publishes |
| `not_found` | Date is before `INCEPTION_DATE` |
| `not_available` | Future date |

## Running Tests

```bash
# Unit tests only (no database required)
uv run pytest tests/unit/

# Integration + contract tests (requires the database container)
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/arxiv_test \
  uv run pytest

# With coverage report
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/arxiv_test \
  uv run pytest --cov=src --cov-report=term-missing
```

## Project Structure

```
src/
  api/          # FastAPI routers and Pydantic schemas
  db/           # SQLAlchemy ORM models and async session
  llm/          # Anthropic client with retry and structured output
  migrations/   # Alembic migration scripts
  pipeline/     # Fetcher, processor, detector, digest generators, RAG indexer
  rag/          # Sentence-transformer embedder and pgvector retriever
  scheduler/    # APScheduler jobs and inception backfill
  config.py     # Pydantic Settings (all env vars validated at startup)
  main.py       # Service entrypoint
tests/
  unit/         # Fast tests, no external dependencies
  integration/  # Database and API tests (requires running DB)
  contract/     # OpenAPI contract validation
```

## Linting

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```
