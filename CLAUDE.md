<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
at `specs/001-arxiv-intelligence-agent/plan.md`.
<!-- SPECKIT END -->

# ArXivAgent — Project Context

## What This Project Is

ArXivAgent is an always-on background service that monitors arXiv daily, synthesizes
ML research papers into structured digests, and exposes those digests — plus a
conversational RAG Q&A interface — through HTTP endpoints.

## Active Feature

**001-arxiv-intelligence-agent** (branch: `001-arxiv-intelligence-agent`)

| Artifact | Path |
|----------|------|
| Specification | `specs/001-arxiv-intelligence-agent/spec.md` |
| System Design | `specs/001-arxiv-intelligence-agent/system_design.md` |
| Implementation Plan | `specs/001-arxiv-intelligence-agent/plan.md` *(not yet created)* |
| Tasks | `specs/001-arxiv-intelligence-agent/tasks.md` *(not yet created)* |

## Critical Design Constraints

These are non-obvious decisions already made — do not second-guess them without
reading the spec/system design first.

### arXiv Announcement Schedule

arXiv publishes new listings at **20:00 ET, Sunday through Thursday only**.
Fridays and Saturdays have **no announcements** — this is a structural property
of arXiv, not a failure condition.

| Scheduler | Time | Covers |
|-----------|------|--------|
| Daily | 20:30 ET, Sun–Thu | That day's arXiv announcement |
| Weekly | 01:00 ET, Friday | Prior Sun–Thu digest window |

### Four Date States (not two, not three)

Every calendar date has exactly one of these states — they are mutually exclusive
and all must be handled distinctly by the API:

| State | Meaning | API response |
|-------|---------|--------------|
| `published` | Digest generated successfully | Digest document |
| `no_announcement` | Friday or Saturday — arXiv never publishes | "arXiv does not publish on Fridays or Saturdays." |
| `no_papers_skip` | Announcement day, arXiv reachable, 0 papers | "No new papers were published on this date." |
| `fetch_failure_skip` | Announcement day, all 3 retries failed | "Data retrieval from arXiv failed after 3 attempts on this date." |

### Weekly Digest Window

The weekly digest covers **Sunday through Thursday** (the 5 arXiv announcement
days), not Monday–Sunday. Fridays and Saturdays are never part of a weekly digest.

### Inception Backfill

On first run, every pipeline component (Fetcher → Processor → Detector → Daily
Generator → Weekly Generator → RAG Indexer) runs for each historical
announcement day from `INCEPTION_DATE` forward before handing off to the
regular schedulers.

## Required Environment Variables

| Variable | Default | Notes |
|----------|---------|-------|
| `INCEPTION_DATE` | *(required)* | ISO date — earliest date to backfill from on first run |
| `RAG_WINDOW_DAYS` | `90` | Days of digests indexed for Q&A; older digests still stored |
| `ARXIV_CATEGORIES` | `cs.LG,cs.CV,cs.CL,cs.AI,cs.RO,stat.ML` | Configurable |
| `DAILY_SCHEDULER_TIME` | `30 20 * * 0,1,2,3,4` | Cron — 20:30 ET, Sun–Thu |
| `WEEKLY_SCHEDULER_TIME` | `0 1 * * 5` | Cron — 01:00 ET, Friday |
| `LOG_LEVEL` | `INFO` | |

## Definition of Done — Per Task

**A task is not complete until all of the following are true:**

1. **Tests pass** — run the test file(s) associated with the task; every test must
   be green. Never mark a task `[X]` while any test in the relevant file is failing
   or skipped.

2. **100% coverage on the implemented file** — run:
   ```bash
   uv run pytest <test_file> --cov=src/<module_path> --cov-report=term-missing
   ```
   The `Miss` column for the implemented source file must be `0` and `BrPart` must
   be `0`. If uncovered lines or branches remain, add tests before proceeding.

3. **No ruff errors** — run `uv run ruff check src/ tests/` and fix any violations
   before moving on.

**Workflow for each task pair (test file + implementation file):**

```
1. Write the test file (TDD — all tests fail initially).
2. Implement the source file until all tests pass.
3. Run: uv run pytest <test_file> --cov=src/<module> --cov-report=term-missing
4. If any line or branch is uncovered, add tests to cover it, then re-run.
5. Confirm 0 Miss, 0 BrPart for the implemented file.
6. Mark the task [X] in tasks.md only after steps 1–5 all pass.
```

**What counts as "related files" for coverage:**
- The source file the task creates (e.g. `src/config.py` for T003/T006).
- Any helper module the implementation introduces that has its own logic
  (e.g. `src/db/constants.py` if it contains non-trivial functions).
- Migrations, `__init__.py` files, and `src/main.py` are excluded from the
  100% requirement (they are excluded in `[tool.coverage.run]` omit or are
  trivially empty).

---

## Coding Guidelines

### Docstrings

For every function, method, or class you write: add a docstring unless the name
and signature are fully self-explanatory to a reader who has never seen this
codebase. When in doubt, write one.

A good docstring explains **why** or **what contract** the code enforces — not
what the code literally does line-by-line. Include:

- A one-line summary (imperative mood: "Fetch papers…", "Return the digest…").
- Parameters and return value when their purpose or type is non-obvious.
- Any non-obvious preconditions, side-effects, or exceptions raised.

Use Google-style docstrings:

```python
def fetch_papers(date: datetime.date, categories: list[str]) -> list[Paper]:
    """Fetch arXiv papers for the given date and categories.

    Retries up to 3 times with exponential backoff before raising FetchError.

    Args:
        date: Announcement date (must be a Sun–Thu, not Fri/Sat).
        categories: arXiv category identifiers, e.g. ["cs.LG", "cs.CV"].

    Returns:
        List of Paper objects; empty list if arXiv reports zero results.

    Raises:
        FetchError: If all 3 retry attempts fail.
    """
```

Skip the docstring only when the name, parameters, and return type together
leave absolutely nothing ambiguous (e.g. `def is_weekend(date: datetime.date) -> bool`).

### Library Versions & Documentation

Before writing any code that uses a third-party library:

1. **Check the pinned version** — read `requirements.txt` (or `pyproject.toml`)
   to find the exact version in use. Never assume a version from memory.
2. **Fetch targeted docs via the `context7-plugin:docs-researcher` agent** — use
   this agent to retrieve the specific section of documentation relevant to what
   you are about to write (e.g., "APScheduler cron trigger API", "SQLAlchemy
   async session usage"). Pass the library name, pinned version, and the specific
   topic or API surface you need. Do not fetch entire library docs — be specific.

**Workflow**:
```
1. Read pyproject.toml → find pinned version for the library
2. If the pinned version is a major-version bump from what training data likely knows
   (e.g. arxiv 3.x, sentence-transformers 5.x, pytest 9.x, pytest-asyncio 1.x),
   check the library's changelog/migration guide before writing any code.
3. Spawn context7-plugin:docs-researcher with: library, version, specific topic
4. Write code using only APIs confirmed in the returned docs
```

This prevents version mismatch bugs where training data reflects an older or
newer API than what is actually installed.

### Known Major-Version Bumps (verify APIs before use)

These packages in `pyproject.toml` are at a major version that likely differs
from training data — treat their APIs as unknown until confirmed via docs:

| Package | Pinned | Risk |
|---------|--------|------|
| `arxiv` | 3.0.0 | 2.x → 3.x breaking changes |
| `sentence-transformers` | 5.4.1 | 4.x → 5.x breaking changes |
| `pytest` | 9.0.3 | 8.x → 9.x breaking changes |
| `pytest-asyncio` | 1.3.0 | 0.x → 1.x breaking changes |

## Technology Stack (see system_design.md for rationale)

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.12 |
| API | FastAPI |
| Scheduler | APScheduler |
| Database | PostgreSQL 16 + pgvector (single DB for all storage + vector search) |
| ORM | SQLAlchemy + Alembic |
| Embeddings | `BAAI/bge-small-en-v1.5` via `sentence-transformers` (local, no API cost) |
| LLM heavy | `claude-sonnet-4-6` (extraction, detection, generation, Q&A) |
| LLM light | `claude-haiku-4-5-20251001` (topic classification, scope detection) |
| arXiv | `arxiv` library (metadata) + `httpx` (HTML full text) + `pdfplumber` (PDF fallback) |
| Tooling | `uv`, `ruff`, `pytest` + `pytest-asyncio` |

## Key Design Decisions (already resolved — see spec for full rationale)

- **Digest format**: JSON envelope with per-topic rendered Markdown `body` field
- **RAG scope**: rolling `RAG_WINDOW_DAYS` window; digests outside window are
  stored but not indexed; no admin endpoint in v1
- **Multi-topic papers**: one primary topic for digest grouping; optional secondary
  tags for discoverability; no duplicate digest entries
- **arXiv pull failure**: retry 3× with exponential backoff; skip permanently on
  failure (no backfill in v1)
- **Digest retention**: indefinite — never auto-deleted
- **Weekly digest threshold**: none — generates from whatever days have content
- **RAG chunking**: two chunks per paper (abstract chunk + content chunk), each
  with searchable metadata: title, authors, institutions, date, topic

## Future Upgrade Paths (explicitly out of scope for v1)

- Backfill-on-recovery after fetch-failure skips
- Runtime `RAG_WINDOW_DAYS` reconfiguration via admin endpoint
- Digest retention / auto-deletion policy
- WebSocket / SSE streaming for Q&A responses
- Multi-source ingestion beyond arXiv
