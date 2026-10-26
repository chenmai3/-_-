from fastapi import APIRouter, File, Form, Request, UploadFile

from .conversation_history.create_conversation import handle_upsert_conversation
from .conversation_history.delete_conversation import handle_delete_conversation_by_id
from .conversation_history.get_conversation_detail import handle_get_conversations
from .conversation_history.list_user_conversations import handle_get_history_conversations
from .document_upload.user_file_vector_store import handle_upload
from .permissions.theme_permission import handle_get_koqatheme_with_permission
from .qa_answer.graph_stream_answer import handle_ko4csg_hci
from .qa_answer.rag_stream_answer import handle_direct_question, handle_receive_question
from .speech_recognition.speech_to_text import handle_speech_to_text
from .standard_document.download_generated_document import handle_download_word
from .standard_document.generate_standard_document import handle_gen_biaozhun


router = APIRouter(prefix="/kdzn_qa", tags=["kdzn_hciqa.vue"])


@router.post("/ko4csg_hci")
async def ko4csg_hci(request: Request):
    return await handle_ko4csg_hci(request)


@router.post("/receive_question")
async def receive_question(request: Request):
    return await handle_receive_question(request)


@router.post("/deepseek_hci")
async def deepseek_hci(request: Request):
    return await handle_direct_question(request)


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    userId: str = Form(...),
    scene_choose: str = Form(...),
):
    return await handle_upload(scene_choose=scene_choose, userId=userId, file=file)


@router.post("/speechToText")
async def speech_to_text(file: UploadFile = File(...)):
    return await handle_speech_to_text(file)


@router.post("/gen_biaozhun")
async def gen_biaozhun(request: Request):
    return await handle_gen_biaozhun(request)


@router.get("/download_word")
async def download_word(word_name: str):
    return await handle_download_word(word_name)


@router.post("/get_conversations")
async def get_conversations(request: Request):
    return await handle_get_conversations(request)


@router.post("/getHistoryConversations")
async def get_history_conversations(request: Request):
    return await handle_get_history_conversations(request)


@router.post("/upsertConversation")
async def upsert_conversation(request: Request):
    return await handle_upsert_conversation(request)


@router.post("/deleteConversationById")
async def delete_conversation_by_id(request: Request):
    return await handle_delete_conversation_by_id(request)


@router.get("/get_koqathemeWithpermission")
async def get_koqatheme_with_permission(userID: str):
    return await handle_get_koqatheme_with_permission(userID)
