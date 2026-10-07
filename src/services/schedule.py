from datetime import date, datetime, time
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.holiday import Holiday
from src.models.service_schedule import ServiceSchedule
from src.utils.exceptions.database import DatabaseUnavailableError

SANTIAGO = ZoneInfo("America/Santiago")

Slots = dict[int, tuple[time, time]]

def is_open(now: datetime, slots: Slots, holidays: set[date]) -> bool:
    local = now.astimezone(SANTIAGO)
    if local.date() in holidays or local.weekday() not in slots:
        return False
    opens_at, closes_at = slots[local.weekday()]
    return opens_at <= local.time() < closes_at

async def load_schedule(session: AsyncSession) -> tuple[Slots, set[date]]:
    try:
        schedules = (await session.execute(select(ServiceSchedule))).scalars()
        holidays = (await session.execute(select(Holiday.date))).scalars()
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc
    return {s.weekday: (s.opens_at, s.closes_at) for s in schedules}, set(holidays)
