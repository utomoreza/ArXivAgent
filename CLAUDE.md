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

## Coding Guidelines

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
