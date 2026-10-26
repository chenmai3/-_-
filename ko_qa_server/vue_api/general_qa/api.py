from fastapi import APIRouter, Request

from .service import handle_chat, handle_chat2kb, handle_chat2url


router = APIRouter(prefix="/general_qa", tags=["general_qa.vue"])


@router.post("/chat")
async def chat(request: Request):
    return await handle_chat(await request.json())


@router.post("/chat2kb")
async def chat2kb(request: Request):
    return await handle_chat2kb(await request.json())


@router.post("/chat2url")
async def chat2url(request: Request):
    return await handle_chat2url(await request.json())
