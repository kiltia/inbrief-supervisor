from uuid import UUID, uuid4

from api.requests import call_linker
from context import (
    ctx,
    linking_settings,
)
from utils import link_entity

from shared.entities import (
    Source,
)
from shared.models import (
    ClusteringMethod,
    EmbeddingSource,
    LinkingConfig,
)


async def clusterize(
    request_id, embedding_source, clustering_method, entries
) -> list[tuple[UUID, list[Source]]]:
    settings = linking_settings.model_dump()[embedding_source][
        clustering_method
    ]

    linking_config = LinkingConfig(
        embedding_source=EmbeddingSource(embedding_source),
        method=ClusteringMethod(clustering_method),
        scorer=settings["scorer"],
        metric=settings["metric"],
    )

    weights = ctx.shared_settings.config.ranking.weights
    response = await call_linker(request_id, entries, linking_config)
    unsorted_category_nums = response["results"][0]["stories_nums"]
    uuids = [uuid4() for _ in range(len(unsorted_category_nums))]
    clusters = ctx.ranker.get_sorted(
        zip(
            uuids,
            link_entity(unsorted_category_nums, entries),
            strict=True,
        ),
        weights=weights,
    )

    return clusters
