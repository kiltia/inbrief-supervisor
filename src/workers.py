from asyncio import Queue
from uuid import UUID, uuid4

from clustering import clusterize

from db import save_category_to_db, save_stories_to_db
from shared.entities import (
    Config,
    Source,
)
from shared.models import (
    CategoryEntry,
    StoryEntry,
)


async def process_categories(
    corr_id: UUID,
    config: Config,
    categories: list[tuple[UUID, list[Source]]],
    queue: Queue,
):
    while categories:
        category_id, category = categories.pop()
        if not category:
            continue
        stories = await clusterize(
            corr_id,
            config.embedding_source,
            config.linking_method,
            category,
        )
        await queue.put((corr_id, category_id, stories))


async def finalize_category_entries(
    queue: Queue,
    category_entries,
    index_map: dict[UUID, int],
):
    for _ in range(len(index_map)):
        corr_id, category_id, stories = await queue.get()
        await save_category_to_db(corr_id, category_id, stories)

        story_entries: list[StoryEntry] = []
        for story in stories[:-1]:
            story_id = story[0]
            await save_stories_to_db(story_id, story[1])
            story_entries.append(StoryEntry(uuid=story_id, noise=False))
        for noise_story in stories[-1][1]:
            uuid = uuid4()
            await save_stories_to_db(uuid, [noise_story])
            story_entries.append(StoryEntry(uuid=uuid, noise=True))
        category_entries[index_map[category_id]] = CategoryEntry(
            uuid=category_id,
            stories=story_entries,
        )
