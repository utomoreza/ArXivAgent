# Feature Specification: ArXiv Intelligence Agent

**Feature Branch**: `001-arxiv-intelligence-agent`
**Created**: 2026-04-22
**Status**: Draft
**Input**: User description: "develop ArXivAgent, ArXiv Intelligence Agent — monitors latest ML research papers and synthesizes insights"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Daily Research Digest (Priority: P1)

As a researcher, I want automated daily and weekly digests of the latest ML papers
from arXiv, grouped by research topic, so I can efficiently stay current with the
field without manually searching.

**Why this priority**: This is the core value proposition. Without digest generation,
no other feature (groundbreaking detection, Q&A) can deliver value.

**Independent Test**: Trigger a digest generation run and verify that a structured
digest document is produced containing papers grouped by topic, each with a summary,
key contributions, methodology notes, and benchmark results.

**Acceptance Scenarios**:

1. **Given** it is the scheduled daily digest time, **When** the agent runs, **Then**
   it fetches all new ML papers published on arXiv that day and produces a digest
   grouped by topic (e.g., Large Language Models, Computer Vision, Reinforcement
   Learning, Multimodal AI)
2. **Given** a weekly digest is generated, **When** the agent aggregates the week's
   papers, **Then** it produces a consolidated digest comparing and synthesizing
   papers across the week's publications
3. **Given** a paper is fetched, **When** the agent processes it, **Then** it
   extracts and stores the key contributions, methodologies, and benchmark results
4. **Given** a digest is generated, **When** a user retrieves it via the digest
   endpoint, **Then** they receive a structured document with topic-grouped summaries

---

### User Story 2 - Groundbreaking Paper Detection (Priority: P2)

As a researcher, I want papers flagged as "groundbreaking" with an explicit reasoning
statement, so I can immediately identify the most impactful work to prioritize.

**Why this priority**: Filtering signal from noise is a key differentiator; however,
digests (P1) must exist before flagging adds value.

**Independent Test**: Provide a controlled set of papers with known significance
levels and verify that papers meeting the groundbreaking criteria are correctly
flagged with a non-empty reasoning explanation, while others are not.

**Acceptance Scenarios**:

1. **Given** a paper meets the defined groundbreaking criteria, **When** it is
   processed, **Then** it is flagged as groundbreaking with a human-readable
   explanation of why
2. **Given** a paper does not meet the criteria, **When** it is processed, **Then**
   it is NOT flagged as groundbreaking
3. **Given** a digest is generated, **When** a user views it, **Then** groundbreaking
   papers are visually distinguished from regular papers with their reasoning displayed

---

### User Story 3 - Digest Q&A via RAG (Priority: P3)

As a researcher, I want to ask natural language questions about the generated digests
and receive accurate, grounded answers, so I can quickly explore synthesized knowledge
without reading entire documents.

**Why this priority**: RAG Q&A extends the value of digests but requires them to
already exist and be indexed.

**Independent Test**: Ingest a completed digest into the knowledge base, submit
diverse in-scope questions via the Q&A endpoint, and verify answers are grounded in
digest content. Submit out-of-scope questions and verify they are rejected.

**Acceptance Scenarios**:

1. **Given** one or more digests exist, **When** a user submits a question relevant
   to the digest content via the Q&A endpoint, **Then** the system returns a grounded
   answer citing specific papers or digest sections
2. **Given** a user submits a question unrelated to the digest content (e.g.,
   "What is the weather in Paris?" or "Write me a poem"), **When** the system
   processes it, **Then** it rejects the query with a clear message stating it only
   answers questions about the research digests
3. **Given** a user asks about a specific paper or topic covered in a digest,
   **When** the system responds, **Then** the answer references the relevant
   digest entry

---

### Edge Cases

- What happens when arXiv is unavailable during the scheduled pull? → Retry up to 3 times with exponential backoff; if all fail, record the day as a **fetch-failure skip** (distinct from a no-papers skip). No backfill in v1 — intentionally kept simple; backfill-on-recovery is a designated future upgrade path. The weekly digest excludes fetch-failure days but MUST note that those dates were skipped due to an external API failure, not due to absence of papers. If a client requests a fetch-failure date via the digest endpoint, the system returns a message such as "Data retrieval from arXiv failed after 3 attempts on this date — no digest available."
- How does the system handle papers that span multiple research topics? → One primary topic for grouping; secondary tags stored for discoverability; no duplicate digest entries.
- What happens when no new papers are published on a given day? → No digest is generated for that date. The weekly digest excludes skipped days entirely (no empty topic sections). If a client requests a skipped date via the digest endpoint, the system returns a clear "no new papers published on this date" message rather than an empty document.
- What happens when a client requests a Friday or Saturday digest? → These are **no-announcement** days — arXiv structurally never publishes on Fridays or Saturdays. The endpoint returns "arXiv does not publish on Fridays or Saturdays." This is distinct from a no-papers skip (which is unexpected) and from a fetch-failure skip.
- How does the system respond to a Q&A query when the knowledge base is empty? → Return a successful response with a human-readable message: "No digests are available yet within the current window — please check back after the first digest is generated." Not treated as an error or an out-of-scope rejection.
- What if a weekly digest is requested but fewer than 7 days of daily digests exist? → No minimum threshold. The arXiv announcement week is Sun–Thu (5 days); Fri/Sat are never part of a weekly digest. The weekly digest is generated from whatever announcement days have content. Skipped days (no-papers and fetch-failure types) are noted in the coverage note. If the requested week is still ongoing (weekly scheduler has not yet run), the endpoint returns "Week still ongoing — weekly digest not yet generated."

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST pull new ML papers from arXiv on a daily schedule,
  firing at 20:30 ET on announcement days (Sunday through Thursday). arXiv does
  not publish on Fridays or Saturdays; no fetch is attempted on those days and
  they are recorded as a **no-announcement** state distinct from all other skip
  types. On first run, the system MUST backfill from `INCEPTION_DATE` (env var)
  through the current date before handing off to the regular daily schedule,
  running the full pipeline for each historical announcement day.
  If a pull fails, the system MUST retry up to 3 times with exponential backoff.
  If all retries fail, the day MUST be recorded as a **fetch-failure skip**.
  Backfill-on-recovery is out of scope for v1 and reserved for a future upgrade.
- **FR-002**: The system MUST extract key contributions, methodologies, and benchmark
  results from each fetched paper
- **FR-003**: The system MUST group papers by research topic (e.g., Large Language
  Models, Computer Vision, Reinforcement Learning, Multimodal AI); the topic list
  MUST be configurable. Each paper MUST be assigned exactly one primary topic for
  digest grouping; papers spanning multiple topics MAY additionally carry secondary
  topic tags that are stored on the paper record and used for cross-topic
  discoverability but do not cause duplicate entries in the digest.
- **FR-004**: The system MUST flag papers meeting the groundbreaking criteria and
  include a reasoning explanation for each flagged paper
- **FR-005**: The system MUST generate a daily research digest summarizing new papers
  grouped by topic. Three date states are defined and MUST be distinguishable:
  (1) **no-announcement** — Friday or Saturday; arXiv structurally never publishes
  these days; digest endpoint returns "arXiv does not publish on Fridays or
  Saturdays."
  (2) **no-papers skip** — arXiv was reachable on an announcement day but published
  no papers (e.g., holiday); digest endpoint returns "No new papers were published
  on this date."
  (3) **fetch-failure skip** — arXiv was unreachable after 3 retries; digest endpoint
  returns "Data retrieval from arXiv failed after 3 attempts on this date — no digest
  available."
- **FR-006**: The system MUST generate a weekly research digest covering the arXiv
  announcement week (Sunday through Thursday) via a scheduler that runs every
  Friday at 01:00 ET — after Thursday's daily digest (the last of the week) has
  fully completed. Friday and Saturday are never included as they carry
  no-announcement status. There is no minimum daily digest threshold — the weekly
  digest is generated from whatever announcement days have content. The weekly
  digest MUST include a coverage note listing any skipped days with their reason
  (no-papers skip or fetch-failure skip; no-announcement days are not listed as
  skips — they are expected absences). The weekly digest endpoint MUST accept a
  week identifier (Sunday start date) from the client; if the requested week is
  still in progress (weekly scheduler has not yet run), the endpoint MUST return
  "Week still ongoing — weekly digest not yet generated." During inception backfill,
  the system generates one weekly digest per historical Sun–Thu week in
  chronological order before the regular Friday scheduler takes over.
- **FR-007**: The system MUST expose a digest endpoint to retrieve available digests
  (daily and weekly) by time period. Responses MUST use a JSON envelope containing
  structured metadata fields (type, date, paper_count, groundbreaking_count) alongside
  a per-topic `body` field of rendered Markdown, enabling both programmatic access
  and direct human-readable rendering without a separate transform step.
- **FR-008**: The system MUST expose a Q&A endpoint that accepts natural language
  questions about the digests; the queryable knowledge base is scoped to a rolling
  window of the most recent N days, where N is read from the `RAG_WINDOW_DAYS`
  environment variable (default: 90 days). Runtime reconfiguration via admin
  endpoint is out of scope for v1 and reserved for a future upgrade.
- **FR-009**: The Q&A endpoint MUST reject queries unrelated to the research digests
  with an informative rejection message. If the knowledge base is empty (no digests
  fall within the current `RAG_WINDOW_DAYS` window), the endpoint MUST return a
  successful response with the message "No digests are available yet within the
  current window — please check back after the first digest is generated." This
  state MUST NOT be treated as an error or an out-of-scope rejection.
- **FR-010**: The Q&A endpoint MUST return answers grounded in digest content, citing
  relevant papers or digest sections
- **FR-011**: The system MUST classify a paper as groundbreaking when it satisfies
  BOTH of the following conditions: (1) it claims a measurable improvement on an
  established benchmark, AND (2) it introduces a novel architecture or paradigm
  (not merely an incremental tuning of an existing approach). The reasoning
  explanation MUST state which benchmark was improved and what novel element was
  introduced.
- **FR-012**: The weekly digest MUST compare papers using all three of the following
  lenses: (1) side-by-side benchmark comparisons for papers targeting the same task
  or dataset, (2) thematic trend synthesis per topic identifying directions that
  gained momentum during the week, and (3) a cross-paper analysis section explicitly
  highlighting complementary or contradictory findings across papers.

### Key Entities

- **Paper**: An arXiv publication with title, authors, author institutions,
  abstract, submission date, one primary topic category (used for digest grouping),
  zero or more secondary topic tags (for cross-topic discoverability), extracted
  key contributions, methodologies, benchmark results, and a groundbreaking flag
  with reasoning. Papers are searchable by title, authors, institutions, and date.
- **Digest**: A structured research summary document covering a time period (daily
  or weekly), containing topic-grouped paper entries and — for weekly digests — a
  cross-paper comparison section. Each date in the system has one of three states:
  **published** (digest exists), **no-papers skip** (arXiv had no content that day),
  or **fetch-failure skip** (arXiv was unreachable after 3 retries). The latter two
  produce no digest document but are recorded with their distinct reasons.
- **Topic**: A research domain grouping used to categorize papers (configurable list)
- **Q&A Query**: A natural language question submitted against the digest knowledge
  base, paired with a grounded answer and source citations

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Daily digests are available within 4 hours of arXiv's daily paper
  publication cutoff
- **SC-002**: 90% of papers are correctly categorized into their primary research
  topic on first pass (validated on a labeled sample set)
- **SC-003**: Groundbreaking paper detection achieves a false-positive rate below
  10%, as validated by researcher review of a random sample of flagged papers
- **SC-004**: The Q&A endpoint returns relevant, grounded answers for at least 85%
  of questions directly about digest content (measured by researcher evaluation)
- **SC-005**: Out-of-scope queries are rejected with 99% accuracy — no hallucinated
  answers for unrelated questions
- **SC-006**: Digest retrieval responds within 2 seconds for any requested digest
- **SC-007**: Q&A responses are returned within 10 seconds for any in-scope query

## Clarifications

### Session 2026-04-22

- Q: What format does the digest endpoint return to consumers? → A: JSON envelope with structured metadata fields plus a per-topic `body` field containing rendered Markdown (Option B).
- Q: Which digests are queryable via the RAG Q&A endpoint? → A: Rolling window of most recent N days, configured via environment variable `RAG_WINDOW_DAYS` (default 90). Runtime admin endpoint deferred to a future upgrade.
- Q: How should a paper spanning multiple research topics be handled? → A: Assign one primary topic for digest grouping; store optional secondary topic tags on the paper for cross-topic discoverability (Option B).
- Q: What should the system do when the arXiv pull fails? → A: Retry up to 3 times with exponential backoff; skip the day permanently if all retries fail (gap in digest history). Backfill-on-recovery explicitly deferred to a future upgrade.
- Q: How long are digests retained? → A: Indefinitely — no auto-deletion. All digests remain accessible via the digest endpoint regardless of age. RAG queryability is separately bounded by `RAG_WINDOW_DAYS`; older digests exist but are not indexed for Q&A.

## Assumptions

- arXiv's public data feed is the sole paper source; no institutional access or paid
  subscription is assumed
- arXiv publishes new listings at 20:00 ET, Sunday through Thursday only. Fridays
  and Saturdays have no announcements — this is a structural property of arXiv,
  not an error condition
- The initial release targets ML/AI arXiv categories (cs.LG, cs.CV, cs.CL, cs.AI,
  cs.RO, stat.ML); this list is configurable
- Endpoint authentication is handled by existing infrastructure and is out of scope
  for this feature
- `INCEPTION_DATE` (env var, required) defines the earliest date the system
  backfills from on first run; the full pipeline runs for each historical
  announcement day from that date to the present
- "Weekly digest" covers the arXiv announcement week (Sunday through Thursday) and
  is generated by a scheduler that runs every Friday at 01:00 ET; there is no
  minimum daily content threshold for generation
- The system operates as an always-on service, not a one-shot CLI tool
- Digest content and Q&A knowledge base persist across service restarts
- Digests are retained indefinitely and never auto-deleted; the digest endpoint
  provides access to all historical digests regardless of age. RAG queryability
  is separately bounded by `RAG_WINDOW_DAYS` — older digests exist in storage
  but are not included in the Q&A knowledge base index.
- Paper volume is expected to be in the range of 100–500 new papers per day across
  monitored categories
