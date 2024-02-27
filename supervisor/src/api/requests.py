import logging
from uuid import UUID

import httpx
from context import ctx, linking_settings, network_settings
from fastapi import status
from fastapi.exceptions import HTTPException
from utils import REQUEST_TIMEOUT, create_url, form_scraper_request

from shared.entities import Config, Preset, User
from shared.models import (
    Density,
    EmbeddingSource,
    Entry,
    FetchRequest,
    LinkingConfig,
    OpenAIModels,
    SummaryMethod,
)
from shared.routes import LinkerRoutes, ScraperRoutes, SummarizerRoutes

logger = logging.getLogger("supervisor")


# TODO(nrydanov): Add detailed verification for all possible situations (#80)
def verifiable_request(call):
    async def wrapper(*args, **kwargs) -> dict:
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
                raise HTTPException(
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"{call.__name__} is unavailable at the moment.",
                )

    return wrapper


@verifiable_request
async def call_scraper(
    corr_id: UUID,
    request: FetchRequest,
    embedding_source: EmbeddingSource,
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

    async with httpx.AsyncClient() as client:
        response = await client.get(
            create_url(
                network_settings.scraper_port,
                ScraperRoutes.SYNC + f"?link={preset.chat_folder_link}",
                network_settings.scraper_host,
            )
        )

        # TODO(nrydanov): Move channel sync in seperate @verifiable_request
        if response.status_code != httpx.codes.OK:
            raise HTTPException(status_code=httpx.codes.BAD_REQUEST)

        body = form_scraper_request(request, embedding_source, response.json())
        return await client.post(
            url,
            json=body,
            timeout=REQUEST_TIMEOUT,
            headers={"X-Request-ID": str(corr_id)},
        )


@verifiable_request
async def call_linker(
    corr_id: UUID,
    entries: list[Entry],
    config: LinkingConfig,
    *,
    return_plot_data: bool = False,
) -> httpx.Response:
    logger.info("Creating a new linker request")
    settings = linking_settings.model_dump()[config.embedding_source.value][
        config.method.value
    ]

    async with httpx.AsyncClient() as client:
        response = await client.post(
            create_url(
                network_settings.linker_port,
                LinkerRoutes.GET_STORIES,
                network_settings.linker_host,
            ),
            json={
                "entries": [e.model_dump() for e in entries],
                "config": config.model_dump(),
                "settings": settings["config"],
                "return_plot_data": return_plot_data,
            },
            timeout=REQUEST_TIMEOUT,
            headers={"X-Request-ID": str(corr_id)},
        )
        return response


@verifiable_request
async def call_summarizer(
    corr_id: UUID,
    story: list[str],
    config: Config,
    density: Density,
    preset: Preset,
    edit: bool = True,
):
    logger.info("Creating a new summarizer request")
    summary_method = (
        SummaryMethod.OPENAI.value
        if OpenAIModels.has_value(config.summary_method)
        else config.summary_method
    )
    summary_model = (
        None if summary_method == SummaryMethod.BART else config.summary_method
    )
    body = {
        "story": story,
        "density": density.value,
        "summary_method": summary_method,
        "config": {
            "summary_model": summary_model,
        },
    }

    if edit:
        body["config"]["editor_config"] = {
            "style": preset.editor_prompt,
            "model": config.editor_model,
        }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            create_url(
                network_settings.summarizer_port,
                SummarizerRoutes.SUMMARIZE,
                network_settings.summarizer_host,
            ),
            json=body,
            timeout=REQUEST_TIMEOUT,
            headers={"X-Request-ID": str(corr_id)},
        )
        return response
