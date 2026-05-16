from datetime import datetime
from typing import AsyncGenerator
# from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.utils.funcs import logger
from src.config import get_settings
from src.api.schemas import DailyDigestData, Type, DailyDigestResponse, Status, MAP_STATUS_TO_REASON, WeeklyDigestData, WeeklyDigestResponse, ErrorResponse, Error, MAP_ERROR_MESSAGE
from src.db import constants 
from src.db.models import DateRecord, DailyDigest, WeeklyDigest
from src.api.deps import get_session


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
    requested_date = datetime.fromisoformat(date)
    if requested_date > datetime.today():
        return DailyDigestResponse(
            status=Status.NOT_AVAILABLE,
            reason=MAP_STATUS_TO_REASON.get("future_date"),
        )

    if requested_date.date() < get_settings().INCEPTION_DATE:
        return DailyDigestResponse(
            status=Status.NOT_FOUND,
            reason=MAP_STATUS_TO_REASON.get("before_inception_date"),
        )

    stmt = select(DateRecord).where(DateRecord.date == requested_date.date())
    result = await session.execute(stmt)
    existing = result.scalars().first()
    if existing is None:
        logger.warning("DateRecord on %s gives empty", date)
        return DailyDigestResponse(
            status=Status.EMPTY,
            reason=MAP_STATUS_TO_REASON.get("empty", "").format("DateRecord"),
        )

    if existing.status == constants.DATE_STATUS_PUBLISHED:
        stmt = select(DailyDigest).options(selectinload(DailyDigest.topic_sections)).where(DailyDigest.date == existing.date)
        result = await session.execute(stmt)
        daily_digest_result = result.scalars().first()

        if daily_digest_result is None:
            logger.warning("DailyDigest with status '%s' on date %s gives empty", existing.status, date)
            return DailyDigestResponse(
                status=Status.EMPTY,
                reason=MAP_STATUS_TO_REASON.get("empty", "").format("DailyDigest"),
            )
        return DailyDigestResponse(status=Status.OK, data=DailyDigestData.model_validate(daily_digest_result))

    else:
        return DailyDigestResponse(
            status=MapDateStatusToResponseStatus.get(existing.status),
            reason=MAP_STATUS_TO_REASON.get(existing.status),
        )


@router.get("/digests/weekly/{week_start_date}")
async def get_digest_weekly(week_start_date: str, session: AsyncSession = Depends(get_session)):
    requested_week_start_date = datetime.fromisoformat(week_start_date)
    if requested_week_start_date.weekday() != _SUNDAY:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(error=Error.VALIDATION, message=MAP_ERROR_MESSAGE.get(Type.WEEKLY.value)).model_dump(),
        )

    if requested_week_start_date.date() < get_settings().INCEPTION_DATE:
        return WeeklyDigestResponse(
            status=Status.NOT_FOUND,
            reason=MAP_STATUS_TO_REASON.get("before_inception_date"),
        )

    if requested_week_start_date > datetime.today():
        return WeeklyDigestResponse(
            status=Status.NOT_AVAILABLE,
            reason=MAP_STATUS_TO_REASON.get("future_date"),
        )

    stmt = select(WeeklyDigest).where(WeeklyDigest.week_start == requested_week_start_date.date())
    result = await session.execute(stmt)
    existing = result.scalars().first()
    if existing is None:
        logger.warning("WeeklyDigest on week_start %s gives empty", week_start_date)
        return WeeklyDigestResponse(
            status=Status.PENDING,
            reason=MAP_STATUS_TO_REASON.get("empty", "").format("WeeklyDigest"),
        )

    return WeeklyDigestResponse(
        status=Status.OK,
        data=WeeklyDigestData.model_validate(existing),
    )
