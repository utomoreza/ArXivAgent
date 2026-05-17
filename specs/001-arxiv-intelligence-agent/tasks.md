# Tasks: ArXiv Intelligence Agent

**Input**: Design documents from `specs/001-arxiv-intelligence-agent/`
**Branch**: `001-arxiv-intelligence-agent`
**Generated**: 2026-04-25

**Prerequisites read**:
- `plan.md` — tech stack, library versions, project structure, implementation sequence
- `spec.md` — three user stories (P1 Daily Digest, P2 Groundbreaking Detection, P3 Q&A RAG)
- `data-model.md` — 5 entities: Paper, DateRecord, DailyDigest, TopicSection, WeeklyDigest, PaperEmbedding
- `contracts/openapi.yaml` — 3 endpoints, all response schemas
- `research.md` — confirmed API patterns for all pinned library versions
- `quickstart.md` — environment setup and run steps

## Definition of Done

**A task is not complete (`[X]`) until ALL of the following hold:**

1. All tests in the associated test file(s) pass (`0 failed, 0 error`).
2. The implemented source file has **100% line and branch coverage**
   (`Miss = 0`, `BrPart = 0`) when measured with:
   ```
   uv run pytest <test_file> --cov=src/<module> --cov-report=term-missing
   ```
3. `uv run ruff check src/ tests/` reports no violations.

Coverage exclusions (do not need 100%): `src/migrations/*`, `src/main.py`,
all `__init__.py` files. Everything else must be fully covered before the
task is marked complete.

---

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel with other [P] tasks in the same phase
- **[Story]**: User story this task belongs to (US1, US2, US3)
- All paths are relative to the repository root

---

## Phase 1: Setup

**Purpose**: Scaffold the project, install dependencies, and configure tooling.
No user story work can begin before this phase.
**Gate**: Every task in this phase must satisfy the Definition of Done above before Phase 2 begins.

- [X] T001 Initialise uv project: run `uv sync` to install all dependencies from `pyproject.toml` and generate `uv.lock`
- [X] T002 Create directory structure under `src/` and `tests/` exactly as shown in `plan.md` → Project Structure (all `__init__.py` files included)
- [X] T003 [P] Create `src/config.py` — Pydantic `Settings` class covering all env vars listed in `plan.md` → Technical Context (`INCEPTION_DATE`, `DATABASE_URL`, `ANTHROPIC_API_KEY`, `RAG_WINDOW_DAYS`, `ARXIV_CATEGORIES`, `TOPIC_LIST`, `DAILY_SCHEDULER_TIME`, `WEEKLY_SCHEDULER_TIME`, `LOG_LEVEL`); see `CLAUDE.md` → Required Environment Variables for defaults
- [X] T004 [P] Create `.env.example` with all required vars, placeholder values, and inline comments matching `CLAUDE.md` → Required Environment Variables
- [X] T005 [P] Configure `ruff` in `pyproject.toml` — linting and formatting rules are already present; verify `uv run ruff check src/ tests/` passes on empty source tree
- [X] T006 [P] Write `tests/unit/test_config.py` **(test first)**:
  - **`INCEPTION_DATE`**: missing raises `ValidationError`; parametrized invalid formats (wrong separators, out-of-range values, non-string types) all raise `ValidationError`; valid ISO string parses to `datetime.date` object
  - **`ANTHROPIC_API_KEY`**: missing raises `ValidationError`; empty string and non-string types rejected
  - **`DATABASE_URL`**: missing raises `ValidationError`; valid `postgresql+asyncpg://` URLs with host/port/path variants accepted; non-asyncpg schemes (`postgresql://`, `sqlite://`), special chars in credentials, empty string, and non-string types rejected
  - **`RAG_WINDOW_DAYS`**: defaults to `_DEFAULT_RAG_WINDOW_DAYS`; non-negative int and numeric string accepted; negative values (int and string) rejected; floats and empty string rejected
  - **`TOPIC_LIST`**: defaults to `_DEFAULT_TOPIC_LIST`; comma-separated string parses to list; single-topic string produces one-element list; whitespace stripped per entry; each entry title-cased; empty string and non-string types rejected
  - **`ARXIV_CATEGORIES`**: defaults to `_DEFAULT_ARXIV_CATEGORIES`; comma-separated `cs.XX` format accepted; whitespace stripped per entry; wrong case, numeric, empty, and non-string inputs rejected (parametrized)
  - **`DAILY_SCHEDULER_TIME`**: defaults to `_DEFAULT_DAILY_SCHEDULER_TIME`; non-string and empty string rejected; invalid cron expressions (6-field, 4-field, out-of-range values) rejected
  - **`WEEKLY_SCHEDULER_TIME`**: same validation shape as `DAILY_SCHEDULER_TIME`
  - **`LOG_LEVEL`**: defaults to `_DEFAULT_LOG_LEVEL`; all valid `Literal` options accepted; arbitrary strings, numbers, and empty string rejected

---

## Phase 2: Foundation (Blocking Prerequisites)

**Purpose**: Database layer, LLM client, and arXiv fetcher. Every user story
depends on these. **No Phase 3+ work can begin until this phase is complete.**
**Gate**: Every task in this phase must satisfy the Definition of Done above before Phase 3 begins.

**⚠️ CRITICAL**: Complete in task order — ORM models before migrations, session
before LLM client, fetcher last.

### Database

- [X] T007 Write `tests/integration/test_db_models.py` **(test first)**:
  - **DateRecord CHECK**: rejects `paper_count` when `status != 'published'`; accepts `NULL` paper_count on non-published rows; accepts `paper_count >= 0` on `published` rows
  - **Paper CHECK**: rejects `is_groundbreaking=True` with `NULL` reasoning; rejects `is_groundbreaking=False` with non-null reasoning; accepts both valid combinations
  - **FK violations** (ordered before fixtures that depend on them): `Paper.submitted_date → DateRecord.date`; `TopicSection.digest_id → DailyDigest.id`; `DailyDigest.date → DateRecord.date`; `PaperEmbedding.arxiv_id → Paper.arxiv_id`
  - **DailyDigest CHECK**: rejects `paper_count = 0`; accepts `paper_count > 0` (parametrized)
  - **DailyDigest UNIQUE**: rejects duplicate `date` with distinct PKs
  - **WeeklyDigest CHECK**: rejects `paper_count = 0`; accepts `paper_count > 0` (parametrized)
  - **WeeklyDigest UNIQUE**: rejects duplicate `week_start` with distinct PKs
  - **WeeklyDigest CHECK** (parametrized over all 6 non-Sunday days): rejects `week_start` that is not a Sunday
  - **WeeklyDigest CHECK** (parametrized over all 5 non-Thursday days): rejects `week_end` that is not a Thursday
  - **PaperEmbedding ENUM**: rejects invalid `chunk_type` value outside `('abstract', 'content')`
  - **PaperEmbedding UNIQUE**: rejects duplicate `(arxiv_id, chunk_type)` with distinct PKs — enforces 1:2 fixed cardinality
  - **PaperEmbedding happy path**: both `abstract` and `content` chunk types accepted for a valid parent `Paper`
  - See `data-model.md` → Entities and Constraints for full constraint definitions
- [X] T008 Create `src/db/models.py` — all ORM classes using `DeclarativeBase` and `Mapped`/`mapped_column` (SQLAlchemy 2.0 style); implement in dependency order: `DateRecord` → `DailyDigest` → `TopicSection` → `WeeklyDigest` → `Paper` → `PaperEmbedding`; column types, enums (`date_status`, `chunk_type`), FKs, and all indexes exactly as specified in `data-model.md` → Entities; use `Vector(384)` from `pgvector.sqlalchemy` for `PaperEmbedding.embedding`; see `research.md §10` → pgvector 0.4.x for correct import; shared DB strings (enum values, constraint expressions, constraint names, index names) centralised in `src/db/forms.py`
- [X] T009 Create `src/db/session.py` — `create_async_engine`, `async_sessionmaker`, and `get_session` async dependency function; see `research.md §10` → FastAPI + SQLAlchemy async session pattern
- [X] T010 Create `src/migrations/env.py` — async Alembic runner using `async_engine_from_config` and `run_sync`; DATABASE_URL injected from `get_settings()` at migration time; see `research.md §10` → Alembic async env.py pattern; `alembic.ini` created at project root with `script_location = src/migrations`
- [X] T011 Create initial Alembic revision `src/migrations/versions/0001_initial.py` — creates `date_status` and `chunk_type` enums first, then enables `vector` extension, then all tables and B-tree indexes; `paper_embeddings` created via raw SQL to support `vector(384)` type; **does NOT create HNSW vector index** (created post-backfill); all constraint/index names imported from `src/db/forms.py`; see `data-model.md` → Migration Notes for ordering rules

### LLM Client

- [X] T012 Write `tests/unit/test_llm_client.py` **(test first)**: mock `AsyncAnthropic`; assert retry fires 3 times on `anthropic.APIError`; assert correct model string is forwarded; assert structured parse returns typed Pydantic output
- [X] T013 Create `src/llm/client.py` — single `AsyncAnthropic()` instance; `parse_structured(model, prompt, output_schema)` wrapping `messages.parse(output_format=schema)`; `classify(model, prompt, tool_def)` wrapping `messages.create(tools=[tool_def], tool_choice={"type":"tool",...})`; 3-attempt exponential-backoff retry on `anthropic.APIError`; structured JSON logging at DEBUG on entry and INFO/ERROR on exit with elapsed time; see `research.md §10` → Anthropic SDK 0.97.0 for both method signatures; see `research.md §6` for Sonnet vs Haiku task mapping

### arXiv Fetcher

- [X] T014 Write `tests/unit/test_fetcher.py` **(test first)**: mock `arxiv.Client`; assert Fri/Sat input writes `no_announcement` `DateRecord` without calling the arXiv API; assert successful fetch writes `published` `DateRecord` and returns paper list; assert 3 consecutive API failures write `fetch_failure_skip`; assert `no_papers_skip` written when API returns empty list
- [X] T015 Create `src/pipeline/fetcher.py` — `fetch_papers(date, session) -> FetchResult`; instantiate `arxiv.Client(page_size=100, delay_seconds=3.0, num_retries=3)`; build `arxiv.Search` filtered by `settings.ARXIV_CATEGORIES`; iterate via `client.results(search)` (**not** `search.results()` — see `research.md §10` → arxiv 3.0.0 breaking change); guard Fri/Sat before any network call; implement 3-attempt retry with exponential backoff; write `DateRecord` for all four outcomes; see `spec.md FR-001` and `system_design.md §3.2`

---

## Phase 3: User Story 1 — Daily Research Digest (Priority: P1) 🎯 MVP

**Goal**: Fetch arXiv papers on schedule, extract structured content, generate
daily and weekly digests, and serve them via the digest endpoint.
**Gate**: Every task in this phase must satisfy the Definition of Done above before Phase 4/5 begins.

**Independent Test** (from `spec.md` US1): Trigger a digest generation run;
verify a structured digest document is produced with papers grouped by topic,
each containing summary, key contributions, methodology notes, and benchmark
results. Retrieve it via `GET /digests/daily/{date}` and confirm the response
matches `contracts/openapi.yaml` → `DailyDigest` schema.

### Paper Processor

- [X] T016 Write `tests/unit/test_processor.py` **(test first)**: mock `httpx.AsyncClient` and `llm.client`; assert `primary_topic` is always one member of `settings.TOPIC_LIST`; assert `groundbreaking_reasoning` is null when `is_groundbreaking=False`; assert HTML fetch is attempted before PDF fallback; assert paper is persisted to DB
- [X] T017 [US1] Create `src/pipeline/processor.py` — `process_paper(result: arxiv.Result, session) -> Paper`; fetch HTML from `arxiv.org/html/{arxiv_id}` via `httpx.AsyncClient`; fall back to `pdfplumber` PDF parse if HTML returns non-200; define Pydantic extraction schema `{contributions, methodologies, benchmarks, institutions}`; call `llm.client.parse_structured(model=SONNET, ...)` for extraction; call `llm.client.classify(model=HAIKU, ...)` with topic enum tool for `primary_topic`; persist `Paper` row; see `system_design.md §3.3`, `data-model.md` → Paper entity, `research.md §6` for model tier assignments

### Groundbreaking Detector (needed by Daily Digest Generator)

- [X] T018 Write `tests/unit/test_detector.py` **(test first)**: mock LLM; assert paper with both criteria (benchmark improvement + novel architecture) is flagged with non-empty reasoning in format "Improves {benchmark}; introduces {novel element}"; assert paper failing either criterion alone is NOT flagged; assert no partial flag state exists; see `spec.md FR-011`
- [X] T019 [US1] Create `src/pipeline/detector.py` — `detect_groundbreaking(paper: Paper, session) -> None`; define Pydantic schema `{is_groundbreaking: bool, benchmark_improved: str|None, novel_element: str|None}`; call Sonnet via `messages.parse()`; set `paper.is_groundbreaking` and assemble reasoning string `"Improves {benchmark}; introduces {novel_element}."` only when both fields are non-null; persist update; see `spec.md FR-004, FR-011`, `system_design.md §3.4`

### Daily Digest Generator

- [X] T020 Write `tests/unit/test_daily_generator.py` **(test first)**: mock LLM and DB; assert no digest is produced when `DateRecord.status != 'published'`; assert all papers are assigned `topic_section_id` after generation; assert `groundbreaking_count` exactly matches papers with `is_groundbreaking=True`; assert topics are returned ordered by `paper_count DESC`
- [X] T021 [US1] Create `src/pipeline/daily_generator.py` — `generate_daily_digest(date, session) -> DailyDigest | None`; skip immediately if `DateRecord.status != 'published'`; group papers by `primary_topic`; call Sonnet via `messages.parse()` to render Markdown `body` per topic group; persist `DailyDigest` + `TopicSection` rows; update `Paper.topic_section_id` for every paper; retrieve topics ordered by `paper_count DESC` (no stored position field); see `system_design.md §3.5`, `data-model.md` → DailyDigest + TopicSection, `contracts/openapi.yaml` → DailyDigest schema

### Weekly Digest Generator

- [X] T022 Write `tests/unit/test_weekly_generator.py` **(test first)**: mock LLM; assert `fetch_failure_skip` dates appear in `fetch_failure_skips` array and NOT in `no_papers_skips`; assert week with zero daily digests returns `None`; assert all three Markdown sections (`benchmark_comparisons`, `trend_synthesis`, `cross_paper_analysis`) are non-empty when daily digests exist; assert `week_start` must be a Sunday
- [X] T023 [US1] Create `src/pipeline/weekly_generator.py` — `generate_weekly_digest(week_start: date, session) -> WeeklyDigest | None`; derive `week_end = week_start + timedelta(days=4)`; query daily digests via `WHERE date BETWEEN week_start AND week_end` (**no FK** — date range query); return `None` if no digests found; call Sonnet for each of three synthesis sections separately; build coverage arrays from `DateRecord` statuses for the week window; persist `WeeklyDigest` with inlined coverage fields; see `system_design.md §3.6`, `spec.md FR-006, FR-012`, `data-model.md` → WeeklyDigest entity

### Scheduler & Inception Backfill

- [X] T024 Write `tests/unit/test_scheduler.py` **(test first)**: mock full pipeline; assert backfill writes `no_announcement` for every Fri/Sat in the range without calling the pipeline; assert backfill does not re-run when `DateRecord` rows already exist (idempotent); assert weekly generator is called once per complete or partial Sun–Thu week; assert daily job cron string matches `DAILY_SCHEDULER_TIME` env var
- [X] T025 [US1] Create `src/scheduler/jobs.py` — `setup_scheduler(scheduler, session_factory)` registers daily and weekly jobs via `CronTrigger.from_crontab(settings.DAILY_SCHEDULER_TIME, timezone="America/New_York")` and `CronTrigger.from_crontab(settings.WEEKLY_SCHEDULER_TIME, timezone="America/New_York")`; `run_inception_backfill(session_factory)` checks `DateRecord` table — exits immediately if any rows exist; otherwise iterates `INCEPTION_DATE` → yesterday chronologically, writes `no_announcement` for Fri/Sat, runs full pipeline per announcement day, then runs `generate_weekly_digest` per historical Sun–Thu week in order; see `research.md §2, §3, §10` → APScheduler pattern, `spec.md FR-001, FR-006`, `system_design.md §3.1`

### API — Digest Endpoints

- [X] T026 Write `tests/integration/test_api_digests.py` **(test first)**: seed `DateRecord` rows for each of the 6 daily states; assert each state returns correct `status` string and `reason` per `contracts/openapi.yaml` examples; assert non-Sunday `week_start_date` returns 400; assert pending week returns `status: "pending"`; assert existing weekly digest returns full document with all three sections and coverage arrays
- [X] T027 [P] [US1] Create `src/api/schemas.py` — Pydantic models for every schema in `contracts/openapi.yaml`: `DailyDigestData`, `TopicSectionData`, `WeeklyDigestData`, `WeeklySectionsData`, response envelopes (`DailyDigestResponse`, `SkippedResponse`, `FetchFailureResponse`, `NoAnnouncementResponse`, `NotFoundResponse`, `NotAvailableResponse`, `PendingResponse`, `WeeklyDigestResponse`); all field names must match `contracts/openapi.yaml` exactly; see `research.md §8` for envelope structure
- [X] T028 [US1] Create `src/api/routers/digests.py` — `GET /digests/daily/{date}`: look up `DateRecord`, return correct envelope for all 6 states including pre-`INCEPTION_DATE` and future-date guards; `GET /digests/weekly/{week_start_date}`: validate `week_start_date` is a Sunday (400 otherwise), check if week is still in progress, return weekly digest or pending state; see `system_design.md §3.8`, `contracts/openapi.yaml` → paths section

### Service Entry Point (US1 milestone)

- [ ] T029 [US1] Create `src/api/app.py` — FastAPI app factory with `@asynccontextmanager lifespan`: initialise DB engine → `async_sessionmaker` → run inception backfill check → start `AsyncIOScheduler`; shutdown disposes engine and calls `scheduler.shutdown(wait=False)`; do NOT `await scheduler.start()`; see `research.md §10` → FastAPI lifespan + APScheduler pattern
- [ ] T030 [US1] Create `src/main.py` — import `app` from `api/app.py`; configure structured JSON logging from `settings.LOG_LEVEL` at startup; run via `uvicorn.run(app, host="0.0.0.0", port=8000)`; see `quickstart.md` → Run the Service for expected log output

### US1 Integration & Contract Tests

- [ ] T031 [US1] Write `tests/integration/test_pipeline.py` — end-to-end: mock arXiv HTTP + LLM; seed one day's papers; run `fetch_papers` → `process_paper` → `detect_groundbreaking` → `generate_daily_digest`; assert digest retrievable via `GET /digests/daily/{date}` with `status: "ok"`; assert `groundbreaking_count` correct
- [ ] T032 [US1] Write `tests/contract/test_openapi.py` — validate every response body from all endpoints against the corresponding schema in `contracts/openapi.yaml` using `jsonschema`; test all 6 daily states, all 3 weekly states, and all 3 Q&A states; see `contracts/openapi.yaml` → components/schemas

---

## Phase 4: User Story 2 — Groundbreaking Paper Detection (Priority: P2)

**Goal**: Ensure groundbreaking papers are visually distinguished in digests with
their reasoning displayed, and that detection accuracy is independently verifiable.
**Gate**: Every task in this phase must satisfy the Definition of Done above before Phase 6 begins.

**Independent Test** (from `spec.md` US2): Provide a controlled set of papers
with known significance levels; verify papers meeting both criteria (benchmark
improvement AND novel architecture) are flagged with non-empty reasoning;
verify papers failing either criterion are NOT flagged. Check the daily digest
response to confirm groundbreaking papers include `is_groundbreaking: true` and
reasoning in the topic body Markdown.

*Note: `detector.py` was already implemented in Phase 3 (T018–T019) as a
prerequisite for the digest generator. This phase adds the acceptance-level
verification and digest presentation layer.*

- [ ] T033 [US2] Write `tests/integration/test_groundbreaking.py` — acceptance test with controlled paper fixtures: two papers meeting both criteria, two meeting one criterion only, two meeting neither; run full pipeline; assert exactly the two qualifying papers have `is_groundbreaking=True` with non-empty `groundbreaking_reasoning`; assert the others have `is_groundbreaking=False` and null reasoning; assert `groundbreaking_count` in digest response equals 2; assert false-positive rate across sample is below 10% (SC-003)
- [ ] T034 [P] [US2] Update `src/pipeline/daily_generator.py` — ensure Markdown `body` generated per `TopicSection` visually distinguishes groundbreaking papers: include the `groundbreaking_reasoning` string as a callout or highlighted block within the rendered Markdown for each flagged paper; see `spec.md` US2 Acceptance Scenario 3
- [ ] T035 [P] [US2] Update `src/api/schemas.py` — confirm `TopicSectionData.body` field description notes it may contain groundbreaking callouts; no schema change needed if `body` is already `str`, but verify the `groundbreaking_count` field propagates correctly through the response envelope for both daily and weekly digests

---

## Phase 5: User Story 3 — Digest Q&A via RAG (Priority: P3)

**Goal**: Allow researchers to ask natural language questions about digests and
receive grounded, cited answers; reject out-of-scope questions; return an
informational message when the knowledge base is empty.
**Gate**: Every task in this phase must satisfy the Definition of Done above before Phase 6 begins.

**Independent Test** (from `spec.md` US3): Ingest a completed digest into the
vector store; submit three in-scope questions; verify each answer cites specific
papers; submit two out-of-scope questions; verify each is rejected with
`status: "rejected"`; empty the window; verify `status: "empty"` response.

### Embedder & RAG Indexer

- [ ] T036 Write `tests/unit/test_embedder.py` **(test first)**: assert `embed()` returns numpy array of shape `(n, 384)`; assert `normalize_embeddings=True` is passed (vectors should have unit norm); assert `inputs=` keyword is used (not deprecated `sentences=`); see `research.md §10` → sentence-transformers 5.4.1
- [ ] T037 [P] [US3] Create `src/rag/embedder.py` — load `SentenceTransformer('BAAI/bge-small-en-v1.5')` once at module level; `embed(texts: list[str]) -> np.ndarray` calls `model.encode(inputs=texts, normalize_embeddings=True, batch_size=64)`; see `research.md §5, §10`
- [ ] T038 Write `tests/unit/test_rag_indexer.py` **(test first)**: assert exactly 2 `PaperEmbedding` rows created per paper (one `abstract`, one `content`); assert abstract chunk never truncates; assert content chunk truncation order is benchmarks → methodologies → contributions when over 512 tokens; assert all denormalized metadata fields are populated; see `data-model.md` → PaperEmbedding
- [ ] T039 [US3] Create `src/pipeline/rag_indexer.py` — `index_paper(paper: Paper, session) -> None`; build abstract chunk text: `title + authors + institutions + abstract`; build content chunk text: `title + contributions + methodologies + benchmarks + groundbreaking_reasoning`; truncate content chunk to 512 tokens (truncate benchmarks first, then methodologies, then contributions); call `embedder.embed()` for both chunks; persist two `PaperEmbedding` rows with all denormalized fields from `data-model.md` → PaperEmbedding entity; see `research.md §7` for chunking rationale

### RAG Retriever

- [ ] T040 Write `tests/unit/test_retriever.py` **(test first)**: mock DB; assert window filter excludes embeddings outside `RAG_WINDOW_DAYS`; assert results are re-ranked by date descending after cosine retrieval; assert top-K is respected; assert empty result set (no in-window embeddings) returns empty list without error
- [ ] T041 [US3] Create `src/rag/retriever.py` — `retrieve(question: str, session, window_days: int, k: int = 10) -> list[PaperEmbedding]`; embed question via `embedder.embed([question])[0]`; query pgvector with `ORDER BY embedding.cosine_distance(query_vec)` and SQL date filter `WHERE date >= now() - window_days * interval '1 day'`; re-rank by `date DESC`; return top-K; see `research.md §7, §10` → pgvector cosine_distance usage

### Q&A API Endpoint

- [ ] T042 Write `tests/integration/test_api_qa.py` **(test first)**: seed vector store with 5 paper embeddings; assert in-scope question returns `status: "ok"` with non-empty `answer` and at least one `source`; assert out-of-scope question ("What is the weather in Paris?") returns `status: "rejected"` with correct reason message; assert empty knowledge base (no in-window embeddings) returns `status: "empty"` with correct reason message; see `contracts/openapi.yaml` → POST /qa response schemas and `spec.md FR-008, FR-009`
- [ ] T043 [US3] Create `src/api/routers/qa.py` — `POST /qa`; accept `QARequest{question: str}`; first call `llm.client.classify(model=HAIKU, ...)` for scope check — return `RejectedResponse` immediately if out-of-scope; then call `retriever.retrieve()`; if result list is empty, return `EmptyKBResponse`; otherwise call `llm.client.parse_structured(model=SONNET, ...)` with retrieved chunks as context to generate `QAAnswer{answer, sources}`; return `QAResponse`; see `system_design.md §3.8`, `contracts/openapi.yaml` → POST /qa, `research.md §6`
- [ ] T044 [US3] Register `qa` router in `src/api/app.py` and add `QARequest`, `QAResponse`, `RejectedResponse`, `EmptyKBResponse` to `src/api/schemas.py`; ensure schemas match `contracts/openapi.yaml` → QARequest, QAAnswer, QASource schemas exactly

### Pipeline Integration — RAG Indexer Hook

- [ ] T045 [US3] Update `src/pipeline/daily_generator.py` — after persisting `DailyDigest`, call `rag_indexer.index_paper(paper, session)` for each paper whose `submitted_date` falls within `RAG_WINDOW_DAYS`; ensure this is called AFTER `Paper.topic_section_id` is set; see `system_design.md §5.1` happy path flow

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Observability, performance validation, and post-backfill index
creation. These complete the system but do not unlock any new user story.
**Gate**: Every task in this phase must satisfy the Definition of Done above before the feature branch is merged.

- [ ] T046 [P] Add structured JSON logging to all pipeline components (`fetcher.py`, `processor.py`, `detector.py`, `daily_generator.py`, `weekly_generator.py`, `rag_indexer.py`) — DEBUG on entry, INFO on success with elapsed time, ERROR on failure; every external call (arXiv API, LLM API, DB write) must emit at least one log entry; see `CLAUDE.md` constitution Principle V and `research.md §10` → logging requirement
- [ ] T047 [P] Add structured JSON logging to `src/api/routers/digests.py` and `src/api/routers/qa.py` — log each request at DEBUG with endpoint + params; log response status at INFO with elapsed time
- [ ] T048 [P] Write `tests/integration/test_performance.py` — assert `GET /digests/daily/{date}` responds within 2 s at p95 (SC-006); assert `POST /qa` responds within 10 s for in-scope question with seeded vector store (SC-007); assert paper batch processing throughput ≥ 10 papers/s (Constitution IV); see `plan.md` → Performance Goals
- [ ] T049 Create post-backfill HNSW index migration `migrations/versions/0002_hnsw_index.py` — runs `CREATE INDEX ON paper_embeddings USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)` only after confirming table has rows; alternatively add a post-backfill hook in `src/scheduler/jobs.py` that runs this SQL after `run_inception_backfill` completes; see `data-model.md` → Migration Notes and `research.md §10` → pgvector HNSW decision

---

## Dependencies

```
Phase 1 (Setup)
  └── Phase 2 (Foundation: DB + LLM + Fetcher)
        └── Phase 3 (US1: Digest pipeline + endpoints)  ← MVP
              ├── Phase 4 (US2: Groundbreaking verification)
              ├── Phase 5 (US3: RAG Q&A)
              └── Phase 6 (Polish)
```

US2 and US3 can be worked in parallel after Phase 3 is complete.

---

## Parallel Execution (within each phase)

**Phase 1**: T003, T004, T005, T006 can all run in parallel after T001–T002.

**Phase 2**:
- DB tasks (T007–T011) must be sequential.
- T012–T013 (LLM client) can run in parallel with T007–T011.
- T014–T015 (Fetcher) depends on T008 (models) and T013 (LLM client).

**Phase 3**:
- T016–T019 (Processor + Detector) can run in parallel with each other after Phase 2.
- T020–T021 (Daily Generator) depends on T019.
- T022–T023 (Weekly Generator) can run in parallel with T020–T021.
- T024–T025 (Scheduler) depends on T021 + T023.
- T027 (schemas.py) can run in parallel with T026.
- T029–T030 (app + main) depend on T025 + T028.

**Phase 4**: T034 and T035 can run in parallel.

**Phase 5**: T036–T037 (embedder) can run in parallel with T038–T039 (indexer).
T040–T041 (retriever) depends on T037. T042–T044 depends on T041.

**Phase 6**: T046, T047, T048 all run in parallel.

---

## Implementation Strategy

**MVP = Phase 1 + Phase 2 + Phase 3** (T001–T032)

This delivers the full US1 value: papers fetched, processed, and digested daily
and weekly, served via API with all six date-state responses correctly handled.

US2 (T033–T035) adds groundbreaking detection acceptance verification on top.
US3 (T036–T045) adds the Q&A interface on top of the existing digest store.
Phase 6 (T046–T049) completes observability, performance gates, and the HNSW index.

**Total tasks**: 49
**Tasks by story**: US1 = 26 (T007–T032), US2 = 3 (T033–T035), US3 = 10 (T036–T045), Setup/Foundation/Polish = 10
**Test-first tasks**: T006, T007, T012, T014, T016, T018, T020, T022, T024, T026, T031, T032, T033, T036, T038, T040, T042, T048 (18 total)
