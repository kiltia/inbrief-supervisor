import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import api.routes.callback as callback_routes
import api.routes.config as config_routes
import api.routes.dashboard as dashboard_routes
import api.routes.feedback as feedback_routes
import api.routes.preset as preset_routes
import api.routes.summary as summary_routes
import api.routes.user as user_routes
from api.requests import call_linker, call_scraper, call_summarizer
from asgi_correlation_id import CorrelationIdMiddleware, correlation_id
from context import ctx, linking_settings
from fastapi import FastAPI, Response, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter
from utils import link_entity

from db import retrieve_config, save_category_to_db, save_stories_to_db
from shared.entities import (
    Config,
    Request,
    Source,
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
    ParseResponse,
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
app.include_router(feedback_routes.router)

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


logger = logging.getLogger("supervisor")


@app.get("/")
async def hello():
    return {"message": "Supervisor API is running"}


async def clusterize(
    request_id, embedding_source, clustering_method, sources
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
    response = await call_linker(request_id, sources, linking_config)
    unsorted_category_nums = response["results"][0]["stories_nums"]
    uuids = [uuid4() for _ in range(len(unsorted_category_nums))]
    clusters = ctx.ranker.get_sorted(
        zip(
            uuids,
            link_entity(unsorted_category_nums, sources),
            strict=False,
        ),
        weights=weights,
    )

    return clusters


@app.post(
    SupervisorRoutes.FETCH,
    response_model=FetchResponse,
    responses={204: {"model": None}},
)
async def fetch(request: FetchRequest, response: Response):
    corr_id = UUID(correlation_id.get())
    time = datetime.now()
    logger.info("Started fetching updates")

    config = await retrieve_config(request.config_id)
    response = await call_scraper(
        corr_id, request, EmbeddingSource(config.embedding_source)
    )

    if response == []:
        return JSONResponse(
            status_code=204, content={"message": "Nothing was found"}
        )

    typed_body = TypeAdapter(ParseResponse).validate_python(response)
    sources = typed_body.sources
    skipped_channel_ids = typed_body.skipped_channel_ids

    if skipped_channel_ids:
        logger.debug(
            f"A few channels were skipped by scraper: {skipped_channel_ids}"
        )

    if not sources:
        response.status_code = status.HTTP_204_NO_CONTENT
        return {"skipped_channel_ids": skipped_channel_ids}

    categories = await clusterize(
        corr_id, config.embedding_source, config.categorize_method, sources
    )
    category_entries: list[CategoryEntry] = []
    for category_id, category in categories:
        if not category:
            continue
        stories = await clusterize(
            corr_id, config.embedding_source, config.linking_method, category
        )
        await save_category_to_db(corr_id, category_id, stories)

        story_entries: list[StoryEntry] = []
        for story in stories:
            story_id = story[0]
            await save_stories_to_db(story_id, story[1])
            story_entries.append(StoryEntry(uuid=story_id, noise=False))

        # NOTE(nrydanov): Dates sorting
        category_entries.append(
            CategoryEntry(uuid=category_id, stories=story_entries)
        )

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
        {
            "config_id": config.config_id,
            "categories": category_entries,
            "skipped_channel_ids": skipped_channel_ids,
        }
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
