"""Shared DB string constants for ORM models and Alembic migrations.

Centralises enum values, enum type names, table names, column names,
constraint expressions, constraint names, and index names so that models.py
and migration files stay in sync — change once here, and both consumers
reflect the update automatically.
"""

# ---------------------------------------------------------------------------
# Enum values
# ---------------------------------------------------------------------------

DATE_STATUS_VALUES: tuple[str, ...] = (
    "published",
    "no_announcement",
    "no_papers_skip",
    "fetch_failure_skip",
)

CHUNK_TYPE_VALUES: tuple[str, ...] = ("abstract", "content")

# ---------------------------------------------------------------------------
# Enum type names
# ---------------------------------------------------------------------------

ENUM_DATE_STATUS = "date_status"
ENUM_CHUNK_TYPE = "chunk_type"

# ---------------------------------------------------------------------------
# Table names
# ---------------------------------------------------------------------------

TBL_DATE_RECORDS = "date_records"
TBL_DAILY_DIGESTS = "daily_digests"
TBL_TOPIC_SECTIONS = "topic_sections"
TBL_WEEKLY_DIGESTS = "weekly_digests"
TBL_PAPERS = "papers"
TBL_PAPER_EMBEDDINGS = "paper_embeddings"

# ---------------------------------------------------------------------------
# Column names
# ---------------------------------------------------------------------------

COL_ID = "id"
COL_DATE = "date"
COL_STATUS = "status"
COL_PAPER_COUNT = "paper_count"
COL_RECORDED_AT = "recorded_at"
COL_GENERATED_AT = "generated_at"
COL_GROUNDBREAKING_COUNT = "groundbreaking_count"
COL_CREATED_AT = "created_at"
COL_ARXIV_ID = "arxiv_id"
COL_CHUNK_TYPE = "chunk_type"
COL_CONTENT = "content"
COL_EMBEDDING = "embedding"
COL_DIGEST_ID = "digest_id"
COL_TOPIC_SECTION_ID = "topic_section_id"
COL_NAME = "name"
COL_BODY = "body"
COL_SUBMITTED_DATE = "submitted_date"
COL_WEEK_START = "week_start"
COL_WEEK_END = "week_end"
COL_BENCHMARK_COMPARISONS = "benchmark_comparisons"
COL_TREND_SYNTHESIS = "trend_synthesis"
COL_CROSS_PAPER_ANALYSIS = "cross_paper_analysis"
COL_DAYS_WITH_CONTENT = "days_with_content"
COL_NO_PAPERS_SKIPS = "no_papers_skips"
COL_FETCH_FAILURE_SKIPS = "fetch_failure_skips"
COL_TITLE = "title"
COL_ABSTRACT = "abstract"
COL_IS_GROUNDBREAKING = "is_groundbreaking"
COL_GROUNDBREAKING_REASONING = "groundbreaking_reasoning"
COL_PRIMARY_TOPIC = "primary_topic"
COL_SECONDARY_TOPICS = "secondary_topics"
COL_CONTRIBUTIONS = "contributions"
COL_METHODOLOGIES = "methodologies"
COL_BENCHMARKS = "benchmarks"
COL_AUTHORS = "authors"
COL_INSTITUTIONS = "institutions"

# ---------------------------------------------------------------------------
# Constraint SQL expressions
# ---------------------------------------------------------------------------

# DateRecord: paper_count is only valid on published rows
CK_DATE_RECORD_PAPER_COUNT_EXPR = (
    "(paper_count IS NULL) OR (status = 'published' AND paper_count >= 0)"
)

# DailyDigest / WeeklyDigest: a digest row can only exist when papers were published
CK_DIGEST_PAPER_COUNT_POSITIVE_EXPR = "paper_count > 0"

# WeeklyDigest: week_start must be a Sunday (DOW=0), week_end a Thursday (DOW=4)
CK_WEEKLY_WEEK_START_IS_SUNDAY_EXPR = "EXTRACT(DOW FROM week_start) = 0"
CK_WEEKLY_WEEK_END_IS_THURSDAY_EXPR = "EXTRACT(DOW FROM week_end) = 4"

# Paper: groundbreaking_reasoning must be non-null iff is_groundbreaking is True
CK_PAPER_GROUNDBREAKING_EXPR = (
    "is_groundbreaking = (groundbreaking_reasoning IS NOT NULL)"
)

# ---------------------------------------------------------------------------
# Constraint names
# ---------------------------------------------------------------------------

CK_DATE_RECORD_PAPER_COUNT_NAME = "ck_date_record_paper_count"
CK_DAILY_DIGEST_PAPER_COUNT_NAME = "ck_daily_digest_paper_count_positive"
CK_WEEKLY_DIGEST_PAPER_COUNT_NAME = "ck_weekly_digest_paper_count_positive"
CK_WEEKLY_WEEK_START_NAME = "ck_weekly_digest_week_start_is_sunday"
CK_WEEKLY_WEEK_END_NAME = "ck_weekly_digest_week_end_is_thursday"
CK_PAPER_GROUNDBREAKING_NAME = "ck_paper_groundbreaking_reasoning"

UQ_DAILY_DIGEST_DATE_NAME = "uq_daily_digest_date"
UQ_WEEKLY_DIGEST_WEEK_START_NAME = "uq_weekly_digest_week_start"
UQ_PAPER_EMBEDDING_ARXIV_CHUNK_NAME = "uq_paper_embedding_arxiv_chunk"

# ---------------------------------------------------------------------------
# Index names
# ---------------------------------------------------------------------------

IDX_DAILY_DIGEST_DATE = "idx_daily_digest_date"
IDX_TOPIC_SECTION_DIGEST_ID = "idx_topic_section_digest_id"
IDX_WEEKLY_DIGEST_WEEK_START = "idx_weekly_digest_week_start"
IDX_PAPERS_SUBMITTED_DATE = "idx_papers_submitted_date"
IDX_PAPERS_PRIMARY_TOPIC = "idx_papers_primary_topic"
IDX_PAPERS_IS_GROUNDBREAKING = "idx_papers_is_groundbreaking"
IDX_PAPERS_FTS = "idx_papers_fts"
IDX_PAPERS_AUTHORS = "idx_papers_authors"
IDX_PAPERS_INSTITUTIONS = "idx_papers_institutions"
IDX_PAPER_EMBEDDING_DATE = "idx_paper_embedding_date"
IDX_PAPER_EMBEDDING_ARXIV_ID = "idx_paper_embedding_arxiv_id"
