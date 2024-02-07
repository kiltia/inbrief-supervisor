from datetime import datetime
from typing import Any
from uuid import uuid4

import httpx
from context import ctx, network_settings
from fastapi import APIRouter
from pydantic import TypeAdapter
from utils import create_url

from shared.entities import Preset, User, UserPreset
from shared.models import ChangePresetRequest, PartialPresetUpdate, PresetData
from shared.routes import ScraperRoutes, SupervisorRoutes
from shared.utils import DB_DATE_FORMAT

router = APIRouter()


@router.get(SupervisorRoutes.USER + "/{chat_id}/presets")
async def get_presets(chat_id: int):
    response: dict[str, Any] = {}
    response["presets"] = await ctx.preset_view.get("chat_id", chat_id)
    user: list[User] = await ctx.user_repo.get("chat_id", chat_id)
    response["cur_preset"] = user[0].cur_preset
    return response


@router.patch(SupervisorRoutes.USER + "/{chat_id}/presets", status_code=204)
async def change_preset(chat_id: int, request: ChangePresetRequest):
    user: User = (await ctx.user_repo.get("chat_id", chat_id))[0]
    user.cur_preset = request.cur_preset
    await ctx.user_repo.update(user, fields=["cur_preset"])


@router.patch(SupervisorRoutes.PRESET, status_code=204)
async def update_preset(request: PartialPresetUpdate):
    presets = await ctx.preset_repo.get("preset_id", request.preset_id)
    preset = presets[0]

    request_dump = request.model_dump()
    preset_dump = preset.model_dump()
    for key, value in request_dump.items():
        if value is not None:
            preset_dump[key] = value

    request_dump.pop("chat_id")
    keys = request_dump.keys()

    return await ctx.preset_repo.update(
        TypeAdapter(Preset).validate_python(preset_dump), list(keys)
    )


@router.post(SupervisorRoutes.PRESET, status_code=204)
async def add_preset(chat_id: int, preset: PresetData):
    preset_id = uuid4()
    async with httpx.AsyncClient() as client:
        await client.get(
            create_url(
                network_settings.scraper_port,
                ScraperRoutes.SYNC + f"?link={preset.chat_folder_link}",
                network_settings.scraper_host,
            )
        )

    await ctx.preset_repo.add(
        Preset(
            preset_id=preset_id,
            date_created=datetime.now().strftime(DB_DATE_FORMAT),
            **preset.model_dump(),
        ),
    )
    await ctx.up_repo.add(UserPreset(chat_id=chat_id, preset_id=preset_id))
