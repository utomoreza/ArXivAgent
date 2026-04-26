# Research: ArXiv Intelligence Agent

**Phase**: 0 | **Date**: 2026-04-23 | **Last updated**: 2026-04-25 | **Plan**: [plan.md](plan.md)

All decisions below are resolved from the specification, system design, and
established library best practices. No NEEDS CLARIFICATION items remain.

> **Note**: Section 10 (Library API Notes) was substantially updated on 2026-04-25
> to reflect the pinned versions in `pyproject.toml`, which include several
> major-version bumps from training-data baselines. All API patterns in that
> section are confirmed against live docs or release notes fetched at update time.

---

## 1. arXiv Data Access

**Decision**: Use the `arxiv` Python library (v3.0.0) for metadata + `httpx` async for
HTML full text (`arxiv.org/html/{arxiv_id}`); fall back to `pdfplumber` for PDF
parsing when HTML is unavailable.

**Rationale**: The `arxiv` library wraps the arXiv API cleanly and returns
structured `Result` objects (title, authors, abstract, submission date, arXiv
ID). HTML full text at `arxiv.org/html/{id}` is available for most recent papers
and is far easier to parse than PDF. PDF parsing via `pdfplumber` is the
established fallback for older or rendering-unavailable papers.

**arxiv 3.0.0 breaking change — Client is now required**: In 3.x, `Search.results()`
was removed. A `Client` object must be instantiated and used to drive result
iteration. See Section 10 for the updated API pattern.

**Alternatives considered**:
- Semantic Scholar API: additional dependency, rate limits, not all arXiv papers
  indexed promptly.
- arXiv OAI-PMH feed: XML parsing complexity for no structural benefit over the
  `arxiv` library.

---

## 2. Scheduler: APScheduler Cron Setup

**Decision**: Use `APScheduler` with `AsyncIOScheduler` and `CronTrigger`.
Daily job: `CronTrigger(day_of_week='sun,mon,tue,wed,thu', hour=20, minute=30, timezone='America/New_York')`.
Weekly job: `CronTrigger(day_of_week='fri', hour=1, minute=0, timezone='America/New_York')`.

**Rationale**: `AsyncIOScheduler` runs in the same event loop as FastAPI,
avoiding thread-safety issues. `CronTrigger` with `timezone` handles ET/EDT
transitions automatically. The cron expression is also configurable via env vars
(`DAILY_SCHEDULER_TIME`, `WEEKLY_SCHEDULER_TIME`) as raw cron strings, allowing
override without code changes.

**Alternatives considered**:
- Celery + Redis: adds broker infrastructure dependency unnecessary for two cron
  jobs in v1.
- `asyncio.create_task` with sleep loops: fragile, does not handle DST correctly.

---

## 3. Inception Backfill Strategy

**Decision**: On service startup, check whether any `DateRecord` rows exist. If
the table is empty, run the full pipeline (Fetcher → Processor → Detector →
Daily Generator → RAG Indexer) for each date from `INCEPTION_DATE` to yesterday
in chronological order. After all daily dates are processed, run Weekly Generator
for each complete or partial Sun–Thu week in the backfill range. Then hand off
to the regular schedulers.

**Rationale**: Checking for empty `DateRecord` table is a reliable one-time
trigger — once backfill completes, records exist for every date and the check
short-circuits on all subsequent restarts.

**Alternatives considered**:
- Separate backfill CLI command: requires operator action on first deploy; easy
  to forget or mis-sequence.
- `BACKFILL_COMPLETE` flag in a config table: additional state to manage.

---

## 4. PostgreSQL + pgvector Setup

**Decision**: Single PostgreSQL 16 database with the `vector` extension enabled.
SQLAlchemy ORM with async engine (`asyncpg` driver). Alembic for migrations.
Vector columns use `pgvector`'s `Vector(384)` type (BAAI/bge-small-en-v1.5
produces 384-dimensional embeddings).

**Rationale**: Consolidates relational + vector storage in one service. pgvector's
`<=>` cosine distance operator is sufficient for semantic search over 100–500
papers/day. At this volume (~45k–180k chunks over 90 days), query latency is
well within the 10 s Q&A budget.

**Alternatives considered**:
- Qdrant/Weaviate as a separate vector DB: operational overhead of a second service
  in v1; designated as a future upgrade path if pgvector performance proves
  insufficient.

---

## 5. Embedding Model: BAAI/bge-small-en-v1.5

**Decision**: `sentence-transformers` library (v5.4.1), model `BAAI/bge-small-en-v1.5`,
384 dimensions. Run in-process synchronously; embed in batches during pipeline.

**Rationale**: bge-small-en-v1.5 scores well on MTEB for scientific/ML text
retrieval. At 384 dims it is compact enough to store in pgvector without index
bloat. Running locally eliminates per-call API cost; at 100–500 papers × 2
chunks each, embedding cost on a hosted API would accumulate.

**sentence-transformers 5.x API notes**: The `encode()` method's `sentences`
parameter was renamed to `inputs` (old name still accepted but triggers deprecation
warning). New specialized `encode_query()` / `encode_document()` methods exist for
retrieval tasks but are not required for bge-small. See Section 10 for updated
patterns.

**Alternatives considered**:
- OpenAI `text-embedding-3-small`: hosted, per-token cost, external dependency.
- `all-MiniLM-L6-v2`: good general performance but slightly lower quality on
  domain-specific scientific text than bge-small.

---

## 6. LLM Prompting Strategy

**Decision**: Two tiers.

| Task | Model | Why |
|------|-------|-----|
| Paper extraction (contributions, methodologies, benchmarks, institutions) | `claude-sonnet-4-6` | Requires reading comprehension + structured output |
| Groundbreaking detection + reasoning | `claude-sonnet-4-6` | Two-criterion eval + explanation generation |
| Daily digest Markdown generation | `claude-sonnet-4-6` | Long-form synthesis |
| Weekly digest synthesis (3 sections) | `claude-sonnet-4-6` | Cross-paper reasoning |
| Q&A answer generation | `claude-sonnet-4-6` | Grounded, cited responses |
| Topic classification | `claude-haiku-4-5-20251001` | Binary label from a fixed list; speed/cost matter |
| Out-of-scope query detection | `claude-haiku-4-5-20251001` | Binary classification; low latency required |

All LLM calls use structured output (Anthropic tool use / JSON mode) to guarantee
parseable responses. Retry on transient API errors up to 3 times.

---

## 7. RAG Retrieval Design

**Decision**: Cosine similarity search over pgvector with metadata pre-filters.
Window filter applied in SQL (`date >= now() - RAG_WINDOW_DAYS * interval '1 day'`).
Top-K retrieval (K=10 by default, configurable). Re-rank by date recency before
passing to the answer generation model.

**Rationale**: SQL-level window filter avoids loading out-of-window chunks into
the retrieval set. Cosine similarity on 384-dim vectors is fast at this scale.
Re-ranking by recency ensures that the answer generation model sees the most
relevant and recent context first.

**Two-chunk strategy per paper**:
- **Abstract chunk**: title + authors + institutions + abstract — handles "who
  wrote this", "what is this paper about" queries.
- **Content chunk**: title + contributions + methodologies + benchmarks +
  groundbreaking reasoning — handles "how does X work", "what benchmark did Y
  improve" queries.

**Known v1 limitation**: the content chunk is compressed by LLM extraction before
chunking (raw paper text never reaches the RAG layer), so the 50-page paper problem
is partially mitigated. However, for papers with multiple major contributions or
dense methodology descriptions, even the extracted summaries can approach or exceed
the 512-token cap, resulting in lossy truncation (benchmarks dropped first, then
methodologies). A finer-grained approach — three separate content chunks per paper
(contributions, methodologies, benchmarks) totalling 4 chunks per paper — would
eliminate truncation entirely and allow retrieval to target specific content types.
This is deferred to a future upgrade (see `system_design.md §8`).

---

## 8. API Response Schema

**Decision**: All API responses use a consistent envelope:

```json
{
  "status": "ok | skipped | no_announcement | not_found | not_available | pending | rejected | empty",
  "data": { ... } | null,
  "reason": "..." | null
}
```

Success responses set `status: "ok"` and populate `data`. All non-success states
set a `status` label and a human-readable `reason`; `data` is null. This matches
the Constitution III requirement for a single envelope schema.

---

## 9. Test Strategy

**Decision**:
- **Unit tests**: mock external I/O at system boundaries (arXiv HTTP calls, LLM
  API calls, DB session). Test business logic of each pipeline stage in isolation.
- **Integration tests**: use a real test PostgreSQL instance (via `pytest-asyncio`
  + SQLAlchemy). Mock arXiv HTTP and LLM API only. Verify all API response states
  (6 for daily digest, 3 for weekly, 3 for Q&A).
- **Contract tests**: verify API response shapes match `openapi.yaml` using
  `jsonschema` validation against actual endpoint responses.

External I/O mocking is limited to system boundaries (HTTP clients, Anthropic SDK
client). SQLAlchemy ORM layer is always tested against a real DB — no in-memory
SQLite substitution (per Constitution II: "mocking internal modules is prohibited").

---

## 10. Key Third-Party Library API Notes

Verified against live docs and release notes fetched 2026-04-25. All patterns
reflect the exact versions pinned in `pyproject.toml`.

---

### arxiv 3.0.0 ⚠️ BREAKING from 2.x

The `Search.results()` direct call was **removed** in 3.x. A `Client` object is
now required:

```python
import arxiv

# 2.x (REMOVED — do not use):
# results = arxiv.Search(query="cat:cs.LG", max_results=100).results()

# 3.x (correct):
client = arxiv.Client(
    page_size=100,
    delay_seconds=3.0,   # polite delay between API calls
    num_retries=3,
)
search = arxiv.Search(
    query="cat:cs.LG OR cat:cs.CV OR cat:cs.CL",
    max_results=500,
    sort_by=arxiv.SortCriterion.SubmittedDate,
)
for result in client.results(search):
    print(result.title, result.authors, result.summary, result.published, result.entry_id)
```

`Result` field names are **unchanged**: `.title`, `.authors`, `.summary`,
`.published`, `.entry_id`, `.categories` all remain the same.
`Client` accepts `page_size`, `delay_seconds`, and `num_retries` — use these
to control rate limiting and retry behaviour instead of our own retry loop for
arXiv API calls specifically.

---

### sentence-transformers 5.4.1 ⚠️ RENAMED PARAMS from 4.x

The `sentences` parameter to `encode()` was renamed to `inputs`. Old name still
works but triggers a deprecation warning — use `inputs` in new code.

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('BAAI/bge-small-en-v1.5')

# 5.x correct — use keyword 'inputs' not 'sentences':
embeddings = model.encode(
    inputs=texts,
    normalize_embeddings=True,
    batch_size=64,
)
# returns numpy array of shape (len(texts), 384)
```

Other 5.x changes (not blocking for this project):
- `encode_query()` / `encode_document()` added for asymmetric retrieval — not
  needed for bge-small which uses symmetric encoding.
- `encode_multi_process()` deprecated; multi-device via `device=[...]` param.
- `get_sentence_embedding_dimension()` → `get_embedding_dimension()` (old still
  works with deprecation warning).

---

### pytest-asyncio 1.3.0 ⚠️ BREAKING from 0.x

The `event_loop` fixture was **removed** in 1.0.0 (the biggest migration blocker).
`asyncio_mode = "auto"` in `[tool.pytest.ini_options]` **still works** in 1.x.

```toml
# pyproject.toml — no change needed:
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

Key behaviour change: scoped event loops (module-scoped, session-scoped) are now
created **once per scope** rather than once per test within that scope — tests
sharing a module-scoped loop now truly share the same loop instance.

Do **not** define a custom `event_loop` fixture — it is gone. Use
`@pytest.fixture(scope="module")` on async fixtures and set
`pytest.mark.asyncio(loop_scope="module")` or rely on `asyncio_mode = "auto"`.

Python 3.9 is dropped in 1.3.0 — Python 3.12 is fully supported.

---

### Anthropic SDK 0.97.0 — two structured output approaches

**Option A — `messages.parse()` with Pydantic (preferred for extraction tasks)**:

```python
from anthropic import AsyncAnthropic
from pydantic import BaseModel

class PaperExtraction(BaseModel):
    contributions: str
    methodologies: str
    benchmarks: str
    is_groundbreaking: bool
    groundbreaking_reasoning: str | None

client = AsyncAnthropic()

response = await client.messages.parse(
    model="claude-sonnet-4-6",
    max_tokens=2048,
    messages=[{"role": "user", "content": prompt}],
    output_format=PaperExtraction,
)
result: PaperExtraction = response.parsed_output
```

`messages.parse()` guarantees the response matches the Pydantic schema exactly —
no `json.loads()` or error handling for malformed JSON needed.

**Option B — `messages.create()` with tools (for agentic / multi-turn tasks)**:

```python
response = await client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=256,
    tools=[{
        "name": "classify_topic",
        "description": "Assign the paper's primary research topic",
        "input_schema": {
            "type": "object",
            "properties": {"topic": {"type": "string", "enum": TOPIC_LIST}},
            "required": ["topic"],
        },
    }],
    tool_choice={"type": "tool", "name": "classify_topic"},
    messages=[{"role": "user", "content": prompt}],
)
topic = response.content[0].input["topic"]
```

Add `strict=True` to any tool definition to enforce exact schema conformance.

**Recommendation for this project**: Use `messages.parse()` (Option A) for all
extraction and detection tasks. Use `messages.create()` with `tools=` only where
multi-turn or agentic behaviour is needed. Both use `AsyncAnthropic()` client.

---

### pgvector 0.4.2 — asyncpg registration changed from 0.3.x

`from pgvector.sqlalchemy import Vector` and `cosine_distance()` are **unchanged**.

Key change in 0.4.x: `register_vector()` per-connection call is **no longer
needed** for asyncpg. pgvector-python now hooks into SQLAlchemy's asyncpg dialect
automatically when the `Vector` type is present in the metadata.

```python
# 0.3.x (do NOT use — manual per-connection registration removed):
# from pgvector.asyncpg import register_vector
# await register_vector(conn)

# 0.4.x (correct — nothing extra needed beyond declaring Vector columns):
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

class PaperEmbedding(Base):
    __tablename__ = "paper_embeddings"
    embedding = Column(Vector(384), nullable=False)

# Cosine similarity query — unchanged:
from sqlalchemy import select
stmt = (
    select(PaperEmbedding)
    .order_by(PaperEmbedding.embedding.cosine_distance(query_vector))
    .limit(10)
)
results = await session.execute(stmt)
```

**Index choice**: Use HNSW (not IVFFlat) for ~180k vectors at 384 dims.
HNSW gives better recall and query latency without `lists` tuning:

```sql
CREATE INDEX ON paper_embeddings
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

Create this index **after** initial backfill data is loaded, not in the Alembic
migration (building HNSW on an empty table provides no benefit).

---

### APScheduler 3.11.2 — no breaking changes from 3.10.x

The 3.x API is stable. The major break is between **3.x and 4.x** (4.x is a
complete rewrite — we pin 3.11.2 and are unaffected).

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import os

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Add jobs before starting
    scheduler.add_job(
        daily_pipeline,
        trigger=CronTrigger.from_crontab(
            os.environ["DAILY_SCHEDULER_TIME"],   # "30 20 * * 0,1,2,3,4"
            timezone="America/New_York",
        ),
    )
    scheduler.add_job(
        weekly_pipeline,
        trigger=CronTrigger.from_crontab(
            os.environ["WEEKLY_SCHEDULER_TIME"],  # "0 1 * * 5"
            timezone="America/New_York",
        ),
    )
    scheduler.start()          # synchronous — do NOT await
    yield
    scheduler.shutdown(wait=False)

app = FastAPI(lifespan=lifespan)
```

`CronTrigger.from_crontab(cron_string, timezone=...)` parses standard 5-field
cron strings from env vars and handles ET/EDT timezone transitions automatically.

---

### FastAPI 0.136.x + SQLAlchemy 2.0.49 async session

**Lifespan pattern** (replaces deprecated `@app.on_event`):

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

engine = None
session_factory = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, session_factory
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield
    await engine.dispose()

app = FastAPI(lifespan=lifespan)

async def get_session() -> AsyncSession:
    async with session_factory() as session:
        yield session

@app.get("/example")
async def example(session: AsyncSession = Depends(get_session)):
    ...
```

**ORM model base** — `DeclarativeBase` is correct for SQLAlchemy 2.0:

```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class Paper(Base):
    __tablename__ = "papers"
    arxiv_id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str]
```

**Alembic async env.py** — `env.py` must use `run_async_migrations()`:

```python
# migrations/env.py
import asyncio
from sqlalchemy.ext.asyncio import async_engine_from_config

def run_migrations_online():
    connectable = async_engine_from_config(config.get_section(config.config_ini_section))
    asyncio.run(run_async_migrations(connectable))

async def run_async_migrations(connectable):
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
```
