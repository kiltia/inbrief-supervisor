from context import ctx
from fastapi import APIRouter

from shared.entities import User
from shared.models import UserRequest
from shared.routes import SupervisorRoutes

router = APIRouter()


@router.post(SupervisorRoutes.USER, status_code=204)
async def register(request: UserRequest):
    chat_id = request.chat_id
    user = await ctx.user_repo.get("chat_id", chat_id)
    if not user:
        await ctx.user_repo.add(User(chat_id=chat_id))
