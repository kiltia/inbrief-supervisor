import logging
import random
from uuid import UUID

import httpx
from context import ctx
from fastapi import HTTPException

from shared.entities import Config, Source, Story, StorySource

logger = logging.getLogger("supervisor")


async def save_category_to_db(
    request_id: UUID,
    category_id: UUID,
    entries: list[tuple[UUID, list[Source]]],
):
    story_uuids = list(map(lambda x: x[0], entries))
    story_entities = list(
        map(
            lambda x: Story(
                story_id=x, request_id=request_id, category_id=category_id
            ),
            story_uuids,
        )
    )
    await ctx.story_repo.add(story_entities)


async def save_stories_to_db(story_id: UUID, entries: list[Source]) -> None:
    entities = list(
        map(
            lambda x: StorySource(
                story_id=story_id,
                source_id=x.source_id,
                channel_id=x.channel_id,
            ),
            entries,
        )
    )
    await ctx.ss_repo.add(entities)


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
