# Data Model: ArXiv Intelligence Agent

**Phase**: 1 | **Date**: 2026-04-23 | **Plan**: [plan.md](plan.md)

---

## Entities

### Paper

Represents a single arXiv publication after full processing.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `arxiv_id` | `VARCHAR(20)` | PRIMARY KEY | e.g., `2604.11023` |
| `title` | `TEXT` | NOT NULL | Full paper title |
| `authors` | `TEXT[]` | NOT NULL | Ordered list of author names |
| `institutions` | `TEXT[]` | NOT NULL DEFAULT `'{}'` | Extracted author affiliations |
| `abstract` | `TEXT` | NOT NULL | |
| `submitted_date` | `DATE` | NOT NULL, FK → `DateRecord.date` | arXiv announcement date |
| `topic_section_id` | `UUID` | NULLABLE, FK → `TopicSection.id` | Set after digest generation; null until then |
| `primary_topic` | `VARCHAR(100)` | NOT NULL | One value from `TOPIC_LIST` |
| `secondary_topics` | `TEXT[]` | NOT NULL DEFAULT `'{}'` | Cross-topic discoverability |
| `contributions` | `TEXT` | NOT NULL DEFAULT `''` | Extracted from paper body |
| `methodologies` | `TEXT` | NOT NULL DEFAULT `''` | Extracted from paper body |
| `benchmarks` | `TEXT` | NOT NULL DEFAULT `''` | Extracted from paper body |
| `is_groundbreaking` | `BOOLEAN` | NOT NULL DEFAULT `FALSE` | |
| `groundbreaking_reasoning` | `TEXT` | NULLABLE | Non-null iff `is_groundbreaking = TRUE` |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT `now()` | |

**Indexes**:
- `idx_papers_submitted_date` on `submitted_date`
- `idx_papers_primary_topic` on `primary_topic`
- `idx_papers_is_groundbreaking` on `is_groundbreaking`
- Full-text search: GIN index on `to_tsvector('english', title || ' ' || abstract)` for title/abstract keyword search
- `idx_papers_authors` GIN index on `authors` for author name filtering
- `idx_papers_institutions` GIN index on `institutions` for institution filtering

**Validation rules**:
- `primary_topic` must be one of the values in the configured `TOPIC_LIST`
- `groundbreaking_reasoning` must be non-null when `is_groundbreaking = TRUE`
- `arxiv_id` format: digits, dot, digits (e.g., `2604.11023`)

---

### DateRecord

One record per calendar date. Single source of truth for every date's status.
Pre-populated for Fri/Sat as `no_announcement` on service startup or lazily on
first request for that date.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `date` | `DATE` | PRIMARY KEY | |
| `status` | `date_status` ENUM | NOT NULL | See status enum below |
| `paper_count` | `INTEGER` | NULLABLE | Non-null only when `status = 'published'` |
| `recorded_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT `now()` | |

**Status enum** (`date_status`):
- `published` — digest generated successfully
- `no_announcement` — Friday or Saturday; arXiv never publishes
- `no_papers_skip` — arXiv reachable, 0 papers returned
- `fetch_failure_skip` — all 3 retries failed

**Constraints**:
- `paper_count IS NULL OR (status = 'published' AND paper_count >= 0)` — count only on published dates

---

### DailyDigest

Stored digest document for one announcement day.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | `UUID` | PRIMARY KEY DEFAULT `gen_random_uuid()` | |
| `date` | `DATE` | NOT NULL UNIQUE | FK → `DateRecord.date` |
| `generated_at` | `TIMESTAMPTZ` | NOT NULL | |
| `paper_count` | `INTEGER` | NOT NULL | |
| `groundbreaking_count` | `INTEGER` | NOT NULL | |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT `now()` | |

**Indexes**: `idx_daily_digest_date` on `date`

---

### TopicSection

One section per topic within a DailyDigest.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | `UUID` | PRIMARY KEY DEFAULT `gen_random_uuid()` | |
| `digest_id` | `UUID` | NOT NULL | FK → `DailyDigest.id` ON DELETE CASCADE |
| `name` | `VARCHAR(100)` | NOT NULL | Topic name |
| `paper_count` | `INTEGER` | NOT NULL | |
| `body` | `TEXT` | NOT NULL | Rendered Markdown for this topic |

Ordering is applied at query time (`ORDER BY paper_count DESC`) — no stored position field needed.

**Indexes**: `idx_topic_section_digest_id` on `digest_id`

---

### WeeklyDigest

Stored digest document for one Sun–Thu announcement week.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | `UUID` | PRIMARY KEY DEFAULT `gen_random_uuid()` | |
| `week_start` | `DATE` | NOT NULL UNIQUE | Sunday of the announcement week |
| `week_end` | `DATE` | NOT NULL | Thursday of the same week |
| `generated_at` | `TIMESTAMPTZ` | NOT NULL | |
| `paper_count` | `INTEGER` | NOT NULL | |
| `groundbreaking_count` | `INTEGER` | NOT NULL | |
| `benchmark_comparisons` | `TEXT` | NOT NULL | Rendered Markdown |
| `trend_synthesis` | `TEXT` | NOT NULL | Rendered Markdown |
| `cross_paper_analysis` | `TEXT` | NOT NULL | Rendered Markdown |
| `days_with_content` | `DATE[]` | NOT NULL DEFAULT `'{}'` | Dates of published daily digests in this week |
| `no_papers_skips` | `DATE[]` | NOT NULL DEFAULT `'{}'` | `no_papers_skip` dates in this week |
| `fetch_failure_skips` | `DATE[]` | NOT NULL DEFAULT `'{}'` | `fetch_failure_skip` dates in this week |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT `now()` | |

Coverage arrays are inlined directly — no separate `CoverageNote` table needed.
`announcement_days` (`["Sun","Mon","Tue","Wed","Thu"]`) is a constant derived at
serialization time, not stored.

**Indexes**: `idx_weekly_digest_week_start` on `week_start`

---

### PaperEmbedding

Vector embeddings for RAG retrieval. One row per chunk per paper (two rows
per paper: abstract chunk + content chunk).

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | `UUID` | PRIMARY KEY DEFAULT `gen_random_uuid()` | |
| `arxiv_id` | `VARCHAR(20)` | NOT NULL | FK → `Paper.arxiv_id` |
| `chunk_type` | `chunk_type` ENUM | NOT NULL | `abstract` or `content`; UNIQUE with `arxiv_id` |
| `content` | `TEXT` | NOT NULL | Raw text that was embedded |
| `embedding` | `vector(384)` | NOT NULL | BAAI/bge-small-en-v1.5 output |
| `date` | `DATE` | NOT NULL | Paper's submitted_date (for window filtering) |
| `primary_topic` | `VARCHAR(100)` | NOT NULL | Denormalized for filter performance |
| `secondary_topics` | `TEXT[]` | NOT NULL | Denormalized |
| `is_groundbreaking` | `BOOLEAN` | NOT NULL | Denormalized |
| `title` | `TEXT` | NOT NULL | Denormalized for metadata return |
| `authors` | `TEXT[]` | NOT NULL | Denormalized for metadata return |
| `institutions` | `TEXT[]` | NOT NULL | Denormalized for metadata return |

**Chunk type enum** (`chunk_type`): `abstract`, `content`

**Constraints**:
- `UNIQUE(arxiv_id, chunk_type)` — enforces exactly one abstract chunk and one content chunk per paper (the "1:2 fixed" cardinality)

**Indexes**:
- `idx_paper_embedding_date` on `date` — enables fast window filtering
- `idx_paper_embedding_arxiv_id` on `arxiv_id`
- IVFFlat or HNSW vector index on `embedding` for cosine similarity search

---

## State Transitions

### DateRecord Status Flow

```
         startup / lazy init
              │
              ▼
    ┌─────────────────┐
    │ no_announcement │  ← Friday or Saturday (never fetched)
    └─────────────────┘

         daily scheduler fires (Sun–Thu)
              │
              ├── arXiv reachable, papers > 0  ──► published
              ├── arXiv reachable, papers = 0  ──► no_papers_skip
              └── all 3 retries fail           ──► fetch_failure_skip
```

All states are terminal in v1 — no state transitions after recording.
Backfill-on-recovery is a designated future upgrade.

---

## Data Modeling Diagram

```
┌─────────────────────────────────────────────────────┐
│  DateRecord                                         │
│─────────────────────────────────────────────────────│
│ PK  date          DATE                              │
│     status        date_status ENUM                  │
│     paper_count   INTEGER (nullable)                │
│     recorded_at   TIMESTAMPTZ                       │
└───────┬──────────────────────────┬──────────────────┘
        │ date = submitted_date    │ date = date (1:0–1)
        │ (1:N)                    │
        │            ┌─────────────▼────────────────────┐
        │            │  DailyDigest                     │
        │            │──────────────────────────────────│
        │            │ PK  id                UUID       │
        │            │ FK  date    DATE → DateRecord.date│
        │            │     generated_at      TIMESTAMPTZ│
        │            │     paper_count       INTEGER    │
        │            │     groundbreaking_count INTEGER │
        │            │     created_at        TIMESTAMPTZ│
        │            └──────────────┬───────────────────┘
        │                          │ digest_id = id (1:N)
        │            ┌─────────────▼────────────────────┐
        │            │  TopicSection                    │
        │            │──────────────────────────────────│
        │            │ PK  id         UUID              │
        │            │ FK  digest_id  UUID→DailyDigest.id│
        │            │     name       VARCHAR(100)      │
        │            │     paper_count INTEGER          │
        │            │     body       TEXT (Markdown)   │
        │            │  [ordered at query time by       │
        │            │   paper_count DESC]              │
        │            └──────────────┬───────────────────┘
        │                          │ id = topic_section_id
        │                          │ (1:N)
        ▼                          ▼
┌─────────────────────────────────────────────────────┐
│  Paper                                              │
│─────────────────────────────────────────────────────│
│ PK  arxiv_id         VARCHAR(20)                    │
│ FK  submitted_date   DATE → DateRecord.date          │
│ FK  topic_section_id UUID → TopicSection.id          │
│                      (null until digest generation) │
│     title            TEXT                           │
│     authors          TEXT[]                         │
│     institutions     TEXT[]                         │
│     abstract         TEXT                           │
│     primary_topic    VARCHAR(100)                   │
│     secondary_topics TEXT[]                         │
│     contributions    TEXT                           │
│     methodologies    TEXT                           │
│     benchmarks       TEXT                           │
│     is_groundbreaking BOOLEAN                       │
│     groundbreaking_reasoning TEXT (nullable)        │
│     created_at       TIMESTAMPTZ                    │
└──────────────────────────┬──────────────────────────┘
                           │ arxiv_id = arxiv_id (1:2)
                           │  [one abstract chunk +
                           │   one content chunk]
┌──────────────────────────▼──────────────────────────┐
│  PaperEmbedding                                     │
│─────────────────────────────────────────────────────│
│ PK  id               UUID                           │
│ FK  arxiv_id         VARCHAR(20) → Paper.arxiv_id   │
│     chunk_type       chunk_type ENUM                │
│                      ('abstract' | 'content')       │
│     content          TEXT                           │
│     embedding        vector(384)                    │
│     date             DATE  (denorm: submitted_date) │
│     primary_topic    VARCHAR(100) (denorm)          │
│     secondary_topics TEXT[] (denorm)                │
│     is_groundbreaking BOOLEAN (denorm)              │
│     title            TEXT (denorm)                  │
│     authors          TEXT[] (denorm)                │
│     institutions     TEXT[] (denorm)                │
└─────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────┐
│  WeeklyDigest                                       │
│─────────────────────────────────────────────────────│
│ PK  id                    UUID                      │
│     week_start            DATE (Sunday)             │
│     week_end              DATE (Thursday)           │
│     generated_at          TIMESTAMPTZ               │
│     paper_count           INTEGER                   │
│     groundbreaking_count  INTEGER                   │
│     benchmark_comparisons TEXT (Markdown)           │
│     trend_synthesis       TEXT (Markdown)           │
│     cross_paper_analysis  TEXT (Markdown)           │
│     days_with_content     DATE[] (coverage)         │
│     no_papers_skips       DATE[] (coverage)         │
│     fetch_failure_skips   DATE[] (coverage)         │
│     created_at            TIMESTAMPTZ               │
│                                                     │
│  [DailyDigests for this week found by date range:   │
│   WHERE date BETWEEN week_start AND week_end]       │
└─────────────────────────────────────────────────────┘
```

### Cardinalities at a glance

| Parent | Child | Join fields | Cardinality |
|--------|-------|-------------|-------------|
| `DateRecord` | `DailyDigest` | `DateRecord.date = DailyDigest.date` | 1 : 0–1 |
| `DateRecord` | `Paper` | `DateRecord.date = Paper.submitted_date` | 1 : N |
| `DailyDigest` | `TopicSection` | `DailyDigest.id = TopicSection.digest_id` | 1 : N |
| `TopicSection` | `Paper` | `TopicSection.id = Paper.topic_section_id` | 1 : N |
| `WeeklyDigest` | `DailyDigest` | `DailyDigest.date BETWEEN week_start AND week_end` | 1 : 0–5 (by date range, no FK) |
| `Paper` | `PaperEmbedding` | `Paper.arxiv_id = PaperEmbedding.arxiv_id` | 1 : 2 (fixed) |

### Navigation paths

| Goal | Query path |
|------|-----------|
| All papers for a given date | `DateRecord → Paper` via `submitted_date = date` |
| All papers in a daily digest | `DailyDigest → TopicSection → Paper` via `digest_id` then `topic_section_id` |
| All papers in a topic section | `TopicSection → Paper` via `topic_section_id` |
| Which digest contains a paper | `Paper.topic_section_id → TopicSection.digest_id → DailyDigest` |
| Date status for a paper's day | `Paper.submitted_date → DateRecord.status` |
| Daily digests for a weekly digest | `SELECT * FROM daily_digest WHERE date BETWEEN week_start AND week_end` |
| All papers covered by a weekly digest | date range → `DailyDigest → TopicSection → Paper` |

## Relationships Summary

```
DateRecord (1) ──── date = date ──────────── DailyDigest (0–1)
     │                                              │
     │ date = submitted_date             digest_id = id (1:N)
     │ (1:N)                                        │
     │                                      TopicSection (N)
     │                                              │
     └───────────────────── id = topic_section_id (1:N)
                                                    │
                                                Paper (N)
                                                    │
                                      arxiv_id = arxiv_id (1:2)
                                                    │
                                           PaperEmbedding
                                      [abstract chunk + content chunk]

WeeklyDigest — no FK to DailyDigest; linked by date range at query time
               (coverage arrays stored inline on WeeklyDigest)
```

---

## Migration Notes

- Create `date_status` and `chunk_type` enum types before tables that reference them
- Enable `pgvector` extension before creating `PaperEmbedding` table: `CREATE EXTENSION IF NOT EXISTS vector;`
- Do **not** create the vector index in the Alembic migration — create it **after** initial backfill data is loaded:
  ```sql
  CREATE INDEX ON paper_embeddings
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
  ```
  HNSW is preferred over IVFFlat for ~180k vectors at 384 dims (better recall, no `lists` tuning required).
