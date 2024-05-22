from uuid import UUID

import httpx
from context import ctx
from fastapi import APIRouter, HTTPException

from shared.models import Density
from shared.routes import SupervisorRoutes

router = APIRouter()


@router.get(SupervisorRoutes.SUMMARIZE)
async def get_cached_summary(summary_id: UUID):
    summaries = await ctx.summary_repo.get("summary_id", summary_id)

    if not summaries:
        raise HTTPException(status_code=httpx.codes.BAD_REQUEST)

    sources = await ctx.ss_view.get("story_id", summaries[0].story_id)
    references = list(map(lambda x: x.reference, sources))

    small_summary = list(
        filter(lambda x: x.density == Density.SMALL, summaries)
    )[0]

    large_summary = list(
        filter(lambda x: x.density == Density.LARGE, summaries)
    )[0]

    return {
        "references": references,
        "small": small_summary.summary,
        "large": large_summary.summary,
        "title": large_summary.title,
    }
