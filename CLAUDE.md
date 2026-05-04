<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
at `specs/001-arxiv-intelligence-agent/plan.md`.
<!-- SPECKIT END -->

# ArXivAgent — Project Context

ArXivAgent is an always-on background service that monitors arXiv daily, synthesizes
ML research papers into structured digests, and exposes those digests — plus a
conversational RAG Q&A interface — through HTTP endpoints.

**Active feature**: `001-arxiv-intelligence-agent` (branch: `001-arxiv-intelligence-agent`)  
**Design artifacts**: `specs/001-arxiv-intelligence-agent/` — `spec.md`, `system_design.md`, `plan.md`, `tasks.md`

## Critical Design Constraints

Non-obvious decisions — do not change without reading `spec.md` and `system_design.md` first.

**arXiv schedule**: publishes at 20:00 ET, Sun–Thu only. Fri/Sat have no announcements — this is structural, not a failure.

**Four date states** (mutually exclusive — all must be handled distinctly by the API):

| State | Meaning |
|-------|---------|
| `published` | Digest generated successfully |
| `no_announcement` | Fri or Sat — arXiv never publishes |
| `no_papers_skip` | Announcement day, arXiv reachable, 0 papers |
| `fetch_failure_skip` | Announcement day, all 3 retries failed |

**Weekly digest window**: Sun–Thu only (the 5 arXiv announcement days). Fri/Sat are never part of a weekly digest.

**Inception backfill**: on first run, full pipeline runs for every announcement day from `INCEPTION_DATE` forward before handing off to schedulers.

For env vars, tech stack, library versions, key design decisions, and out-of-scope items — see `specs/001-arxiv-intelligence-agent/plan.md` → Technical Context and `spec.md`.

## Definition of Done

See `specs/001-arxiv-intelligence-agent/tasks.md` → Definition of Done for the full checklist (tests pass, 100% line/branch coverage, no ruff errors). Coverage exclusions: `src/migrations/*`, `src/main.py`, all `__init__.py`.

---

## Coding Guidelines

### Docstrings

Add a docstring to every function, method, or class unless the name and signature are fully self-explanatory. Explain **why** or **what contract** the code enforces, not what it does line-by-line. Include a one-line summary, non-obvious parameters/returns, and any exceptions raised. Use Google-style:

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

### Library Versions & Documentation

Before writing code that uses any third-party library:

1. Read `pyproject.toml` to find the pinned version.
2. If it is a major-version bump from training data (see known bumps below), check the changelog before writing any code.
3. Spawn `context7-plugin:docs-researcher` with the library name, pinned version, and the specific API surface you need. Do not fetch entire docs — be targeted.
4. Write code using only APIs confirmed in the returned docs.

**Known major-version bumps** (treat APIs as unknown until confirmed via docs):

| Package | Pinned | Risk |
|---------|--------|------|
| `arxiv` | 3.0.0 | 2.x → 3.x: use `Client` object; `client.results()` not `search.results()` |
| `sentence-transformers` | 5.4.1 | 4.x → 5.x: use `inputs=` not `sentences=` |
| `pytest` | 9.0.3 | 8.x → 9.x breaking changes |
| `pytest-asyncio` | 1.3.0 | 0.x → 1.x: `event_loop` fixture removed |
