import logging
from uuid import UUID

from api.requests import call_linker
from context import ctx, linking_settings
from fastapi import APIRouter
from pydantic import TypeAdapter

from shared.entities import Config, Request, StorySources
from shared.models import (
    ClusteringMethod,
    DistancesMetrics,
    EmbeddingSource,
    Entry,
    LinkingConfig,
    LinkingScorers,
    PlotData,
)
from shared.routes import SupervisorRoutes

router = APIRouter()

adapter = TypeAdapter(PlotData)

logger = logging.getLogger("app")


@router.post(SupervisorRoutes.DASH + "/config")
async def get_used_config(uuid: UUID):
    reqs: list[Request] = await ctx.request_repo.get("request_id", uuid)
    if not reqs:
        # TODO(nrydanov): Add proper handling
        pass

    configs: list[Config] = await ctx.config_repo.get(
        "config_id", reqs[0].config_id
    )

    config = configs[0]

    settings = linking_settings.model_dump()[config.embedding_source][
        config.linking_method
    ]
    return LinkingConfig(
        embedding_source=EmbeddingSource(config.embedding_source),
        method=ClusteringMethod(config.linking_method),
        scorer=LinkingScorers(settings["scorer"]),
        metric=DistancesMetrics(settings["metric"]),
    )


@router.post(SupervisorRoutes.DASH)
async def get_dashboard_data(uuid: UUID, config: LinkingConfig):
    data: list[StorySources] = await ctx.ss_view.get("request_id", uuid)

    entries = list(
        map(
            lambda x: Entry(text=x.text, embeddings=x.embeddings).model_dump(),
            data,
        )
    )
    response = await call_linker(uuid, entries, config, return_plot_data=True)

    return adapter.validate_python(
        {
            "payload": data,
            "results": response["results"],
            "embeddings": response["embeddings"],
        }
    )
