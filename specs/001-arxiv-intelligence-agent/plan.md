# Implementation Plan: ArXiv Intelligence Agent

**Branch**: `001-arxiv-intelligence-agent` | **Date**: 2026-04-23 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/001-arxiv-intelligence-agent/spec.md`

## Summary

ArXivAgent is an always-on Python service that fetches arXiv ML papers on a
Sun–Thu schedule, processes them through an extraction → detection → digest
pipeline, and serves structured digests plus a RAG Q&A interface over HTTP.
The implementation uses FastAPI + APScheduler for the service layer,
PostgreSQL 16 + pgvector for all storage (relational and vector), local
`BAAI/bge-small-en-v1.5` embeddings, and two Claude model tiers (Sonnet for
deep reasoning, Haiku for classification) via the Anthropic SDK.

## Technical Context

**Language/Version**: Python 3.12
**Authoritative dependency versions**: [`pyproject.toml`](../../pyproject.toml) — always read this file before writing code that uses any library (per CLAUDE.md coding guidelines).

| Library | Pinned version | Role |
|---------|---------------|------|
| `fastapi` | 0.136.1 | HTTP API framework |
| `uvicorn[standard]` | 0.46.0 | ASGI server |
| `pydantic` | 2.13.3 | Request/response validation |
| `pydantic-settings` | 2.14.0 | Env var config |
| `apscheduler` | 3.11.2 | In-process cron scheduler |
| `sqlalchemy` | 2.0.49 | Async ORM |
| `alembic` | 1.18.4 | DB migrations |
| `asyncpg` | 0.31.0 | Async PostgreSQL driver |
| `pgvector` | 0.4.2 | SQLAlchemy vector column type |
| `arxiv` | 3.0.0 ⚠️ | arXiv API metadata client — requires `Client` object (see research.md §10) |
| `httpx` | 0.28.1 | Async HTTP (arXiv HTML full text) |
| `pdfplumber` | 0.11.9 | PDF text extraction (fallback) |
| `sentence-transformers` | 5.4.1 ⚠️ | Local embedding model — `inputs=` not `sentences=` (see research.md §10) |
| `anthropic` | 0.97.0 | Claude Sonnet + Haiku API client — use `messages.parse()` for structured output |
| `pytest` | 9.0.3 ⚠️ | Test runner |
| `pytest-asyncio` | 1.3.0 ⚠️ | Async test support — `event_loop` fixture removed (see research.md §10) |
| `ruff` | 0.15.12 | Linter + formatter |

**Storage**: PostgreSQL 16 with pgvector extension (single DB for papers, digests, date records, and vector embeddings)
**Testing**: pytest 9.0.3 + pytest-asyncio 1.3.0
**Target Platform**: Linux server (always-on service)
**Project Type**: web-service (HTTP API + background scheduler)
**Performance Goals**:
- Digest endpoint: ≤ 2 s response at p95 (SC-006)
- Q&A endpoint: ≤ 10 s response at p95 (SC-007)
- Batch paper processing: ≥ 10 papers/s throughput (Constitution IV)
- RSS memory: ≤ 512 MB under sustained workload
**Constraints**:
- arXiv announcement window: 20:00 ET Sun–Thu only; no fetches on Fri/Sat
- Inception backfill must run before regular schedule hands off
- RAG window scoped to `RAG_WINDOW_DAYS` (default 90) without re-index requirement
- Digests and Date Records retained indefinitely
**Scale/Scope**: 100–500 papers/day across 6 arXiv categories; single-user query mode in v1

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| **I. Code Quality** | ✅ PASS | Single-responsibility components (Fetcher, Processor, Detector, generators, API); no preemptive abstractions |
| **II. Test-First** | ✅ PASS | Unit tests required for every pipeline stage; integration tests required for all 3 API endpoints and arXiv interaction; external I/O mocked at system boundary only |
| **III. UX Consistency** | ✅ PASS | Single JSON envelope schema for all API responses; error messages follow `[context] what went wrong: why`; all terminology matches spec |
| **IV. Performance** | ✅ PASS | Explicit goals stated in Technical Context above; SC-006 ≤ 2 s, SC-007 ≤ 10 s; batch throughput ≥ 10 items/s |
| **V. Observability** | ✅ PASS | Structured JSON logging required; DEBUG/INFO/ERROR on all external calls; `LOG_LEVEL` configurable via env |

**Post-Phase 1 re-check**: Required after data model and contracts are finalised.

## Project Structure

### Documentation (this feature)

```text
specs/001-arxiv-intelligence-agent/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── openapi.yaml
└── tasks.md             # Phase 2 output (/speckit-tasks command)
```

### Source Code (repository root)

```text
src/
├── api/
│   ├── __init__.py
│   ├── app.py                  # FastAPI app factory
│   ├── routers/
│   │   ├── digests.py          # GET /digests/daily/{date}, GET /digests/weekly/{week_start_date}
│   │   └── qa.py               # POST /qa
│   └── schemas.py              # Pydantic request/response models
├── pipeline/
│   ├── __init__.py
│   ├── fetcher.py              # arXiv Fetcher (retry 3×, exponential backoff)
│   ├── processor.py            # Paper Processor (metadata + full text + topic)
│   ├── detector.py             # Groundbreaking Detector
│   ├── daily_generator.py      # Daily Digest Generator
│   ├── weekly_generator.py     # Weekly Digest Generator
│   └── rag_indexer.py          # RAG Indexer (chunking + embedding + pgvector)
├── scheduler/
│   ├── __init__.py
│   └── jobs.py                 # APScheduler job definitions + inception backfill logic
├── db/
│   ├── __init__.py
│   ├── constants.py            # Single source of truth for all DB string literals (enum values/type names, table names, column names, constraint expressions/names, index names)
│   ├── session.py              # SQLAlchemy async engine + session factory
│   └── models.py               # ORM models (Paper, DateRecord, DailyDigest, WeeklyDigest, etc.)
├── migrations/                 # Alembic migration scripts
│   ├── env.py
│   └── versions/
├── rag/
│   ├── __init__.py
│   ├── embedder.py             # sentence-transformers wrapper
│   └── retriever.py            # pgvector similarity search + window filtering
├── llm/
│   ├── __init__.py
│   └── client.py               # AsyncAnthropic client + helpers; model name passed as argument
├── config.py                   # Pydantic settings (all env vars)
└── main.py                     # Entrypoint: start FastAPI + APScheduler

tests/
├── conftest.py                 # Fixtures: test DB, mock arXiv, mock LLM
├── unit/
│   ├── test_fetcher.py
│   ├── test_processor.py
│   ├── test_detector.py
│   ├── test_daily_generator.py
│   ├── test_weekly_generator.py
│   ├── test_rag_indexer.py
│   └── test_scheduler.py       # backfill logic, date-state classification
├── integration/
│   ├── test_api_digests.py     # All 6 GET /digests/daily states, 3 GET /digests/weekly states
│   ├── test_api_qa.py          # In-scope, out-of-scope, empty KB
│   └── test_pipeline.py        # End-to-end happy path + failure paths
└── contract/
    └── test_openapi.py         # Response shapes match openapi.yaml
```

**Structure Decision**: Single-project layout. All components are Python modules
under `src/`; no separate frontend. Scheduler runs in-process via APScheduler.
Test pyramid: unit (per-component logic) → integration (API + pipeline flows) →
contract (schema conformance).

## Implementation Sequence

Build order is bottom-up: foundation first, pipeline second, service layer last.
Each step lists the **design references** to read before writing any code, the
**test file(s)** to write first (TDD — tests must fail before implementation),
and any **hard constraints** that cannot be skipped.

---

### Step 1 — Project scaffold & configuration

**Files**: `pyproject.toml`, `src/config.py`, `.env.example`

**Design references**:
- `plan.md` → Technical Context table (all env var names and types)
- `CLAUDE.md` → Required Environment Variables table
- `quickstart.md` → Environment setup section

**What to implement**:
- `config.py`: Pydantic `Settings` class covering all env vars (`INCEPTION_DATE`,
  `DATABASE_URL`, `ANTHROPIC_API_KEY`, `RAG_WINDOW_DAYS`, `ARXIV_CATEGORIES`,
  `TOPIC_LIST`, `DAILY_SCHEDULER_TIME`, `WEEKLY_SCHEDULER_TIME`, `LOG_LEVEL`)
- `.env.example`: all required vars with placeholder values and inline comments

**Tests first**: `tests/unit/test_config.py` — validate that missing required vars
raise `ValidationError`, that defaults are applied correctly, and that
`TOPIC_LIST` parses as a list.

---

### Step 2 — Database models & migrations

**Files**: `src/db/constants.py`, `src/db/models.py`, `src/db/session.py`,
`src/migrations/env.py`, `src/migrations/versions/0001_initial.py`

**Design references**:
- `data-model.md` → Entities section (every field, type, constraint, and index)
- `data-model.md` → State Transitions (DateRecord status enum)
- `data-model.md` → Migration Notes (enum creation order, pgvector extension,
  HNSW index timing)
- `research.md §10` → SQLAlchemy 2.0 async session pattern + Alembic async
  `env.py` pattern
- `research.md §10` → pgvector 0.4.x: no `register_vector()` needed; `Vector`
  column type import

**What to implement**:
- `models.py`: `DeclarativeBase`, then all ORM classes in dependency order:
  `DateRecord` → `DailyDigest` → `TopicSection` → `WeeklyDigest` →
  `Paper` → `PaperEmbedding`. Include all indexes.
- `session.py`: `create_async_engine`, `async_sessionmaker`, `get_session`
  dependency function.
- `migrations/env.py`: async migration runner (see research.md §10 pattern).
- Initial Alembic revision: creates enums (`date_status`, `chunk_type`), enables
  `vector` extension, creates all tables and B-tree indexes. **Does not create
  HNSW index** (created post-backfill).

**Tests first**: `tests/integration/test_db_models.py` — create all entities,
assert FK constraints and enum constraints are enforced by the real DB.

---

### Step 3 — LLM client

**Files**: `src/llm/client.py`

**Design references**:
- `research.md §10` → Anthropic SDK 0.97.0: `messages.parse()` for structured
  output, `messages.create()` with `tools=` for classification; `AsyncAnthropic()`
  client; `strict=True` on tool definitions
- `research.md §6` → LLM task-to-model mapping (which tasks use Sonnet vs Haiku)

**What to implement**:
- `AsyncAnthropic()` client instantiated once and shared.
- Helper functions that take `model` as a parameter (do not hard-code per file):
  `parse_structured(model, prompt, schema)` wrapping `messages.parse()`,
  `classify(model, prompt, tool_def)` wrapping `messages.create()` with tools.
- Retry logic (3 attempts, exponential backoff) for transient `anthropic.APIError`.
- Structured JSON logging at DEBUG on entry, INFO/ERROR on exit with elapsed time
  (Constitution V).

**Tests first**: `tests/unit/test_llm_client.py` — mock `AsyncAnthropic`, assert
retry behaviour on transient errors, assert correct model name is forwarded.

---

### Step 4 — arXiv Fetcher

**Files**: `src/pipeline/fetcher.py`

**Design references**:
- `research.md §1` → arxiv 3.0.0 breaking change: must use `arxiv.Client`
- `research.md §10` → arxiv 3.x exact code pattern (`Client`, `Search`,
  `client.results(search)`, `Result` field names)
- `spec.md FR-001` → fetch schedule, retry policy, four DateRecord outcomes
- `system_design.md §3.2` → Fetcher component design and inception backfill logic
- `data-model.md` → DateRecord status enum values

**What to implement**:
- `fetch_papers(date: date, session: AsyncSession) -> FetchResult` — fetches
  papers for one announcement date, writes `DateRecord`, returns papers or skip
  reason.
- Retry: 3 attempts with exponential backoff using `httpx` or `asyncio.sleep`.
- Fri/Sat guard: immediately records `no_announcement` without fetching.
- Returns structured result: papers list or `FetchFailure | NoPapers | NoAnnouncement`.

**Tests first**: `tests/unit/test_fetcher.py` — mock `arxiv.Client`; assert each
of the four DateRecord outcomes is written correctly; assert retry count and
backoff are respected.

---

### Step 5 — Paper Processor

**Files**: `src/pipeline/processor.py`

**Design references**:
- `system_design.md §3.3` → two-step fetch: arXiv API metadata then
  `arxiv.org/html/{id}`; PDF fallback; primary topic + secondary tags
- `research.md §6` → LLM model tier for extraction (Sonnet) and topic
  classification (Haiku)
- `research.md §10` → Anthropic `messages.parse()` pattern for extraction;
  `messages.create()` with tool for topic classification
- `data-model.md` → Paper entity (all fields, validation rules)
- `spec.md FR-002, FR-003` → what must be extracted; primary/secondary topic rules

**What to implement**:
- `process_paper(result: arxiv.Result, session: AsyncSession) -> Paper` — fetches
  HTML, falls back to PDF, calls Sonnet for extraction, Haiku for classification,
  persists `Paper` row.
- HTML fetch via `httpx.AsyncClient` to `arxiv.org/html/{arxiv_id}`.
- Pydantic schema for extraction output (contributions, methodologies, benchmarks,
  institutions) passed to `messages.parse()`.
- Topic classification via `messages.create()` with a tool whose `enum` is
  `settings.TOPIC_LIST`.

**Tests first**: `tests/unit/test_processor.py` — mock HTTP client and LLM;
assert primary topic is always one of `TOPIC_LIST`; assert `groundbreaking_reasoning`
is null when `is_groundbreaking=False`.

---

### Step 6 — Groundbreaking Detector

**Files**: `src/pipeline/detector.py`

**Design references**:
- `spec.md FR-004, FR-011` → exact two-criterion rule (benchmark improvement AND
  novel architecture); reasoning statement format
- `system_design.md §3.4` → detector design; no partial flag
- `research.md §6` → Sonnet for this task

**What to implement**:
- `detect_groundbreaking(paper: Paper, session: AsyncSession) -> None` — evaluates
  criteria via `messages.parse()`, updates `paper.is_groundbreaking` and
  `paper.groundbreaking_reasoning` in-place, persists.
- Pydantic output schema: `{is_groundbreaking: bool, benchmark_improved: str | None, novel_element: str | None}`.
- Reasoning is assembled as: `"Improves {benchmark} by {delta}; introduces {novel_element}."` only when both criteria are met.

**Tests first**: `tests/unit/test_detector.py` — mock LLM; assert papers meeting
both criteria are flagged with non-empty reasoning; assert papers failing either
criterion are NOT flagged; assert no partial flag.

---

### Step 7 — Daily Digest Generator

**Files**: `src/pipeline/daily_generator.py`

**Design references**:
- `system_design.md §3.5` → generator design, skip handling, Markdown body format
- `contracts/openapi.yaml` → `DailyDigest` and `TopicSection` schemas (exact
  field names the API must return)
- `data-model.md` → DailyDigest and TopicSection entity definitions
- `spec.md FR-005` → three date states; when to produce vs skip a digest
- `research.md §6` → Sonnet for digest Markdown generation

**What to implement**:
- `generate_daily_digest(date: date, session: AsyncSession) -> DailyDigest | None`
  — groups papers by `primary_topic`, calls Sonnet to render Markdown `body` per
  topic, persists `DailyDigest` + `TopicSection` rows, sets
  `Paper.topic_section_id` for each paper.
- Skip guard: if `DateRecord.status != 'published'`, returns `None` immediately.
- TopicSection ordering: `ORDER BY paper_count DESC` at query time (no stored
  position field).

**Tests first**: `tests/unit/test_daily_generator.py` — mock LLM; assert digest
is not generated for skip states; assert all papers are assigned `topic_section_id`;
assert `groundbreaking_count` matches papers with `is_groundbreaking=True`.

---

### Step 8 — Embedding & RAG Indexer

**Files**: `src/rag/embedder.py`, `src/rag/retriever.py`,
`src/pipeline/rag_indexer.py`

**Design references**:
- `research.md §5` → sentence-transformers 5.x: use `inputs=` not `sentences=`
- `research.md §7` → chunking strategy (abstract chunk vs content chunk), top-K,
  recency re-ranking, window SQL filter
- `research.md §10` → sentence-transformers exact encode pattern;
  pgvector 0.4.x `cosine_distance()` usage; HNSW index creation timing
- `data-model.md` → PaperEmbedding entity (all denormalized fields, 512-token cap)
- `spec.md FR-008` → RAG_WINDOW_DAYS scope; window evaluated per-query

**What to implement**:
- `embedder.py`: `SentenceTransformer('BAAI/bge-small-en-v1.5')` loaded once;
  `embed(texts: list[str]) -> np.ndarray` using `model.encode(inputs=texts, normalize_embeddings=True)`.
- `rag_indexer.py`: `index_paper(paper: Paper, session: AsyncSession)` — builds
  two chunks (abstract + content), truncates content chunk at 512 tokens,
  calls embedder, persists two `PaperEmbedding` rows with all denormalized fields.
  The `UNIQUE(arxiv_id, chunk_type)` constraint on `PaperEmbedding` enforces
  exactly one abstract and one content chunk per paper at the DB level.
- `retriever.py`: `retrieve(question: str, session: AsyncSession, window_days: int, k: int = 10)` — embeds question, queries pgvector with window date filter,
  re-ranks by recency, returns top-K `PaperEmbedding` rows.

**Tests first**: `tests/unit/test_rag_indexer.py` — assert two chunks produced
per paper; assert abstract chunk never truncates; assert content chunk field
truncation order (benchmarks → methodologies → contributions).
`tests/unit/test_retriever.py` — mock DB; assert window filter excludes
out-of-window chunks; assert results re-ranked by date.

**Known v1 limitation — content chunk truncation**: the content chunk merges
contributions + methodologies + benchmarks into one vector with a 512-token cap.
For complex papers this causes lossy truncation. The upgrade path (3 separate
content chunks per paper) is documented in `system_design.md §8` — the
`PaperEmbedding` table and indexer logic would need to be extended to support it.

**Known v1 limitation — metadata pre-filters**: metadata fields on `PaperEmbedding`
(`primary_topic`, `secondary_topics`, `is_groundbreaking`, `authors`, `institutions`)
are stored but not used as dynamic SQL pre-filters during retrieval. Only `date`
(RAG window) is applied. The upgrade path — a Haiku query analysis step that
extracts filter conditions and applies them as `WHERE` clauses before vector
search — is documented in `system_design.md §8`.

---

### Step 9 — Scheduler & inception backfill

**Files**: `src/scheduler/jobs.py`

**Design references**:
- `research.md §2` → APScheduler `AsyncIOScheduler` + `CronTrigger.from_crontab()`
- `research.md §3` → inception backfill strategy: check empty `DateRecord` table,
  iterate dates chronologically, run weekly generator per historical week
- `research.md §10` → APScheduler lifespan pattern (do not `await` `start()`)
- `system_design.md §3.1` → scheduler timing rationale
- `spec.md FR-001, FR-006` → schedule constraints and backfill scope

**What to implement**:
- `setup_scheduler(scheduler: AsyncIOScheduler, session_factory)` — registers
  daily and weekly jobs from env var cron strings via `CronTrigger.from_crontab()`.
- `run_inception_backfill(session_factory)` — checks `DateRecord` table; if empty,
  iterates `INCEPTION_DATE` → yesterday calling the full pipeline per date;
  then runs weekly generator per historical Sun–Thu week in order.
- Fri/Sat dates within backfill range: write `no_announcement` `DateRecord`
  without running the pipeline.

**Tests first**: `tests/unit/test_scheduler.py` — mock pipeline; assert backfill
skips Fri/Sat as `no_announcement`; assert backfill does not re-run when
`DateRecord` rows already exist; assert weekly generator is called once per
historical week.

---

### Step 10 — Weekly Digest Generator

**Files**: `src/pipeline/weekly_generator.py`

**Design references**:
- `system_design.md §3.6` → generator design; Sun–Thu window; no minimum
  threshold; coverage note structure; three Markdown sections
- `spec.md FR-006, FR-012` → weekly scheduler timing; three comparison lenses
  (benchmark comparisons, trend synthesis, cross-paper analysis)
- `contracts/openapi.yaml` → `WeeklyDigest` schema (exact field names)
- `data-model.md` → WeeklyDigest entity; DailyDigest date-range query (no FK —
  use `WHERE date BETWEEN week_start AND week_end`)
- `research.md §6` → Sonnet for weekly synthesis (three sections)

**What to implement**:
- `generate_weekly_digest(week_start: date, session: AsyncSession) -> WeeklyDigest | None`
  — reads daily digests for the Sun–Thu window via date range query, calls Sonnet
  for each of the three synthesis sections, builds coverage arrays from
  `DateRecord` statuses, persists `WeeklyDigest`.
- Returns `None` if no daily digests exist for the week.

**Tests first**: `tests/unit/test_weekly_generator.py` — mock LLM; assert
`fetch_failure_skip` days appear in `fetch_failure_skips` array (not
`no_papers_skips`); assert weeks with zero daily digests produce no output;
assert all three Markdown sections are populated.

---

### Step 11 — API layer

**Files**: `src/api/app.py`, `src/api/schemas.py`, `src/api/routers/digests.py`,
`src/api/routers/qa.py`

**Design references**:
- `contracts/openapi.yaml` → **single source of truth** for all request/response
  shapes; every Pydantic schema in `schemas.py` must match exactly
- `system_design.md §3.8` → all response states per endpoint (6 for daily, 3 for
  weekly, 3 for Q&A)
- `research.md §8` → envelope schema (`status`, `data`, `reason`)
- `research.md §10` → FastAPI lifespan pattern (scheduler + DB engine startup)
- `spec.md FR-007, FR-008, FR-009, FR-010` → endpoint requirements

**What to implement**:
- `schemas.py`: Pydantic models mirroring every schema in `openapi.yaml`. One
  class per response type.
- `digests.py`: `GET /digests/daily/{date}` (all 6 states) and
  `GET /digests/weekly/{week_start_date}` (all 3 states including Sunday-only
  validation for `week_start_date`).
- `qa.py`: `POST /qa` — scope check via Haiku, empty-KB check, RAG retrieval,
  Sonnet answer generation. All 3 response states.
- `app.py`: FastAPI app factory with `lifespan` context manager starting
  scheduler and DB engine.

**Tests first**:
- `tests/integration/test_api_digests.py` — all 6 daily states, all 3 weekly
  states, 400 for non-Sunday `week_start_date`.
- `tests/integration/test_api_qa.py` — in-scope answer, out-of-scope rejection,
  empty KB informational response.
- `tests/contract/test_openapi.py` — assert every response body validates against
  its schema in `openapi.yaml`.

**Known v1 limitations**:
- `POST /qa` is stateless — no session ID, no conversation history. Each request
  is fully independent; follow-up questions have no memory of prior answers.
  Multi-turn support upgrade path documented in `system_design.md §8`.
- No feedback mechanism — clients cannot rate or correct answers. Feedback
  endpoint upgrade path documented in `system_design.md §8`.

---

### Step 12 — Service entry point

**Files**: `src/main.py`

**Design references**:
- `quickstart.md` → startup command and expected log output
- `research.md §10` → FastAPI lifespan + APScheduler integration code pattern

**What to implement**:
- Import `app` from `api/app.py`; run via `uvicorn.run(app, ...)`.
- Lifespan initialises: DB engine → session factory → inception backfill check →
  scheduler start.
- Structured JSON logging configured at startup from `settings.LOG_LEVEL`.

**Tests first**: `tests/integration/test_pipeline.py` — end-to-end: seed a
controlled paper set, run pipeline, assert digest is retrievable via the daily
endpoint.

---

### Step 13 — Post-backfill HNSW index

**Timing**: Run once after inception backfill completes, before serving Q&A traffic.

**Design references**:
- `data-model.md` → Migration Notes (HNSW index creation SQL, `m=16 ef_construction=64`)
- `research.md §10` → pgvector HNSW vs IVFFlat decision rationale

**What to implement**:
- A standalone Alembic migration (separate from initial schema) that creates the
  HNSW index **only if the table has rows**, or a post-backfill hook in
  `jobs.py` that runs the `CREATE INDEX` SQL after backfill completes.

---

### Build order summary

```
Step 1  Config
Step 2  DB models + migrations
Step 3  LLM client
Step 4  arXiv Fetcher          ← depends on 2, 3
Step 5  Paper Processor        ← depends on 3, 4
Step 6  Groundbreaking Detector ← depends on 3, 5
Step 7  Daily Digest Generator  ← depends on 2, 3, 6
Step 8  Embedder + RAG Indexer  ← depends on 2, 7
Step 9  Scheduler + backfill    ← depends on 4–8
Step 10 Weekly Digest Generator ← depends on 7, 9
Step 11 API layer               ← depends on 2, 7, 8, 10
Step 12 Entry point             ← depends on 9, 11
Step 13 HNSW index              ← after backfill data exists
```

---

## Complexity Tracking

> No constitution violations identified. The following over-engineering was caught
> and removed during the post-Phase 1 constitution re-check:

| Removed | Why it was rejected | Simpler alternative used |
|---------|--------------------|-----------------------|
| `llm/sonnet.py` + `llm/haiku.py` | Two files for what is just a model name string — abstraction without concrete present use-case | Single `llm/client.py`; model name passed as argument to helper functions |
| `CoverageNote` ORM table | Always fetched with `WeeklyDigest`, no independent lifecycle — separate table adds a join with no benefit | Three array columns (`days_with_content`, `no_papers_skips`, `fetch_failure_skips`) inlined directly on `WeeklyDigest` |
| `TopicSection.position` | Derived data — `ORDER BY paper_count DESC` at query time gives identical ordering without a stored field | Removed; query-time ordering used |
| `DailyDigest.weekly_digest_id` FK | Adds write complexity (UPDATE up to 5 rows when weekly digest is generated); trivially derivable by date range at this scale | Removed; weekly generator queries `WHERE date BETWEEN week_start AND week_end` |
