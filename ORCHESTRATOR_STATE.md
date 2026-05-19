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

## Final test state

309 unit + integration tests PASS, 0 ruff violations, 99% coverage.
All 11 digest endpoints and all 3 QA endpoint scenarios verified live.

## Key environment facts

- Integration tests: TEST_DATABASE_URL="<set TEST_DATABASE_URL env var to the asyncpg connection string for the test DB>"
- Patch LLM at module import site, NOT at src.llm.client
- Pipeline integration tests: use TRUNCATE-based cleanup (pipeline commits internally)
- httpx.AsyncClient doesn't trigger lifespan — use app.router.lifespan_context()
- MagicMock(spec=Paper).submitted_date CANNOT do >= comparisons — set explicitly
- autouse pytest fixtures MUST go after all module-level imports (E402)
- pydantic-settings reads .env but does NOT set os.environ — pass api_key explicitly to AsyncAnthropic()
