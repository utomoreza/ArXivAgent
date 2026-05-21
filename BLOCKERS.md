# Blockers

## Session Bootstrap — 2026-05-16

**Status**: RESOLVED in 2026-05-19 session. Environment unblocked; all tasks complete.

---

## BUG-004: Fetcher historical backfill returns 0 papers for past dates

**Status**: FIXED (commit `67d661b`, 2026-05-21)

### Root cause

`Fetcher._build_search()` was a class-level method that built a single global
`arxiv.Search` at construction time, using the 500 most-recent papers sorted
by `SubmittedDate`. When `run_inception_backfill` called `fetch_papers()` for
a date months in the past, the API returned the 500 most-recent papers from
today — none of which matched the historical date filter in
`_postprocess_fetched_results` → `no_papers_skip` for every historical date.

### Fix

`_build_search` is now an instance method that takes `date` and constructs a
`submittedDate:[from TO to]` range query specifically for that date:

```python
from_ts = from_date.strftime("%Y%m%d1400")
to_ts = date.strftime("%Y%m%d1400")
query=f"({category_query}) AND submittedDate:[{from_ts} TO {to_ts}]"
```

Monday/Sunday use a 3-day lookback to cover the weekend gap; Tue–Sat use 1 day.

---

## BUG-005: Timezone bug — papers announced Mon 20:00 ET recorded as Tue UTC, dropped

**Status**: FIXED (commit `67d661b`, 2026-05-21)

### Root cause

arXiv announces at 20:00 ET. During EDT (UTC-4) that is 00:00 UTC the next
calendar day. `arxiv.Result.published` is a UTC datetime, so
`r.published.date()` for a Monday announcement returns Tuesday.
`_postprocess_fetched_results` compared strictly to `date`, so all papers
from announcement days near midnight EDT were dropped → `no_papers_skip`.

### Fix

Accept `date+1` as an in-window published date:

```python
papers = [
    r for r in results
    if r.published.date() == date
    or r.published.date() == date + datetime.timedelta(days=1)
]
```

`date+2` and beyond are still rejected.

---

## BUG-006: Backfill not resumable — interrupted pipeline cannot continue

**Status**: FIXED (commit `67d661b`, 2026-05-21)

### Root cause

`run_inception_backfill` started with:

```python
count = await session.scalar(select(func.count()).select_from(DateRecord))
if count > 0:
    logger.info("backfill skipped: DateRecord rows already exist")
    return
```

If the backfill was interrupted mid-run (server restart, crash), the function
would detect the partial DateRecord rows and skip entirely. Any date that had
a `DateRecord(status=published)` but no corresponding `DailyDigest` would
never get its digest generated.

### Fix

Per-date idempotent check:

```python
existing = await session.scalar(select(DateRecord).where(DateRecord.date == current))
if existing is None:
    await _run_pipeline_for_date(current, session)
elif existing.status == DATE_STATUS_PUBLISHED:
    digest = await session.scalar(select(DailyDigest).where(DailyDigest.date == current))
    if digest is None:
        generator = DailyDigestGenerator()
        await generator.generate(current, session)
        logger.info("resumed digest generation for %s", current)
# else: skip/failure status — nothing to do
```

---

## Session Bootstrap — 2026-05-16 (original, archived)

**Status**: RESOLVED

The container had `uv` installed as root but not accessible to the `claude`
user, and the `.venv` was a stale macOS build. Fixed by rebuilding the
container image (Dockerfile.claude) so `uv` is installed world-accessible
and the venv is rebuilt inside Linux.
