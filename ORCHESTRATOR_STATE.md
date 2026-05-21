# Orchestrator State

Last completed task: T049 (all tasks complete)
Last action: Session 2026-05-19 — live endpoint testing found 3 bugs, all fixed.
Retry counts: {}
Blockers: []

## Phase Gate Status

- Phase 1 (Setup): SATISFIED — T001-T006 [X]
- Phase 2 (Foundation): SATISFIED — T007-T015 [X]
- Phase 3 (US1): SATISFIED — T016-T032 [X]
- Phase 4 (US2): SATISFIED — T033-T035 [X]
- Phase 5 (US3): SATISFIED — T036-T044 [X]
- Phase 6 (Polish): SATISFIED — T046-T049 [X]

## Bugs fixed in session 2026-05-19

BUG-001: AsyncAnthropic() created without API key (pydantic-settings doesn't set os.environ)
  Fix: AsyncAnthropic(api_key=get_settings().ANTHROPIC_API_KEY) in client.py

BUG-002: datetime.fromisoformat() on bad date → unhandled ValueError → HTTP 500
  Fix: try/except ValueError → JSONResponse(400) in both digest handlers

BUG-003: not_found reason string returned literal "{}" instead of INCEPTION_DATE
  Fix: .format(settings.INCEPTION_DATE) at call site in digests.py

## Bugs fixed in session 2026-05-21 (commit 67d661b)

BUG-004: Fetcher historical backfill returned 0 papers for past dates
  Root cause: _build_search() built a single global search (500 most-recent papers),
  never matching historical dates in _postprocess_fetched_results.
  Fix: per-date submittedDate range query with 3-day lookback for Mon/Sun.

BUG-005: Timezone bug — papers announced Mon 20:00 ET have published.date() == Tue UTC
  Root cause: arXiv announces at 20:00 ET = 00:00 UTC next day during EDT.
  _postprocess_fetched_results compared strictly to date, dropping all midnight-EDT papers.
  Fix: accept date+1 as valid published date; reject date+2 and beyond.

BUG-006: Backfill not resumable after server restart or crash
  Root cause: run_inception_backfill returned early if ANY DateRecord existed.
  Fix: per-date idempotent check; resumes digest generation for published dates missing digest.

## Final test state

318 unit + integration tests PASS, 0 ruff violations, 99% coverage.
All 11 digest endpoints and all 3 QA endpoint scenarios verified live.

## Key environment facts

- Integration tests: TEST_DATABASE_URL="<set TEST_DATABASE_URL env var to the asyncpg connection string for the test DB>"
- Patch LLM at module import site, NOT at src.llm.client
- Pipeline integration tests: use TRUNCATE-based cleanup (pipeline commits internally)
- httpx.AsyncClient doesn't trigger lifespan — use app.router.lifespan_context()
- MagicMock(spec=Paper).submitted_date CANNOT do >= comparisons — set explicitly
- autouse pytest fixtures MUST go after all module-level imports (E402)
- pydantic-settings reads .env but does NOT set os.environ — pass api_key explicitly to AsyncAnthropic()
