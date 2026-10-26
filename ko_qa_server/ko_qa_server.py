import uvicorn
from fastapi import FastAPI, Request

from vue_api.common.server_settings import load_server_settings
from vue_api.jiapu_qa.api import router as jiapu_qa_router
from vue_api.kdzn_hciqa.api import (
    deepseek_hci,
    gen_biaozhun,
    get_conversations,
    get_history_conversations,
    get_koqatheme_with_permission,
    ko4csg_hci,
    speech_to_text,
    upload,
    upsert_conversation,
)
from vue_api.router import vue_api_router
from vue_api.rule_construct.graph_match import handle_neo4j_query


def create_app() -> FastAPI:
    settings = load_server_settings()
    application = FastAPI(debug=settings.debug)
    application.include_router(vue_api_router)
    # The Java gateway still calls the original family-QA URLs without /api/jiapu_qa.
    # Register aliases for the complete workflow using the same endpoint functions.
    for route in jiapu_qa_router.routes:
        application.add_api_route(
            route.path[len(jiapu_qa_router.prefix):],
            route.endpoint,
            methods=route.methods,
            include_in_schema=False,
        )
    application.add_api_route(
        "/deepseek_hci", deepseek_hci, methods=["POST"], include_in_schema=False
    )
    application.add_api_route(
        "/upload", upload, methods=["POST"], include_in_schema=False
    )
    for path in ("/speech-to-text", "/speechToText"):
        application.add_api_route(path, speech_to_text, methods=["POST"], include_in_schema=False)
    for path in ("/gen_biaozhun", "/zhongshaoxuan/test"):
        application.add_api_route(path, gen_biaozhun, methods=["POST"], include_in_schema=False)
    application.add_api_route(
        "/getHistoryConversations",
        get_history_conversations,
        methods=["POST"],
        include_in_schema=False,
    )
    application.add_api_route(
        "/get_conversations", get_conversations, methods=["POST"], include_in_schema=False
    )
    application.add_api_route(
        "/get_koqathemeWithpermission",
        get_koqatheme_with_permission,
        methods=["GET"],
        include_in_schema=False,
    )
    application.add_api_route(
        "/upsertConversation",
        upsert_conversation,
        methods=["POST"],
        include_in_schema=False,
    )
    application.add_api_route(
        "/ko4csg_hci", ko4csg_hci, methods=["POST"], include_in_schema=False
    )

    @application.post("/neo4j_query")
    async def neo4j_query(request: Request):
        return await handle_neo4j_query(await request.json())

    return application


app = create_app()


if __name__ == '__main__':
    server_settings = load_server_settings()
    uvicorn.run(
        "ko_qa_server:app",
        host=server_settings.host,
        port=server_settings.port,
        reload=server_settings.reload,
    )
