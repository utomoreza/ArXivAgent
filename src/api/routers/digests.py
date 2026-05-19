import time
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.deps import get_session
from src.api.schemas import (
    MAP_ERROR_MESSAGE,
    MAP_STATUS_TO_REASON,
    DailyDigestData,
    DailyDigestResponse,
    Error,
    ErrorResponse,
    Status,
    Type,
    WeeklyDigestData,
    WeeklyDigestResponse,
)
from src.config import get_settings
from src.db import constants
from src.db.models import DailyDigest, DateRecord, WeeklyDigest
from src.utils.funcs import logger

_SUNDAY = 6
MapDateStatusToResponseStatus: dict[str, Status] = {
    constants.DATE_STATUS_NO_PAPERS_SKIP: Status.SKIPPED,
    constants.DATE_STATUS_FETCH_FAILURE_SKIP: Status.FETCH_FAILED,
    constants.DATE_STATUS_NO_ANNOUNCEMENT: Status.NO_ANNOUNCE,
}


router = APIRouter(
    # prefix="/",
    # tags=["users"],
)


@router.get("/digests/daily/{date}")
async def get_digest_daily(date: str, session: AsyncSession = Depends(get_session)):
    logger.debug("GET /digests/daily/%s", date)
    t0 = time.perf_counter()
    try:
        requested_date = datetime.fromisoformat(date)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error=Error.VALIDATION,
                message="Invalid date format. Expected YYYY-MM-DD.",
            ).model_dump(),
        )
    if requested_date > datetime.today():
        return DailyDigestResponse(
            status=Status.NOT_AVAILABLE,
            reason=MAP_STATUS_TO_REASON.get("future_date"),
        )

    settings = get_settings()
    if requested_date.date() < settings.INCEPTION_DATE:
        return DailyDigestResponse(
            status=Status.NOT_FOUND,
            reason=MAP_STATUS_TO_REASON.get("before_inception_date", "").format(
                settings.INCEPTION_DATE
            ),
        )

    stmt = select(DateRecord).where(DateRecord.date == requested_date.date())
    result = await session.execute(stmt)
    existing = result.scalars().first()
    if existing is None:
        logger.warning("DateRecord on %s gives empty", date)
        return DailyDigestResponse(
            status=Status.EMPTY,
            reason=(
                "No DateRecord found for this date"
                " — data may still be processing."
            ),
        )

    if existing.status == constants.DATE_STATUS_PUBLISHED:
        stmt = (
            select(DailyDigest)
            .options(selectinload(DailyDigest.topic_sections))
            .where(DailyDigest.date == existing.date)
        )
        result = await session.execute(stmt)
        daily_digest_result = result.scalars().first()

        if daily_digest_result is None:
            logger.warning(
                "DailyDigest with status '%s' on date %s gives empty",
                existing.status,
                date,
            )
            return DailyDigestResponse(
                status=Status.EMPTY,
                reason=(
                    "DateRecord shows published but DailyDigest is missing"
                    " — data may still be processing."
                ),
            )
        response = DailyDigestResponse(
            status=Status.OK,
            data=DailyDigestData.model_validate(daily_digest_result),
        )
        logger.info(
            "GET /digests/daily/%s status=%s elapsed_s=%.3f",
            date, response.status, time.perf_counter() - t0,
        )
        return response

    else:
        response = DailyDigestResponse(
            status=MapDateStatusToResponseStatus.get(existing.status),
            reason=MAP_STATUS_TO_REASON.get(existing.status),
        )
        logger.info(
            "GET /digests/daily/%s status=%s elapsed_s=%.3f",
            date, response.status, time.perf_counter() - t0,
        )
        return response


@router.get("/digests/weekly/{week_start_date}")
async def get_digest_weekly(
    week_start_date: str, session: AsyncSession = Depends(get_session)
):
    logger.debug("GET /digests/weekly/%s", week_start_date)
    t0 = time.perf_counter()
    try:
        requested_week_start_date = datetime.fromisoformat(week_start_date)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error=Error.VALIDATION,
                message="Invalid date format. Expected YYYY-MM-DD.",
            ).model_dump(),
        )
    if requested_week_start_date.weekday() != _SUNDAY:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error=Error.VALIDATION,
                message=MAP_ERROR_MESSAGE.get(Type.WEEKLY.value),
            ).model_dump(),
        )

    settings = get_settings()
    if requested_week_start_date.date() < settings.INCEPTION_DATE:
        return WeeklyDigestResponse(
            status=Status.NOT_FOUND,
            reason=MAP_STATUS_TO_REASON.get("before_inception_date", "").format(
                settings.INCEPTION_DATE
            ),
        )

    if requested_week_start_date > datetime.today():
        return WeeklyDigestResponse(
            status=Status.NOT_AVAILABLE,
            reason=MAP_STATUS_TO_REASON.get("future_date"),
        )

    stmt = select(WeeklyDigest).where(
        WeeklyDigest.week_start == requested_week_start_date.date()
    )
    result = await session.execute(stmt)
    existing = result.scalars().first()
    if existing is None:
        logger.warning("WeeklyDigest on week_start %s gives empty", week_start_date)
        return WeeklyDigestResponse(
            status=Status.PENDING,
            reason=MAP_STATUS_TO_REASON.get(
                Status.PENDING.value, "Weekly digest not yet generated."
            ),
        )

    response = WeeklyDigestResponse(
        status=Status.OK,
        data=WeeklyDigestData.model_validate(existing),
    )
    logger.info(
        "GET /digests/weekly/%s status=%s elapsed_s=%.3f",
        week_start_date, response.status, time.perf_counter() - t0,
    )
    return response
