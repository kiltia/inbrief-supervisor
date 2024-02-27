import httpx
from context import ctx
from fastapi import APIRouter
from starlette.responses import JSONResponse

from shared.models import UserFeedbackRequest
from shared.routes import SupervisorRoutes

router = APIRouter()


@router.post(SupervisorRoutes.FEEDBACK)
async def send_summary_feedback(request: UserFeedbackRequest):
    summaries = await ctx.summary_repo.get("summary_id", request.summary_id)

    if not summaries:
        return JSONResponse(status_code=httpx.codes.BAD_REQUEST)

    summary = next(filter(lambda s: s.density == request.density, summaries))
    summary.feedback = request.feedback
    await ctx.summary_repo.update(summary, ["feedback"])
