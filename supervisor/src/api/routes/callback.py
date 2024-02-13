import json
from uuid import uuid4

from context import ctx
from fastapi import APIRouter

from shared.entities import Callback
from shared.models import CallbackPatchRequest, CallbackPostRequest
from shared.routes import SupervisorRoutes

router = APIRouter()


@router.post(SupervisorRoutes.CALLBACK)
async def set_callback(request: CallbackPostRequest):
    callback_id = uuid4()
    callback_row = Callback(
        callback_id=callback_id,
        callback_data=json.dumps(request.callback_data),
    )
    await ctx.callback_repository.add(callback_row)
    return callback_id


@router.get(SupervisorRoutes.CALLBACK + "/{callback_id}")
async def get_callback(callback_id):
    callback_data = await ctx.callback_repository.get(
        "callback_id", callback_id
    )
    return json.loads(callback_data[0].callback_data)


@router.patch(SupervisorRoutes.CALLBACK, status_code=204)
async def update_callback(request: CallbackPatchRequest):
    callback_row = Callback(
        callback_id=request.callback_id,
        callback_data=json.dumps(request.callback_data),
    )
    await ctx.callback_repository.update(callback_row, ["callback_data"])
