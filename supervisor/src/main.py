import asyncio
import logging
from asyncio import Queue
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import api.routes.callback as callback_routes
import api.routes.config as config_routes
import api.routes.dashboard as dashboard_routes
import api.routes.feedback as feedback_routes
import api.routes.preset as preset_routes
import api.routes.schedule as schedule_routes
import api.routes.summary as summary_routes
import api.routes.user as user_routes
from api.requests import call_scraper, call_summarizer
from asgi_correlation_id import CorrelationIdMiddleware, correlation_id
from clustering import clusterize
from context import ctx
from exceptions import (
    ComponentException,
    component_exception_handler,
    supervisor_exception_handler,
)
from fastapi import FastAPI, Response, status
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter
from workers import finalize_category_entries, process_categories

from db import retrieve_config
from shared.entities import (
    Config,
    Request,
    StorySources,
    Summary,
)
from shared.logger import configure_logging
from shared.models import (
    CategoryTitleRequest,
    Density,
    EmbeddingSource,
    FetchRequest,
    FetchResponse,
    ParseResponse,
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
    await ctx.start_scheduler()
    yield
    shutdown_tasks = [
        ctx.stop_scheduler(),
        ctx.dispose_db(),
    ]
    logger.debug("Waiting for running tasks to stop")
    try:
        await asyncio.wait_for(
            asyncio.gather(*shutdown_tasks),
            ctx.shared_settings.config.scheduler.shutdown_timeout,
        )
        logger.debug("All running tasks are stopped")
    except asyncio.TimeoutError:
        logger.warn("Timed out cancelling running tasks, force exiting")


app = FastAPI(lifespan=lifespan)

app.include_router(callback_routes.router)
app.include_router(config_routes.router)
app.include_router(dashboard_routes.router)
app.include_router(preset_routes.router)
app.include_router(summary_routes.router)
app.include_router(user_routes.router)
app.include_router(feedback_routes.router)
app.include_router(schedule_routes.router)

app.add_middleware(CorrelationIdMiddleware, validator=None)

app.add_exception_handler(ComponentException, component_exception_handler)
app.add_exception_handler(Exception, supervisor_exception_handler)


logger = logging.getLogger("supervisor")


@app.get("/")
async def hello():
    return {"message": "Supervisor API is running"}


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
    index_map: dict[UUID, int] = {
        uuid: i for i, (uuid, stories) in enumerate(categories) if stories
    }
    category_entries = [None] * len(index_map)
    queue: Queue = Queue()

    workers = [
        process_categories(corr_id, config, categories, queue)
        for _ in range(ctx.shared_settings.config.category_async_pool_size)
    ]
    workers.append(
        finalize_category_entries(queue, category_entries, index_map)
    )
    await asyncio.gather(*workers)

    elapsed = datetime.now() - time
    logger.info(
        f"Finished fetching updates, sending response. Time elapsed: {elapsed}"
    )
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
    preset = (await ctx.preset_repo.get("preset_id", request.preset_id))[0]
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
    preset = (await ctx.preset_repo.get("preset_id", request.preset_id))[0]

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
