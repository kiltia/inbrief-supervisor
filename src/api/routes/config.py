from context import ctx
from fastapi import APIRouter

from shared.entities import Config
from shared.models import ConfigPostRequest
from shared.routes import SupervisorRoutes

router = APIRouter()


@router.post(SupervisorRoutes.CONFIG, status_code=204)
async def add_config(request: ConfigPostRequest):
    await ctx.config_repo.add(
        Config(
            config_id=request.config_id,
            embedding_source=request.embedding_source,
            linking_method=request.linking_method,
            summary_method=request.summary_method,
            editor_model=request.editor_model,
            inactive=False,
        ),
    )


@router.patch(SupervisorRoutes.CONFIG, status_code=204)
async def drop_config(config_id: int):
    config = (await ctx.config_repo.get("config_id", config_id))[0]
    config.inactive = True

    return await ctx.config_repo.update(config, ["inactive"])
