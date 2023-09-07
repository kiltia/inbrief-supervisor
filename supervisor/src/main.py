import logging
from typing import Dict, List
from uuid import uuid4

import pandas as pd
import requests
from config import LinkingSettings, NetworkSettings
from fastapi import FastAPI, Response
from fastapi.exceptions import HTTPException
from models import (
    Density,
    EmbeddingSource,
    LinkingMethod,
    Request,
    SummaryMethod,
    SummaryType,
)
from utils import LOGGING_FORMAT

app = FastAPI()
logger = logging.getLogger(__name__)

network_settings = NetworkSettings(_env_file="config/network.cfg")
linking_settings = LinkingSettings("config/linker_config.json")


# TODO(nrydanov): Add detailed verification for all possible situations ()
def verifiable_request(call):
    def wrapper(*args, **kwargs):
        response = call(*args, **kwargs)
        if response.status_code != 200:
            raise HTTPException(
                500, detail="One of a services is unavailable at the moment."
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
def call_scraper(uuid, **body):
    url = create_url(
        network_settings.scraper_port, "scraper/", network_settings.scraper_host
    )
    logger.info(f"Creating a new scraper request ({uuid})")

    body = body.copy()

    match body["embedding_source"]:
        case EmbeddingSource.FTMLM:
            body["required_embedders"] = ["fast-text-embedder", "mini-lm-embedder"]
        case EmbeddingSource.OPENAI:
            body["required_embedders"] = ["open-ai-embedder"]
        case EmbeddingSource.MLM:
            body["required_embedders"] = ["mini-lm-embedder"]

    body.pop("embedding_source")

    return requests.post(url, json=body)


@verifiable_request
def call_linker(
    uuid, data: pd.DataFrame, embedding_source: EmbeddingSource, method: LinkingMethod
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
                500,
                f"Got unexpected embedding source, available one's: {possible_values}",
            )

    body = {
        "texts": texts.tolist(),
        "dates": dates.tolist(),
        "embeddings": embeddings.tolist(),
        "method": method.value,
        "config": (config.model_dump())[method.value],
    }
    response = requests.post(
        create_url(
            network_settings.linker_port, "get_stories", network_settings.linker_host
        ),
        json=body,
    )

    return response


@verifiable_request
def call_summarizer(uuid, story: List[str], method: SummaryMethod, density: Density):
    logger.info(f"Creating a new summarizer request ({uuid})")
    body = {"story": story, "method": method.value, "density": density.value}

    response = requests.post(
        create_url(
            network_settings.summarizer_port,
            "summarize",
            network_settings.summarizer_host,
        ),
        json=body,
    )

    return response


@verifiable_request
def call_editor(uuid, summary: str, style: str):
    logger.info(f"Creating a new editor request ({uuid})")
    body = {"input": summary, "style": style}

    response = requests.post(
        create_url(network_settings.editor_port, "edit", network_settings.editor_host),
        json=body,
    )

    return response


@app.post("/api/summarize")
async def serve_request(request: Request, response: Response):
    uuid = uuid4()
    logger.info(f"Started serving request, generated uuid: {uuid}")
    body = request.payload.model_dump()
    config = request.config
    data = pd.DataFrame.from_dict(
        call_scraper(uuid, embedding_source=config.embedding_source, **body)
    )

    if not data.shape[0]:
        return {}

    linked_data = (
        call_linker(uuid, data, config.embedding_source, config.linking_method)
        if config.linking_method != LinkingMethod.NO_LINKER
        else data["text"]
    )

    summary: Dict[Density, Dict[SummaryType, list]] = {}

    for density in config.required_density:
        summary[density] = {SummaryType.STORYLINES: [], SummaryType.SINGLE_NEWS: []}
        for story in linked_data["stories"][:-1]:
            summary[density][SummaryType.STORYLINES].append(
                call_summarizer(uuid, story, config.summary_method, density)
            )

        # NOTE(nrydanov): Probably remove it if we think that single news
        # shouldn't be summarized same as stories
        for post in linked_data["stories"][-1]:
            summary[density][SummaryType.SINGLE_NEWS].append(
                call_summarizer(uuid, [post], config.summary_method, density)
            )

        for group in SummaryType:
            for i in range(len(summary[density][group])):
                summary[density][group][i]["summary"] = call_editor(
                    uuid, summary[density][group][i]["summary"], config.editor
                )

    return summary


@app.on_event("startup")
async def main() -> None:
    logging.basicConfig(
        format=LOGGING_FORMAT, datefmt="%m-%d %H:%M:%S", level=logging.INFO, force=True
    )
