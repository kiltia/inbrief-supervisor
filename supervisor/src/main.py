import logging
import random
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, List
from uuid import UUID, uuid4

import api.routes.callback as callback_routes
import api.routes.config as config_routes
import api.routes.dashboard as dashboard_routes
import api.routes.preset as preset_routes
import api.routes.summary as summary_routes
import api.routes.user as user_routes
import httpx
from api.requests import call_linker, call_scraper, call_summarizer
from asgi_correlation_id import CorrelationIdMiddleware, correlation_id
from context import ctx, linking_settings
from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter

from shared.entities import (
    Config,
    Request,
    Source,
    Story,
    StorySource,
    StorySources,
    Summary,
)
from shared.logger import configure_logging
from shared.models import (
    CategoryEntry,
    CategoryTitleRequest,
    ClusteringMethod,
    Density,
    EmbeddingSource,
    FetchRequest,
    FetchResponse,
    LinkingConfig,
    StoryEntry,
    SummarizeRequest,
)
from shared.routes import (
    SupervisorRoutes,
)
from shared.utils import DB_DATE_FORMAT


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await ctx.init_db()
    yield
    await ctx.dispose_db()


app = FastAPI(lifespan=lifespan)

app.include_router(callback_routes.router)
app.include_router(config_routes.router)
app.include_router(dashboard_routes.router)
app.include_router(preset_routes.router)
app.include_router(summary_routes.router)
app.include_router(user_routes.router)

app.add_middleware(CorrelationIdMiddleware, validator=None)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    return await http_exception_handler(
        request,
        HTTPException(
            500,
            "Internal server error",
            headers={"X-Request-ID": correlation_id.get() or ""},
        ),
    )


logger = logging.getLogger("app")


@app.get("/")
async def hello():
    return {"message": "Supervisor API is running"}


async def retrieve_config(config_id) -> Config:
    configs: list[Config] = await ctx.config_repo.get()
    configs = list(filter(lambda config: not config.inactive, configs))
    if not config_id:
        config = random.choice(configs)
        logger.debug(f"Using random config ID: {config.config_id}")
    else:
        filtered_configs = list(
            filter(lambda x: x.config_id == config_id, configs)
        )
        if not filtered_configs:
            raise HTTPException(
                httpx.codes.BAD_REQUEST, detail="Bad config ID"
            )
        else:
            config = filtered_configs[0]
        logger.debug("Using requested config ID: {config.config_id}")

    return config


def link_entity(clusters, texts):
    return list(map(lambda x: list(map(lambda y: texts[y], x)), clusters))


@app.post(
    SupervisorRoutes.FETCH,
    response_model=FetchResponse,
    responses={204: {"model": None}},
)
async def fetch(request: FetchRequest):
    corr_id = UUID(correlation_id.get())
    time = datetime.now()
    logger.info("Started fetching updates")

    config = await retrieve_config(request.config_id)
    data = await call_scraper(
        corr_id, request, EmbeddingSource(config.embedding_source)
    )
    entries = TypeAdapter(list[Source]).validate_python(data)

    if data == []:
        return JSONResponse(
            status_code=204, content={"message": "Nothing was found"}
        )

    categorizer_settings = linking_settings.model_dump()[
        config.embedding_source
    ][config.categorize_method]
    settings = linking_settings.model_dump()[config.embedding_source][
        config.linking_method
    ]

    categorizer_config = LinkingConfig(
        embedding_source=EmbeddingSource(config.embedding_source),
        method=ClusteringMethod(config.categorize_method),
        scorer=categorizer_settings["scorer"],
        metric=categorizer_settings["metric"],
    )

    linking_config = LinkingConfig(
        embedding_source=EmbeddingSource(config.embedding_source),
        method=ClusteringMethod(config.linking_method),
        scorer=settings["scorer"],
        metric=settings["metric"],
    )

    weights = ctx.shared_settings.config.ranking.weights

    response = await call_linker(corr_id, data, categorizer_config)
    unsorted_category_nums = response["results"][0]["stories_nums"]
    category_nums = ctx.ranker.get_sorted(
        zip(
            unsorted_category_nums,
            link_entity(unsorted_category_nums, entries),
            strict=False,
        ),
        weights=weights,
    )
    category_nums = list(map(lambda t: t[0], category_nums))

    uuids = [uuid4() for _ in range(len(category_nums))]

    categorized_posts = link_entity(category_nums, data)
    categorized_entries = link_entity(category_nums, entries)

    categories: list[CategoryEntry] = []
    # TODO(nrydanov): Make requests parallel
    for n in range(len(categorized_posts)):
        category, entries = categorized_posts[n], categorized_entries[n]
        if len(category) < 1:
            continue
        linker_response = await call_linker(corr_id, category, linking_config)
        stories_nums = linker_response["results"][0]["stories_nums"]
        story_uuids = [
            uuid4()
            for _ in range(len(stories_nums) + len(stories_nums[-1]) - 1)
        ]
        story_entities = list(
            map(
                lambda x: Story(
                    story_id=x, request_id=corr_id, category_id=uuids[n]
                ),
                story_uuids,
            )
        )

        await ctx.story_repo.add(story_entities)

        entities = []
        stories: list[tuple[StoryEntry, List[Source]]] = []
        uuid_num = 0
        for i in range(len(stories_nums[:-1])):
            stories.append((StoryEntry(uuid=story_uuids[uuid_num]), []))
            for j in range(len(stories_nums[i])):
                source = entries[stories_nums[i][j]]
                entity = StorySource(
                    story_id=story_uuids[uuid_num],
                    source_id=source.source_id,
                    channel_id=source.channel_id,
                )
                entities.append(entity)
                stories[i][1].append(source)

            uuid_num += 1

        for i in range(len(stories_nums[-1])):
            stories.append(
                (StoryEntry(uuid=story_uuids[uuid_num], noise=True), [])
            )
            source = entries[stories_nums[-1][i]]
            entity = StorySource(
                story_id=story_uuids[uuid_num],
                source_id=source.source_id,
                channel_id=source.channel_id,
            )
            entities.append(entity)
            stories[-1][1].append(source)
            uuid_num += 1

        await ctx.ss_repo.add(entities)

        # NOTE(nrydanov): Dates sorting
        stories = list(
            map(
                lambda t: (
                    t[0],
                    sorted(
                        t[1],
                        key=lambda x: datetime.strptime(
                            x.date, DB_DATE_FORMAT
                        ),
                    ),
                ),
                stories,
            )
        )
        stories = ctx.ranker.get_sorted(stories, weights=weights)
        story_entries = list(map(lambda t: t[0], stories))
        categories.append(CategoryEntry(uuid=uuids[n], stories=story_entries))

    logger.info("Finished fetching updates, sending response")
    elapsed = datetime.now() - time
    request_entity = Request(
        chat_id=request.chat_id,
        request_id=corr_id,
        request_type="fetch",
        status="completed",
        time_passed=elapsed,
        config_id=config.config_id,
    )
    await ctx.request_repo.add(request_entity)

    return TypeAdapter(FetchResponse).validate_python(
        {"config_id": config.config_id, "categories": categories}
    )


@app.post(SupervisorRoutes.SUMMARIZE)
async def summarize(request: SummarizeRequest):
    corr_id = correlation_id.get()
    logger.info("Started serving summary request")
    request.required_density = request.required_density[::-1]
    summary_id = uuid4()
    config: Config = (
        await ctx.config_repo.get("config_id", request.config_id)
    )[0]
    user = (await ctx.user_repo.get("chat_id", request.chat_id))[0]
    preset = (await ctx.preset_repo.get("preset_id", user.cur_preset))[0]
    sources: list[StorySources] = await ctx.ss_view.get(
        "story_id", request.story_id
    )
    story = list(map(lambda x: x.text, sources))

    response: dict[Any, Any] = {}
    response["summary"] = {}
    request.required_density.append(Density.TITLE)
    for density in request.required_density:
        logger.debug(f"Started generating {density.value} summary")
        if density == Density.TITLE:
            summary = await call_summarizer(
                UUID(corr_id),
                [response["summary"][Density.LARGE]["original"]],
                config,
                density,
                preset,
            )
        else:
            summary = await call_summarizer(
                UUID(corr_id), story, config, density, preset
            )
        logger.debug(f"Finished generating {density.value} summary")
        response["summary"][density] = summary

    response["summary_id"] = summary_id

    entities = []

    for density in request.required_density:
        if density == density.TITLE:
            pass
        summary_entity = Summary(
            summary_id=summary_id,
            chat_id=request.chat_id,
            story_id=UUID(request.story_id),
            summary=response["summary"][density]["edited"],
            title=response["summary"][Density.TITLE]["edited"],
            density=density,
            config_id=request.config_id,
            feedback=None,
            date_created=datetime.now().strftime(DB_DATE_FORMAT),
        )
        entities.append(summary_entity)

    await ctx.summary_repo.add(entities)

    response["references"] = list(map(lambda x: x.reference, sources))

    logger.info("Sending response with summarized news")
    return response


@app.post(SupervisorRoutes.CATEGORY_TITLE)
async def get_category_title(request: CategoryTitleRequest):
    corr_id = correlation_id.get()
    logger.info("Started serving category title request")
    config: Config = (
        await ctx.config_repo.get("config_id", request.config_id)
    )[0]
    user = (await ctx.user_repo.get("chat_id", request.chat_id))[0]
    preset = (await ctx.preset_repo.get("preset_id", user.cur_preset))[0]

    logger.debug("Started generating title for category")
    title = await call_summarizer(
        UUID(corr_id),
        request.texts,
        config,
        Density.CATEGORY,
        preset,
        edit=False,
    )
    response = {"title": title}

    logger.info("Sending response with category title")
    return response
