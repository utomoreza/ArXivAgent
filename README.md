# ArXiv Intelligence Agent

An always-on background service that monitors arXiv daily, synthesizes ML research
papers into structured digests, and exposes those digests — plus a conversational
RAG Q&A interface — through HTTP endpoints.

## Features

- **Daily digest**: papers fetched at 20:30 ET (Sun–Thu), grouped by topic, with
  key contributions, methodology notes, and benchmark results extracted via LLM
- **Groundbreaking detection**: papers that both improve a benchmark and introduce
  a novel architecture are flagged with a one-line reasoning string
- **Weekly synthesis**: cross-paper trend analysis covering the full Sun–Thu window
- **RAG Q&A**: natural-language questions answered from the rolling digest window
  with cited sources; out-of-scope questions rejected

## Prerequisites

- Python 3.12
- [`uv`](https://docs.astral.sh/uv/) (`pip install uv`)
- Docker or Podman (for the PostgreSQL + pgvector container)
- An [Anthropic API key](https://console.anthropic.com)

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd ArXivAgent
uv sync
```

### 2. Start the database

The project ships with a `compose.yml` that starts PostgreSQL 15 with pgvector
and automatically creates both the application database (`arxivagent`) and the
test database (`arxiv_test`).

**Docker:**
```bash
docker compose up -d
```

**Podman:**
```bash
podman-compose up -d
# or
podman compose up -d
```

Wait for the container to be healthy before proceeding:
```bash
docker compose ps   # STATUS should show "healthy"
podman compose ps
```

> If you prefer a native PostgreSQL install, create the two databases manually
> and enable the vector extension in each:
> ```sql
> CREATE DATABASE arxivagent;
> CREATE DATABASE arxiv_test;
> \connect arxivagent
> CREATE EXTENSION IF NOT EXISTS vector;
> \connect arxiv_test
> CREATE EXTENSION IF NOT EXISTS vector;
> ```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in the required values:

| Variable | Required | Description |
|----------|----------|-------------|
| `INCEPTION_DATE` | Yes | ISO date — earliest date to backfill from on first run (e.g. `2026-01-01`) |
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `DATABASE_URL` | Yes | `postgresql+asyncpg://postgres:postgres@localhost:5432/arxivagent` |

All other variables have sensible defaults (see `.env.example`).

### 4. Run database migrations

```bash
uv run alembic upgrade head
```

### 5. Start the service

```bash
uv run python -m src.main
```

On first run the service detects an empty database and runs the inception
backfill — fetching and processing every arXiv announcement day from
`INCEPTION_DATE` to yesterday — before handing off to the regular scheduler.

## Running Tests

```bash
# Unit tests only (no database required)
uv run pytest tests/unit/

# Integration tests (requires the database container to be running)
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/arxiv_test \
  uv run pytest tests/integration/

# All tests
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/arxiv_test \
  uv run pytest

# With coverage
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/arxiv_test \
  uv run pytest --cov=src --cov-report=term-missing
```

## API

Once the service is running:

```bash
# Daily digest
curl http://localhost:8000/digests/daily/2026-04-21

# Weekly digest (week_start must be a Sunday)
curl http://localhost:8000/digests/weekly/2026-04-19

# Q&A
curl -X POST http://localhost:8000/qa \
  -H "Content-Type: application/json" \
  -d '{"question": "Which papers improved MMLU this week?"}'
```

## Project Structure

```
src/
  api/          # FastAPI routers and Pydantic schemas
  db/           # SQLAlchemy ORM models and async session
  llm/          # Anthropic client with retry logic
  migrations/   # Alembic migration scripts
  pipeline/     # Fetcher, processor, detector, digest generators, RAG indexer
  rag/          # Embedder and retriever
  scheduler/    # APScheduler jobs and inception backfill
  config.py     # Pydantic Settings (all env vars)
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
