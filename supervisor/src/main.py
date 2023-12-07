import json
import logging
import random
from datetime import datetime
from typing import Dict, List
from uuid import UUID, uuid4

import httpx
from asgi_correlation_id import CorrelationIdMiddleware, correlation_id
from databases import Database
from fastapi import FastAPI, Response, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter
from utils import (
    REQUEST_TIMEOUT,
    chain_correlations,
    form_linking_request,
    form_scraper_request,
)

from config import LinkingSettings, NetworkSettings
from shared.db import PgRepository, create_db_string
from shared.entities import (
    Callback,
    Config,
    Folder,
    Preset,
    Summary,
    User,
    UserPreset,
    UserPresets,
)
from shared.logging import configure_logging
from shared.models import (
    CallbackPatchRequest,
    CallbackPostRequest,
    ChangePresetRequest,
    ConfigPostRequest,
    Density,
    EmbeddingSource,
    FetchRequest,
    LinkingMethod,
    PartialPresetUpdate,
    PresetData,
    SummarizeRequest,
    UserRequest,
)
from shared.resources import SharedResources
from shared.routes import (
    EditorRoutes,
    LinkerRoutes,
    ScraperRoutes,
    SummarizerRoutes,
    SupervisorRoutes,
)
from shared.utils import DB_DATE_FORMAT, SHARED_CONFIG_PATH

app = FastAPI()
app.add_middleware(CorrelationIdMiddleware, validator=None)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception) -> JSONResponse:
    return await http_exception_handler(
        request,
        HTTPException(
            500,
            "Internal server error",
            headers={"X-Request-ID": correlation_id.get() or ""},
        ),
    )


logger = logging.getLogger("app")

network_settings = NetworkSettings(_env_file="config/network.cfg")
linking_settings = LinkingSettings("config/linker_config.json")


class Context:
    def __init__(self) -> None:
        self.shared_settings = SharedResources(
            f"{SHARED_CONFIG_PATH}/settings.json"
        )
        self.pg = Database(create_db_string(self.shared_settings.pg_creds))
        self.callback_repository = PgRepository(self.pg, Callback)
        self.preset_view = PgRepository(self.pg, UserPresets)
        self.user_repo = PgRepository(self.pg, User)
        self.preset_repo = PgRepository(self.pg, Preset)
        self.up_repo = PgRepository(self.pg, UserPreset)
        self.config_repo = PgRepository(self.pg, Config)
        self.summary_repo = PgRepository(self.pg, Summary)
        self.folder_repo = PgRepository(self.pg, Folder)

    async def init_db(self) -> None:
        await self.pg.connect()

    async def dispose_db(self) -> None:
        await self.pg.disconnect()


ctx = Context()


# TODO(nrydanov): Add detailed verification for all possible situations (#80)
def verifiable_request(call):
    async def wrapper(*args, **kwargs):
        response = await call(*args, **kwargs)
        match response.status_code:
            case status.HTTP_200_OK:
                return response.json()
            case status.HTTP_204_NO_CONTENT:
                logger.warning(
                    f"Got no content response after calling to {call.__name__}"
                )
                raise HTTPException(
                    status.HTTP_204_NO_CONTENT,
                    detail=f"{call.__name__} returned no content response",
                )
            case _:
                logger.error(
                    f"Got {response.status_code} after calling to {call.__name__}"
                )
                return HTTPException(
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"{call.__name__} is unavailable at the moment.",
                    headers={"X-Request-ID": correlation_id.get() or ""},
                )

    return wrapper


@app.get("/")
async def hello():
    return {"message": "Supervisor API is running"}


def create_url(port, method, host="localhost"):
    return f"http://{host}:{port}{method}"


@verifiable_request
async def call_scraper(
    corr_id: UUID, request: FetchRequest, embedding_source: EmbeddingSource
):
    url = create_url(
        network_settings.scraper_port,
        ScraperRoutes.PARSE,
        network_settings.scraper_host,
    )
    logger.info("Creating a new scraper request")

    user: User = (await ctx.user_repo.get("chat_id", request.chat_id))[0]

    preset: Preset = (
        await ctx.preset_repo.get("preset_id", str(user.cur_preset))
    )[0]

    channels: List[int] = (
        await ctx.folder_repo.get("chat_folder_link", preset.chat_folder_link)
    )[0].channels

    body = form_scraper_request(request, embedding_source, channels)
    async with httpx.AsyncClient() as client:
        return await client.post(
            url,
            json=body,
            timeout=REQUEST_TIMEOUT,
            headers={
                "X-Request-ID": chain_correlations(corr_id, uuid4().hex[:4])
            },
        )


@verifiable_request
async def call_linker(
    corr_id: UUID,
    data: dict,
    embedding_source: EmbeddingSource,
    method: LinkingMethod,
):
    logger.info("Creating a new linker request")

    # NOTE(nrydanov): List of dict -> dict of list conversion.
    # Those actions are obvious overhead, but it won't be visible for now
    data = {k: [entity[k] for entity in data] for k in data[0]}
    data["embeddings"] = list(map(lambda x: json.loads(x), data["embeddings"]))

    data["embeddings"] = {
        k: [entity[k] for entity in data["embeddings"]]
        for k in data["embeddings"][0]
    }

    request = form_linking_request(
        data, embedding_source, linking_settings, method
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            create_url(
                network_settings.linker_port,
                LinkerRoutes.GET_STORIES,
                network_settings.linker_host,
            ),
            json=request,
            timeout=REQUEST_TIMEOUT,
            headers={
                "X-Request-ID": chain_correlations(corr_id, uuid4().hex[:4])
            },
        )
        return response


@verifiable_request
async def call_summarizer(
    corr_id: UUID,
    story_id: UUID,
    summary_id: UUID,
    chat_id: int,
    config_id: UUID,
    density: Density,
):
    logger.info("Creating a new summarizer request")
    body = {
        "story_id": str(story_id),
        "config_id": config_id,
        "density": density.value,
        "summary_id": str(summary_id),
        "chat_id": chat_id,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            create_url(
                network_settings.summarizer_port,
                SummarizerRoutes.SUMMARIZE,
                network_settings.summarizer_host,
            ),
            json=body,
            # NOTE(nrydanov): Maybe it's a bad idea, but I don't really
            # understand what would be a nice value there
            timeout=REQUEST_TIMEOUT,
            headers={
                "X-Request-ID": chain_correlations(corr_id, uuid4().hex[:4])
            },
        )
        return response


@verifiable_request
async def call_editor(
    corr_id: UUID, summary_id: str, style: str, model: str, density: Density
):
    logger.info("Creating a new editor request")
    body = {
        "style": style,
        "model": model,
        "summary_id": str(summary_id),
        "density": density.value,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            create_url(
                network_settings.editor_port,
                EditorRoutes.EDIT,
                network_settings.editor_host,
            ),
            json=body,
            timeout=REQUEST_TIMEOUT,
            headers={
                "X-Request-ID": chain_correlations(corr_id, uuid4().hex[:4])
            },
        )
        return response


@app.post(SupervisorRoutes.USER, status_code=204)
async def register(request: UserRequest):
    chat_id = request.chat_id
    user = await ctx.user_repo.get("chat_id", chat_id)
    if not user:
        await ctx.user_repo.add(User(chat_id=chat_id))


@app.get(SupervisorRoutes.USER + "/{chat_id}/presets")
async def get_presets(chat_id: int):
    response = {}
    response["presets"] = await ctx.preset_view.get("chat_id", chat_id)
    user: List[User] = await ctx.user_repo.get("chat_id", chat_id)
    response["cur_preset"] = user[0].cur_preset
    return response


@app.get(SupervisorRoutes.SUMMARIZE)
async def get_cached_summary(density: Density, summary_id: UUID):
    response = await ctx.summary_repo.get("summary_id", summary_id)

    return list(filter(lambda x: x.density == density, response))[0]


@app.patch(SupervisorRoutes.USER + "/{chat_id}/presets", status_code=204)
async def change_preset(chat_id: int, request: ChangePresetRequest):
    user: User = (await ctx.user_repo.get("chat_id", chat_id))[0]
    user.cur_preset = request.cur_preset
    await ctx.user_repo.update(user, fields=["cur_preset"])


@app.patch(SupervisorRoutes.PRESET, status_code=204)
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
        TypeAdapter(Preset).validate_python(preset_dump), keys
    )


@app.post(SupervisorRoutes.PRESET, status_code=204)
async def add_preset(chat_id: int, preset: PresetData):
    preset_id = uuid4()
    async with httpx.AsyncClient() as client:
        await client.post(
            create_url(
                network_settings.scraper_port,
                ScraperRoutes.SYNC,
                network_settings.scraper_host,
            ),
            json={"chat_folder_link": preset.chat_folder_link},
            timeout=REQUEST_TIMEOUT,
        )
    await ctx.preset_repo.add(
        Preset(
            preset_id=preset_id,
            date_created=datetime.now().strftime(DB_DATE_FORMAT),
            **preset.model_dump(),
        ),
    )
    await ctx.up_repo.add(UserPreset(chat_id=chat_id, preset_id=preset_id))


@app.post(SupervisorRoutes.FETCH)
async def fetch(request: FetchRequest, response: Response):
    corr_id = correlation_id.get()
    logger.info("Started fetching updates")
    configs: List[Config] = await ctx.config_repo.get()
    configs = list(filter(lambda config: not config.inactive, configs))
    config: Config = random.choice(configs)
    logger.info(f"Using config {config.config_id}")
    data = await call_scraper(
        corr_id, request, EmbeddingSource(config.embedding_source)
    )

    if data == []:
        response.status_code = status.HTTP_204_NO_CONTENT
        return {}

    linked_data = (
        await call_linker(
            corr_id,
            data,
            EmbeddingSource(config.embedding_source),
            LinkingMethod(config.linking_method),
        )
        if config.linking_method != LinkingMethod.NO_LINKER
        else data["text"]
    )

    logger.info("Finished fetching updates, sending response")
    return {"config_id": config.config_id, "story_ids": linked_data}


@app.post(SupervisorRoutes.SUMMARIZE)
async def summarize(request: SummarizeRequest):
    corr_id = correlation_id.get()
    summary_id = uuid4()
    logger.info("Started serving summary request")
    request.required_density = request.required_density[::-1]

    config: Config = (
        await ctx.config_repo.get("config_id", request.config_id)
    )[0]
    user: User = (await ctx.user_repo.get("chat_id", request.chat_id))[0]
    preset: Preset = (await ctx.preset_repo.get("preset_id", user.cur_preset))[
        0
    ]
    summary: Dict[Density, Dict[str, str]] = {}
    for density in request.required_density:
        logger.debug(f"Started generating {density.value} summary")
        summary_story = await call_summarizer(
            corr_id,
            request.story_id,
            summary_id,
            request.chat_id,
            config.config_id,
            density,
        )
        summary[density] = summary_story
        logger.debug(f"Finished generating {density.value} summary")
        logger.debug(f"Started editing {density.value} summary")
        summary[density]["summary"] = await call_editor(
            corr_id,
            summary_id,
            preset.editor_prompt,
            config.editor_model,
            density,
        )
        logger.debug(f"Finished editing {density.value} summary")
    summary["summary_id"] = summary_id

    logger.info("Sending response with summarized news")
    return summary


@app.post(SupervisorRoutes.CALLBACK)
async def set_callback(request: CallbackPostRequest):
    callback_id = uuid4()
    callback_row = Callback(
        callback_id=callback_id,
        callback_data=json.dumps(request.callback_data),
    )
    await ctx.callback_repository.add(callback_row)
    return callback_id


@app.get(SupervisorRoutes.CALLBACK + "/{callback_id}")
async def get_callback(callback_id):
    callback_data = await ctx.callback_repository.get(
        "callback_id", callback_id
    )
    return json.loads(callback_data[0].callback_data)


@app.patch(SupervisorRoutes.CALLBACK, status_code=204)
async def update_callback(request: CallbackPatchRequest):
    callback_row = Callback(
        callback_id=request.callback_id,
        callback_data=json.dumps(request.callback_data),
    )
    await ctx.callback_repository.update(callback_row, ["callback_data"])


@app.on_event("startup")
async def main() -> None:
    configure_logging()
    await ctx.init_db()


@app.on_event("shutdown")
async def disconnect() -> None:
    await ctx.dispose_db()


@app.post(SupervisorRoutes.CONFIG, status_code=204)
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


@app.patch(SupervisorRoutes.CONFIG, status_code=204)
async def drop_config(config_id: int):
    config = (await ctx.config_repo.get("config_id", config_id))[0]
    config.inactive = True

    return await ctx.config_repo.update(config, ["inactive"])
