from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from context import ctx
from fastapi import APIRouter, status
from pydantic import TypeAdapter

from shared.entities import Schedule
from shared.models import (
    PartialScheduleUpdate,
    SchedulePostRequest,
)
from shared.routes import SupervisorRoutes

router = APIRouter()


@router.get(SupervisorRoutes.USER + "/{chat_id}/schedule")
async def get_schedules(chat_id: int):
    response: dict[str, Any] = {}
    response["schedules"] = await ctx.schedule_view.get("chat_id", chat_id)
    return response


@router.post(SupervisorRoutes.SCHEDULE, status_code=status.HTTP_204_NO_CONTENT)
async def add_schedule_entry(request: SchedulePostRequest):
    schedule_id = uuid4()

    # TODO(vinc3nzo): limit amount of schedules
    # See: https://github.com/kiltia/inbrief/issues/315
    # TODO(vinc3nzo): for now, use UTC time. Implement user timezones
    # See: https://github.com/kiltia/inbrief/issues/314
    td = timedelta(hours=0)
    tz = timezone(td)
    schedule = Schedule(
        schedule_id=schedule_id,
        last_run=datetime.now(tz),
        cron=request.cron,
        preset_id=request.preset_id,
        chat_id=request.chat_id,
        user_id=request.user_id,
        active=False,
        deleted=False,
    )

    await ctx.schedule_repo.add(schedule)
    return schedule_id


@router.get(SupervisorRoutes.SCHEDULE + "/{schedule_id}")
async def get_schedule_entry(schedule_id: UUID):
    schedule_entry = await ctx.schedule_repo.get("schedule_id", schedule_id)
    return schedule_entry[0]


@router.patch(
    SupervisorRoutes.SCHEDULE, status_code=status.HTTP_204_NO_CONTENT
)
async def update_schedule(request: PartialScheduleUpdate):
    schedule_entries = await ctx.schedule_repo.get(
        "schedule_id", request.schedule_id
    )
    schedule = schedule_entries[0]

    request_dump = request.model_dump()
    schedule_dump = schedule.model_dump()
    for key, value in request_dump.items():
        if value is not None:
            schedule_dump[key] = value

    request_dump.pop("chat_id")
    keys = request_dump.keys()

    await ctx.schedule_repo.update(
        TypeAdapter(Schedule).validate_python(schedule_dump), list(keys)
    )
