import logging
from typing import Dict, List
from uuid import UUID, uuid4

import httpx
import pandas as pd
from config import LinkingSettings, NetworkSettings
from fastapi import FastAPI, Response, status
from fastapi.exceptions import HTTPException

from shared.models import (
    Density,
    EmbeddingSource,
    LinkingMethod,
    Request,
    SummaryMethod,
    SummaryType,
)
from shared.utils import LOGGING_FORMAT

app = FastAPI()
logger = logging.getLogger(__name__)

network_settings = NetworkSettings(_env_file="config/network.cfg")
linking_settings = LinkingSettings("config/linker_config.json")


# TODO(nrydanov): Add detailed verification for all possible situations (#80)
def verifiable_request(call):
    async def wrapper(*args, **kwargs):
        response = await call(*args, **kwargs)
        if response.status_code != status.HTTP_200_OK:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="One of a services is unavailable at the moment.",
            )
            logger.error(
                f"Got {response.status_code} after calling to {call.__name__} (args['uuid'])"
            )
        return response.json()

    return wrapper


@app.get("/")
async def hello():
    return {"message": "Supervisor API is running"}


def create_url(port, method, host="localhost"):
    return f"http://{host}:{port}/{method}"


@verifiable_request
async def call_scraper(uuid: UUID, request: Request):
    url = create_url(
        network_settings.scraper_port,
        "scraper/",
        network_settings.scraper_host,
    )
    logger.info(f"Creating a new scraper request ({uuid})")

    config = request.config

    body = request.payload.model_dump()
    body.pop("preset_data")

    body["chat_folder_link"] = request.payload.preset_data.chat_folder_link

    match config.embedding_source:
        case EmbeddingSource.FTMLM:
            body["required_embedders"] = [
                "fast-text-embedder",
                "mini-lm-embedder",
            ]
        case EmbeddingSource.OPENAI:
            body["required_embedders"] = ["open-ai-embedder"]
        case EmbeddingSource.MLM:
            body["required_embedders"] = ["mini-lm-embedder"]

    async with httpx.AsyncClient() as client:
        return await client.post(url, json=body, timeout=30)


@verifiable_request
async def call_linker(
    uuid: UUID,
    data: pd.DataFrame,
    embedding_source: EmbeddingSource,
    method: LinkingMethod,
):
    logger.info(f"Creating a new linker request ({uuid})")
    embeddings = None

    texts = data["text"]
    dates = data["date"]
    match embedding_source:
        case EmbeddingSource.FTMLM:
            embeddings = data["mini-lm-embedder"] + data["fast-text-embedder"]
            config = linking_settings.ftmlm
        case EmbeddingSource.OPENAI:
            embeddings = data["open-ai-embedder"]
            config = linking_settings.openai
        case EmbeddingSource.MLM:
            embeddings = data["mini-lm-embedder"]
            config = linking_settings.mlm
        case _:
            possible_values = [e.value for e in EmbeddingSource]
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Got unexpected embedding source, available one's: {possible_values}",
            )

    request = {
        "texts": texts.tolist(),
        "dates": dates.tolist(),
        "embeddings": embeddings.tolist(),
        "method": method.value,
        "config": (config.model_dump())[method.value],
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            create_url(
                network_settings.linker_port,
                "get_stories",
                network_settings.linker_host,
            ),
            json=request,
            timeout=1e12,
        )
        return response


@verifiable_request
async def call_summarizer(
    uuid: UUID, story: List[str], method: SummaryMethod, density: Density
):
    logger.info(f"Creating a new summarizer request ({uuid})")
    body = {"story": story, "method": method.value, "density": density.value}

    async with httpx.AsyncClient() as client:
        response = await client.post(
            create_url(
                network_settings.summarizer_port,
                "summarize",
                network_settings.summarizer_host,
            ),
            json=body,
            # NOTE(nrydanov): Maybe it's a bad idea, but I don't really
            # understand what would be a nice value there
            timeout=1e12,
        )
        return response


@verifiable_request
async def call_editor(uuid: UUID, summary: str, style: str):
    logger.info(f"Creating a new editor request ({uuid})")
    body = {"input": summary, "style": style}

    async with httpx.AsyncClient() as client:
        response = await client.post(
            create_url(
                network_settings.editor_port,
                "edit",
                network_settings.editor_host,
            ),
            json=body,
            timeout=1e12,
        )
        return response


@app.post("/api/summarize")
async def serve_request(request: Request, response: Response):
    uuid = uuid4()
    logger.info(f"Started serving request, generated uuid: {uuid}")
    config, payload = request.config, request.payload
    data = pd.DataFrame.from_dict(await call_scraper(uuid, request))

    if not data.shape[0]:
        response.status_code = status.HTTP_204_NO_CONTENT
        return {}

    linked_data = (
        await call_linker(
            uuid, data, config.embedding_source, config.linking_method
        )
        if config.linking_method != LinkingMethod.NO_LINKER
        else data["text"]
    )

    summary: Dict[Density, Dict[SummaryType, list]] = {}

    for density in request.required_density:
        summary[density] = {
            SummaryType.STORYLINES: [],
            SummaryType.SINGLE_NEWS: [],
        }
        for story in linked_data["stories"][:-1]:
            summary[density][SummaryType.STORYLINES].append(
                await call_summarizer(
                    uuid, story, config.summary_method, density
                )
            )

        # NOTE(nrydanov): Probably remove it if we think that single news
        # shouldn't be summarized same as stories
        for post in linked_data["stories"][-1]:
            summary[density][SummaryType.SINGLE_NEWS].append(
                await call_summarizer(
                    uuid, [post], config.summary_method, density
                )
            )

        for group in SummaryType:
            for i in range(len(summary[density][group])):
                summary[density][group][i]["summary"] = await call_editor(
                    uuid,
                    summary[density][group][i]["summary"],
                    payload.preset_data.editor_prompt,
                )

    return summary


@app.on_event("startup")
async def main() -> None:
    logging.basicConfig(
        format=LOGGING_FORMAT,
        datefmt="%m-%d %H:%M:%S",
        level=logging.INFO,
        force=True,
    )
